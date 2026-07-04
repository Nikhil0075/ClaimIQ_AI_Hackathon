"""
ClaimIQ — BigQuery Writer
==========================
Writes pipeline results to two tables:
  claims.claims_master   — one row per claim (key fields for Looker dashboard)
  claims.agent_outputs   — one row per agent per claim (full JSON output)

Both tables use streaming inserts (insert_rows_json) for low latency.

To add a new table write:
  1. Build the row dict
  2. Call _insert(table_name, [row])
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "claimiq-ai-demo")
DATASET    = os.getenv("BQ_DATASET", "claims")

log = logging.getLogger("claimiq.bq")

_bq_client = None


def _client():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery

        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _get_table_fields(table: str) -> set[str]:
    """Return the set of field names that exist in the BQ table schema."""
    try:
        t = _client().get_table(f"{PROJECT_ID}.{DATASET}.{table}")
        return {f.name for f in t.schema}
    except Exception as exc:
        log.warning("Could not fetch schema for %s: %s — skipping field filtering", table, exc)
        return set()


def _insert(table: str, rows: list[dict]) -> bool:
    """
    Stream-insert rows. Auto-strips fields not present in the table schema
    so that new columns in the code don't break existing tables.
    Run bigquery/migrate_add_attachment_columns.sh to add missing columns.
    """
    full_table = f"{PROJECT_ID}.{DATASET}.{table}"
    try:
        known_fields = _get_table_fields(table)
        if known_fields:
            stripped = [{k: v for k, v in row.items() if k in known_fields} for row in rows]
            dropped = set(rows[0].keys()) - known_fields if rows else set()
            if dropped:
                log.warning(
                    "BQ [%s]: stripped unknown fields %s — run migrate_add_attachment_columns.sh",
                    table, sorted(dropped),
                )
        else:
            stripped = rows

        errors = _client().insert_rows_json(full_table, stripped)
        if errors:
            log.error("BQ insert errors [%s]: %s", table, errors)
            return False
        log.info("BQ: inserted %d row(s) into %s", len(rows), table)
        return True
    except Exception as e:
        log.error("BQ insert failed [%s]: %s", table, e)
        return False


def write_claim(
    claim_id: str,
    sender: str,
    agents: dict,
    drive_folder_url: str = "",
    attachment_count: int = 0,
    doc_risk_signals: list = None,
    agent_timings: dict = None,
) -> None:
    """
    Write the pipeline result to claims_master + agent_outputs.
    agents: dict with keys intake, coverage, fraud, triage, copilot
    agent_timings: optional {agent: {started_at, completed_at, duration_ms}}
                   from the orchestrator — real per-agent execution times.
    """
    now    = datetime.now(timezone.utc).isoformat()
    intake = agents.get("intake", {})
    triage = agents.get("triage", {})

    # ── claims_master ─────────────────────────────────────────────────────────
    master_row = {
        "claim_id":               claim_id,
        "sender_email":           sender,
        "claimant_name":          intake.get("claimant_name", "Unknown"),
        "policy_number":          intake.get("policy_number"),
        "claim_type":             intake.get("claim_type", "other"),
        "incident_date":          intake.get("incident_date"),
        "incident_description":   intake.get("incident_description"),
        "claim_amount_mentioned": float(intake.get("claim_amount") or 0),
        "contact_phone":          intake.get("contact_phone"),
        "location_of_incident":   intake.get("location_of_incident"),
        "vehicle_registration":   intake.get("vehicle_registration"),
        "supporting_docs_mentioned": intake.get("documents_mentioned", []),
        "attachment_gcs_paths":   [],
        "attachment_count":       attachment_count,
        "drive_folder_url":       drive_folder_url,
        "doc_risk_signals":       doc_risk_signals or [],
        "validation_status":      "complete",
        "missing_fields":         intake.get("missing_information", []),
        "pipeline_status":        (
            "awaiting_review"
            if triage.get("required_human_approval") or triage.get("requires_human_approval")
            else "processing"
        ),
        "created_at":  now,
        "updated_at":  now,
    }
    _insert("claims_master", [master_row])

    # ── agent_outputs — one row per agent ─────────────────────────────────────
    timings = agent_timings or {}
    agent_rows = []
    for name, output in agents.items():
        output_json = json.dumps(output, default=str)
        timing = timings.get(name) or {}
        agent_rows.append({
            "claim_id":      claim_id,
            "agent_name":    name,
            "agent_version": "1.0",
            # Deterministic content hash (claim + agent + output) so identical
            # reruns produce identical hashes and duplicates are detectable.
            "input_hash":    hashlib.sha256(
                f"{claim_id}|{name}|{output_json}".encode("utf-8")
            ).hexdigest()[:16],
            "output_json":   output_json,
            "status":        "error" if "error" in output else "success",
            "error_message": output.get("error"),
            "started_at":    timing.get("started_at") or now,
            "completed_at":  timing.get("completed_at") or now,
            "duration_ms":   int(timing.get("duration_ms") or 0),
        })
    _insert("agent_outputs", agent_rows)
