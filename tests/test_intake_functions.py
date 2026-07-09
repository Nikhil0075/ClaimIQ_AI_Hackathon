from pathlib import Path

from claimiq.agents.intake.functions import deterministic_extract, detect_quality_issues, enrich_intake_result
from claimiq.agents.intake.tool import analyze_uploaded_document, extract_multimodal_documents, merge_document_summaries


def test_deterministic_extract_does_not_use_policy_number_as_amount():
    result = deterministic_extract(
        "Policy POL-482913. Repair estimate is INR 185000 after accident."
    )
    assert result["policy_number"] == "POL-482913"
    assert result["claim_amount"] == 185000


def test_health_cashless_claim_identifies_missing_mandatory_documents():
    result = deterministic_extract(
        "Cashless pre-authorization for Policy HLT-78901. Patient: Aarav Sen. "
        "Procedure: ACL Reconstruction at Apollo Hospital. Estimate INR 280000.",
        {
            "total_documents": 2,
            "documents_analyzed": ["health_card.pdf", "mri_report.pdf"],
            "per_document": [
                {"filename": "health_card.pdf", "document_type": "health card", "confidence": 0.9},
                {"filename": "mri_report.pdf", "document_type": "MRI report", "confidence": 0.9},
            ],
            "risk_signals": [],
        },
    )

    assert result["claim_type"] == "health"
    assert result["request_type"] == "cashless_pre_authorization"
    assert result["intake_status"] == "incomplete"
    assert "pre_authorization_form" in result["missing_documents"]
    assert "doctor_prescription" in result["missing_documents"]
    assert result["next_recommended_agent"] == "customer_document_request"


def test_intake_merges_multimodal_document_summary():
    result = merge_document_summaries(
        {"documents_analyzed": ["email_summary.txt"], "risk_signals": ["email_risk"]},
        {
            "total_documents": 1,
            "documents_analyzed": ["estimate.png"],
            "aggregate_summary": "Hospital estimate image read by vision model.",
            "risk_signals": ["image_risk"],
            "per_document": [{"filename": "estimate.png", "document_type": "hospital_estimate"}],
            "modalities": ["image"],
        },
    )

    assert result["intake_multimodal_source"] is True
    assert result["documents_analyzed"] == ["email_summary.txt", "estimate.png"]
    assert result["risk_signals"] == ["email_risk", "image_risk"]
    assert result["per_document"][0]["filename"] == "estimate.png"


def test_multimodal_pdf_replaces_unreadable_attachment_summary():
    result = merge_document_summaries(
        {
            "documents_analyzed": ["Police FIR.pdf"],
            "risk_signals": ["manual_review_needed_for_unreadable_document"],
            "per_document": [
                {
                    "filename": "Police FIR.pdf",
                    "document_type": "scanned_pdf",
                    "summary": "scanned_pdf received. Text/visual extraction was not available.",
                    "confidence": 0.25,
                }
            ],
        },
        {
            "documents_analyzed": ["Police FIR.pdf"],
            "risk_signals": ["fraud_pattern_suspected"],
            "per_document": [
                {
                    "filename": "Police FIR.pdf",
                    "document_type": "fir_or_police_report",
                    "summary": "FIR number NPR/2025/56789 visible.",
                    "rendered_from_pdf": True,
                    "confidence": 0.92,
                }
            ],
            "modalities": ["pdf_image"],
        },
    )

    assert result["risk_signals"] == ["fraud_pattern_suspected"]
    assert len(result["per_document"]) == 1
    assert result["per_document"][0]["document_type"] == "fir_or_police_report"


def test_multimodal_rate_limit_is_retryable_not_quality_issue(monkeypatch):
    class FakeRateLimitError(Exception):
        status_code = 429

    def fake_analyze_uploaded_document(document):
        raise FakeRateLimitError("Rate limit reached. Please try again in 181ms.")

    monkeypatch.setattr("claimiq.agents.intake.tool.analyze_uploaded_document", fake_analyze_uploaded_document)

    result = extract_multimodal_documents([
        {
            "filename": "Insurance_Card.png",
            "mime_type": "image/png",
            "data": b"fake",
        }
    ])

    doc = result["per_document"][0]
    assert doc["error_type"] == "rate_limit_exceeded"
    assert doc["retryable"] is True
    assert doc["quality_issues"] == []
    assert "rate limited" in doc["summary"].lower()


def test_acute_appendicitis_does_not_trigger_cut_quality_issue():
    result = detect_quality_issues({
        "aggregate_summary": "Patient had acute appendicitis and emergency laparoscopic appendectomy.",
        "analyst_notes": "Medical narrative is internally consistent.",
        "risk_signals": [],
        "per_document": [{"filename": "discharge.pdf", "confidence": 0.93}],
    })

    assert result == []


