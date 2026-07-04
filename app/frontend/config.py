"""Shared frontend configuration for the ClaimIQ Streamlit console."""

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
RUN_PY_PATH = APP_DIR / "run.py"
LOG_FILE = APP_DIR / "claimiq_streamlit_logs.json"
LOCK_FILE = APP_DIR / ".claimiq.lock"
LOG_LIMIT = 80
AUTO_INTERVAL_SEC = 10
LOGO_PATH = APP_DIR / "FullLogo_Transparent_NoBuffer.png"
LOOKER_URL = os.getenv(
    "LOOKER_URL",
    "https://datastudio.google.com/u/0/reporting/"
    "cc1bb8db-5fb5-4707-b3aa-5e851aa0e06f/page/RHqzF",
)

AGENTS = [
    ("🔍", "Intake Agent",      "intake"),
    ("📋", "Coverage Agent",    "coverage"),
    ("🚨", "Fraud Agent",       "fraud"),
    ("⚡", "Priority Agent",    "priority"),
    ("📝", "Copilot / Summary", "copilot"),
]
AGENT_COLORS = ["#a78bfa", "#34d399", "#f87171", "#facc15", "#60a5fa"]
AGENT_BG     = ["rgba(167,139,250,.08)", "rgba(52,211,153,.06)",
                "rgba(248,113,113,.06)", "rgba(250,204,21,.06)", "rgba(96,165,250,.06)"]

STAGE_AGENT = {
    "claim_received":       0,
    "coverage_needs_review":1,
    "fraud_alert":          2,
    "routing_assigned":     3,
    "pipeline_complete":    4,
}
