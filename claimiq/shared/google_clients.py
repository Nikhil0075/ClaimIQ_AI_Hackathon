"""Lazy Google Cloud client factories."""

from __future__ import annotations

from .config import settings


def bigquery_client():
    from google.cloud import bigquery

    return bigquery.Client(project=settings.project_id or None)


def storage_client():
    from google.cloud import storage

    return storage.Client(project=settings.project_id or None)
