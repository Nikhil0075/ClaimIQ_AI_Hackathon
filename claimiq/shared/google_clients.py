"""Lazy Google Cloud client factories."""

from __future__ import annotations

import os
from pathlib import Path

from .config import settings


def _has_application_default_credentials() -> bool:
    configured = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if configured and Path(configured).exists():
        return True

    candidates = [
        Path.home() / ".config" / "gcloud" / "application_default_credentials.json",
    ]
    appdata = os.getenv("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "gcloud" / "application_default_credentials.json")

    return any(path.exists() for path in candidates)


def _require_google_credentials() -> None:
    if _has_application_default_credentials():
        return
    raise RuntimeError(
        "Google Cloud credentials are not configured. In Streamlit Cloud, set "
        "GOOGLE_APPLICATION_CREDENTIALS_JSON to a service account JSON with BigQuery access."
    )


def bigquery_client():
    _require_google_credentials()
    from google.cloud import bigquery

    return bigquery.Client(project=settings.project_id or None)


def storage_client():
    _require_google_credentials()
    from google.cloud import storage

    return storage.Client(project=settings.project_id or None)
