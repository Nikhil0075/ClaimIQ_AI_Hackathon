"""Coverage Agent entry point."""

from __future__ import annotations

import logging
import time
from typing import Any

from claimiq.shared.audit import write_agent_output, write_audit_event

from .functions import apply_regulatory_compliance, deterministic_coverage
from .tool import derive_policy_from_reference, load_policy_evidence, lookup_policy, reason_about_coverage

log = logging.getLogger(__name__)


def run(claim_id: str, intake: dict[str, Any]) -> dict[str, Any]:
    start = time.time()
    write_audit_event(claim_id, "agent_started", "coverage")
    policy = lookup_policy(intake.get("policy_number"))
    evidence = load_policy_evidence(intake, policy)
    if not policy:
        policy = derive_policy_from_reference(intake, evidence)
        if policy:
            evidence = load_policy_evidence(intake, policy)
    try:
        result = reason_about_coverage(intake, policy, evidence)
        if "error" in result:
            raise RuntimeError(result["error"])
    except Exception as exc:
        log.warning("Coverage OpenAI path failed, using deterministic coverage: %s", exc)
        result = deterministic_coverage(intake, policy)
        result["_fallback_reason"] = str(exc)
    result = apply_regulatory_compliance(
        result,
        claim_id=claim_id,
        intake=intake,
        policy=policy,
        evidence=evidence,
    )

    duration_ms = int((time.time() - start) * 1000)
    write_agent_output(claim_id, "coverage", result, duration_ms=duration_ms)
    write_audit_event(claim_id, "agent_completed", "coverage", payload={"coverage_status": result.get("coverage_status")}, duration_ms=duration_ms)
    return result
