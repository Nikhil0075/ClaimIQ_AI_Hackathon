"""Front-door relevance and format guard for incoming claim emails."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from claimiq.shared.config import settings
from claimiq.shared.openai_client import generate_json

CLAIM_KEYWORDS = {
    "claim", "policy", "accident", "hospital", "medical", "repair", "invoice",
    "fir", "damage", "vehicle", "insurance", "incident", "loss", "theft",
}
REQUIRED_FIELDS = ("claimant_name", "policy_number", "incident_date", "incident_description")


def evaluate_email(email_body: str, subject: str = "") -> dict[str, Any]:
    text = f"{subject}\n{email_body}".strip()
    try:
        result = _evaluate_with_openai(text)
        return _normalize_guard(result, text)
    except Exception as exc:
        result = _deterministic_guard(text)
        result["_fallback_reason"] = str(exc)
        return result


def _evaluate_with_openai(text: str) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    prompt = f"""You are the ClaimIQ Insurance Claims Front-Door Guard.
Your job is binary: decide whether this email contains enough valid claim
information to proceed to the Intake Agent, or whether the customer must resend
the claim using the structured form.

Current date: {today}. Use this exact date when deciding whether an incident
date is future-dated. Do not reject an otherwise complete claim only because
the incident date is old; downstream coverage/triage agents handle stale or
legacy timing review.

Return "proceed" only when the email is a legitimate, single insurance claim
submission with enough quality for intake. Return "rewrite_request" for general
questions, vague intent to claim, missing or placeholder facts, suspicious mail,
spam/phishing, multi-claim chains, or anything that would waste downstream agent
capacity.

Current output schema is fixed. Return ONLY valid JSON and leave reply_subject
and reply_body as empty strings because the system will generate them:
{{
  "action": "proceed|rewrite_request",
  "is_relevant": true,
  "missing_fields": ["policy_number", "incident_date", ...],
  "reason": "short internal reason",
  "reply_subject": "",
  "reply_body": "",
  "confidence": 0.0
}}

Mandatory fields for proceed:
- Claimant full name: first and last name, not only initials or first name.
- Policy number: plausible insurance policy identifier. Prefer Indian-style
  patterns such as two or three letters followed by 6-12 digits; also accept
  existing ClaimIQ demo prefixes such as POL, CLM, HLT, HLTH, MTR, or INS followed by
  enough digits. Reject placeholders, partial values, repeated digits, and fake
  examples such as 111111, 000000, ABCDEF000000, POLICY123, or unknown.
- Incident date: a valid date, not in the future. Older incident dates are not
  a mail-guard blocker when the claim otherwise contains enough intake facts.
- Incident location: city, area, hospital, workshop, police station, or other
  specific place. Reject vague locations such as "there", "near home", or
  "somewhere".
- Brief description: at least about 50 meaningful characters describing what
  happened. Reject boilerplate such as "I need to claim", "please process my
  claim", or a copied blank template.

Validation rules:
1. If claimant name is incomplete, add "claimant_name" to missing_fields and
   return "rewrite_request".
2. If policy number is absent, partial, malformed, placeholder-like, or visibly
   fabricated, add "policy_number" and return "rewrite_request" unless the
   rest of the email gives exceptionally strong claim evidence and confidence
   is above 0.90.
3. If incident date is absent, invalid, or future-dated, add "incident_date"
   and return "rewrite_request". Do not use date age alone as a rewrite reason.
4. If location is absent or vague, add "incident_location" and return
   "rewrite_request".
5. If the description is too short, templated, or only a general enquiry, add
   "incident_description" and return "rewrite_request".
6. If the email appears to contain more than one claim submission, forwarded
   chain, or many unrelated incidents, return "rewrite_request" and explain
   that one claim should be submitted at a time.
7. Treat obvious spam, phishing, credential requests, payment links, threats,
   malware language, mismatched corporate domains, disposable-looking sender
   claims, fake urgency, or fabricated incident patterns as not relevant enough
   for intake. Return "rewrite_request" with low confidence.
8. If metadata such as sender domain, SPF, DKIM, or headers are present in the
   email text, use them as supporting evidence. Do not invent metadata that is
   absent. Suspicious or failed authentication metadata should lower confidence.

Confidence guidance:
- High confidence, above 0.85: all mandatory fields are present and plausible.
- Medium confidence, 0.50-0.85: claim-related but some quality concerns; choose
  "proceed" only if the mandatory fields are still present and coherent.
- Low confidence, below 0.50: missing, vague, suspicious, or general enquiry;
  choose "rewrite_request".

Populate missing_fields only with existing downstream-friendly field names such
as "claimant_name", "policy_number", "incident_date", "incident_location", and
"incident_description". Keep reason short and internal. is_relevant should be
true only for a usable or near-usable insurance claim email, not for generic
insurance questions.

