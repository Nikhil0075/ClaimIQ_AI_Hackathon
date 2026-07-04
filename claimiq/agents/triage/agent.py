"""Triage Agent entry point."""

from __future__ import annotations

import logging
import time
from typing import Any

from claimiq.shared.audit import write_agent_output, write_audit_event

from .functions import SLA_MAP, apply_hard_overrides, approval_reasons, safe_triage
from .tool import synthesize_triage

log = logging.getLogger(__name__)


def run(claim_id: str, intake: dict[str, Any], coverage: dict[str, Any], fraud: dict[str, Any]) -> dict[str, Any]:
    start = time.time()
    write_audit_event(claim_id, "agent_started", "triage")
    hard_reasons = approval_reasons(intake, coverage, fraud)
    try:
        result = synthesize_triage(intake, coverage, fraud, hard_reasons)
        if "error" in result:
            raise RuntimeError(result["error"])
    except Exception as exc:
        log.warning("Triage OpenAI path failed, using hard-rule triage: %s", exc)
        result = safe_triage(intake, coverage, fraud)
        result["_fallback_reason"] = str(exc)

    result = apply_hard_overrides(result, intake, coverage, fraud)
    if hard_reasons:
        result["required_human_approval"] = True
        result["human_approval_reasons"] = sorted(set(result.get("human_approval_reasons", []) + hard_reasons))
    result["sla_hours"] = SLA_MAP.get(result.get("routing"), result.get("sla_hours", 48))

    duration_ms = int((time.time() - start) * 1000)
    write_agent_output(claim_id, "triage", result, duration_ms=duration_ms)
    write_audit_event(claim_id, "agent_completed", "triage", payload={"routing": result.get("routing")}, duration_ms=duration_ms)
    return result
