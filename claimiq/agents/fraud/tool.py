"""Fraud Agent tools."""

from __future__ import annotations

import json
import os
from typing import Any

from claimiq.shared.config import settings
from claimiq.shared.openai_client import generate_json
from claimiq.shared.google_clients import bigquery_client
from .functions import recommended_action

import logging

log = logging.getLogger(__name__)


def find_duplicate_claims(claim_id: str, intake: dict[str, Any]) -> list[str]:
    if not settings.project_id or not intake.get("sender_email") or not intake.get("incident_date"):
        return []
    try:
        from google.cloud import bigquery

        query = f"""
            SELECT claim_id
            FROM `{settings.project_id}.{settings.bq_dataset}.claims_master`
            WHERE sender_email = @sender_email
              AND claim_id != @claim_id
              AND claim_type = @claim_type
              AND incident_date BETWEEN DATE_SUB(@incident_date, INTERVAL 90 DAY)
                                  AND DATE_ADD(@incident_date, INTERVAL 90 DAY)
            LIMIT 5
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("sender_email", "STRING", intake.get("sender_email")),
            bigquery.ScalarQueryParameter("claim_id", "STRING", claim_id),
            bigquery.ScalarQueryParameter("claim_type", "STRING", intake.get("claim_type")),
            bigquery.ScalarQueryParameter("incident_date", "DATE", intake.get("incident_date")),
        ])
        return [row["claim_id"] for row in bigquery_client().query(query, job_config=job_config).result()]
    except Exception as exc:
        log.warning("Duplicate lookup failed: %s", exc)
        return []


def synthesize_fraud(claim_id: str, intake: dict[str, Any], coverage: dict[str, Any], signals: list[dict[str, Any]], score: int, level: str, duplicate_ids: list[str]) -> dict[str, Any]:
    action = recommended_action(score, signals)
    prompt = f"""You are the ClaimIQ Fraud Signal Agent in a Track 1 insurance industry workflow.
Act like an experienced Special Investigation Unit investigator. The deterministic
fraud score, risk level, signals, score contributions, duplicate_claim_ids, and
recommended_action are fixed. You must explain the evidence without changing,
removing, re-scoring, or softening them. Do not reject or approve the claim;
recommend investigation priority only.

SIU explanation requirements:
1. Explain every signal supplied in SIGNALS. Do not omit signals that look
   uncomfortable or duplicative; consolidate only in prose, not in the returned
   signals array.
2. For each signal, state why it is present using the evidence object, claim type,
   document summary, coverage data, duplicate ids, provider/watchlist context, or
   benchmark detail supplied to you.
3. Treat fraud_score as capped at 100 and deterministic. Never recalculate it.
4. Borderline actions must follow deterministic logic:
   - high-severity signal plus score >=75 supports hold_processing_pending_investigation
   - high-severity signal plus score >=60 supports refer_to_siu
   - three or more medium signals plus score >=50 supports request_additional_documents
   - duplicate claim plus new policy and score >=60 supports refer_to_siu
   - score below 40 normally supports continue_processing
5. Do not call a claim fraudulent as a final conclusion. Use SIU language:
   "requires verification", "investigation priority", "evidence to validate",
   "document authenticity check", or "provider billing review".
6. For AI-generated or tampered document signals, discuss the observed indicators:
   metadata mismatch, pasted/missing signatures or stamps, font/layout mismatch,
   repeated wording, terminology inconsistency, unusually polished medical prose,
   OCR/layout anomalies, or inconsistent PDF/document dates when present.
7. For billing anomaly signals, cite the benchmark or policy-limit evidence
   supplied in the signal and identify the amount that should be validated.
8. For timeline inconsistency signals, describe the chronological impossibility
   or date mismatch and list which dates require source verification.
9. For provider risk, cite the watchlist reason, severity, city, or added date
   when supplied. Do not invent public database or news evidence.

Return strict JSON with fraud_score, risk_level, signals, duplicate_claim_ids,
invoice_anomaly, vendor_flagged, fraud_reasoning, fraud_confidence,
recommended_action, fraud_notes, fraud_indicators, investigation_focus.

CLAIM_ID: {claim_id}
INTAKE:
{json.dumps(intake, indent=2, default=str)[:2500]}
COVERAGE:
{json.dumps(coverage, indent=2, default=str)[:1800]}
SIGNALS:
{json.dumps(signals, indent=2, default=str)}
FRAUD_SCORE: {score}
RISK_LEVEL: {level}
RECOMMENDED_ACTION: {action}
DUPLICATE_IDS: {json.dumps(duplicate_ids)}
"""
    return generate_json(
        prompt,
        temperature=0.05,
        max_tokens=4096,
        model=os.getenv("CLAIMIQ_FRAUD_MODEL", settings.reasoning_model),
    )
