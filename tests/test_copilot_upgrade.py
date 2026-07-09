from claimiq.agents.copilot.agent import run
from claimiq.agents.copilot.functions import enrich_copilot_brief
from claimiq.tools.report_tool import _format_confidence


def test_copilot_fallback_is_human_assistive_and_role_aware(monkeypatch):
    monkeypatch.setenv("CLAIMIQ_USE_OPENAI", "false")
    monkeypatch.setenv("CLAIMIQ_WRITE_BQ", "false")

    result = run(
        "CLM-COPILOT-1",
        {
            "claim_summary": "Patient: Aarav Sen. Diagnosis: ACL tear. Procedure: ACL Reconstruction.",
            "claimant_name": "Aarav Sen",
            "patient_name": "Aarav Sen",
            "policy_number": "HLT-78901",
            "claim_type": "health",
            "request_type": "cashless_pre_authorization",
            "incident_date": "2026-06-10",
            "diagnosis": "Complete ACL Tear",
            "procedure": "ACL Reconstruction",
            "hospital_name": "Apollo Hospital",
            "claim_amount": 280000,
            "currency": "INR",
            "documents_received": ["mri_report", "hospital_estimate"],
            "missing_documents": ["doctor_prescription"],
            "missing_information": ["document:doctor_prescription"],
        },
        {
            "coverage_status": "needs_review",
            "coverage_reasoning": "Policy section and clinical evidence need human confirmation.",
            "manual_review_required": True,
            "manual_review_reasons": ["Critical coverage information is missing; no assumptions were made."],
            "policy_sections_referenced": [{"section_reference": "Section 4.2", "document_title": "Group Health Policy"}],
            "calculation_methodology": {"sum_insured": 500000, "deductible": 10000, "remaining_sum_insured": 400000},
        },
        {
            "fraud_score": 20,
            "risk_level": "low",
            "signals": [{"signal_id": "LOW_DOCUMENT_CONFIDENCE", "description": "MRI extraction confidence needs review."}],
            "recommended_action": "continue_processing",
        },
        {
            "triage_color": "amber",
            "priority": "high",
            "routing": "medical_document_request",
            "required_human_approval": True,
            "requires_manual_medical_review": True,
            "human_approval_reasons": ["Claim type health requires human review"],
            "recommended_specialist": "Orthopedic Reviewer",
            "clinical_flags": [{"flag_id": "mri_required_for_acl", "category": "medical_documentation", "description": "ACL reconstruction requires MRI evidence."}],
            "recommended_next_steps": ["Request missing clinical evidence before authorization."],
            "sla_hours": 24,
        },
    )

    assert "does not approve" in result["copilot_role"]
    assert "customer_service_executive" in result["role_assistance"]
    assert "claims_officer" in result["role_assistance"]
    assert result["generated_letters"]["document_request_email"].startswith("Dear Aarav Sen")
    assert any(item.get("section_reference") == "Section 4.2" for item in result["citations"])
    assert any(item.get("signal_id") == "LOW_DOCUMENT_CONFIDENCE" for item in result["citations"])
    assert "authorized humans" in " ".join(result["decision_guardrails"])
    assert "Copilot assists the claims team" in result["adjuster_brief_markdown"]


def test_pipeline_copilot_output_contains_upgrade_fields(monkeypatch):
    monkeypatch.setenv("CLAIMIQ_USE_OPENAI", "false")
    monkeypatch.setenv("CLAIMIQ_WRITE_BQ", "false")
    monkeypatch.setattr("claimiq.agents.coverage.agent.lookup_policy", lambda policy_number: {})
    monkeypatch.setattr("claimiq.agents.fraud.agent.find_duplicate_claims", lambda claim_id, intake: [])

    result = __import__("claimiq.pipeline.orchestrator", fromlist=["run_pipeline"]).run_pipeline(
        claim_id="CLM-COPILOT-PIPELINE",
        email_body="Policy POL-123456, car accident on 2026-06-10, repair cost INR 50000.",
        sender_email="customer@example.com",
    )

    copilot = result["outputs"]["copilot"]
    assert copilot["decision_guardrails"]
    assert copilot["plain_english_explanations"]["fraud"]
    assert copilot["recommended_tools"]
    assert copilot["employee_question_suggestions"]


def test_copilot_enrichment_tolerates_string_fields_from_model():
    result = enrich_copilot_brief(
        {
            "claim_details": "Health claim for Akash Chopra",
            "coverage_position": "Needs review",
            "fraud_assessment": "Critical fraud risk",
            "routing_decision": "Send to special investigation",
        },
        "CLM-STRING-FIELDS",
        {"claim_summary": "Health claim.", "policy_number": "HLT-12345", "claim_amount": 95000},
        {"coverage_status": "needs_review", "coverage_reasoning": "Manual review required."},
        {"fraud_score": 80, "risk_level": "critical", "fraud_confidence": "high"},
        {"routing": "special_investigation", "priority": "critical", "triage_color": "red"},
    )

    assert result["routing_decision"]["routing"] == "special_investigation"
    assert result["routing_decision"]["summary"] == "Send to special investigation"
    assert "Route: special_investigation" in result["adjuster_brief_markdown"]


def test_not_covered_payable_explanation_does_not_imply_payout():
    result = enrich_copilot_brief(
        {},
        "CLM-NOT-COVERED",
        {"claim_type": "motor", "claim_amount": 160000, "currency": "INR"},
        {
            "coverage_status": "not_covered",
            "coverage_reasoning": "Incident occurred after policy expiry.",
            "calculation_methodology": {"sum_insured": 450000, "deductible": 5000},
        },
        {"fraud_score": 20, "risk_level": "low"},
        {"routing": "senior_review", "priority": "high", "required_human_approval": True},
    )

    payable = result["plain_english_explanations"]["payable_calculation"]
    assert "No payable amount is calculated" in payable
    assert "Policy limit reference: INR 450,000" in payable
    assert "Final payable amount still requires authorized review" not in payable


def test_report_confidence_formatter_accepts_labels():
    assert _format_confidence("high") == "High"
    assert _format_confidence(0.75) == "75%"
    assert _format_confidence(75) == "75%"
