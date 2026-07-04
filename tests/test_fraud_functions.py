from claimiq.agents.fraud.functions import compute_signals, recommended_action, risk_level


def test_fraud_agent_scores_siu_category_signals():
    intake = {
        "claimant_name": "Aarav Sen",
        "patient_name": "Rahul Sen",
        "claim_type": "health",
        "incident_date": "2026-01-04",
        "claim_amount": 520000,
        "hospital_name": "ABC Hospital",
        "diagnosis": "Minor ACL sprain",
        "procedure": "ACL Reconstruction",
        "risk_indicators": [
            "Invoice appears edited with font mismatch and Photoshop metadata.",
            "Billing exceeds benchmark for procedure.",
        ],
        "documents_summary": {
            "per_document": [
                {"filename": "invoice.pdf", "confidence": 0.31},
            ],
            "risk_signals": ["Doctor signature pasted digitally."],
        },
        "previous_claim_count_90d": 3,
    }
    coverage = {
        "policy_inception_date": "2026-01-01",
        "applicable_limits": {"max_claim_amount": 300000},
    }

    signals, score = compute_signals(intake, coverage, duplicate_ids=["CLM-OLD-1"])
    signal_ids = {signal["signal_id"] for signal in signals}

    assert score == 100
    assert risk_level(score) == "critical"
    assert recommended_action(score, signals) == "hold_processing_pending_investigation"
    assert {
        "NEW_POLICY_CLOSE_TO_INCIDENT",
        "DUPLICATE_CLAIM_DETECTED",
        "IDENTITY_MISMATCH",
        "AI_OR_TAMPERED_DOCUMENT",
        "MEDICAL_INCONSISTENCY",
        "BILLING_ANOMALY",
        "PROVIDER_RISK",
        "BEHAVIORAL_PATTERN",
    }.issubset(signal_ids)


def test_fraud_agent_keeps_low_risk_claim_processing():
    intake = {
        "claimant_name": "Arjun Mehta",
        "patient_name": "Arjun Mehta",
        "claim_type": "motor",
        "incident_date": "2026-06-10",
        "claim_amount": 50000,
        "hospital_name": "",
        "risk_indicators": [],
        "documents_summary": {"risk_signals": [], "per_document": []},
    }

    signals, score = compute_signals(intake, {"applicable_limits": {"max_claim_amount": 200000}}, duplicate_ids=[])

    assert signals == []
    assert score == 0
    assert risk_level(score) == "low"
    assert recommended_action(score, signals) == "continue_processing"


def test_fraud_agent_uses_claim_type_weights_and_combo_rules():
    health_intake = {
        "claim_type": "health",
        "incident_date": "2026-01-20",
        "claim_amount": 100000,
        "claimant_name": "Neha Rao",
        "patient_name": "Neha Rao",
        "risk_indicators": [],
        "documents_summary": {"risk_signals": [], "per_document": []},
    }
    travel_intake = dict(health_intake, claim_type="travel")
    coverage = {"policy_inception_date": "2026-01-01", "applicable_limits": {"max_claim_amount": 200000}}

    health_signals, health_score = compute_signals(health_intake, coverage, duplicate_ids=[])
    travel_signals, travel_score = compute_signals(travel_intake, coverage, duplicate_ids=[])

    assert health_score == 40
    assert travel_score == 10
    assert health_signals[0]["score_contribution"] == 40
    assert travel_signals[0]["score_contribution"] == 10

    combo_signals = [
        {"signal_id": "NEW_POLICY_CLOSE_TO_INCIDENT", "score_contribution": 30},
        {"signal_id": "DUPLICATE_CLAIM_DETECTED", "score_contribution": 35},
    ]
    assert recommended_action(65, combo_signals) == "refer_to_siu"
