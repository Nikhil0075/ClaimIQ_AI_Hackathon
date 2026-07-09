"""OpenAI prompt/tooling for the Intake Agent."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from typing import Any

from claimiq.shared.openai_client import generate_json, generate_json_messages, image_content_part, is_rate_limit_error
from claimiq.shared.config import settings


INTAKE_REASONING_MODEL = os.getenv("CLAIMIQ_INTAKE_REASONING_MODEL", settings.reasoning_model)
INTAKE_VISION_MODEL = os.getenv("CLAIMIQ_INTAKE_VISION_MODEL", settings.vision_model)
INTAKE_TEXT_DOCUMENT_MODEL = os.getenv("CLAIMIQ_INTAKE_TEXT_DOCUMENT_MODEL", settings.lightweight_model)

SYSTEM_PROMPT = """You are the ClaimIQ Intake AI in a Track 1 insurance industry workflow.
Extract structured claim data from a free-form claim email and attached document
summaries. Your job is not to approve, deny, or adjudicate coverage. Your job is
to extract facts precisely as stated, flag ambiguities, and give downstream
agents complete context.

Extraction principles:
1. Extract only facts stated in the email or document summaries. Do not infer,
   guess, normalize into unsupported values, or hallucinate missing facts.
2. When sources conflict, preserve the most credible value in the top-level
   field only when the source basis is clear, and record the contradiction in
   consistency_issues. Use needs_review when the conflict affects identity,
   policy number, incident date, amount, claim type, or document authenticity.
3. Treat confidence_score as the confidence in intake completeness and
   extraction quality: high 0.80-1.00 means directly stated and coherent,
   medium 0.50-0.79 means partially stated or minor uncertainty, and low below
   0.50 means missing, conflicting, unreadable, or suspicious evidence.
4. Prefer explicit document evidence over email-only statements for dates,
   amounts, provider names, diagnosis, procedure, and patient details. If email
   and documents differ by about 30 days or more, add a date_discrepancy item to
   consistency_issues.
5. Keep source references inside intake_notes, claim_summary, consistency_issues,
   quality_issues, or classified_documents using existing fields. Do not add new
   top-level keys outside the schema.

Document dependency logic:
- health: needs policy_number plus doctor_prescription and hospital_estimate; a
  discharge summary or hospital bill can support the hospital_estimate slot when
  it contains provider/date/amount facts. Cashless pre-authorization needs a
  pre_authorization_form. Surgery or MRI claims need procedure evidence, and MRI
  evidence when MRI is mentioned.
- motor: needs policy_number plus repair_invoice; damage_photo and
  fir_or_police_report are required when accident, third party, theft, or police
  involvement is stated.
- property: needs policy_number plus damage_photo or repair_quote/repair_invoice.
- travel: needs policy_number and any incident-specific support that is actually
  mentioned in the email or documents.
- life: needs policy_number plus kyc_document or id_card; death claims also need
  death_certificate evidence when mentioned.

Routing decision tree:
- complete with no quality issues, consistency issues, or red flags:
  next_recommended_agent = coverage_agent.
- complete with two or more risk_indicators/basic_red_flags or strong document
  authenticity concern: next_recommended_agent = fraud_agent_after_intake.
- incomplete because required facts or documents are missing:
  next_recommended_agent = customer_document_request.
- needs_review because of conflicts, ambiguous identity, suspicious documents,
  unreadable critical documents, or uncertain claim type:
  next_recommended_agent = human_reviewer.

Risk signal taxonomy:
- Use risk_indicators for suspicious or fraud-adjacent signals such as
  tampered_appearance, duplicate_document, altered_amount, inconsistent_dates,
  identity_mismatch, policy_mismatch, provider_mismatch, ai_generated_text,
  inconsistent_formatting, unusual_urgency, or fabricated_policy_pattern.
- Use basic_red_flags for concise routing-level red flags that summarize why the
  claim should not go straight to coverage.
- Use quality_issues for evidence quality problems such as unreadable, blurry,
  cropped, rotated, missing signature, missing stamp, redacted critical field,
  low OCR confidence, or unsupported file.

