"""Deterministic extraction and validation helpers for the Intake Agent."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


POLICY_RE = re.compile(r"\b(?:POL|CLM|HLTH?|MTR|INS|LIFE|TRV|PROP)[- ]?\d{4,}(?:[- ]?\w+)*\b", re.IGNORECASE)
CLAIMANT_RE = re.compile(r"\bClaimant\s*:\s*([^|\n\r]+)", re.IGNORECASE)
PATIENT_RE = re.compile(r"\bPatient\s*:\s*([^|\n\r]+)", re.IGNORECASE)
HOSPITAL_RE = re.compile(r"\b([A-Z][A-Za-z&.\s]+(?:Hospital|Clinic|Medical Centre|Medical Center))\b")
PROCEDURE_RE = re.compile(r"\b(?:Procedure|Surgery|Treatment)\s*:\s*([^|\n\r.]+)", re.IGNORECASE)
DIAGNOSIS_RE = re.compile(r"\b(?:Diagnosis|Diagnosed with)\s*:\s*([^|\n\r.]+)", re.IGNORECASE)
AMOUNT_RE = re.compile(
    r"(?:INR|Rs\.?|₹|\$)\s*([0-9][0-9,]*(?:\.\d{1,2})?)|"
    r"([0-9][0-9,]*(?:\.\d{1,2})?)\s*(?:INR|rupees|rs)",
    re.IGNORECASE,
)

CLAIM_AMOUNT_CONTEXT_RE = re.compile(
    r"(?:claim(?:ed)?\s+amount|claim\s+value|estimated\s+repair\s+cost|"
    r"estimated\s+cost|estimated\s+amount|estimate\s+amount|repair\s+estimate|"
    r"total\s+estimate(?:\s+amount)?|invoice\s+amount|bill\s+amount|"
    r"damage\s+(?:estimate|valuation|value|cost))\s*[:\-]?\s*"
    r"(?:INR|Rs\.?|\$)?\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
AMOUNT_CONTEXT_BLOCKLIST = (
    "sum insured",
    "policy amount",
    "policy limit",
    "coverage limit",
    "insured declared value",
    "idv",
    "premium",
    "deductible",
)

DOCUMENT_ALIASES = {
    "insurance_card": ("motor insurance card", "vehicle insurance card", "insurance card"),
    "health_card": ("health card", "ecard", "e-card", "insurance card", "policy card"),
    "policy_number": ("policy number", "policy no", "policy:", "pol-", "ins-", "hlt-"),
    "doctor_prescription": ("prescription", "doctor prescription", "rx"),
    "mri_report": ("mri", "radiology", "scan report"),
    "hospital_estimate": ("estimate", "quotation", "hospital bill", "invoice", "bill",
                          "discharge", "discharge summary", "discharge_summary"),
    "pre_authorization_form": ("pre-authorization", "preauthorisation", "preauth", "pre auth"),
    "kyc_document": ("aadhaar", "aadhar", "pan card", "passport", "kyc", "id proof"),
    "fir_or_police_report": ("fir", "police report", "accident report"),
    "fire_brigade_report": ("fire brigade", "fire department", "fire report", "noc", "no objection certificate"),
    "damage_photo": ("photo", "image", "damage"),
    "repair_invoice": (
        "repair invoice", "garage estimate", "garage invoice", "repair quote",
        "contractor quote", "damage assessment", "valuation", "loss assessor",
        "damage valuation",
    ),
    "property_policy": ("property policy", "policy copy", "copy of policy"),
}

MANDATORY_DOCUMENTS_BY_CLAIM_TYPE = {
    "health": {
        "policy_number",
        # health_card removed: not a standard submission document in India;
        # requiring it causes every health claim to be flagged as incomplete.
        "doctor_prescription",
        "hospital_estimate",  # also matches discharge summaries via DOCUMENT_ALIASES
    },
    "motor": {
        "policy_number",
        "repair_invoice",
        "damage_photo",
    },
    "property": {
        "policy_number",
        "damage_photo",
        "repair_invoice",
    },
    "travel": {"policy_number"},
    "life": {"policy_number", "kyc_document"},
    "other": {"policy_number"},
}

SURGERY_KEYWORDS = ("surgery", "reconstruction", "operation", "procedure", "acl")
CASHLESS_KEYWORDS = ("cashless", "pre-authorization", "preauthorisation", "preauth", "pre auth")
QUALITY_TERMS = ("unreadable", "blurry", "blurred", "cropped", "manual_review_needed")
QUALITY_PHRASES = ("cut off", "partially cut", "text cut", "image cut")
RED_FLAG_TERMS = ("edited", "mismatch", "contradict", "suspicious", "tamper", "duplicate", "forged")
DATE_RE = re.compile(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]20\d{2})\b")
MONTH_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(20\d{2})\b",
    re.IGNORECASE,
)


def infer_claim_type(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("car", "vehicle", "motor", "accident", "garage")):
        return "motor"
    if any(word in lower for word in ("hospital", "medical", "surgery", "doctor")):
        return "health"
    if any(word in lower for word in ("home", "fire", "flood", "property")):
        return "property"
    if any(word in lower for word in ("flight", "baggage", "travel")):
        return "travel"
    if "life" in lower:
        return "life"
    return "other"


def deterministic_extract(email_body: str, documents_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    text = email_body or ""
    policy = POLICY_RE.search(text)
    claimant = CLAIMANT_RE.search(text)
    patient = PATIENT_RE.search(text)
    hospital = HOSPITAL_RE.search(text)
    procedure = PROCEDURE_RE.search(text)
    diagnosis = DIAGNOSIS_RE.search(text)
    amount = _extract_claim_amount(text)

    date_match = DATE_RE.search(text)
    month_date_match = MONTH_DATE_RE.search(text)
    incident_date = date_match.group(0).replace("/", "-") if date_match else None
    if not incident_date and month_date_match:
        incident_date = _month_date_to_iso(month_date_match)
    claim_type = infer_claim_type(text)
    docs = documents_summary or {}
    classified_documents = classify_documents(docs, text)
    documents_received = sorted(set(classified_documents.values()))
    missing_documents = mandatory_missing_documents(claim_type, text, documents_received, bool(policy), docs)
    quality_issues = detect_quality_issues(docs)
    consistency_issues = detect_consistency_issues(docs, claimant.group(1).strip() if claimant else None)
    basic_red_flags = detect_basic_red_flags(text, docs, consistency_issues)
    intake_status = "complete"
    if missing_documents or quality_issues:
        intake_status = "incomplete"
    elif consistency_issues or basic_red_flags:
        intake_status = "needs_review"
    next_agent = recommend_next_agent(intake_status, basic_red_flags)

    return {
        "intake_status": intake_status,
        "documents_received": documents_received,
        "classified_documents": classified_documents,
        "missing_documents": missing_documents,
        "quality_issues": quality_issues,
        "consistency_issues": consistency_issues,
        "basic_red_flags": basic_red_flags,
        "message_to_customer": customer_message(missing_documents, quality_issues),
        "next_recommended_agent": next_agent,
        "claimant_name": claimant.group(1).strip() if claimant else patient.group(1).strip() if patient else None,
        "policy_number": policy.group(0).replace(" ", "-").upper() if policy else None,
        "claim_type": claim_type,
        "request_type": infer_request_type(text),
        "incident_date": incident_date,
        "incident_time": None,
        "incident_description": text[:500],
        "claim_amount": amount,
        "currency": "INR",
        "location_of_incident": None,
        "vehicle_registration": None,
        "third_party_involved": None,
        "police_report_filed": None,
        "police_report_number": None,
        "hospital_name": hospital.group(1).strip() if hospital else _first_doc_fact(docs, "all_vendors"),
        "patient_name": patient.group(1).strip() if patient else claimant.group(1).strip() if claimant else None,
        "diagnosis": diagnosis.group(1).strip() if diagnosis else None,
        "procedure": procedure.group(1).strip() if procedure else infer_procedure(text, docs),
        "estimated_amount": amount,
        "contact_phone": None,
        "documents_mentioned": documents_mentioned(docs),
        "risk_indicators": basic_red_flags,
        "claim_summary": text[:300] or "No claim text provided.",
        "confidence_score": 0.55 if intake_status == "complete" else 0.4,
        "missing_information": missing_information(policy, amount, incident_date, missing_documents),
        "intake_notes": "Deterministic fallback extraction used.",
    }


def enrich_intake_result(
    result: dict[str, Any],
    email_body: str,
    documents_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backfill workflow fields so AI and fallback intake outputs share a contract."""
    deterministic = deterministic_extract(email_body, documents_summary)
    enriched = dict(result)
    for key in (
        "intake_status",
        "documents_received",
        "classified_documents",
        "missing_documents",
        "quality_issues",
        "consistency_issues",
        "basic_red_flags",
        "message_to_customer",
        "next_recommended_agent",
        "request_type",
        "patient_name",
        "diagnosis",
        "procedure",
        "claim_amount",
        "estimated_amount",
    ):
        if key in {"claim_amount", "estimated_amount"}:
            if _as_positive_amount(enriched.get(key)) <= 0 and _as_positive_amount(deterministic.get(key)) > 0:
                enriched[key] = deterministic.get(key)
        elif key not in enriched or enriched.get(key) in (None, "", []):
            enriched[key] = deterministic.get(key)

    # Only merge deterministic missing_information when the AI didn't produce its own list.
    # Unconditional merging injects spurious "document:health_card" entries that cause
    # the router to treat complete claims as incomplete.
    ai_missing = [item for item in (enriched.get("missing_information") or []) if item]
    if not ai_missing:
        det_missing = deterministic.get("missing_information") or []
        enriched["missing_information"] = sorted(set(str(item) for item in det_missing if item))
    else:
        enriched["missing_information"] = sorted(set(str(item) for item in ai_missing if item))
    enriched["risk_indicators"] = sorted(set(
        [str(item) for item in enriched.get("risk_indicators") or [] if item]
        + [str(item) for item in enriched.get("basic_red_flags") or [] if item]
    ))
    return reconcile_intake_result(enriched, documents_summary or {})


