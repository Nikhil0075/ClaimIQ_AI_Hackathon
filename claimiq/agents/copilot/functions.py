"""Adjuster and employee copilot helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def evidence_log(outputs: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"agent": name, "status": "error" if "error" in output else "success", "completed_at": now}
        for name, output in outputs.items()
    ]


def enrich_copilot_brief(
    brief: dict[str, Any],
    claim_id: str,
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> dict[str, Any]:
    """Backfill the copilot contract with grounded assistant capabilities."""
    enriched = dict(brief or {})
    generated_at = enriched.get("generated_at") or datetime.now(timezone.utc).isoformat()
    citations = _citations(intake, coverage, fraud, triage)
    explanations = _plain_english_explanations(intake, coverage, fraud, triage)
    timeline = _timeline(intake)
    next_steps = _next_steps(intake, coverage, fraud, triage)
    role_views = _role_views(intake, coverage, fraud, triage, next_steps)
    letters = _draft_letters(claim_id, intake, coverage, fraud, triage)

    enriched.setdefault("brief_version", "2.0")
    enriched["copilot_role"] = (
        "Human-assistive claims copilot. It summarizes, explains, drafts, "
        "and retrieves context; it does not approve, reject, or settle claims."
    )
    enriched.setdefault("generated_at", generated_at)
    enriched.setdefault("triage_color", triage.get("triage_color", "amber"))
    # Ensure executive_summary is always a plain string (AI may return a dict)
    _raw_es = enriched.get("executive_summary")
    if isinstance(_raw_es, dict):
        enriched["executive_summary"] = (
            _raw_es.get("summary") or _raw_es.get("non_decision_statement")
            or intake.get("claim_summary", "Claim summary unavailable.")
        )
    elif not _raw_es:
        enriched["executive_summary"] = intake.get("claim_summary", "Claim summary unavailable.")
    enriched["claim_details"] = _merge_dict(enriched.get("claim_details"), _claim_details(intake), "summary")
    enriched["coverage_position"] = _merge_dict(enriched.get("coverage_position"), _coverage_position(coverage), "summary")
    enriched["fraud_assessment"] = _merge_dict(enriched.get("fraud_assessment"), _fraud_assessment(fraud), "summary")
    enriched["routing_decision"] = _merge_dict(enriched.get("routing_decision"), _routing_decision(triage), "summary")
    enriched.setdefault("open_questions", _open_questions(intake, coverage, fraud, triage))
    enriched.setdefault("approval_checklist", _human_review_checklist(intake, coverage, fraud, triage))

    enriched["decision_guardrails"] = [
        "Copilot may recommend evidence to review, but final claim decisions remain with authorized humans.",
        "No denial should be communicated without cited policy wording and a human review.",
        "Fraud signals explain investigation triggers; they are not proof of fraud by themselves.",
    ]
    enriched["citations"] = citations
    enriched["plain_english_explanations"] = explanations
    enriched["role_assistance"] = role_views
    enriched["claim_timeline"] = timeline
    enriched["suggested_next_steps"] = next_steps
    enriched["generated_letters"] = letters
    enriched["internal_notes"] = _internal_notes(coverage, fraud, triage)
    enriched["employee_question_suggestions"] = _employee_questions(intake, coverage, fraud, triage)
    enriched["knowledge_sources_used"] = _knowledge_sources(intake, coverage, fraud, triage, citations)
    enriched["recommended_tools"] = _recommended_tools(intake, coverage, fraud, triage)
    enriched["adjuster_brief_markdown"] = _markdown(
        claim_id,
        enriched,
        explanations,
        timeline,
        citations,
        next_steps,
    )
    return enriched


def fallback_brief(claim_id: str, intake: dict[str, Any], coverage: dict[str, Any], fraud: dict[str, Any], triage: dict[str, Any]) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    brief = {
        "brief_version": "1.0",
        "generated_at": generated_at,
        "triage_color": triage.get("triage_color", "amber"),
        "executive_summary": intake.get("claim_summary", "Claim summary unavailable."),
        "claim_details": _claim_details(intake),
        "coverage_position": _coverage_position(coverage),
        "fraud_assessment": _fraud_assessment(fraud),
        "routing_decision": _routing_decision(triage),
        "open_questions": _open_questions(intake, coverage, fraud, triage),
        "approval_checklist": _human_review_checklist(intake, coverage, fraud, triage),
        "evidence_log": [],
    }
    return enrich_copilot_brief(brief, claim_id, intake, coverage, fraud, triage)


def _claim_details(intake: dict[str, Any]) -> dict[str, Any]:
    return {
        "claimant_name": intake.get("claimant_name"),
        "patient_name": intake.get("patient_name"),
        "policy_number": intake.get("policy_number"),
        "claim_type": intake.get("claim_type"),
        "request_type": intake.get("request_type"),
        "incident_date": intake.get("incident_date"),
        "diagnosis": intake.get("diagnosis"),
        "procedure": intake.get("procedure"),
        "hospital_name": intake.get("hospital_name"),
        "claim_amount": intake.get("claim_amount") or intake.get("estimated_amount"),
        "currency": intake.get("currency", "INR"),
        "location": intake.get("location_of_incident"),
    }


def _merge_dict(value: Any, fallback: dict[str, Any], text_key: str) -> dict[str, Any]:
    if isinstance(value, dict):
        merged = dict(fallback)
        merged.update(value)
        return merged
    if value not in (None, "", []):
        merged = dict(fallback)
        merged[text_key] = str(value)
        return merged
    return dict(fallback)


def _coverage_position(coverage: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": coverage.get("coverage_status", "needs_review"),
        "summary": coverage.get("coverage_reasoning", "Coverage reasoning unavailable."),
        "policy_sections": coverage.get("policy_sections_referenced", []),
        "exclusions_identified": coverage.get("applicable_exclusions", []),
        "waiting_period_breach": coverage.get("waiting_period_breach", False),
        "calculation_methodology": coverage.get("calculation_methodology", {}),
        "manual_review_required": coverage.get("manual_review_required", True),
        "appeals_process": coverage.get("appeals_process"),
    }


def _fraud_assessment(fraud: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": fraud.get("fraud_score", 0),
        "risk_level": fraud.get("risk_level", "low"),
        "key_signals": fraud.get("signals", []),
        "recommended_action": fraud.get("recommended_action", "continue_processing"),
        "duplicate_claim_ids": fraud.get("duplicate_claim_ids", []),
    }


def _routing_decision(triage: dict[str, Any]) -> dict[str, Any]:
    return {
        "routing": triage.get("routing", "standard_review"),
        "priority": triage.get("priority", "medium"),
        "requires_human_approval": triage.get("required_human_approval", True),
        "approval_reasons": triage.get("human_approval_reasons", []),
        "recommended_specialist": triage.get("recommended_specialist"),
        "sla_hours": triage.get("sla_hours", 48),
    }


def _citations(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in _listify(coverage.get("policy_sections_referenced")):
        if isinstance(item, dict):
            citation = dict(item)
        else:
            citation = {"section_reference": str(item)}
        citation.setdefault("source", "coverage_agent")
        citation.setdefault("supports", "coverage explanation")
        citations.append(citation)

    for item in _listify(coverage.get("documents_reviewed")):
        if isinstance(item, dict):
            citations.append({
                "document_id": item.get("document_id") or item.get("title"),
                "document_title": item.get("title"),
                "source_url": item.get("source_url"),
                "source": "coverage_documents",
                "supports": "documents reviewed",
            })

    for signal in _listify(fraud.get("signals")):
        if isinstance(signal, dict):
            citations.append({
                "signal_id": signal.get("signal_id"),
                "source": "fraud_agent",
                "supports": signal.get("description"),
                "evidence": signal.get("evidence", {}),
            })

    for flag in _listify(triage.get("clinical_flags")):
        if isinstance(flag, dict):
            citations.append({
                "flag_id": flag.get("flag_id"),
                "source": "triage_agent",
                "supports": flag.get("description"),
                "category": flag.get("category"),
            })

    for document in _listify(intake.get("documents_received")):
        citations.append({
            "document_id": str(document),
            "source": "intake_agent",
            "supports": "claim document received",
        })
    return _dedupe_citations(citations)


def _plain_english_explanations(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> dict[str, str]:
    coverage_status = coverage.get("coverage_status", "needs_review")
    fraud_score = int(fraud.get("fraud_score") or 0)
    fraud_level = fraud.get("risk_level", "low")
    routing = triage.get("routing", "standard_review")
    claim_amount = _money(intake.get("claim_amount") or intake.get("estimated_amount"), intake.get("currency", "INR"))
    return {
        "coverage": (
            f"Coverage is currently marked as {coverage_status}. "
            f"{coverage.get('coverage_reasoning', 'A reviewer should confirm the policy wording and limits.')}"
        ),
        "fraud": (
            f"The fraud score is {fraud_score} ({fraud_level}). "
            "This is an investigation priority signal, not a final accusation."
        ),
        "triage": (
            f"The claim is routed to {routing} with {triage.get('priority', 'medium')} priority. "
            f"Reason: {', '.join(_listify(triage.get('human_approval_reasons'))) or 'standard workflow routing'}."
        ),
        "payable_calculation": _calculation_explanation(claim_amount, coverage),
        "medical": _medical_explanation(intake, triage),
    }


def _calculation_explanation(claim_amount: str, coverage: dict[str, Any]) -> str:
    coverage_status = str(coverage.get("coverage_status") or "").lower()
    methodology = coverage.get("calculation_methodology") if isinstance(coverage.get("calculation_methodology"), dict) else {}
    if coverage_status == "not_covered":
        reason = str(coverage.get("coverage_reasoning") or coverage.get("denial_reason") or "").strip()
        parts = [f"No payable amount is calculated because coverage is currently not_covered. Claimed amount: {claim_amount}."]
        if methodology.get("sum_insured") is not None:
            parts.append(f"Policy limit reference: {_money(methodology.get('sum_insured'))}.")
        if methodology.get("deductible") is not None:
            parts.append(f"Deductible reference: {_money(methodology.get('deductible'))}.")
        if reason:
            parts.append(f"Reason: {reason}")
        parts.append("Any payment decision requires authorized human review and policy verification.")
        return " ".join(parts)
    if methodology:
        parts = [f"Claimed amount: {claim_amount}."]
        if methodology.get("sum_insured") is not None:
            parts.append(f"Sum insured or limit considered: {_money(methodology.get('sum_insured'))}.")
        if methodology.get("deductible") is not None:
            parts.append(f"Deductible considered: {_money(methodology.get('deductible'))}.")
        if methodology.get("remaining_sum_insured") is not None:
            parts.append(f"Remaining sum insured: {_money(methodology.get('remaining_sum_insured'))}.")
        parts.append("Final payable amount still requires authorized review.")
        return " ".join(parts)
    return f"Claimed amount is {claim_amount}. Policy limits, deductibles, co-pay, and prior payouts should be checked before any payout decision."


def _medical_explanation(intake: dict[str, Any], triage: dict[str, Any]) -> str:
    """Return a medical summary only when the claim actually has a medical dimension.

    Non-medical claim types (property, motor) must not get placeholder medical
    text, and even medical claims with nothing captured return "" so PDF
    renderers can skip the section entirely.
    """
    claim_type = str(intake.get("claim_type") or "").strip().lower()
    diagnosis = intake.get("diagnosis")
    procedure = intake.get("procedure")
    if claim_type not in ("health", "travel"):
        return ""
    if not (diagnosis or procedure):
        return ""
    diagnosis = diagnosis or "Diagnosis is not clearly captured"
    procedure = procedure or "procedure is not clearly captured"
    specialist = triage.get("recommended_specialist") or "Medical Reviewer"
    return f"{diagnosis}; requested treatment: {procedure}. Suggested reviewer: {specialist}."


def _timeline(intake: dict[str, Any]) -> list[dict[str, str]]:
    events = []
    for label, key in (
        ("Incident", "incident_date"),
        ("Admission", "admission_date"),
        ("Surgery or procedure", "surgery_date"),
        ("Discharge", "discharge_date"),
    ):
        if intake.get(key):
            events.append({"date": str(intake[key]), "event": label, "source": "intake_agent"})
    if not events and intake.get("claim_summary"):
        events.append({"date": "unknown", "event": "Claim received and summarized", "source": "intake_agent"})
    return events


def _next_steps(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> list[str]:
    steps = []
    for missing in _open_questions(intake, coverage, fraud, triage):
        steps.append(f"Resolve missing or unclear item: {missing}.")
    steps.extend(str(item) for item in _listify(triage.get("recommended_next_steps")))
    if coverage.get("manual_review_required"):
        steps.append("Human reviewer should confirm cited policy wording before customer communication.")
    if int(fraud.get("fraud_score") or 0) >= 50:
        steps.append("Fraud investigator should review the highlighted risk signals before processing continues.")
    if not steps:
        steps.append("Prepare claim file for authorized human review.")
    return list(dict.fromkeys(steps))


def _role_views(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
    next_steps: list[str],
) -> dict[str, list[str]]:
    return {
        "customer_service_executive": [
            "Explain current claim status in plain language.",
            "Share missing document request if required.",
            f"Customer-safe summary: {intake.get('message_to_customer') or 'Claim is under review.'}",
        ],
        "claims_officer": [
            f"Routing: {triage.get('routing', 'standard_review')}.",
            f"Coverage status: {coverage.get('coverage_status', 'needs_review')}.",
            f"Immediate next step: {next_steps[0] if next_steps else 'review claim file'}.",
        ],
        "medical_reviewer": [
            item for item in (
                _medical_explanation(intake, triage) or "No medical review dimension for this claim type.",
                f"Clinical flags: {', '.join(flag.get('description', str(flag)) for flag in _listify(triage.get('clinical_flags')) if isinstance(flag, dict)) or 'none captured'}.",
            ) if item
        ],
        "fraud_investigator": [
            f"Fraud score: {fraud.get('fraud_score', 0)} ({fraud.get('risk_level', 'low')}).",
            f"Action: {fraud.get('recommended_action', 'continue_processing')}.",
        ],
        "supervisor": [
            f"SLA hours: {triage.get('sla_hours', 48)}.",
            f"Human approval required: {triage.get('required_human_approval', True)}.",
        ],
        "audit_team": [
            "Review citations, evidence log, guardrails, and generated communications before closure.",
        ],
    }


def _draft_letters(
    claim_id: str,
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> dict[str, str]:
    missing = _open_questions(intake, coverage, fraud, triage)
    customer_name = intake.get("claimant_name") or intake.get("patient_name") or "Customer"
    missing_text = ", ".join(str(item).replace("_", " ") for item in missing[:6])
    document_request = (
        f"Dear {customer_name},\n\n"
        f"Your claim {claim_id} needs the following information before review can continue: "
        f"{missing_text or 'no additional documents at this time'}.\n\n"
        "Regards,\nClaims Team"
    )
    hospital_clarification = (
        "Dear Hospital Team,\n\n"
        f"Please confirm the diagnosis, procedure, estimated cost, and admission timeline for claim {claim_id}.\n\n"
        "Regards,\nClaims Team"
    )
    internal_investigation = (
        f"Claim {claim_id} requires review of fraud score {fraud.get('fraud_score', 0)} "
        f"and routing {triage.get('routing', 'standard_review')}. "
        f"Coverage status: {coverage.get('coverage_status', 'needs_review')}."
    )
    return {
        "document_request_email": document_request,
        "hospital_clarification_letter": hospital_clarification,
        "internal_investigation_note": internal_investigation,
    }


def _internal_notes(coverage: dict[str, Any], fraud: dict[str, Any], triage: dict[str, Any]) -> list[str]:
    notes = [
        f"Coverage status: {coverage.get('coverage_status', 'needs_review')}.",
        f"Fraud risk: {fraud.get('risk_level', 'low')} with score {fraud.get('fraud_score', 0)}.",
        f"Triage route: {triage.get('routing', 'standard_review')} at {triage.get('priority', 'medium')} priority.",
    ]
    if triage.get("required_human_approval", True):
        notes.append("Human approval is required before any final customer decision.")
    return notes


def _employee_questions(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> list[str]:
    questions = [
        "Summarize this claim for a claims officer.",
        "Explain the coverage position in plain English.",
        "What documents are missing or unclear?",
        "Generate a customer-safe document request email.",
    ]
    if fraud.get("signals"):
        questions.append("Explain the fraud indicators and what evidence supports them.")
    if triage.get("clinical_flags"):
        questions.append("Summarize the medical review concerns.")
    if intake.get("documents_received"):
        questions.append("Compare the uploaded documents for inconsistencies.")
    return questions


def _knowledge_sources(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
    citations: list[dict[str, Any]],
) -> list[str]:
    sources = ["intake result", "coverage agent output", "fraud agent output", "triage agent output"]
    if coverage.get("policy_sections_referenced"):
        sources.append("policy wording and benefit sections")
    if intake.get("documents_received"):
        sources.append("uploaded claim documents")
    if fraud.get("signals"):
        sources.append("fraud signal evidence")
    if triage.get("clinical_flags"):
        sources.append("clinical triage flags")
    if citations:
        sources.append("citation engine")
    return list(dict.fromkeys(sources))


def _recommended_tools(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> list[dict[str, str]]:
    tools = [
        {"tool": "RAG Retriever", "purpose": "Search policy wording, SOPs, manuals, FAQs, and templates."},
        {"tool": "Citation Engine", "purpose": "Point reviewers to exact policy sections and evidence snippets."},
        {"tool": "Calculator", "purpose": "Explain limits, deductible, co-pay, prior payouts, and payable amount."},
        {"tool": "Letter Generator", "purpose": "Draft customer, hospital, approval, rejection, and document request letters."},
        {"tool": "Timeline Generator", "purpose": "Build claim event chronology for reviewers and investigators."},
    ]
    if intake.get("documents_received") or intake.get("documents_mentioned"):
        tools.append({"tool": "Document Comparator", "purpose": "Compare medical reports, bills, estimates, and prescriptions."})
    if fraud.get("signals"):
        tools.append({"tool": "Enterprise Search", "purpose": "Search prior claims, provider risk history, and duplicate cases."})
    if triage.get("clinical_flags"):
        tools.append({"tool": "Medical Report Explainer", "purpose": "Summarize diagnosis, procedure, and reviewer concerns."})
    if coverage.get("appeals_process"):
        tools.append({"tool": "Appeal Response Generator", "purpose": "Draft transparent appeal or reconsideration guidance."})
    return tools


def _open_questions(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> list[str]:
    questions = []
    questions.extend(str(item) for item in _listify(intake.get("missing_information")))
    questions.extend(str(item) for item in _listify(intake.get("missing_documents")))
    questions.extend(str(item) for item in _listify(coverage.get("missing_information")))
    questions.extend(str(item) for item in _listify(coverage.get("manual_review_reasons")))
    if fraud.get("recommended_action") in {"refer_to_siu", "hold_processing_pending_investigation"}:
        questions.append("fraud_investigation_clearance")
    if triage.get("requires_manual_medical_review") or triage.get("required_human_approval"):
        questions.append("authorized_human_review")
    return list(dict.fromkeys(item for item in questions if item))


def _human_review_checklist(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    triage: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "item": "Confirm customer, policy, incident date, amount, and claim type.",
            "status": "needs_review" if intake.get("missing_information") else "ready",
        },
        {
            "item": "Verify coverage position against cited policy wording.",
            "status": "needs_review" if coverage.get("manual_review_required", True) else "ready",
        },
        {
            "item": "Review fraud and document authenticity signals.",
            "status": "needs_review" if int(fraud.get("fraud_score") or 0) >= 40 else "ready",
        },
        {
            "item": "Confirm medical necessity and specialist routing.",
            "status": "needs_review" if triage.get("requires_manual_medical_review", True) else "ready",
        },
        {
            "item": "Human approver records final claim decision outside Copilot.",
            "status": "required",
        },
    ]


def _markdown(
    claim_id: str,
    brief: dict[str, Any],
    explanations: dict[str, str],
    timeline: list[dict[str, str]],
    citations: list[dict[str, Any]],
    next_steps: list[str],
) -> str:
    claim = brief.get("claim_details", {})
    coverage = brief.get("coverage_position", {})
    fraud = brief.get("fraud_assessment", {})
    routing = brief.get("routing_decision", {})
    timeline_lines = "\n".join(f"- {item['date']}: {item['event']}" for item in timeline) or "- No dated events captured."
    citation_lines = "\n".join(f"- {_citation_label(item)}" for item in citations[:8]) or "- No citations available; human review required."
    step_lines = "\n".join(f"- {step}" for step in next_steps)
    return f"""# Claim {claim_id} Copilot Brief