Return strict JSON. Do not invent missing values."""

SCHEMA_PROMPT = """Return exactly this JSON shape and no extra top-level keys:
{
  "intake_status": "complete|incomplete|needs_review",
  "documents_received": [],
  "classified_documents": {},
  "missing_documents": [],
  "quality_issues": [],
  "consistency_issues": [],
  "basic_red_flags": [],
  "message_to_customer": "string or null",
  "next_recommended_agent": "coverage_agent|fraud_agent_after_intake|customer_document_request|human_reviewer",
  "claimant_name": "string or null",
  "patient_name": "string or null",
  "policy_number": "string or null",
  "claim_type": "motor|health|property|travel|life|other",
  "request_type": "cashless_pre_authorization|reimbursement|standard_claim",
  "incident_date": "YYYY-MM-DD or null",
  "incident_time": "HH:MM or null",
  "incident_description": "string",
  "claim_amount": 0,
  "estimated_amount": 0,
  "currency": "INR|USD|GBP|EUR|other",
  "location_of_incident": "string or null",
  "vehicle_registration": "string or null",
  "third_party_involved": true,
  "police_report_filed": true,
  "police_report_number": "string or null",
  "hospital_name": "string or null",
  "diagnosis": "string or null",
  "procedure": "string or null",
  "contact_phone": "string or null",
  "documents_mentioned": [],
  "risk_indicators": [],
  "claim_summary": "string",
  "confidence_score": 0.0,
  "missing_information": [],
  "intake_notes": "string"
}

Schema enforcement:
- intake_status must be one of complete, incomplete, or needs_review.
- Use incomplete when mandatory documents or mandatory facts are missing.
- Use needs_review when facts are present but conflicting, ambiguous, suspicious,
  or too low-confidence for automated downstream review.
- missing_documents must list only document/fact slots needed to continue, using
  names already used by the system such as policy_number, doctor_prescription,
  hospital_estimate, pre_authorization_form, repair_invoice, damage_photo,
  fir_or_police_report, kyc_document, mri_report, or supporting_document.
- classified_documents maps filename or source label to document type.
- consistency_issues may contain strings or small objects describing the
  conflicting field, values, sources, severity, and recommended action.
- quality_issues should describe document quality or extraction limitations.
- risk_indicators and basic_red_flags should be concise, non-duplicative lists.
- claim_amount is the strongest actual invoice/bill amount. estimated_amount is
  the estimate/pre-authorization amount. If multiple amounts conflict, choose the
  most credible explicit amount and record all conflict details in
  consistency_issues or intake_notes.
- Use null for unknown strings and 0 for unknown numeric amounts when required by
  this schema. Do not fabricate values to fill required keys.
- incident_date should be YYYY-MM-DD when known. Prefer incident date from a
  police report, claim form, or explicit incident statement; for health claims,
  do not confuse admission_date or document_date with incident_date unless the
  document explicitly makes it the claim event date.
- claim_summary and intake_notes should mention important source context, such as
  "email", "hospital_estimate", "discharge_summary", or filename labels."""


DOCUMENT_SCHEMA_PROMPT = """Return ONLY valid JSON with this shape and no extra top-level keys:
{
  "filename": "string",
  "document_type": "health_card|insurance_card|doctor_prescription|mri_report|hospital_estimate|pre_authorization_form|kyc_document|repair_invoice|repair_quote|damage_valuation|damage_photo|fire_brigade_report|fir_or_police_report|property_policy|supporting_document|other",
  "summary": "short factual summary",
  "extracted_fields": {
    "patient_name": "string or null",
    "policy_number": "string or null",
    "hospital_name": "string or null",
    "doctor_name": "string or null",
    "diagnosis": "string or null",
    "procedure": "string or null",
    "estimated_amount": 0,
    "claimed_amount": 0,
    "policy_amount": 0,
    "admission_date": "YYYY-MM-DD or null",
    "document_date": "YYYY-MM-DD or null",
    "incident_report_number": "string or null",
    "fir_number": "string or null",
    "license_number": "string or null",
    "property_address": "string or null",
    "damage_extent": "string or null"
  },
  "quality_issues": [],
  "risk_signals": [],
  "supports_claim": true,
  "confidence": 0.0
}

Document classification rules:
- Classify the document by visible content, not only filename. Use other when
  the type is uncertain.
- For policy documents, insurance cards, health cards, and ID/KYC documents, do
  not put sum insured, IDV, coverage limits, premium, deductible, or policy
  limit values into estimated_amount or claimed_amount. Use policy_amount only
  when a policy-side amount must be captured.
