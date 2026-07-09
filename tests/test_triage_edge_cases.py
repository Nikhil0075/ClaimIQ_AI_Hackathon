from claimiq.agents.triage.functions import apply_hard_overrides, safe_triage


def test_emergency_remains_critical_when_coverage_inactive():
    result = safe_triage(
        {
            "claim_type": "health",
            "diagnosis": "Acute myocardial infarction",
            "procedure": "Emergency angioplasty",
            "claim_summary": "Patient had a heart attack and needs emergency angioplasty.",
        },
        {"coverage_status": "not_covered", "policy_status": "expired"},
        {"fraud_score": 0},
    )

    assert result["priority"] == "critical"
    assert result["routing"] == "medical_emergency_review"
    assert result["sla_hours"] == 0.25
    assert result["coverage_status"] == "not_covered"


def test_acl_authorization_requests_mri_when_missing():
    result = safe_triage(
        {
            "claim_type": "health",
            "diagnosis": "Complete ACL Tear",
            "procedure": "ACL Reconstruction",
            "missing_documents": ["mri_report"],
            "claim_summary": "Cashless pre-authorization for ACL reconstruction.",
        },
        {"coverage_status": "covered"},
        {"fraud_score": 0},
    )

    assert result["routing"] == "medical_document_request"
    assert result["medical_necessity"] == "Needs evidence"
    assert any(flag["flag_id"] == "mri_required_for_acl" for flag in result["clinical_flags"])


def test_clinical_inconsistencies_trigger_medical_review():
    result = safe_triage(
        {
            "claim_type": "health",
            "gender": "Male",
            "patient_age": 5,
            "admission_date": "2026-07-10",
            "discharge_date": "2026-07-08",
            "diagnosis": "Pregnancy and age-related cataract",
            "procedure": "Routine review",
            "claim_summary": "Right knee ACL tear on prescription but left knee ACL tear in MRI.",
        },
        {"coverage_status": "covered"},
        {"fraud_score": 0},
    )

    flag_ids = {flag["flag_id"] for flag in result["clinical_flags"]}
    assert result["routing"] == "senior_review"
    assert result["requires_manual_medical_review"] is True
    assert {"male_pregnancy", "child_adult_disease", "laterality_conflict", "admission_after_discharge"} <= flag_ids


def test_emergency_vitals_and_stemi_route_immediate_review():
    result = safe_triage(
        {
            "claim_type": "health",
            "diagnosis": "STEMI with cardiogenic shock",
            "procedure": "Emergency PCI",
            "vitals": "BP 82/50, HR 132, SpO2 88",
            "claim_summary": "Patient has acute coronary syndrome with hypotension.",
        },
        {"coverage_status": "covered"},
        {"fraud_score": 0},
    )

    assert result["routing"] == "medical_emergency_review"
    assert result["triage_color"] == "red"
    assert result["severity_score"] >= 80
    assert result["recommended_specialist"] == "Cardiology Reviewer"
    assert any(flag["flag_id"] == "critical_vital_threshold" for flag in result["clinical_flags"])


def test_standard_mri_routes_to_radiology_without_emergency():
    result = safe_triage(
        {
            "claim_type": "health",
            "diagnosis": "Knee pain",
            "procedure": "MRI knee",
            "claim_summary": "Routine diagnostic MRI request for stable patient.",
        },
        {"coverage_status": "covered"},
        {"fraud_score": 0},
    )

    assert result["routing"] == "senior_review"
    assert result["recommended_specialist"] == "Radiology Reviewer"
    assert result["severity_score"] < 50


def test_motor_registration_hr_number_does_not_trigger_medical_emergency():
    intake = {
        "claim_type": "motor",
        "claim_amount": 160000,
        "incident_description": (
            "The car collided with another vehicle on the right side. "
            "Other vehicle registration: HR 26 CD 5678. No injuries reported."
        ),
        "claim_summary": "Motor own-damage claim for Maruti Swift Dzire.",
        "documents_summary": {
            "aggregate_summary": (
                "Multiple images show significant damage to the vehicles, particularly the Maruti Swift Dzire. "
                "Image of a damaged vehicle showing significant damage to the left side. No injuries reported."
            ),
        },
    }

    result = safe_triage(
        intake,
        {"coverage_status": "not_covered"},
        {"fraud_score": 60, "duplicate_claim_ids": ["CLM-OLD"]},
    )

    assert result["routing"] == "special_investigation"
    assert result["requires_manual_medical_review"] is False
    assert not any("vital" in reason.lower() for reason in result["human_approval_reasons"])
    assert not result["clinical_flags"]


def test_non_medical_claim_overrides_model_medical_route():
    intake = {
        "claim_type": "motor",
        "incident_description": "Other vehicle registration: HR 26 CD 5678.",
        "claim_amount": 160000,
    }

    merged = apply_hard_overrides(
        {
            "triage_color": "red",
            "priority": "critical",
            "routing": "medical_emergency_review",
            "human_approval_reasons": [
                "Vital signs cross emergency threshold and require immediate clinical review.",
                "Duplicate claim detected",
            ],
        },
        intake,
        {"coverage_status": "not_covered"},
        {"fraud_score": 60, "duplicate_claim_ids": ["CLM-OLD"]},
    )

    assert merged["routing"] == "special_investigation"
    assert merged["requires_manual_medical_review"] is False
    assert not any("vital" in reason.lower() for reason in merged["human_approval_reasons"])


def test_triage_hard_overrides_accept_labeled_flag_confidence():
    result = {
        "priority": "normal",
        "routing": "standard_review",
        "clinical_flags": [
            {
                "flag_id": "model_flag",
                "category": "clinical_mismatch",
                "description": "Model identified a clinical concern.",
                "confidence": "high",
                "severity": "high",
            }
        ],
    }

    merged = apply_hard_overrides(
        result,
        {
            "claim_type": "health",
            "diagnosis": "Appendicitis",
            "procedure": "Emergency appendectomy",
            "claim_summary": "Patient admitted for emergency appendicitis surgery.",
        },
        {"coverage_status": "covered"},
        {"fraud_score": 0},
    )

    model_flag = next(flag for flag in merged["clinical_flags"] if flag["flag_id"] == "model_flag")
    assert model_flag["confidence"] == 0.85
    assert merged["clinical_flags"]


def test_triage_hard_overrides_normalize_numeric_priority():
    merged = apply_hard_overrides(
        {"priority": 2, "routing": "standard_review", "triage_color": "amber"},
        {
            "claim_type": "health",
            "diagnosis": "Stable appendicitis post surgery",
            "procedure": "Appendectomy",
            "claim_summary": "Routine post-surgical health claim.",
        },
        {"coverage_status": "covered"},
        {"fraud_score": 0},
    )

    assert merged["priority"] == "medium"
