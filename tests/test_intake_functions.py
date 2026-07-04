from claimiq.agents.intake.functions import deterministic_extract, detect_quality_issues, enrich_intake_result
from claimiq.agents.intake.tool import analyze_uploaded_document, merge_document_summaries


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
