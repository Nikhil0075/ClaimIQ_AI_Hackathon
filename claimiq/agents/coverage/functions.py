"""Coverage Agent deterministic helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any


APPEALS_PROCESS = (
    "If the customer disagrees with this coverage decision, they may request "
    "reconsideration through the insurer grievance/appeals desk with the claim "
    "ID, policy number, decision letter, and supporting medical documents."
)
CRITICAL_HEALTH_FIELDS = ("hospital_name", "procedure")


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def deterministic_coverage(intake: dict[str, Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    if not policy:
        return {
            "policy_number": intake.get("policy_number"),
            "policy_status": "not_found",
            "coverage_status": "needs_review",
            "claim_type_covered": False,
            "policy_active_on_incident_date": False,
            "waiting_period_breach": False,
            "waiting_period_days": None,
            "days_since_inception_to_incident": None,
            "applicable_exclusions": [],
            "applicable_limits": {"max_claim_amount": None, "deductible": None},
            "policy_sections_referenced": [],
            "coverage_reasoning": "Policy was not found in the configured policy source.",
            "coverage_confidence": 0.2,
        }

    claim_type = str(intake.get("claim_type") or "").lower()
    covered_perils = [str(item).lower() for item in policy.get("covered_perils", [])]
    incident = parse_date(intake.get("incident_date"))
    inception = parse_date(policy.get("inception_date"))
    expiry = parse_date(policy.get("expiry_date"))
    active = bool(incident and inception and expiry and inception <= incident <= expiry)
    covered = claim_type in covered_perils if covered_perils else False
    waiting_days = int(policy.get("waiting_period_days") or 0)
    days_since = (incident - inception).days if incident and inception else None
    waiting_breach = bool(days_since is not None and days_since < waiting_days)

    status = "covered" if active and covered and not waiting_breach else "needs_review"
    if active and not covered:
        status = "not_covered"

    return {
        "policy_number": policy.get("policy_number") or intake.get("policy_number"),
        "policy_holder_name": policy.get("policy_holder_name"),
        "policy_inception_date": policy.get("inception_date"),
        "policy_expiry_date": policy.get("expiry_date"),
        "policy_status": policy.get("status", "active" if active else "unknown"),
        "coverage_status": status,
        "claim_type_covered": covered,
        "policy_active_on_incident_date": active,
        "waiting_period_breach": waiting_breach,
        "waiting_period_days": waiting_days,
        "days_since_inception_to_incident": days_since,
        "applicable_exclusions": policy.get("exclusions", []),
        "applicable_limits": {
            "max_claim_amount": policy.get("max_claim_amount"),
            "deductible": policy.get("deductible"),
        },
        "policy_sections_referenced": policy.get("sections", []),
        "coverage_reasoning": "Deterministic coverage check completed against policy attributes.",
        "coverage_confidence": 0.65,
    }


def apply_regulatory_compliance(
    result: dict[str, Any],
    *,
    claim_id: str,
    intake: dict[str, Any],
    policy: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enforce IRDAI-style transparency, documentation, and denial safeguards."""
    compliant = dict(result or {})
    policy = policy or {}
    evidence = evidence or {}
    now = datetime.now(timezone.utc)
    reviewed_documents = _documents_reviewed(evidence, intake)
    citations = _policy_citations(compliant, evidence, policy)
    missing_information = _missing_coverage_information(intake, policy, citations)
    original_status = str(compliant.get("coverage_status") or "needs_review")

    compliant.setdefault("claim_id", claim_id)
    compliant["policy_number"] = compliant.get("policy_number") or policy.get("policy_number") or intake.get("policy_number")
    compliant["documents_reviewed"] = reviewed_documents
    compliant["policy_sections_referenced"] = citations
    compliant["decision_timestamp"] = now.isoformat()
    compliant["decision_due_date"] = (now + timedelta(days=30)).date().isoformat()
    compliant["regulatory_timeline_days"] = 30
    compliant["reviewing_agent"] = "coverage_agent"
    compliant["appeals_process"] = compliant.get("appeals_process") or APPEALS_PROCESS
    compliant["calculation_methodology"] = _calculation_methodology(intake, policy, compliant)
    compliant["missing_information"] = sorted(set(
        [str(item) for item in compliant.get("missing_information") or [] if item]
        + missing_information
    ))

    manual_reasons: list[str] = []
    if missing_information:
        manual_reasons.append("Critical coverage information is missing; no assumptions were made.")
    if not citations:
        manual_reasons.append("No specific policy section or document snippet was available for a final decision.")
    if original_status == "not_covered" and not citations:
        manual_reasons.append("Coverage denial blocked because no specific policy exclusion or clause was cited.")
    if _uses_prohibited_basis(compliant):
        manual_reasons.append("Potential prohibited decision basis detected without explicit policy support.")

    if manual_reasons:
        compliant["coverage_status"] = "needs_review"
        compliant["manual_review_required"] = True
        compliant["manual_review_reasons"] = sorted(set(manual_reasons))
        compliant["coverage_confidence"] = min(_confidence_value(compliant.get("coverage_confidence"), 0.4), 0.45)
    else:
        compliant["manual_review_required"] = bool(compliant.get("manual_review_required", False))
        compliant["manual_review_reasons"] = compliant.get("manual_review_reasons", [])

    if compliant.get("coverage_status") == "not_covered":
        compliant["denial_reason"] = compliant.get("denial_reason") or _denial_reason(compliant)
    else:
        compliant.setdefault("denial_reason", None)

    compliant["regulatory_compliance_checklist"] = {
        "transparency": bool(compliant["policy_sections_referenced"]),
        "timeline": True,
        "fairness": not _uses_prohibited_basis(compliant),
        "consistency": bool(compliant.get("procedure_code") or intake.get("procedure") or intake.get("claim_type")),
        "documentation": bool(reviewed_documents and compliant["decision_timestamp"]),
        "dispute_resolution": bool(compliant.get("appeals_process")),
        "denial_has_specific_clause": compliant.get("coverage_status") != "not_covered" or bool(citations),
    }
    compliant["prohibited_actions_checked"] = [
        "No age, gender, or family-history basis used unless explicitly supported by policy wording.",
        "No denial issued without a cited exclusion or clause.",
        "No undisclosed limits applied; limits are documented in calculation_methodology.",
        "Waiting periods and exclusions require cited policy wording.",
        "General medical necessity is not used as a standalone rejection reason.",
    ]
    compliant["coverage_reasoning"] = _coverage_reasoning(compliant, original_status)
    return compliant