- Confidence high 0.80-1.00 means clear, legible, complete, and type is certain.
  Medium 0.50-0.79 means partially legible or missing minor fields. Low below
  0.50 means unreadable, heavily cropped, redacted, unsupported, or type is
  uncertain.
- Extract only visible/readable facts. Keep unknown values null or 0 as required
  by the schema.
- Flag quality_issues such as unreadable, blurry, cropped, rotated, cut_off,
  signature_missing, stamp_missing, doctor_name_missing, issuer_missing,
  document_date_missing, critical_field_redacted, or low_ocr_confidence.
- Flag risk_signals such as tampered_appearance, altered_amount,
  inconsistent_formatting, duplicate_document, ai_generated_text,
  policy_mismatch, identity_mismatch, date_discrepancy, or suspicious_provider.
- supports_claim is true only when the document clearly relates to the submitted
  claim. Use false when it appears unrelated, and null when the relationship is
  unclear.
- Include issuer/provider names, dates, signatures/stamps, amounts, diagnosis,
  procedure, property address, report numbers, FIR numbers, damage extent,
  fraud alerts, and policy or patient identifiers in summary when visible."""


def extract_claim(
    email_body: str,
    documents_summary: dict[str, Any] | None = None,
    uploaded_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    multimodal_summary = extract_multimodal_documents(uploaded_documents or [])
    combined_summary = merge_document_summaries(documents_summary, multimodal_summary)
    prompt = f"""{SYSTEM_PROMPT}

CLAIM EMAIL:
{email_body[:6000]}

DOCUMENT SUMMARY:
{json.dumps(combined_summary or {}, indent=2, default=str)[:7000]}

