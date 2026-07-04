"""Intake Agent entry point."""

from __future__ import annotations

import logging
import time
from typing import Any

from claimiq.shared.audit import write_agent_output, write_audit_event

from .functions import deterministic_extract, enrich_intake_result
from .tool import extract_claim

log = logging.getLogger(__name__)


def run(
    claim_id: str,
    email_body: str,
    documents_summary: dict[str, Any] | None = None,
    uploaded_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    start = time.time()
    write_audit_event(claim_id, "agent_started", "intake")
    try:
        result = extract_claim(email_body, documents_summary, uploaded_documents)
        combined_documents_summary = result.pop("_combined_documents_summary", documents_summary or {})
        if "error" in result:
            raise RuntimeError(result["error"])
    except Exception as exc:
        log.warning("Intake OpenAI path failed, using deterministic extraction: %s", exc)
        result = deterministic_extract(email_body, documents_summary)
        result["_fallback_reason"] = str(exc)
        combined_documents_summary = documents_summary or {}
    result = enrich_intake_result(result, email_body, combined_documents_summary)
    result["documents_summary"] = combined_documents_summary

    duration_ms = int((time.time() - start) * 1000)
    write_agent_output(claim_id, "intake", result, duration_ms=duration_ms)
    write_audit_event(claim_id, "agent_completed", "intake", payload={"claim_type": result.get("claim_type")}, duration_ms=duration_ms)
    return result