def _documents_reviewed(evidence: dict[str, Any], intake: dict[str, Any]) -> list[dict[str, Any]]:
    docs = []
    for source in evidence.get("sources") or []:
        docs.append({
            "document_id": source.get("document_id"),
            "title": source.get("title"),
            "source_url": source.get("source_url"),
            "retrieval_status": source.get("retrieval_status"),
        })
    for name in intake.get("documents_received") or intake.get("documents_mentioned") or []:
        docs.append({"document_id": str(name), "title": str(name), "source": "claim_intake"})
    return docs


def _confidence_value(value: Any, default: float = 0.5) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    text = str(value or "").strip().lower()
    label_map = {
        "very low": 0.1,
        "low": 0.3,
        "medium": 0.55,
        "moderate": 0.55,
        "high": 0.85,
        "very high": 0.95,
    }
    if text in label_map:
        return label_map[text]
    try:
        parsed = float(text)
    except ValueError:
        return default
    if parsed > 1:
        parsed = parsed / 100
    return max(0.0, min(parsed, 1.0))


def _policy_citations(
    result: dict[str, Any],
    evidence: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in result.get("policy_sections_referenced") or []:
        if isinstance(item, dict):
            citations.append(item)
        else:
            citations.append({"section_reference": str(item), "source": "coverage_result"})
    for snippet in evidence.get("snippets") or []:
        citations.append({
            "section_reference": snippet.get("section_reference"),
            "document_title": snippet.get("document_title"),
            "source_url": snippet.get("source_url"),
            "page": snippet.get("page"),
            "excerpt": snippet.get("excerpt"),
        })
    for section in policy.get("sections") or []:
        citations.append({"section_reference": str(section), "source": "policy_record"})

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for citation in citations:
        section = str(citation.get("section_reference") or "").strip()
        if not section:
            continue
        key = (section, str(citation.get("document_title")), str(citation.get("page")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(citation)
    return unique[:12]


def _missing_coverage_information(
    intake: dict[str, Any],
    policy: dict[str, Any],
    citations: list[dict[str, Any]],
) -> list[str]:
    missing = []
    if not intake.get("policy_number") and not policy.get("policy_number"):
        missing.append("policy_number")
    if str(intake.get("claim_type") or "").lower() == "health":
        for field in CRITICAL_HEALTH_FIELDS:
            if not intake.get(field):
                missing.append(field)
    if not intake.get("incident_date"):
        missing.append("incident_date")
    if policy and not citations:
        missing.append("specific_policy_section")
    if policy and (not policy.get("inception_date") or not policy.get("expiry_date")):
        missing.append("policy_effective_dates")
    if policy.get("requires_system_record_verification"):
        missing.append("system_policy_record_verification")
    if not policy:
        missing.append("customer_policy_record")
    return sorted(set(missing))


def _calculation_methodology(
    intake: dict[str, Any],
    policy: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    limits = result.get("applicable_limits") if isinstance(result.get("applicable_limits"), dict) else {}
    claim_amount = intake.get("claim_amount") or intake.get("estimated_amount")
    previous_payouts = policy.get("previous_payouts") or policy.get("paid_claims_amount") or 0
    sum_insured = policy.get("sum_insured") or policy.get("max_claim_amount") or limits.get("max_claim_amount")
    remaining_sum_insured = None
    try:
        if sum_insured is not None:
            remaining_sum_insured = float(sum_insured) - float(previous_payouts or 0)
    except (TypeError, ValueError):
        remaining_sum_insured = None
    return {
        "claim_amount": claim_amount,
        "sum_insured": sum_insured,
        "previous_payouts_considered": previous_payouts,
        "remaining_sum_insured": remaining_sum_insured,
        "deductible": limits.get("deductible") or policy.get("deductible"),
        "applied_limits": limits,
        "method": "Compare claimed amount against cited policy limits, deductible, sub-limits, and prior payouts. Manual review is required if any cited limit is unavailable.",
    }


def _uses_prohibited_basis(result: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(result.get(key) or "")
        for key in ("coverage_reasoning", "denial_reason", "applicable_exclusions")
    ).lower()
    prohibited = ("age", "gender", "family history", "medical necessity")
    return any(term in haystack for term in prohibited) and "policy" not in haystack


def _denial_reason(result: dict[str, Any]) -> str:
    raw_exclusions = result.get("applicable_exclusions") or []
    exclusions = raw_exclusions if isinstance(raw_exclusions, list) else [raw_exclusions]
    if exclusions:
        return f"Claim is not covered based on cited policy exclusion(s): {', '.join(map(str, exclusions[:3]))}."
    return "Claim is not covered based on the cited policy clause(s)."


def _coverage_reasoning(result: dict[str, Any], original_status: str) -> str:
    base = str(result.get("coverage_reasoning") or "Coverage check completed.")
    if result.get("manual_review_required") and str(original_status) != "needs_review":
        reasons = "; ".join(result.get("manual_review_reasons") or []) or "regulatory guardrail"
        return f"{base} Regulatory guardrail changed preliminary status '{original_status}' to needs_review: {reasons}."
    return base