{SCHEMA_PROMPT}
"""
    result = generate_json(
        prompt,
        temperature=0.1,
        max_tokens=int(os.getenv("CLAIMIQ_INTAKE_REASONING_MAX_TOKENS", "8192")),
        model=os.getenv("CLAIMIQ_INTAKE_REASONING_MODEL", INTAKE_REASONING_MODEL),
    )
    result["_combined_documents_summary"] = combined_summary
    return result


def extract_multimodal_documents(uploaded_documents: list[dict[str, Any]]) -> dict[str, Any]:
    per_document = []
    for document in uploaded_documents:
        try:
            result = analyze_uploaded_document(document)
        except Exception as exc:
            if is_rate_limit_error(exc):
                result = {
                    "filename": document.get("filename", "unknown"),
                    "document_type": "other",
                    "summary": "Multimodal extraction was temporarily rate limited by the OpenAI API; retry this document.",
                    "extracted_fields": {},
                    "quality_issues": [],
                    "risk_signals": [],
                    "supports_claim": None,
                    "confidence": 0.0,
                    "error": str(exc),
                    "error_type": "rate_limit_exceeded",
                    "retryable": True,
                }
            else:
                result = {
                    "filename": document.get("filename", "unknown"),
                    "document_type": "other",
                    "summary": f"Multimodal extraction failed: {exc}",
                    "extracted_fields": {},
                    "quality_issues": ["multimodal_extraction_failed"],
                    "risk_signals": [],
                    "supports_claim": None,
                    "confidence": 0.0,
                    "error": str(exc),
                }
        per_document.append(result)

    if not per_document:
        return {}

    return {
        "total_documents": len(uploaded_documents),
        "documents_analyzed": [item.get("filename") for item in per_document if item.get("filename")],
        "aggregate_summary": " | ".join(str(item.get("summary", "")) for item in per_document if item.get("summary")),
        "risk_signals": _unique_flatten(per_document, "risk_signals"),
        "missing_documents": [],
        "per_document": per_document,
        "modalities": sorted(set(str(item.get("modality") or "unknown") for item in per_document)),
        "source": "intake_multimodal",
    }


def analyze_uploaded_document(document: dict[str, Any]) -> dict[str, Any]:
    filename = str(document.get("filename") or "uploaded_document")
    mime_type = str(document.get("mime_type") or "application/octet-stream")
    data = document.get("data")
    if not isinstance(data, bytes):
        raise ValueError("uploaded document data must be bytes")

    if mime_type.startswith("image/"):
        result = _analyze_image_document(filename, mime_type, data)
        result.setdefault("modality", "image")
        result.setdefault("mime_type", mime_type)
        return result

    text = _extract_text_document(filename, mime_type, data)
    if text:
        result = _analyze_text_document(filename, mime_type, text)
        result.setdefault("modality", "pdf" if mime_type == "application/pdf" else "text")
        result.setdefault("mime_type", mime_type)
        return result

    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        rendered = _render_pdf_first_page(data)
        if rendered:
            image_data, image_mime_type = rendered
            result = _analyze_image_document(filename, image_mime_type, image_data, source_modality="scanned_pdf")
            result.setdefault("modality", "pdf_image")
            result.setdefault("mime_type", mime_type)
            result.setdefault("rendered_from_pdf", True)
            return result

    return {
        "filename": filename,
        "document_type": "supporting_document",
        "summary": "Document received, but Intake could not extract readable text or pixels for model analysis.",
        "extracted_fields": {},
        "quality_issues": ["unreadable_or_unsupported_document"],
        "risk_signals": [],
        "supports_claim": None,
        "confidence": 0.1,
        "modality": mime_type,
        "mime_type": mime_type,
    }


def merge_document_summaries(
    documents_summary: dict[str, Any] | None,
    multimodal_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    base = dict(documents_summary or {})
    if not multimodal_summary:
        return base

    base["total_documents"] = max(
        int(base.get("total_documents") or 0),
        int(multimodal_summary.get("total_documents") or 0),
    )
    base["documents_analyzed"] = sorted(set(
        [str(item) for item in base.get("documents_analyzed") or base.get("documents") or [] if item]
        + [str(item) for item in multimodal_summary.get("documents_analyzed") or [] if item]
    ))
    base["aggregate_summary"] = " | ".join(
        item for item in [
            str(base.get("aggregate_summary") or "").strip(),
            str(multimodal_summary.get("aggregate_summary") or "").strip(),
        ]
        if item
    )
    multimodal_per_doc = list(multimodal_summary.get("per_document") or [])
    rendered_pdf_names = {
        str(item.get("filename"))
        for item in multimodal_per_doc
        if isinstance(item, dict) and item.get("rendered_from_pdf") and item.get("filename")
    }
    risk_signals = [str(item) for item in base.get("risk_signals") or [] if item]
    if rendered_pdf_names:
        risk_signals = [item for item in risk_signals if item != "manual_review_needed_for_unreadable_document"]
    risk_signals += [str(item) for item in multimodal_summary.get("risk_signals") or [] if item]
    base["risk_signals"] = sorted(set(risk_signals))

    per_doc_by_name: dict[str, dict[str, Any]] = {}
    unnamed_docs = []
    for item in list(base.get("per_document") or []) + multimodal_per_doc:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "")
        if filename:
            per_doc_by_name[filename] = item
        else:
            unnamed_docs.append(item)
    base["per_document"] = unnamed_docs + list(per_doc_by_name.values())
    base["modalities"] = sorted(set(
        [str(item) for item in base.get("modalities") or [] if item]
        + [str(item) for item in multimodal_summary.get("modalities") or [] if item]
    ))
    base["intake_multimodal_source"] = bool(multimodal_summary.get("per_document"))
    return base


def _analyze_image_document(
    filename: str,
    mime_type: str,
    data: bytes,
    *,
    source_modality: str = "image",
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are the ClaimIQ multimodal Intake Agent. Read insurance "
                "claim document images precisely. Extract only visible facts, "
                "classify the document by content, and flag blurry, cropped, "
                "rotated, redacted, missing-signature, missing-stamp, tampered, "
                "or inconsistent evidence through the existing JSON fields."
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Analyze uploaded claim document image: {filename}\n"
                        f"SOURCE_MODALITY: {source_modality}\n"
                        "Check document type, issuer/provider, visible dates, "
                        "patient or claimant names, policy identifiers, amounts, "
                        "property address, report/FIR numbers, damage extent, "
                        "fraud/investigation alerts, signatures/stamps, quality issues, "
                        "and risk signals. If the image is unclear, say so in "
                        "quality_issues and lower confidence.\n\n"
                        f"{DOCUMENT_SCHEMA_PROMPT}"
                    ),
                },
                image_content_part(data, mime_type),
            ],
        },
    ]
    return generate_json_messages(
        messages,
        temperature=0.05,
        max_tokens=4096,
        model=os.getenv("CLAIMIQ_INTAKE_VISION_MODEL", INTAKE_VISION_MODEL),
    )


def _analyze_text_document(filename: str, mime_type: str, text: str) -> dict[str, Any]:
    prompt = f"""You are the ClaimIQ multimodal Intake Agent.