def test_property_fire_reconciles_policy_and_damage_assessment_missing_docs():
    docs = {
        "documents_analyzed": ["Damage Assessment & Valuation.pdf", "property_fire_01.png"],
        "per_document": [
            {
                "filename": "Damage Assessment & Valuation.pdf",
                "document_type": "damage_valuation",
                "summary": "Total claimed damage Rs. 15,80,000 with independent valuation notes.",
                "confidence": 0.9,
            },
            {"filename": "property_fire_01.png", "document_type": "damage_photo", "confidence": 0.9},
        ],
        "risk_signals": [],
    }
    ai_result = {
        "intake_status": "incomplete",
        "claim_type": "property",
        "policy_number": "PRO234567",
        "estimated_amount": 1580000,
        "claim_amount": 0,
        "documents_received": ["damage_valuation", "damage_photo"],
        "missing_documents": ["policy_number", "repair_invoice"],
        "missing_information": ["claim_amount", "policy_number", "document:repair_invoice"],
        "message_to_customer": "Please upload the missing document(s): policy number, repair invoice.",
    }

    result = enrich_intake_result(ai_result, "Policy Number: PRO234567. Fire damage. Estimated damage value: Rs 15,80,000", docs)

    assert result["missing_documents"] == []
    assert "policy_number" not in result["missing_information"]
    assert "claim_amount" not in result["missing_information"]
    assert result["claim_amount"] == 1580000
    assert result["intake_status"] == "complete"


def test_property_fire_uses_document_claimed_amount_when_top_level_amount_is_zero():
    docs = {
        "documents_analyzed": ["Damage Assessment & Valuation.pdf"],
        "per_document": [
            {
                "filename": "Damage Assessment & Valuation.pdf",
                "document_type": "damage_valuation",
                "extracted_fields": {
                    "estimated_amount": 600000,
                    "claimed_amount": 1580000,
                    "policy_amount": 4000000,
                },
                "confidence": 0.85,
            }
        ],
        "risk_signals": [],
    }
    ai_result = {
        "intake_status": "complete",
        "claim_type": "property",
        "policy_number": "PRO234567",
        "estimated_amount": 1580000,
        "claim_amount": 0,
        "documents_received": ["damage_valuation"],
        "missing_documents": [],
        "missing_information": [],
    }

    result = enrich_intake_result(ai_result, "Policy Number: PRO234567. Fire damage.", docs)

    assert result["claim_amount"] == 1580000


def test_motor_email_claim_amount_beats_policy_card_limit():
    email_body = Path("tests/Motor Claim - Car Accident/mail.txt").read_text(encoding="utf-8")
    docs = {
        "documents_analyzed": ["Insurance_Card.png", "Repair_Estimate_from_Quick_Fix_Motors.pdf"],
        "per_document": [
            {
                "filename": "Insurance_Card.png",
                "document_type": "insurance_card",
                "summary": "Motor insurance card for MCA789012 with IDV Rs 4,50,000.",
                "extracted_fields": {"estimated_amount": 450000, "claimed_amount": 0, "policy_amount": 0},
                "confidence": 0.85,
            },
            {
                "filename": "Repair_Estimate_from_Quick_Fix_Motors.pdf",
                "document_type": "repair_quote",
                "summary": "Repair estimate from Quick Fix Motors. Total estimate amount is Rs 169,050.",
                "extracted_fields": {"estimated_amount": 169050, "claimed_amount": 0, "policy_amount": 0},
                "confidence": 0.85,
            },
        ],
        "risk_signals": [],
    }
    ai_result = {
        "intake_status": "complete",
        "claim_type": "motor",
        "policy_number": "MCA789012",
        "claim_amount": 0,
        "estimated_amount": 169050,
        "missing_documents": [],
        "missing_information": ["claim_amount"],
    }

    result = enrich_intake_result(ai_result, email_body, docs)

    assert result["claim_amount"] == 160000
    assert result["estimated_amount"] == 169050
    assert "claim_amount" not in result["missing_information"]


def test_document_claim_amount_ignores_policy_card_limit_when_email_amount_missing():
    docs = {
        "documents_analyzed": ["Insurance_Card.png", "Repair_Estimate_from_Quick_Fix_Motors.pdf"],
        "per_document": [
            {
                "filename": "Insurance_Card.png",
                "document_type": "insurance_card",
                "summary": "Motor insurance card for MCA789012 with IDV Rs 4,50,000.",
                "extracted_fields": {"estimated_amount": 450000, "claimed_amount": 0, "policy_amount": 0},
                "confidence": 0.85,
            },
            {
                "filename": "Repair_Estimate_from_Quick_Fix_Motors.pdf",
                "document_type": "repair_quote",
                "summary": "Repair estimate from Quick Fix Motors. Total estimate amount is Rs 169,050.",
                "extracted_fields": {"estimated_amount": 169050, "claimed_amount": 0, "policy_amount": 0},
                "confidence": 0.85,
            },
        ],
        "risk_signals": [],
    }
    ai_result = {
        "intake_status": "complete",
        "claim_type": "motor",
        "policy_number": "MCA789012",
        "claim_amount": 0,
        "estimated_amount": 0,
        "missing_documents": [],
        "missing_information": ["claim_amount"],
    }

    result = enrich_intake_result(ai_result, "Policy Number: MCA789012. Car accident near Noida.", docs)

    assert result["claim_amount"] == 169050
    assert result["estimated_amount"] == 169050


