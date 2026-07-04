from claimiq.pipeline.mail_guard import _deterministic_guard, _normalize_guard


HEALTH_CLAIM_EMAIL = """Dear Claims Team,

I am filing a health insurance claim under Policy No: HLTH-2024-00892.

Incident Details:
- Date: 20 May 2025
- Hospital: Apollo Hospital, Bengaluru
- Reason: Emergency appendicitis surgery
- Total bill: Rs 95,000

Documents attached:
- Hospital discharge summary
- Doctor's prescription
- Pharmacy bills
- Lab reports

I was admitted as an emergency patient. Surgery was performed on the same day.
No pre-existing conditions declared at policy inception.

Claimant: Akash Chopra
Contact: 8480774892
Policy: HLTH-2024-00892

Regards,
Akash
"""


def test_real_health_claim_with_old_non_future_date_proceeds_in_fallback():
    result = _deterministic_guard(HEALTH_CLAIM_EMAIL)

    assert result["action"] == "proceed"
    assert "incident_date" not in result["missing_fields"]
    assert "policy_number" not in result["missing_fields"]


def test_false_future_date_llm_rewrite_is_corrected_when_claim_is_complete():
    llm_result = {
        "action": "rewrite_request",
        "is_relevant": True,
        "missing_fields": ["incident_date"],
        "reason": "Incident date is in the future.",
        "confidence": 0.0,
    }

    result = _normalize_guard(llm_result, HEALTH_CLAIM_EMAIL)

    assert result["action"] == "proceed"
    assert result["is_relevant"] is True
    assert "incident_date" not in result["missing_fields"]


ACL_CLAIM_EMAIL = """Dear Sir/Madam,

I am writing to submit an insurance claim for my recent ACL reconstruction surgery.

My Details:
- Full Name: Rajesh Kumar Singh
- Policy Number: ABC234567
- Date of Birth: 15/03/1985
- Contact Number: +91-9876543210

Incident Details:
I sustained an injury to my left knee while playing cricket on 18th May 2025 at Delhi.
I was playing at the Delhi Cricket Ground near Vikas Puri when I twisted my knee during
a match. I immediately experienced severe pain and was unable to walk.

I visited Apollo Hospital Delhi on 19th May 2025 and was diagnosed with a complete ACL tear.
The doctor recommended immediate surgical intervention.

Medical Treatment:
- Hospital: Apollo Hospital Delhi, Vikas Puri Branch
- Admission Date: 20th May 2025
- Discharge Date: 24th May 2025
- Procedure: Arthroscopic ACL Reconstruction with Hamstring Graft
- Estimated Cost: Rs 2,50,000

Regards,
Rajesh Kumar Singh
"""


def test_acl_claim_with_ordinal_dates_and_generic_policy_prefix_proceeds():
    result = _deterministic_guard(ACL_CLAIM_EMAIL)

    assert result["action"] == "proceed"
    assert "incident_date" not in result["missing_fields"]
    assert "policy_number" not in result["missing_fields"]
    assert "claimant_name" not in result["missing_fields"]


def test_acl_false_future_date_llm_rewrite_is_corrected():
    llm_result = {
        "action": "rewrite_request",
        "is_relevant": True,
        "missing_fields": ["incident_date"],
        "reason": "incident date is in the future",
        "confidence": 0.0,
    }

    result = _normalize_guard(llm_result, ACL_CLAIM_EMAIL)

    assert result["action"] == "proceed"
    assert result["is_relevant"] is True
    assert result["missing_fields"] == []
