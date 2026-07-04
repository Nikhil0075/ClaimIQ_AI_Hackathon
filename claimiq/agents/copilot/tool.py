"""Adjuster Copilot OpenAI synthesis."""

from __future__ import annotations

import json
import os
from typing import Any

from claimiq.shared.config import settings
from claimiq.shared.openai_client import generate_json


def synthesize_brief(claim_id: str, intake: dict[str, Any], coverage: dict[str, Any], fraud: dict[str, Any], triage: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""You are the ClaimIQ Adjuster Copilot for a Track 1 insurance industry workflow.
You assist insurance employees; you never approve, reject, deny, settle, or accuse.
Behave like an experienced claims assistant for customer service, claims officers,
medical reviewers, fraud investigators, supervisors, and audit teams.

Create a concise, auditable employee copilot brief. Return strict JSON with:
brief_version, generated_at, triage_color, executive_summary, claim_details,
coverage_position, fraud_assessment, routing_decision, open_questions,
approval_checklist, evidence_log, adjuster_brief_markdown, copilot_role,
decision_guardrails, citations, plain_english_explanations, role_assistance,
claim_timeline, suggested_next_steps, generated_letters, internal_notes,
employee_question_suggestions, knowledge_sources_used, recommended_tools.

Use only the supplied agent outputs. Cite policy sections, documents, fraud
signals, and triage flags when available. If evidence is missing, say manual
review is required instead of inventing facts.

CLAIM_ID: {claim_id}
INTAKE:
{json.dumps(intake, indent=2, default=str)[:2500]}
COVERAGE:
{json.dumps(coverage, indent=2, default=str)[:2200]}
FRAUD:
{json.dumps(fraud, indent=2, default=str)[:2200]}
TRIAGE:
{json.dumps(triage, indent=2, default=str)[:2200]}
"""
    return generate_json(
        prompt,
        temperature=0.2,
        max_tokens=8192,
        model=os.getenv("CLAIMIQ_COPILOT_MODEL", settings.reasoning_model),
    )
