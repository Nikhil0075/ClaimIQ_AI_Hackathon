from claimiq.agents.coverage.functions import apply_regulatory_compliance
from claimiq.agents.coverage.functions import deterministic_coverage
from claimiq.agents.coverage import tool as coverage_tool
from claimiq.agents.coverage.tool import derive_policy_from_reference, load_policy_evidence


def _use_local_policy_catalog(monkeypatch):
    monkeypatch.setenv("CLAIMIQ_POLICY_DOCUMENTS_SOURCE", "local")
    coverage_tool.POLICY_DOCUMENTS_CACHE = None


def test_coverage_denial_without_citation_becomes_manual_review(monkeypatch):
    _use_local_policy_catalog(monkeypatch)
    result = {
        "coverage_status": "not_covered",
        "coverage_reasoning": "Excluded condition.",
        "policy_sections_referenced": [],
        "coverage_confidence": 0.8,
    }
    intake = {
        "policy_number": "HLT-78901",
        "claim_type": "health",
        "incident_date": "2026-06-10",
        "hospital_name": "Apollo Hospital",
        "procedure": "ACL Reconstruction",
    }

    compliant = apply_regulatory_compliance(
        result,
        claim_id="CLM-1",
        intake=intake,
        policy={"policy_number": "HLT-78901"},
        evidence={"sources": [], "snippets": []},
    )

    assert compliant["coverage_status"] == "needs_review"
    assert compliant["manual_review_required"] is True
    assert "specific_policy_section" in compliant["missing_information"]
    assert compliant["regulatory_compliance_checklist"]["denial_has_specific_clause"] is True


def test_coverage_result_records_citations_documents_and_calculation_methodology(monkeypatch):
    _use_local_policy_catalog(monkeypatch)
    result = {
        "coverage_status": "covered",
        "coverage_reasoning": "Procedure is covered.",
        "policy_sections_referenced": ["Benefit Schedule - ACL Reconstruction"],
        "coverage_confidence": 0.72,
        "applicable_limits": {"max_claim_amount": 300000, "deductible": 10000},
    }
    intake = {
        "policy_number": "HLT-78901",
        "claim_type": "health",
        "incident_date": "2026-06-10",
        "hospital_name": "Apollo Hospital",
        "procedure": "ACL Reconstruction",
        "claim_amount": 280000,
    }
    evidence = {
        "sources": [
            {
                "document_id": "group_health_policy",
                "title": "Group Health Insurance Policy",
                "source_url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/Group%20Health%20Insurance%20Policy.pdf",
                "retrieval_status": "local_copy_found",
            }
        ],
        "snippets": [
            {
                "document_title": "Group Health Insurance Policy",
                "section_reference": "Benefit Schedule",
                "page": 12,
                "excerpt": "ACL Reconstruction benefit is subject to policy limits.",
            }
        ],
    }

    compliant = apply_regulatory_compliance(
        result,
        claim_id="CLM-2",
        intake=intake,
        policy={
            "policy_number": "HLT-78901",
            "sum_insured": 500000,
            "previous_payouts": 50000,
            "inception_date": "2026-01-01",
            "expiry_date": "2026-12-31",
        },
        evidence=evidence,
    )

    assert compliant["manual_review_required"] is False
    assert compliant["regulatory_compliance_checklist"]["transparency"] is True
    assert compliant["documents_reviewed"][0]["document_id"] == "group_health_policy"
    assert compliant["calculation_methodology"]["remaining_sum_insured"] == 450000
    assert compliant["decision_due_date"]


def test_coverage_manual_review_accepts_labeled_confidence(monkeypatch):
    _use_local_policy_catalog(monkeypatch)
    result = {
        "coverage_status": "not_covered",
        "coverage_reasoning": "Excluded condition.",
        "policy_sections_referenced": [],
        "coverage_confidence": "low",
    }
    intake = {
        "policy_number": "HLTH-2024-00892",
        "claim_type": "health",
        "incident_date": "2025-05-20",
        "hospital_name": "Apollo Hospital",
        "procedure": "Emergency appendicitis surgery",
    }

    compliant = apply_regulatory_compliance(
        result,
        claim_id="CLM-LABELED-CONFIDENCE",
        intake=intake,
        policy={"policy_number": "HLTH-2024-00892"},
        evidence={"sources": [], "snippets": []},
    )

    assert compliant["coverage_status"] == "needs_review"
    assert compliant["manual_review_required"] is True
    assert compliant["coverage_confidence"] == 0.3