EMAIL:
{text[:6000]}
"""
    return generate_json(
        prompt,
        temperature=0.0,
        max_tokens=2048,
        model=os.getenv("CLAIMIQ_MAIL_GUARD_MODEL", settings.lightweight_model),
    )


def _deterministic_guard(text: str) -> dict[str, Any]:
    lower = text.lower()
    relevant_hits = [word for word in CLAIM_KEYWORDS if word in lower]
    is_relevant = len(relevant_hits) >= 2
    missing = []
    if not re.search(r"\b(?:(?:POL|CLM|HLT|HLTH|MTR|INS)[- ]?\d{4,}|[A-Z]{2,3}[- ]?\d{6,12})\b", text, re.IGNORECASE):
        missing.append("policy_number")
    if not re.search(r"\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+20\d{2}|\d{1,2}[-/]\d{1,2}[-/]20\d{2})\b", text, re.IGNORECASE):
        missing.append("incident_date")
    if not re.search(r"\b(?:Claimant|Full Name|Name)\s*:", text, re.IGNORECASE):
        missing.append("claimant_name")
    if len(text) < 80:
        missing.append("incident_description")

    looks_like_general_inquiry = any(phrase in lower for phrase in ("procedure to claim", "how to claim", "want to know", "how can i claim"))
    lacks_core_claim = "policy_number" in missing and "incident_date" in missing
    action = (
        "proceed"
        if is_relevant and not looks_like_general_inquiry and not lacks_core_claim and len(missing) < len(REQUIRED_FIELDS)
        else "rewrite_request"
    )
    return {
        "action": action,
        "is_relevant": is_relevant,
        "missing_fields": sorted(set(missing)),
        "reason": "Email appears claim-related." if action == "proceed" else "Email is not a usable insurance claim submission.",
        "reply_subject": "Please resend your insurance claim details",
        "reply_body": _rewrite_body(sorted(set(missing))),
        "confidence": 0.65 if is_relevant else 0.4,
    }


def _normalize_guard(result: dict[str, Any], text: str) -> dict[str, Any]:
    if result.get("action") not in {"proceed", "rewrite_request"}:
        result["action"] = "rewrite_request"
    result.setdefault("is_relevant", result["action"] == "proceed")
    result.setdefault("missing_fields", [])
    result.setdefault("reason", "")
    result.setdefault("confidence", 0.5)
    # Always use the structured form template — ignore any LLM-composed reply_body/subject
    result["reply_subject"] = ""   # run.py forces "Re: <original subject>" anyway
    result["reply_body"] = _rewrite_body(result.get("missing_fields", []))
    if not text.strip():
        result["action"] = "rewrite_request"
        result["is_relevant"] = False
    _correct_false_incident_date_rewrite(result, text)
    return result


def _correct_false_incident_date_rewrite(result: dict[str, Any], text: str) -> None:
    if result.get("action") != "rewrite_request":
        return
    missing = [str(item) for item in result.get("missing_fields") or []]
    reason = str(result.get("reason") or "").lower()
    date_related = "incident_date" in missing or "incident date" in reason or "future" in reason or "stale" in reason
    if not date_related or not _has_non_future_incident_date(text):
        return
    fallback = _deterministic_guard(text)
    if fallback.get("action") != "proceed":
        return
    result["action"] = "proceed"
    result["is_relevant"] = True
    result["missing_fields"] = [item for item in missing if item != "incident_date"]
    result["reason"] = "Email contains a non-future incident date and enough claim facts for intake."
    result["confidence"] = max(float(result.get("confidence") or 0.0), 0.75)
    result["reply_body"] = _rewrite_body(result.get("missing_fields", []))


def _has_non_future_incident_date(text: str) -> bool:
    today = datetime.now(timezone.utc).date()
    for raw in _incident_date_candidates(text):
        parsed = _parse_guard_date(raw)
        if parsed and parsed <= today:
            return True
    return False


def _incident_date_candidates(text: str) -> list[str]:
    patterns = (
        r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b",
        r"\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+20\d{2}\b",
    )
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(match.group(0) for match in re.finditer(pattern, text))
    return candidates


def _parse_guard_date(raw: str):
    raw = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", raw, flags=re.IGNORECASE)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _rewrite_body(missing_fields: list[str]) -> str:
    missing_note = (
        f"We specifically could not find: {', '.join(f.replace('_', ' ') for f in missing_fields)}.\n\n"
        if missing_fields else ""
    )
    return (
        "Dear Customer,\n\n"
        "Thank you for reaching out to ClaimIQ. We received your message but need a few more\n"
        "details to register and process your insurance claim.\n\n"
        + missing_note +
        "Please reply to this email with the completed form below — just copy it, fill in\n"
        "the blanks, and hit Send. Attach any supporting documents to the same reply.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  INSURANCE CLAIM SUBMISSION FORM\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  Full Name (Claimant)    : ___________________________\n"
        "  Policy Number           : ___________________________\n"
        "  Date of Incident        : ___________________________  (DD MMM YYYY)\n"
        "  Location of Incident    : ___________________________\n"
        "  Description of Incident : ___________________________\n"
        "                            ___________________________\n"
        "  Claim Amount (₹)        : ___________________________\n"
        "  Contact Number          : ___________________________\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  SUPPORTING DOCUMENTS  (attach to your reply)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "  [ ] Hospital Discharge Summary / Repair Estimate / Invoice\n"
        "  [ ] Doctor's Prescription / Police FIR  (if applicable)\n"
        "  [ ] Lab Reports / Damage Photos          (if applicable)\n"
        "  [ ] Any other relevant documents\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Once we receive the completed form, our AI pipeline will begin reviewing your\n"
        "claim immediately and you will receive a Claim Reference number within minutes.\n\n"
        "Regards,\n"
        "ClaimIQ Automated Claims Team"
    )