def _month_date_to_iso(match: re.Match[str]) -> str | None:
    raw = " ".join(match.groups())
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def infer_request_type(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in CASHLESS_KEYWORDS):
        return "cashless_pre_authorization"
    if "reimbursement" in lower:
        return "reimbursement"
    return "standard_claim"


def infer_procedure(text: str, docs: dict[str, Any]) -> str | None:
    lower = text.lower()
    if "acl" in lower and "reconstruction" in lower:
        return "ACL Reconstruction"
    for value in docs.get("all_references", []) + docs.get("all_vendors", []):
        if isinstance(value, str) and any(word in value.lower() for word in SURGERY_KEYWORDS):
            return value
    return None


def classify_documents(docs: dict[str, Any], email_body: str = "") -> dict[str, str]:
    filenames = documents_mentioned(docs)
    per_document = docs.get("per_document") or []
    classified: dict[str, str] = {}

    for item in per_document:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "").strip()
        if filename:
            classified[filename] = classify_document_text(
                " ".join(str(part) for part in (
                    filename,
                    item.get("document_type", ""),
                    item.get("summary", ""),
                ))
            )

    for filename in filenames:
        classified.setdefault(filename, classify_document_text(filename))

    return classified


def classify_document_text(text: str) -> str:
    lower = text.lower().replace("_", " ").replace("-", " ")
    for document_type, aliases in DOCUMENT_ALIASES.items():
        if any(alias in lower for alias in aliases):
            return document_type
    if lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "damage_photo"
    if lower.endswith(".pdf"):
        return "supporting_document"
    return "other"


