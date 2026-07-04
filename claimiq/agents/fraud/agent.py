"""Fraud Agent entry point."""

from __future__ import annotations

import logging
import time
from typing import Any

from claimiq.shared.audit import write_agent_output, write_audit_event

from .functions import compute_signals, recommended_action, risk_level
from .tool import find_duplicate_claims, synthesize_fraud

log = logging.getLogger(__name__)


def run(claim_id: str, intake: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    start = time.time()
    write_audit_event(claim_id, "agent_started", "fraud")
    duplicate_ids = find_duplicate_claims(claim_id, intake)
    signals, score = compute_signals(intake, coverage, duplicate_ids)
    level = risk_level(score)

    try:
        result = synthesize_fraud(claim_id, intake, coverage, signals, score, level, duplicate_ids)
        if "error" in result:
            raise RuntimeError(result["error"])
        result["fraud_score"] = score
        result["risk_level"] = level
        result["signals"] = signals
        result["duplicate_claim_ids"] = duplicate_ids
        result["recommended_action"] = recommended_action(score, signals)
        result["invoice_anomaly"] = any(s["signal_id"] in {"CLAIM_AMOUNT_OUTLIER", "BILLING_ANOMALY"} for s in signals)
        result["vendor_flagged"] = any(s["signal_id"] == "PROVIDER_RISK" for s in signals)
    except Exception as exc:
        log.warning("Fraud OpenAI path failed, using deterministic fraud result: %s", exc)
        result = {
            "fraud_score": score,
            "risk_level": level,
            "signals": signals,
            "duplicate_claim_ids": duplicate_ids,
            "invoice_anomaly": any(s["signal_id"] in {"CLAIM_AMOUNT_OUTLIER", "BILLING_ANOMALY"} for s in signals),
            "vendor_flagged": any(s["signal_id"] == "PROVIDER_RISK" for s in signals),
            "fraud_reasoning": "Deterministic SIU-style fraud checks completed. Fraud score indicates investigation priority, not claim rejection.",
            "fraud_confidence": 0.75 if signals else 0.6,
            "recommended_action": recommended_action(score, signals),
            "fraud_notes": "OpenAI synthesis was unavailable.",
            "_fallback_reason": str(exc),
        }

    duration_ms = int((time.time() - start) * 1000)
    write_agent_output(claim_id, "fraud", result, duration_ms=duration_ms)
    write_audit_event(claim_id, "agent_completed", "fraud", payload={"fraud_score": result.get("fraud_score")}, duration_ms=duration_ms)
    return result
