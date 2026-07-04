"""Adjuster Copilot entry point."""

from __future__ import annotations

import logging
import time
from typing import Any

from claimiq.shared.audit import write_agent_output, write_audit_event

from .functions import enrich_copilot_brief, evidence_log, fallback_brief
from .tool import synthesize_brief

log = logging.getLogger(__name__)


def run(claim_id: str, intake: dict[str, Any], coverage: dict[str, Any], fraud: dict[str, Any], triage: dict[str, Any]) -> dict[str, Any]:
    start = time.time()
    write_audit_event(claim_id, "agent_started", "copilot")
    try:
        result = synthesize_brief(claim_id, intake, coverage, fraud, triage)
        if "error" in result:
            raise RuntimeError(result["error"])
    except Exception as exc:
        log.warning("Copilot OpenAI path failed, using fallback brief: %s", exc)
        result = fallback_brief(claim_id, intake, coverage, fraud, triage)
        result["_fallback_reason"] = str(exc)

    result = enrich_copilot_brief(result, claim_id, intake, coverage, fraud, triage)
    result["evidence_log"] = evidence_log({
        "intake": intake,
        "coverage": coverage,
        "fraud": fraud,
        "triage": triage,
    })
    duration_ms = int((time.time() - start) * 1000)
    write_agent_output(claim_id, "copilot", result, duration_ms=duration_ms)
    write_audit_event(claim_id, "agent_completed", "copilot", payload={"triage_color": result.get("triage_color")}, duration_ms=duration_ms)
    return result