def classify_document_mentions(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for document_type, aliases in DOCUMENT_ALIASES.items():
        if any(alias in lower for alias in aliases):
            found.append(document_type)
    return sorted(set(found))


def documents_mentioned(docs: dict[str, Any]) -> list[str]:
    candidates = docs.get("documents") or docs.get("documents_analyzed") or []
    if not candidates and docs.get("per_document"):
        candidates = [item.get("filename") for item in docs.get("per_document", []) if isinstance(item, dict)]
    return [str(item) for item in candidates if item]


def mandatory_missing_documents(
    claim_type: str,
    text: str,
    documents_received: list[str],
    has_policy_number: bool,
    docs: dict[str, Any],
) -> list[str]:
    if not docs:
        return [] if has_policy_number else ["policy_number"]

    required = set(MANDATORY_DOCUMENTS_BY_CLAIM_TYPE.get(claim_type, MANDATORY_DOCUMENTS_BY_CLAIM_TYPE["other"]))
    lower = text.lower()
    if claim_type == "health" and any(term in lower for term in SURGERY_KEYWORDS):
        required.update({"doctor_prescription", "hospital_estimate"})
        if "acl" in lower or "mri" in lower:
            required.add("mri_report")
    if claim_type == "health" and any(term in lower for term in CASHLESS_KEYWORDS):
        required.add("pre_authorization_form")
    if has_policy_number:
        required.discard("policy_number")

    missing = set(docs.get("missing_documents") or [])
    missing.update(required.difference(set(documents_received)))
    if claim_type == "property" and _has_property_valuation_evidence(documents_received, docs):
        missing.discard("repair_invoice")
    return sorted(str(item) for item in missing if item)


def detect_quality_issues(docs: dict[str, Any]) -> list[str]:
    issues = []
    haystack = " ".join(
        str(value)
        for value in [
            docs.get("aggregate_summary", ""),
            docs.get("analyst_notes", ""),
            " ".join(docs.get("risk_signals") or []),
        ]
    ).lower()
    if any(re.search(rf"\b{re.escape(term)}\b", haystack) for term in QUALITY_TERMS) or any(
        phrase in haystack for phrase in QUALITY_PHRASES
    ):
        issues.append("Document quality issue detected; request clearer copy or manual review.")
    for item in docs.get("per_document") or []:
        if isinstance(item, dict) and float(item.get("confidence") or 1.0) < 0.35:
            issues.append(f"{item.get('filename', 'document')} has low extraction confidence.")
    return sorted(set(issues))


def detect_consistency_issues(docs: dict[str, Any], claimant_name: str | None) -> list[dict[str, Any]]:
    names = [str(name).strip() for name in docs.get("all_vendors", []) if str(name).strip()]
    if claimant_name:
        names = [name for name in names if claimant_name.lower() not in name.lower()]
    unique_names = list(dict.fromkeys(names))
    if len(unique_names) >= 2:
        return [{
            "issue": "Multiple names or vendors found across documents; confirm claimant, provider, and beneficiary.",
            "values": unique_names[:5],
            "severity": "medium",
            "action": "send_to_human_or_request_confirmation",
        }]
    return []


def detect_basic_red_flags(text: str, docs: dict[str, Any], consistency_issues: list[dict[str, Any]]) -> list[str]:
    flags = [str(item) for item in docs.get("risk_signals") or [] if item]
    lower = " ".join([text, docs.get("aggregate_summary", ""), docs.get("analyst_notes", "")]).lower()
    if any(term in lower for term in RED_FLAG_TERMS):
        flags.append("Basic document red flag detected in claim text or document summary.")
    if consistency_issues:
        flags.append("Information mismatch across intake documents.")
    return sorted(set(flags))


def recommend_next_agent(intake_status: str, basic_red_flags: list[str]) -> str:
    if intake_status == "incomplete":
        return "customer_document_request"
    if basic_red_flags:
        return "fraud_agent_after_intake"
    return "coverage_agent"


def customer_message(missing_documents: list[str], quality_issues: list[str]) -> str | None:
    if missing_documents:
        pretty = ", ".join(item.replace("_", " ") for item in missing_documents)
        return f"Please upload the missing document(s) to continue claim processing: {pretty}."
    if quality_issues:
        return "Please upload a clearer copy of the flagged document(s) to continue claim processing."
    return None


def missing_information(
    policy: re.Match[str] | None,
    amount: float | None,
    incident_date: str | None,
    missing_documents: list[str],
) -> list[str]:
    missing = []
    if not policy:
        missing.append("policy_number")
    if amount is None:
        missing.append("claim_amount")
    if not incident_date:
        missing.append("incident_date")
    missing.extend(f"document:{item}" for item in missing_documents)
    return sorted(set(missing))


def _extract_claim_amount(text: str) -> float | None:
    for match in CLAIM_AMOUNT_CONTEXT_RE.finditer(text or ""):
        candidate = _parse_amount_match(match.group(1))
        if candidate and candidate >= 1000:
            return candidate

    for match in AMOUNT_RE.finditer(text or ""):
        prefix = text[max(0, match.start() - 80):match.start()].lower()
        if any(blocked in prefix for blocked in AMOUNT_CONTEXT_BLOCKLIST):
            continue
        raw_amount = match.group(1) or match.group(2)
        candidate = _parse_amount_match(raw_amount)
        if candidate and candidate >= 1000:
            return candidate
    return None


def _parse_amount_match(raw_amount: str | None) -> float | None:
    if not raw_amount:
        return None
    try:
        return float(raw_amount.replace(",", ""))
    except ValueError:
        return None


def reconcile_intake_result(enriched: dict[str, Any], documents_summary: dict[str, Any]) -> dict[str, Any]:
    """Remove contradictions introduced by model output or deterministic backfill."""
    policy_number = str(enriched.get("policy_number") or "").strip()
    claim_type = str(enriched.get("claim_type") or "").lower()
    documents_received = [str(item) for item in enriched.get("documents_received") or []]
    classified = enriched.get("classified_documents") if isinstance(enriched.get("classified_documents"), dict) else {}

    missing_documents = [str(item) for item in enriched.get("missing_documents") or [] if item]
    missing_information_values = [str(item) for item in enriched.get("missing_information") or [] if item]

    if policy_number:
        missing_documents = [item for item in missing_documents if item != "policy_number"]
        missing_information_values = [
            item for item in missing_information_values
            if item not in {"policy_number", "document:policy_number"}
        ]

    if claim_type == "property" and _has_property_valuation_evidence(documents_received, documents_summary, classified):
        missing_documents = [item for item in missing_documents if item not in {"repair_invoice", "repair_quote"}]
        missing_information_values = [
            item for item in missing_information_values
            if item not in {"document:repair_invoice", "document:repair_quote"}
        ]

    estimated_amount = _as_positive_amount(enriched.get("estimated_amount"))
    claim_amount = _as_positive_amount(enriched.get("claim_amount"))
    document_claim_amount = _best_document_claim_amount(documents_summary)
    if claim_amount <= 0:
        if document_claim_amount > 0:
            claim_amount = document_claim_amount
            enriched["claim_amount"] = document_claim_amount
        elif estimated_amount > 0:
            # A repair/hospital/damage estimate is a legitimate provisional claim
            # value for any claim type — better than reporting N/A downstream.
            claim_amount = estimated_amount
            enriched["claim_amount"] = estimated_amount
    if estimated_amount <= 0 and claim_amount > 0:
        enriched["estimated_amount"] = claim_amount
    if claim_amount > 0 or estimated_amount > 0:
        missing_information_values = [item for item in missing_information_values if item != "claim_amount"]

    enriched["missing_documents"] = sorted(set(missing_documents))
    enriched["missing_information"] = sorted(set(missing_information_values))
    if not enriched["missing_documents"] and enriched.get("message_to_customer"):
        text = str(enriched["message_to_customer"]).lower()
        if "missing document" in text or "upload" in text:
            enriched["message_to_customer"] = None
    if enriched.get("intake_status") == "incomplete" and not enriched["missing_documents"]:
        if enriched.get("quality_issues") or enriched.get("consistency_issues"):
            enriched["intake_status"] = "needs_review"
            enriched["next_recommended_agent"] = "human_reviewer"
        else:
            enriched["intake_status"] = "complete"
            enriched["next_recommended_agent"] = "coverage_agent"
    return enriched


def _has_property_valuation_evidence(
    documents_received: list[str],
    docs: dict[str, Any],
    classified: dict[str, Any] | None = None,
) -> bool:
    evidence = " ".join(documents_received).lower()
    evidence += " " + " ".join(str(value) for value in (classified or {}).values()).lower()
    evidence += " " + " ".join(str(key) for key in (classified or {}).keys()).lower()
    for item in docs.get("per_document") or []:
        if isinstance(item, dict):
            evidence += " " + " ".join(str(item.get(key) or "") for key in ("filename", "document_type", "summary")).lower()
    return any(term in evidence for term in ("repair_invoice", "repair quote", "contractor quote", "damage valuation", "damage_assessment", "damage assessment", "valuation", "loss assessor"))


def _as_positive_amount(value: Any) -> float:
    """Parse an amount from numbers or currency-marked strings.

    Handles "1580000", "15,80,000", "INR 1,580,000", "Rs. 2,85,000/-", "₹5000".
    Returns 0.0 when no positive number can be extracted.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else 0.0
    text = str(value)
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        amount = float(match.group(0).replace(",", ""))
    except ValueError:
        return 0.0
    return amount if amount > 0 else 0.0


# Field names in document extraction output that plausibly carry the claim value.
_AMOUNT_FIELD_HINTS = ("amount", "estimate", "total", "cost", "value", "bill")
# Fields that must never be mistaken for the claimed amount.
_AMOUNT_FIELD_BLOCKLIST = (
    "sum_insured",
    "policy_limit",
    "policy_amount",
    "policy_value",
    "coverage_limit",
    "deductible",
    "premium",
    "co_pay",
    "copay",
)
_NON_CLAIM_AMOUNT_DOCUMENT_TERMS = (
    "property_policy",
    "policy.pdf",
    "policy copy",
    "policy document",
    "insurance policy",
    "insurance_card",
    "insurance card",
    "health_card",
    "health card",
    "kyc",
    "id_card",
    "id card",
    "driving_license",
    "driving license",
)


def _best_document_claim_amount(docs: dict[str, Any]) -> float:
    """Best claim-amount candidate across analyzed documents.

    Scans exact keys first, then any extracted field whose name hints at an
    amount (excluding policy-side figures), then currency-marked figures in
    document summaries. Returns the max candidate, 0.0 if none.
    """
    candidates: list[float] = []
    for item in docs.get("per_document") or []:
        if not isinstance(item, dict):
            continue
        if _is_non_claim_amount_document(item):
            continue
        fields = item.get("extracted_fields") if isinstance(item.get("extracted_fields"), dict) else {}
        for key, raw in fields.items():
            key_l = str(key).lower()
            if any(blocked in key_l for blocked in _AMOUNT_FIELD_BLOCKLIST):
                continue
            if key_l in ("claimed_amount", "claim_amount", "estimated_amount") or any(
                hint in key_l for hint in _AMOUNT_FIELD_HINTS
            ):
                amount = _as_positive_amount(raw)
                if amount >= 100:  # ignore page counts, quantities, etc.
                    candidates.append(amount)
        # Currency-marked figures in the document summary text
        summary = str(item.get("summary") or "")
        for match in re.finditer(r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)", summary, re.IGNORECASE):
            amount = _as_positive_amount(match.group(1))
            if amount >= 100:
                candidates.append(amount)
    return max(candidates) if candidates else 0.0


def _is_non_claim_amount_document(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("filename", "document_type", "summary", "modality", "mime_type")
    ).lower().replace("-", "_")
    return any(term.replace("-", "_") in haystack for term in _NON_CLAIM_AMOUNT_DOCUMENT_TERMS)


def _first_doc_fact(docs: dict[str, Any], key: str) -> str | None:
    values = docs.get(key) or []
    return str(values[0]) if values else None
