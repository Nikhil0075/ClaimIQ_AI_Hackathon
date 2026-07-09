from io import BytesIO

from pypdf import PdfReader

from app.email_io import build_summary_email
from claimiq.tools.email_tool import _tpl_routing_assigned
from claimiq.tools.report_tool import generate_claim_report


def _outputs_with_numeric_priority():
    return {
        "intake": {
            "claimant_name": "Akash Chopra",
            "claim_type": "health",
            "policy_number": "HLTH-2024-00892",
            "incident_date": "2025-05-20",
            "claim_amount": 95000,
            "currency": "INR",
        },
        "coverage": {
            "coverage_status": "needs_review",
            "policy_status": "active",
            "policy_sections_referenced": [],
            "manual_review_required": True,
        },
        "fraud": {
            "fraud_score": 20,
            "risk_level": "low",
            "signals": [],
            "recommended_action": "continue_processing",
        },
        "triage": {
            "triage_color": "amber",
            "priority": 2,
            "routing": "standard_review",
            "required_human_approval": True,
            "sla_hours": 48,
            "recommended_next_steps": ["Human adjuster review."],
            "clinical_flags": [],
        },
        "copilot": {
            "executive_summary": "Assessment complete.",
            "open_questions": [],
            "routing_decision": {"requires_human_approval": True},
        },
    }


def test_routing_email_tolerates_numeric_priority():
    subject, body = _tpl_routing_assigned(
        "CLM-NUMERIC-PRIORITY",
        "Akash Chopra",
        "HEALTH",
        "HLTH-2024-00892",
        "INR 95,000",
        _outputs_with_numeric_priority()["coverage"],
        _outputs_with_numeric_priority()["fraud"],
        _outputs_with_numeric_priority()["triage"],
    )

    assert "CLM-NUMERIC-PRIORITY" in subject
    assert "Priority Level" in body


def test_routing_email_keeps_string_next_steps_as_single_item():
    outputs = _outputs_with_numeric_priority()
    outputs["triage"]["recommended_next_steps"] = "Obtain treating hospital discharge summary."

    _, body = _tpl_routing_assigned(
        "CLM-STRING-NEXT-STEPS",
        "Meera Sharma",
        "TRAVEL",
        "TRV123456",
        "INR 160,000",
        outputs["coverage"],
        outputs["fraud"],
        outputs["triage"],
    )

    assert "1. Obtain treating hospital discharge summary." in body
    assert "1. O\n  2. b" not in body


def test_summary_email_keeps_string_next_steps_as_single_item():
    outputs = _outputs_with_numeric_priority()
    outputs["triage"]["recommended_next_steps"] = "Obtain treating hospital discharge summary."

    body = build_summary_email("CLM-SUMMARY-STRING", outputs)

    assert "1. Obtain treating hospital discharge summary." in body
    assert "1. O\n  2. b" not in body


def test_report_generation_tolerates_numeric_priority():
    pdf_bytes = generate_claim_report("CLM-NUMERIC-PRIORITY", _outputs_with_numeric_priority())

    assert pdf_bytes
    assert pdf_bytes.startswith(b"%PDF")


def test_report_next_steps_keeps_string_as_single_item():
    outputs = _outputs_with_numeric_priority()
    outputs["triage"]["recommended_next_steps"] = "Assign to Motor Assessor."
    outputs["copilot"]["suggested_next_steps"] = ["Fraud investigator should review highlighted signals."]

    pdf_bytes = generate_claim_report("CLM-NEXT-STEPS-STRING", outputs)
    assert pdf_bytes

    text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(BytesIO(pdf_bytes)).pages
    )
    assert "Assign to Motor Assessor." in text
    assert "1. A\n2. s" not in text
