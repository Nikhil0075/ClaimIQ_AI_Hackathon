"""Audit and persistence helpers.

These functions are intentionally safe: local development should not fail just because
BigQuery credentials are absent.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .google_clients import bigquery_client

log = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_audit_event(
    claim_id: str,
    event_type: str,
    agent_name: str,
    *,
    payload: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> None:
    if not _write_bq_enabled():
        log.info("audit_event %s %s %s", claim_id, agent_name, event_type)
        return

    row = {
        "audit_id": uuid.uuid4().hex,
        "claim_id": claim_id,
        "event_type": event_type,
        "agent_name": agent_name,
        "duration_ms": duration_ms,
        "timestamp": utc_now(),
    }
    _insert_rows("audit_trail", [row])


def write_agent_output(
    claim_id: str,
    agent_name: str,
    output: dict[str, Any],
    *,
    status: str = "success",
    duration_ms: int | None = None,
) -> None:
    if not _write_bq_enabled():
        log.info("agent_output %s %s %s", claim_id, agent_name, status)
        return

    now = utc_now()
    row = {
        "claim_id": claim_id,
        "agent_name": agent_name,
        "agent_version": "1.0",
        "status": status,
        "output_json": json.dumps(output, default=str),
        "duration_ms": duration_ms,
        "started_at": now,
        "completed_at": now,
    }
    _insert_rows("agent_outputs", [row])


def _get_table_fields(table_name: str) -> set[str]:
    """Return the set of field names present in the BQ table schema."""
    try:
        table_id = f"{settings.project_id}.{settings.bq_dataset}.{table_name}"
        t = bigquery_client().get_table(table_id)
        return {f.name for f in t.schema}
    except Exception as exc:
        log.warning("Could not fetch schema for %s: %s — skipping field filtering", table_name, exc)
        return set()


def _insert_rows(table_name: str, rows: list[dict[str, Any]]) -> None:
    try:
        table_id = f"{settings.project_id}.{settings.bq_dataset}.{table_name}"
        known_fields = _get_table_fields(table_name)
        if known_fields and rows:
            dropped = set(rows[0].keys()) - known_fields
            if dropped:
                log.warning("BQ [%s]: stripped unknown fields %s", table_name, sorted(dropped))
            rows = [{k: v for k, v in row.items() if k in known_fields} for row in rows]
        errors = bigquery_client().insert_rows_json(table_id, rows)
        if errors:
            log.warning("BigQuery insert errors for %s: %s", table_id, errors)
    except Exception as exc:
        log.warning("BigQuery write skipped for %s: %s", table_name, exc)


def _write_bq_enabled() -> bool:
    value = os.getenv("CLAIMIQ_WRITE_BQ")
    if value is None:
        return settings.write_bq
    return value.strip().lower() in {"1", "true", "yes", "on"}