def test_motor_repair_estimate_satisfies_repair_invoice_slot():
    docs = {
        "documents_analyzed": ["Repair_Estimate_from_Quick_Fix_Motors.pdf", "damage_photo_01.png"],
        "per_document": [
            {
                "filename": "Repair_Estimate_from_Quick_Fix_Motors.pdf",
                "document_type": "repair_estimate",
                "summary": "Repair estimate from Quick Fix Motors. Total estimate amount is Rs 1,69,050.",
                "extracted_fields": {"estimated_amount": 169050},
                "confidence": 0.95,
            },
            {
                "filename": "damage_photo_01.png",
                "document_type": "damage_photo",
                "summary": "Vehicle damage photo.",
                "confidence": 0.85,
            },
        ],
        "risk_signals": [],
    }
    ai_result = {
        "intake_status": "incomplete",
        "claim_type": "motor",
        "policy_number": "MCA789012",
        "claim_amount": 160000,
        "estimated_amount": 169050,
        "documents_received": ["Repair_Estimate_from_Quick_Fix_Motors.pdf", "damage_photo_01.png"],
        "classified_documents": {
            "Repair_Estimate_from_Quick_Fix_Motors.pdf": "repair_estimate",
            "damage_photo_01.png": "damage_photo",
        },
        "missing_documents": ["repair_invoice"],
        "missing_information": ["repair_invoice"],
        "message_to_customer": "Please provide the final repair invoice for your vehicle to proceed.",
        "consistency_issues": [
            {
                "field": "estimated_amount",
                "email": 160000,
                "document": 169050,
            }
        ],
    }

    result = enrich_intake_result(
        ai_result,
        "Policy Number: MCA789012. Motor accident. Estimated Repair Cost: Rs 1,60,000.",
        docs,
    )

    assert result["missing_documents"] == []
    assert "repair_invoice" not in result["missing_information"]
    assert result["message_to_customer"] is None
    assert result["intake_status"] == "needs_review"
    assert result["next_recommended_agent"] == "human_reviewer"


def test_scanned_pdf_is_rendered_for_multimodal_analysis(monkeypatch):
    pdf_path = "tests/Property Claim - Fire Damage/Damage Assessment & Valuation.pdf"

    def fake_generate_json_messages(messages, **kwargs):
        content = messages[1]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "SOURCE_MODALITY: scanned_pdf" in content[0]["text"]
        return {
            "filename": "Damage Assessment & Valuation.pdf",
            "document_type": "damage_valuation",
            "summary": "Rendered scanned PDF was analyzed as an image.",
            "extracted_fields": {"claimed_amount": 1580000},
            "quality_issues": [],
            "risk_signals": ["valuation_overstatement"],
            "supports_claim": True,
            "confidence": 0.9,
        }

    monkeypatch.setattr("claimiq.agents.intake.tool.generate_json_messages", fake_generate_json_messages)
    with open(pdf_path, "rb") as handle:
        result = analyze_uploaded_document({
            "filename": "Damage Assessment & Valuation.pdf",
            "mime_type": "application/pdf",
            "data": handle.read(),
        })

    assert result["document_type"] == "damage_valuation"
    assert result["rendered_from_pdf"] is True
    assert result["modality"] == "pdf_image"


def test_scanned_pdf_embedded_image_fallback_without_poppler(monkeypatch):
    pdf_path = "tests/Motor Claim - Car Accident/Police FIR Copy.pdf"

    def fake_generate_json_messages(messages, **kwargs):
        content = messages[1]["content"]
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert "SOURCE_MODALITY: scanned_pdf" in content[0]["text"]
        return {
            "filename": "Police FIR Copy.pdf",
            "document_type": "fir_or_police_report",
            "summary": "Embedded PDF image was analyzed.",
            "extracted_fields": {"fir_number": "FIR-123"},
            "quality_issues": [],
            "risk_signals": [],
            "supports_claim": True,
            "confidence": 0.85,
        }

    monkeypatch.setattr("claimiq.agents.intake.tool._pdftoppm_path", lambda: None)
    monkeypatch.setattr("claimiq.agents.intake.tool.generate_json_messages", fake_generate_json_messages)
    with open(pdf_path, "rb") as handle:
        result = analyze_uploaded_document({
            "filename": "Police FIR Copy.pdf",
            "mime_type": "application/pdf",
            "data": handle.read(),
        })

    assert result["document_type"] == "fir_or_police_report"
    assert result["rendered_from_pdf"] is True
    assert result["modality"] == "pdf_image"