def test_policy_evidence_selects_claim_type_specific_documents(monkeypatch):
    _use_local_policy_catalog(monkeypatch)
    motor_evidence = load_policy_evidence({"claim_type": "motor"}, {})
    motor_sources = [source["document_id"] for source in motor_evidence["sources"]]

    assert motor_sources == ["claimiq_coverage_motor"]
    assert motor_evidence["sources"][0]["source_url"].endswith("ClaimIQ_Coverage_MOTOR.pdf")
    assert motor_evidence["sources"][0]["selection_reason"] == "matched_claim_type:motor"


def test_health_policy_evidence_includes_new_sample_and_existing_health_wordings(monkeypatch):
    _use_local_policy_catalog(monkeypatch)
    health_evidence = load_policy_evidence({"claim_type": "health"}, {})
    health_sources = [source["document_id"] for source in health_evidence["sources"]]

    assert health_sources == [
        "claimiq_coverage_health",
        "fgi_group_health_revised",
        "group_health_policy",
    ]
    assert all("health" in source["claim_types"] or "medical" in source["claim_types"] for source in health_evidence["sources"])


def test_reference_policy_profile_prevents_sample_property_policy_not_found(monkeypatch):
    _use_local_policy_catalog(monkeypatch)
    intake = {
        "policy_number": "PRO234567",
        "claim_type": "property",
        "incident_date": "2025-05-18",
        "incident_description": "Electrical short circuit causing fire in living room area",
        "estimated_amount": 1580000,
    }
    evidence = load_policy_evidence(intake, {})
    policy = derive_policy_from_reference(intake, evidence)

    assert policy["policy_number"] == "PRO234567"
    assert policy["status"] == "reference_policy_found"
    assert policy["sum_insured"] == 4000000
    assert policy["requires_system_record_verification"] is True

    fallback = deterministic_coverage(intake, policy)
    compliant = apply_regulatory_compliance(
        fallback,
        claim_id="CLM-PROPERTY-SAMPLE",
        intake=intake,
        policy=policy,
        evidence=evidence,
    )

    assert compliant["policy_status"] == "reference_policy_found"
    assert compliant["coverage_status"] == "needs_review"
    assert "customer_policy_record" not in compliant["missing_information"]
    assert "policy_effective_dates" in compliant["missing_information"]
    assert "system_policy_record_verification" in compliant["missing_information"]


def test_policy_evidence_can_use_bigquery_policy_documents_catalog(monkeypatch):
    monkeypatch.setenv("CLAIMIQ_POLICY_DOCUMENTS_SOURCE", "bigquery")
    coverage_tool.POLICY_DOCUMENTS_CACHE = None
    monkeypatch.setattr(coverage_tool, "_lookup_policy_documents_from_bq", lambda: [
        {
            "document_id": "bq_health_doc",
            "title": "BQ Health Wording",
            "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/ClaimIQ_Coverage_HEALTH.pdf",
            "local_path": coverage_tool.REPO_ROOT / "docs" / "ClaimIQ_Coverage_HEALTH.pdf",
            "claim_types": ("health", "medical"),
            "catalog_source": "bigquery",
        },
        {
            "document_id": "bq_property_doc",
            "title": "BQ Property Wording",
            "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/ClaimIQ_Coverage_PROPERTY.pdf",
            "local_path": coverage_tool.REPO_ROOT / "docs" / "ClaimIQ_Coverage_PROPERTY.pdf",
            "claim_types": ("property", "home"),
            "catalog_source": "bigquery",
        },
    ])

    evidence = load_policy_evidence({"claim_type": "property"}, {})

    assert [source["document_id"] for source in evidence["sources"]] == ["bq_property_doc"]
    assert evidence["sources"][0]["catalog_source"] == "bigquery"
    assert evidence["sources"][0]["selection_reason"] == "matched_claim_type:property"