## Human Decision Boundary
Copilot assists the claims team. It does not approve, reject, deny, or settle this claim.

## Executive Summary
{brief.get("executive_summary", "Claim summary unavailable.")}

## Claim Snapshot
- Claimant: {claim.get("claimant_name") or "Unknown"}
- Policy: {claim.get("policy_number") or "Unknown"}
- Type: {claim.get("claim_type") or "Unknown"}
- Procedure: {claim.get("procedure") or "Not captured"}
- Amount: {_money(claim.get("claim_amount"), claim.get("currency", "INR"))}

## Coverage
- Status: {coverage.get("status", "needs_review")}
- Explanation: {explanations.get("coverage")}

## Fraud
- Score: {fraud.get("score", 0)}
- Risk level: {fraud.get("risk_level", "low")}
- Explanation: {explanations.get("fraud")}

## Routing
- Route: {routing.get("routing", "standard_review")}
- Priority: {routing.get("priority", "medium")}
- Human approval required: {routing.get("requires_human_approval", True)}
- SLA hours: {routing.get("sla_hours", 48)}

## Timeline
{timeline_lines}

## Citations And Evidence
{citation_lines}

## Suggested Next Steps
{step_lines}
"""


def _citation_label(item: dict[str, Any]) -> str:
    for key in ("section_reference", "document_title", "document_id", "signal_id", "flag_id"):
        if item.get(key):
            support = f" - {item.get('supports')}" if item.get("supports") else ""
            return f"{item[key]} ({item.get('source', 'evidence')}){support}"
    return str(item)


def _dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in citations:
        key = (
            str(item.get("section_reference") or item.get("document_id") or item.get("signal_id") or item.get("flag_id") or ""),
            str(item.get("source") or ""),
            str(item.get("supports") or ""),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:20]


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _money(value: Any, currency: str = "INR") -> str:
    if value in (None, ""):
        return "not captured"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    if currency == "INR":
        return f"INR {amount:,.0f}"
    return f"{currency} {amount:,.2f}"
