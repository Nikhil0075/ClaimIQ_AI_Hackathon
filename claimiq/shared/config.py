"""Runtime configuration for ClaimIQ."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in production images
    load_dotenv = None

if load_dotenv:
    load_dotenv(override=True)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_id: str = os.getenv("GCP_PROJECT_ID", "")
    region: str = os.getenv("GCP_REGION", "us-central1")
    openai_model: str = os.getenv("OPENAI_MODEL", os.getenv("CLAIMIQ_DEFAULT_TEXT_MODEL", "gpt-4o-mini"))
    default_text_model: str = os.getenv("CLAIMIQ_DEFAULT_TEXT_MODEL", "gpt-4o-mini")
    lightweight_model: str = os.getenv("CLAIMIQ_LIGHTWEIGHT_MODEL", os.getenv("CLAIMIQ_DEFAULT_TEXT_MODEL", "gpt-4o-mini"))
    reasoning_model: str = os.getenv("CLAIMIQ_REASONING_MODEL", "o4-mini")
    vision_model: str = os.getenv("CLAIMIQ_VISION_MODEL", "gpt-4o-mini")
    bq_dataset: str = os.getenv("BQ_DATASET", "claims")
    gcs_bucket: str = os.getenv("GCS_BUCKET", "")
    use_openai: bool = _bool("CLAIMIQ_USE_OPENAI", True)
    write_bq: bool = _bool("CLAIMIQ_WRITE_BQ", False)
    high_value_threshold: float = float(os.getenv("HIGH_VALUE_THRESHOLD", "500000"))
    fraud_high_threshold: int = int(os.getenv("FRAUD_HIGH_THRESHOLD", "70"))
    reasoning_effort: str = os.getenv("REASONING_EFFORT", "medium")


settings = Settings()
