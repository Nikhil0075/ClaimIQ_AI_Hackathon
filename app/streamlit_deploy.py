"""Streamlit Cloud deployment helpers.

Streamlit secrets are not automatically exposed as environment variables.
This module bridges the deployed app's secrets into the environment and writes
Google Drive OAuth files to private runtime paths so the existing OAuth-based
Drive uploader can keep using GOOGLE_OAUTH_CREDENTIALS and its cached token.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st


_SCALAR_SECRET_KEYS = {
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "CLAIMIQ_USE_OPENAI",
    "CLAIMIQ_WRITE_BQ",
    "CLAIMIQ_DEFAULT_TEXT_MODEL",
    "CLAIMIQ_LIGHTWEIGHT_MODEL",
    "CLAIMIQ_REASONING_MODEL",
    "CLAIMIQ_VISION_MODEL",
    "CLAIMIQ_ORCHESTRATOR_MODEL",
    "CLAIMIQ_ROUTER_MODEL",
    "CLAIMIQ_INTAKE_REASONING_MODEL",
    "CLAIMIQ_INTAKE_VISION_MODEL",
    "CLAIMIQ_INTAKE_TEXT_DOCUMENT_MODEL",
    "CLAIMIQ_COVERAGE_MODEL",
    "CLAIMIQ_FRAUD_MODEL",
    "CLAIMIQ_TRIAGE_MODEL",
    "CLAIMIQ_COPILOT_MODEL",
    "CLAIMIQ_MAIL_GUARD_MODEL",
    "CLAIMIQ_EMAIL_MODEL",
    "CLAIMIQ_ATTACHMENT_TEXT_MODEL",
    "CLAIMIQ_ATTACHMENT_VISION_MODEL",
    "CLAIMIQ_ATTACHMENT_SYNTHESIS_MODEL",
    "GCP_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "GCP_REGION",
    "BQ_DATASET",
    "GCS_BUCKET",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "LOOKER_URL",
    "FORM_URL_BASE",
    "DRIVE_ROOT_FOLDER_NAME",
    "HIGH_VALUE_THRESHOLD",
    "FRAUD_HIGH_THRESHOLD",
    "FRAUD_EMAIL_THRESHOLD",
    "REPORT_FRAUD_THRESHOLD",
    "REPORT_AMOUNT_THRESHOLD",
    "REASONING_EFFORT",
}


def configure_streamlit_cloud_runtime() -> None:
    """Apply Streamlit secrets for deployed runtime compatibility."""
    _copy_scalar_secrets_to_env()
    oauth_credentials_json = _get_secret("GOOGLE_OAUTH_CREDENTIALS_JSON")
    if oauth_credentials_json:
        runtime_dir = _runtime_secret_dir()
        _write_json_secret(
            raw_value=oauth_credentials_json,
            secret_name="GOOGLE_OAUTH_CREDENTIALS_JSON",
            target_path=runtime_dir / "google_oauth_credentials.json",
            env_name="GOOGLE_OAUTH_CREDENTIALS",
        )

    drive_token_json = _get_secret("GOOGLE_DRIVE_TOKEN_JSON")
    if drive_token_json:
        _write_json_secret(
            raw_value=drive_token_json,
            secret_name="GOOGLE_DRIVE_TOKEN_JSON",
            target_path=_drive_token_path(),
            env_name="GOOGLE_DRIVE_TOKEN_PATH",
        )


def _copy_scalar_secrets_to_env() -> None:
    for key in _SCALAR_SECRET_KEYS:
        value = _get_secret(key)
        if value is None:
            continue
        os.environ[key] = str(value)


def _runtime_secret_dir() -> Path:
    base = Path(os.getenv("CLAIMIQ_RUNTIME_SECRET_DIR", Path.home() / ".claimiq" / "secrets"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _drive_token_path() -> Path:
    configured = os.getenv("GOOGLE_DRIVE_TOKEN_PATH")
    if configured:
        return Path(configured)
    return _runtime_secret_dir() / "drive_token.json"


def _get_secret(key: str):
    try:
        return st.secrets[key]
    except Exception:
        return None


def _write_json_secret(
    *,
    raw_value: str,
    secret_name: str,
    target_path: Path,
    env_name: str | None = None,
) -> None:
    if not raw_value:
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    content = _normalize_json_secret(str(raw_value), secret_name)
    if not target_path.exists() or target_path.read_text(encoding="utf-8") != content:
        target_path.write_text(content, encoding="utf-8")

    if env_name:
        os.environ[env_name] = str(target_path)


def _normalize_json_secret(raw_value: str, secret_name: str) -> str:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{secret_name} must contain valid JSON") from exc
    return json.dumps(parsed, indent=2)