Analyze this uploaded claim document and extract only facts present in the text.
Classify by content, not only filename. Capture issuer/provider, visible dates,
patient or claimant names, policy identifiers, amounts, diagnosis/procedure, and
any signature/stamp/authorization references when text indicates them. If text
is incomplete, contradictory, redacted, OCR-noisy, or unrelated to the submitted
claim, record that in quality_issues, risk_signals, supports_claim, and
confidence using the schema below.

FILENAME: {filename}
MIME_TYPE: {mime_type}
DOCUMENT TEXT:
{text[:6000]}

{DOCUMENT_SCHEMA_PROMPT}
"""
    return generate_json(
        prompt,
        temperature=0.05,
        max_tokens=4096,
        model=os.getenv("CLAIMIQ_INTAKE_TEXT_DOCUMENT_MODEL", INTAKE_TEXT_DOCUMENT_MODEL),
    )


def _extract_text_document(filename: str, mime_type: str, data: bytes) -> str:
    if mime_type.startswith("text/") or filename.lower().endswith((".txt", ".csv")):
        return data.decode("utf-8", errors="replace")
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        try:
            import io
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages[:5]).strip()
        except Exception:
            return ""
    return ""


def _render_pdf_first_page(data: bytes) -> tuple[bytes, str] | None:
    pdftoppm = _pdftoppm_path()
    if pdftoppm:
        tmp = None
        try:
            base_tmp = _pdf_render_tmp_dir()
            tmp = os.path.join(base_tmp, f"claimiq_pdf_{uuid.uuid4().hex}")
            os.makedirs(tmp, exist_ok=True)
            pdf_path = os.path.join(tmp, "document.pdf")
            prefix = os.path.join(tmp, "page")
            with open(pdf_path, "wb") as handle:
                handle.write(data)
            subprocess.run(
                [pdftoppm, "-png", "-f", "1", "-l", "1", "-r", "150", pdf_path, prefix],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            rendered_path = os.path.join(tmp, "page-1.png")
            if os.path.exists(rendered_path):
                with open(rendered_path, "rb") as handle:
                    return handle.read(), "image/png"
        except Exception:
            pass
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    return _extract_first_pdf_image(data)


def _extract_first_pdf_image(data: bytes) -> tuple[bytes, str] | None:
    try:
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        for page in reader.pages[:3]:
            images = list(getattr(page, "images", []) or [])
            if not images:
                continue
            image = max(images, key=lambda item: len(getattr(item, "data", b"") or b""))
            image_data = getattr(image, "data", b"") or b""
            if not image_data:
                continue
            name = str(getattr(image, "name", "") or "").lower()
            if name.endswith((".jpg", ".jpeg")):
                return image_data, "image/jpeg"
            if name.endswith(".png"):
                return image_data, "image/png"
            return image_data, "image/jpeg"
    except Exception:
        return None
    return None


def _pdf_render_tmp_dir() -> str:
    root = os.getenv("CLAIMIQ_PDF_RENDER_TMP") or os.path.join(os.getcwd(), "tmp", "pdfs", "claimiq_render")
    os.makedirs(root, exist_ok=True)
    return root


def _pdftoppm_path() -> str | None:
    configured = os.getenv("PDFTOPPM_PATH")
    if configured and os.path.exists(configured):
        return configured
    bundled = os.path.join(
        os.path.expanduser("~"),
        ".cache",
        "codex-runtimes",
        "codex-primary-runtime",
        "dependencies",
        "native",
        "poppler",
        "Library",
        "bin",
        "pdftoppm.exe",
    )
    if os.path.exists(bundled):
        return bundled
    found = shutil.which("pdftoppm")
    if found:
        return found
    return None


def _unique_flatten(items: list[dict[str, Any]], key: str) -> list[str]:
    values = []
    for item in items:
        raw = item.get(key) or []
        if isinstance(raw, str):
            values.append(raw)
        else:
            values.extend(str(value) for value in raw if value)
    return sorted(set(values))
