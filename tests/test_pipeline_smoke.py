from claimiq.pipeline.orchestrator import run_pipeline


def test_pipeline_smoke(monkeypatch):
    monkeypatch.setenv("CLAIMIQ_USE_OPENAI", "false")
    monkeypatch.setenv("CLAIMIQ_WRITE_BQ", "false")
    monkeypatch.setattr("claimiq.agents.coverage.agent.lookup_policy", lambda policy_number: {})
    monkeypatch.setattr("claimiq.agents.fraud.agent.find_duplicate_claims", lambda claim_id, intake: [])

    result = run_pipeline(
        claim_id="CLM-TEST-1",
        email_body="Policy POL-123456, car accident on 2026-06-10, repair cost INR 50000.",
        sender_email="customer@example.com",
    )
    assert result["claim_id"] == "CLM-TEST-1"
    assert "intake" in result["outputs"]
    assert "copilot" in result["outputs"]


def test_pipeline_pauses_when_intake_documents_are_incomplete(monkeypatch):
    monkeypatch.setenv("CLAIMIQ_USE_OPENAI", "false")
    monkeypatch.setenv("CLAIMIQ_WRITE_BQ", "false")
    monkeypatch.setattr("claimiq.agents.coverage.agent.lookup_policy", lambda policy_number: {})
    monkeypatch.setattr("claimiq.agents.fraud.agent.find_duplicate_claims", lambda claim_id, intake: [])

    result = run_pipeline(
        claim_id="CLM-HEALTH-1",
        email_body=(
            "Cashless pre-authorization for Policy HLT-78901. Patient: Aarav Sen. "
            "Procedure: ACL Reconstruction at Apollo Hospital. Estimate INR 280000."
        ),
        sender_email="customer@example.com",
        documents_summary={
            "total_documents": 1,
            "documents_analyzed": ["health_card.pdf"],
            "per_document": [
                {"filename": "health_card.pdf", "document_type": "health card", "confidence": 0.9},
            ],
            "risk_signals": [],
        },
    )

    assert result["status"] == "intake_only"
    assert result["route"]["next_agent"] == "customer_document_request"
    assert result["route"]["claim_status"] == "pending_customer_documents"
    assert result["workflow_state"]["current_stage"] == "intake_validation"
    assert "coverage" not in result["outputs"]
