"""Shared parsing, persistence, and lock helpers for the frontend."""

import json
import re
import time

from frontend.config import LOG_FILE, LOG_LIMIT, LOCK_FILE, STAGE_AGENT

def _ansi(text: str) -> str:
    """Strip all ANSI escape sequences."""
    return re.sub(r'\x1b\[[0-9;]*[mKJHA-Za-z]', '', text)

def load_logs() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_logs(logs: list[dict]) -> None:
    LOG_FILE.write_text(json.dumps(logs[:LOG_LIMIT], indent=2), encoding="utf-8")

def add_log(entry: dict) -> None:
    logs = load_logs()
    logs.insert(0, entry)
    save_logs(logs)

def parse_run_summary(output: str) -> dict:
    """Parse the PIPELINE COMPLETE block — always strip ANSI first."""
    clean = _ansi(output)
    def find(pat, default=""):
        m = re.search(pat, clean, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else default
    summary = {
        "claim_id":    find(r"Claim ID\s*:\s*(.+)"),
        "claimant":    find(r"Claimant\s*:\s*(.+)"),
        "claim_type":  find(r"Type\s*:\s*(.+)"),
        "amount":      find(r"Amount\s*:\s*(.+)"),
        "attachments": find(r"Attachments\s*:\s*(.+)"),
        "doc_risks":   find(r"Doc Risks\s*:\s*(.+)"),
        "fraud":       find(r"Fraud\s*:\s*(.+)"),
        "priority":    find(r"Priority\s*:\s*(.+)"),
        "routing":     find(r"Routing\s*:\s*(.+)"),
        "decision": (
            "HUMAN APPROVAL REQUIRED" if "HUMAN APPROVAL REQUIRED" in clean
            else "AUTO-ELIGIBLE" if "AUTO-ELIGIBLE" in clean else ""
        ),
        "approval_url": find(r"(https://docs\.google\.com/forms/[^\s]+)"),
        "drive_url":    find(r"(https://drive\.google\.com/drive/folders/[^\s]+)"),
    }
    payload_match = re.search(
        r"CLAIMIQ_EXPLAINABILITY_JSON_BEGIN\s*(\{.*?\})\s*CLAIMIQ_EXPLAINABILITY_JSON_END",
        clean,
        re.DOTALL,
    )
    if payload_match:
        try:
            payload = json.loads(payload_match.group(1))
            summary["pipeline_result"] = payload
            summary["route"] = payload.get("route", {})
            summary["workflow_state"] = payload.get("workflow_state", {})
            summary["outputs"] = payload.get("outputs", {})
            summary["document_summary"] = payload.get("document_summary") or payload.get("outputs", {}).get("intake", {}).get("documents_summary", {})
            summary["status_detail"] = payload.get("status", "")
        except Exception:
            summary["pipeline_result_parse_error"] = "Could not parse structured explainability payload."
    return summary

def detect_agent_live(line: str, current: int) -> int:
    """
    Determine agent index from a live output line.
    Uses EmailTool stage markers (most reliable), then pipeline step markers.
    Returns current index if no match found.
    """
    ll = line.lower()

    # EmailTool stage markers are ground truth
    m = re.search(r'\[emailtool\] stage=(\w+)', ll)
    if m:
        stage = m.group(1)
        if stage in STAGE_AGENT:
            return STAGE_AGENT[stage]

    # Pipeline step markers
    if "[1/6]" in ll:
        return 0  # Intake
    if "[2/6]" in ll or "[attachments]" in ll:
        return 0  # Attachment extraction belongs to pre-agent / intake phase
    if "[3/6]" in ll:
        return 1  # Start of orchestrator = Coverage is first agent after intake
    if "[4/6]" in ll or "[drive]" in ll:
        return 4  # Drive upload → Copilot phase
    if "[5/6]" in ll or "bq:" in ll:
        return 4  # BigQuery → Copilot phase
    if "[6/6]" in ll or "[reporttool]" in ll or "[orchestrator]" in ll:
        return 4  # Final email / PDF → Copilot

    return current  # no change

def segment_stdout(stdout: str) -> dict[int, list[str]]:
    """
    Split stdout into per-agent buckets using EmailTool stage boundaries.
    Boundaries (in order):
      Intake    → lines before  claim_received
      Coverage  → claim_received  →  coverage_needs_review
      Fraud     → coverage_needs_review  →  fraud_alert
      Priority  → fraud_alert  →  routing_assigned
      Copilot   → routing_assigned  →  end
    """
    segs: dict[int, list[str]] = {i: [] for i in range(5)}
    current = 0

    for raw in stdout.splitlines():
        line = _ansi(raw).strip()
        if not line:
            continue

        ll = line.lower()
        m = re.search(r'\[emailtool\] stage=(\w+)', ll)
        if m:
            stage = m.group(1)
            idx = STAGE_AGENT.get(stage, current)
            segs[idx].append(line)
            # Advance current agent after the boundary line
            current = min(idx + 1, 4)
            continue

        # Pipeline step markers
        if "[4/6]" in ll or "[drive]" in ll or "[5/6]" in ll or "bq:" in ll \
                or "[6/6]" in ll or "[reporttool]" in ll or "[orchestrator]" in ll \
                or "pipeline complete" in ll or "claim id" in ll:
            current = 4

        segs[current].append(line)

    return segs

def lock_active() -> bool:
    if not LOCK_FILE.exists():
        return False
    try:
        age = time.time() - float(LOCK_FILE.read_text())
        return age < 420
    except Exception:
        return False

def acquire_lock() -> bool:
    if lock_active():
        return False
    LOCK_FILE.write_text(str(time.time()))
    return True

def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

def _ts_from_line(line: str) -> str:
    """Extract HH:MM:SS from a log line, or return empty string."""
    m = re.search(r'\b(\d{2}:\d{2}:\d{2})\b', line)
    return m.group(1) if m else ""
