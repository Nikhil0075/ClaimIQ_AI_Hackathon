"""OpenAI-backed agent router for ClaimIQ sessions."""

from __future__ import annotations

import json
import os
from typing import Any

from claimiq.pipeline.session import ClaimSession
from claimiq.shared.openai_client import generate_json

VALID_AGENTS = ("coverage", "fraud", "triage", "copilot")


def choose_agents(session: ClaimSession) -> dict[str, Any]:
    pause_route = _pause_for_incomplete_intake(session)
    if pause_route:
        return _normalize_route(pause_route)

    # ── Deterministic fast path (no LLM call) ─────────────────────────────────
    # The routing policy is fixed: a complete or needs_review intake always runs
    # all four downstream agents. Spending an LLM call (with a ~9KB session
    # snapshot) to rediscover that rule adds cost and latency for zero signal.
    # Set CLAIMIQ_ROUTER_ALWAYS_LLM=true to restore the old behaviour.
    intake_status = str(session.outputs.get("intake", {}).get("intake_status") or "").lower()
    always_llm = os.getenv("CLAIMIQ_ROUTER_ALWAYS_LLM", "").strip().lower() in {"1", "true", "yes", "on"}
    if intake_status in ("complete", "needs_review") and not always_llm:
        return _normalize_route({
            "selected_agents": list(VALID_AGENTS),
            "next_agent": VALID_AGENTS[0],
            "reason": f"Intake status '{intake_status}' — fixed policy routes all downstream agents.",
            "required_action": "Run selected downstream agents in dependency order.",
            "claim_status": "ready_for_downstream_review",
            "missing_inputs": [],
            "confidence": 0.95,
        })

    # ── LLM router for ambiguous intake states only ───────────────────────────
    try:
        route = _choose_with_openai(session)
        # If OpenAI returned no agents but intake is complete/needs_review, that is
        # almost certainly the LLM being over-cautious. Fall back to deterministic.
        if not route.get("selected_agents"):
            intake_st = str(session.outputs.get("intake", {}).get("intake_status") or "").lower()
            if intake_st in ("complete", "needs_review", ""):
                det = _deterministic_route(session)
                det["_fallback_reason"] = "OpenAI router returned no agents; using deterministic fallback."
                route = det
    except Exception as exc:
        route = _deterministic_route(session)
        route["_fallback_reason"] = str(exc)
    return _normalize_route(route)


def _pause_for_incomplete_intake(session: ClaimSession) -> dict[str, Any] | None:
    intake = session.outputs.get("intake", {})
    if str(intake.get("intake_status") or "").lower() != "incomplete":
        return None
    missing = list(intake.get("missing_information") or [])
    missing.extend(intake.get("missing_documents") or [])
    return {
        "selected_agents": [],
        "next_agent": "customer_document_request",
        "reason": "Intake found missing or poor-quality mandatory documents, so downstream review is paused.",
        "required_action": intake.get("message_to_customer") or "Request missing or clearer documents from the customer.",
        "claim_status": "pending_customer_documents",
        "missing_inputs": sorted(set(str(item) for item in missing if item)),
        "confidence": 0.9,
    }


def _choose_with_openai(session: ClaimSession) -> dict[str, Any]:
    prompt = f"""You are the ClaimIQ orchestrator router.
Pick only the downstream agents needed for this claim session.

Available agents:
- coverage: validate policy, limits, exclusions, active dates.
- fraud: detect duplicate/high-risk/suspicious claim signals.
- triage: decide routing, priority, SLA, and human approval.
- copilot: create the final adjuster/customer-facing brief.

Rules:
- If intake_status is "complete" or "needs_review", select all four downstream agents.
- Only skip agents if intake_status is explicitly "incomplete" (missing mandatory documents).
- Do NOT treat non-empty missing_information alone as a reason to skip agents; trust intake_status.
- triage depends on coverage and fraud.
- copilot depends on triage.
- Return ONLY valid JSON:
{{
  "selected_agents": ["coverage", "fraud", "triage", "copilot"],
  "reason": "short reason",
  "missing_inputs": [],
  "confidence": 0.0
}}

SESSION:
{json.dumps(session.snapshot(), indent=2, default=str)[:9000]}
"""
    return generate_json(
        prompt,
        temperature=0.0,
        max_tokens=2048,
        model=os.getenv("CLAIMIQ_ORCHESTRATOR_MODEL", os.getenv("CLAIMIQ_ROUTER_MODEL", "gpt-5.5")),
        reasoning_effort=os.getenv(
            "CLAIMIQ_ORCHESTRATOR_REASONING_EFFORT",
            os.getenv("CLAIMIQ_ROUTER_REASONING_EFFORT", "medium"),
        ),
    )


def _deterministic_route(session: ClaimSession) -> dict[str, Any]:
    intake = session.outputs.get("intake", {})
    docs = session.document_context()
    missing = list(intake.get("missing_information") or [])
    selected: list[str] = []
    intake_status = str(intake.get("intake_status") or "").lower()

    if intake_status == "incomplete":
        missing.extend(intake.get("missing_documents") or [])
        return {
            "selected_agents": [],
            "next_agent": "customer_document_request",
            "reason": "Intake found missing or poor-quality mandatory documents, so downstream review is paused.",
            "required_action": intake.get("message_to_customer") or "Request missing or clearer documents from the customer.",
            "claim_status": "pending_customer_documents",
            "missing_inputs": sorted(set(str(item) for item in missing if item)),
            "confidence": 0.8,
        }

    if intake.get("policy_number"):
        selected.append("coverage")
    else:
        missing.append("policy_number")

    has_risk = bool(docs.get("risk_signals") or intake.get("risk_indicators"))
    amount = float(intake.get("claim_amount") or 0)
    if has_risk or amount >= 100000 or intake.get("incident_date"):
        selected.append("fraud")

    if "coverage" in selected or "fraud" in selected:
        selected.append("triage")

    if intake.get("claim_summary") and "triage" in selected:
        selected.append("copilot")

    return {
        "selected_agents": selected,
        "next_agent": selected[0] if selected else "human_reviewer",
        "reason": "Deterministic route based on available intake facts and document risk signals.",
        "required_action": "Run selected downstream agents in dependency order." if selected else "Review intake output manually.",
        "claim_status": "ready_for_downstream_review" if selected else "pending_human_review",
        "missing_inputs": sorted(set(str(item) for item in missing if item)),
        "confidence": 0.6,
    }


def _normalize_route(route: dict[str, Any]) -> dict[str, Any]:
    selected = [agent for agent in route.get("selected_agents", []) if agent in VALID_AGENTS]
    selected = _enforce_dependencies(selected)
    route["selected_agents"] = selected
    route.setdefault("reason", "")
    route.setdefault("next_agent", selected[0] if selected else "human_reviewer")
    route.setdefault("required_action", "Run selected downstream agents in dependency order." if selected else "Review or request missing intake information.")
    route.setdefault("claim_status", "ready_for_downstream_review" if selected else "pending_human_review")
    route.setdefault("missing_inputs", [])
    route.setdefault("confidence", 0.5)
    return route


def _enforce_dependencies(selected: list[str]) -> list[str]:
    expanded = list(dict.fromkeys(selected))
    if "copilot" in expanded and "triage" not in expanded:
        expanded.insert(0, "triage")
    if "triage" in expanded:
        for dependency in ("coverage", "fraud"):
            if dependency not in expanded:
                expanded.insert(0, dependency)
    return [agent for agent in VALID_AGENTS if agent in expanded]
