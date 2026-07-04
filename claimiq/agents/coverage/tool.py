"""Coverage Agent tools."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from claimiq.shared.config import settings
from claimiq.shared.openai_client import generate_json
from claimiq.shared.google_clients import bigquery_client

import logging

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

POLICY_DOCUMENTS = [
    {
        "document_id": "claimiq_coverage_health",
        "title": "ClaimIQ Coverage HEALTH",
        "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/ClaimIQ_Coverage_HEALTH.pdf",
        "local_path": REPO_ROOT / "docs" / "ClaimIQ_Coverage_HEALTH.pdf",
        "claim_types": ("health", "medical"),
    },
    {
        "document_id": "claimiq_coverage_motor",
        "title": "ClaimIQ Coverage MOTOR",
        "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/ClaimIQ_Coverage_MOTOR.pdf",
        "local_path": REPO_ROOT / "docs" / "ClaimIQ_Coverage_MOTOR.pdf",
        "claim_types": ("motor", "vehicle", "auto"),
    },
    {
        "document_id": "claimiq_coverage_property",
        "title": "ClaimIQ Coverage PROPERTY",
        "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/ClaimIQ_Coverage_PROPERTY.pdf",
        "local_path": REPO_ROOT / "docs" / "ClaimIQ_Coverage_PROPERTY.pdf",
        "claim_types": ("property", "home"),
    },
    {
        "document_id": "claimiq_coverage_travel",
        "title": "ClaimIQ Coverage TRAVEL",
        "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/ClaimIQ_Coverage_TRAVEL.pdf",
        "local_path": REPO_ROOT / "docs" / "ClaimIQ_Coverage_TRAVEL.pdf",
        "claim_types": ("travel",),
    },
    {
        "document_id": "fgi_group_health_revised",
        "title": "FGI Group Health Insurance (revised)",
        "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/FGI_GroupHealthInsurance(revised).pdf",
        "local_path": REPO_ROOT / "docs" / "FGI_GroupHealthInsurance(revised).pdf",
        "claim_types": ("health", "medical"),
    },
    {
        "document_id": "group_health_policy",
        "title": "Group Health Insurance Policy",
        "url": "https://storage.googleapis.com/claimiq-raw-claimiq-ai-demo/coverage_docs/Group%20Health%20Insurance%20Policy.pdf",
        "local_path": REPO_ROOT / "docs" / "Group Health Insurance Policy.pdf",
        "claim_types": ("health", "medical"),
    },
]

POLICY_DOCUMENTS_CACHE: list[dict[str, Any]] | None = None

REFERENCE_POLICY_PROFILES = {
    "ABC234567": {
        "claim_type": "health",
        "policy_holder_name": "Sample Health Policyholder",
        "product_name": "Starlight Insurance Health Insurance Policy",
        "sum_insured": 1000000,
        "max_claim_amount": 1000000,
        "deductible": 0,
        "covered_perils": ["health", "medical", "hospitalisation", "surgical procedures", "emergency care"],
        "exclusions": [
            "Pre-existing conditions during the first 12 months from policy inception.",
            "Adventure or hazardous sports injuries.",
            "Self-inflicted injuries.",
            "Claims arising from alcohol or drug use.",
        ],
    },
    "HEA567890": {
        "claim_type": "health",
        "policy_holder_name": "Sample Emergency Health Policyholder",
        "product_name": "Starlight Insurance Health Insurance Policy",
        "sum_insured": 1000000,
        "max_claim_amount": 1000000,
        "deductible": 0,
        "covered_perils": ["health", "medical", "hospitalisation", "cardiac emergency", "icu"],
        "exclusions": [
            "Pre-existing conditions during the first 12 months from policy inception.",
            "Adventure or hazardous sports injuries.",
            "Self-inflicted injuries.",
            "Claims arising from alcohol or drug use.",
        ],
    },
    "MCA789012": {
        "claim_type": "motor",
        "policy_holder_name": "Sample Motor Policyholder",
        "product_name": "Bajaj Allianz Private Car Package Policy",
        "sum_insured": 450000,
        "max_claim_amount": 450000,
        "deductible": 5000,
        "covered_perils": ["motor", "accident", "own damage", "theft", "natural calamities"],
        "exclusions": [
            "Mechanical or electrical breakdown and wear and tear.",
            "Damage attributable to poor maintenance.",
            "Driving under the influence of alcohol or drugs.",
            "Unauthorised vehicle modifications.",
            "Use other than the declared private purpose.",
        ],
    },
    "PRO234567": {
        "claim_type": "property",
        "policy_holder_name": "Sample Property Policyholder",
        "product_name": "Home / Property Fire & Allied Perils Policy",
        "sum_insured": 4000000,
        "max_claim_amount": 4000000,
        "deductible": None,
        "covered_perils": ["property", "fire", "fire and allied perils", "electrical short circuit", "water damage from firefighting"],
        "exclusions": [
            "Arson or wilful / self-inflicted damage.",
            "Any loss where accelerant use or intentional cause is established.",
            "Consequential loss and loss of contents not owned by the insured.",
            "Ordinary wear and tear and gradual deterioration.",
            "Claims under active criminal investigation are not payable until cleared.",
        ],
    },
    "TRV123456": {
        "claim_type": "travel",
        "policy_holder_name": "Sample Travel Policyholder",
        "product_name": "Starlight Travel Insurance International Travel Health Coverage",
        "sum_insured": 500000,
        "max_claim_amount": 500000,
        "deductible": 5000,
        "covered_perils": ["travel", "medical emergency abroad", "hospitalisation", "accident while abroad"],
        "exclusions": [
            "Pre-existing medical conditions.",
            "High-risk sports and activities.",
            "Travel to countries under a government warning.",
            "Claims arising from alcohol or drug use.",
            "Pregnancy-related complications after 24 weeks.",
        ],
    },
}

BASE_COVERAGE_TERMS = (
    "coverage",
    "covered",
    "exclusion",
    "waiting period",
    "sum insured",
    "sub-limit",
    "sublimit",
    "deductible",
    "room rent",
    "network hospital",
    "cashless",
    "pre-authorisation",
    "pre-authorization",
    "endorsement",
    "renewal",
    "appeal",
    "grievance",
)

SECTION_CATEGORY_TERMS = {
    "coverage": ("coverage", "covered", "benefit", "scope", "insured event"),
    "exclusion": ("exclusion", "excluded", "not covered", "waiting period"),
    "limit": ("limit", "sub-limit", "sublimit", "deductible", "co-pay", "sum insured", "room rent"),
    "definition": ("definition", "means", "defined as", "interpretation"),
    "endorsement": ("endorsement", "rider", "amendment", "renewal", "add-on"),
}


def lookup_policy(policy_number: str | None) -> dict[str, Any]:
    if not policy_number or not settings.project_id:
        return {}
    try:
        from google.cloud import bigquery

        query = f"""
            SELECT *
            FROM `{settings.project_id}.{settings.bq_dataset}.policies`
            WHERE policy_number = @policy_number
            LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("policy_number", "STRING", policy_number)]
        )
        rows = list(bigquery_client().query(query, job_config=job_config).result())
        return dict(rows[0]) if rows else {}
    except Exception as exc:
        log.warning("Policy lookup failed: %s", exc)
        return {}


def load_policy_document_catalog(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Load policy wording/reference documents from BigQuery, falling back locally."""
    global POLICY_DOCUMENTS_CACHE
    if POLICY_DOCUMENTS_CACHE is not None and not force_refresh:
        return POLICY_DOCUMENTS_CACHE

    source = os.getenv("CLAIMIQ_POLICY_DOCUMENTS_SOURCE", "auto").strip().lower()
    if source == "local":
        POLICY_DOCUMENTS_CACHE = POLICY_DOCUMENTS
        return POLICY_DOCUMENTS_CACHE

    documents = _lookup_policy_documents_from_bq()
    POLICY_DOCUMENTS_CACHE = documents or POLICY_DOCUMENTS
    return POLICY_DOCUMENTS_CACHE


def _lookup_policy_documents_from_bq() -> list[dict[str, Any]]:
    if not settings.project_id:
        return []
    try:
        from google.cloud import bigquery

        query = f"""
            SELECT document_id, policy_type, title, gcs_url, version, effective_from, effective_to
            FROM `{settings.project_id}.{settings.bq_dataset}.policy_documents`
            WHERE effective_to IS NULL OR effective_to >= CURRENT_DATE()
            ORDER BY policy_type, effective_from DESC, document_id
        """
        rows = list(bigquery_client().query(query).result())
        return [_policy_document_from_bq_row(dict(row)) for row in rows]
    except Exception as exc:
        log.warning("Policy document catalog lookup failed, using local catalog: %s", exc)
        return []


def _policy_document_from_bq_row(row: dict[str, Any]) -> dict[str, Any]:
    policy_type = _normalize_claim_type_text(row.get("policy_type"))
    url = str(row.get("gcs_url") or "").strip()
    filename = _filename_from_url(url)
    return {
        "document_id": str(row.get("document_id") or filename or "policy_document").strip(),
        "title": str(row.get("title") or row.get("document_id") or filename or "Policy Document").strip(),
        "url": url,
        "local_path": REPO_ROOT / "docs" / filename if filename else REPO_ROOT / "docs",
        "claim_types": _claim_type_aliases(policy_type),
        "version": str(row.get("version") or "").strip(),
        "effective_from": row.get("effective_from"),
        "effective_to": row.get("effective_to"),
        "catalog_source": "bigquery",
    }


def _filename_from_url(url: str) -> str:
    if not url:
        return ""
    return unquote(Path(urlparse(url).path).name)


def derive_policy_from_reference(intake: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Use explicit sample-policy references from ClaimIQ coverage PDFs as demo policy records."""
    policy_number = str(intake.get("policy_number") or "").strip().upper()
    if not policy_number:
        return {}

    profile = REFERENCE_POLICY_PROFILES.get(policy_number)
    if not profile:
        return {}

    evidence = evidence or {}
    matching_citations = [
        snippet
        for snippet in evidence.get("snippets") or []
        if policy_number in str(snippet.get("excerpt") or "").upper()
    ]
    if not matching_citations:
        matching_citations = [
            source
            for source in evidence.get("sources") or []
            if _normalized_claim_type(intake, profile) in {str(item).lower() for item in source.get("claim_types") or ()}
        ]
    if not matching_citations:
        return {}

    sections = _reference_sections(evidence, policy_number)
    return {
        **profile,
        "policy_number": policy_number,
        "status": "reference_policy_found",
        "policy_status_note": (
            "Policy number matched an explicit sample policy in the ClaimIQ coverage reference. "
            "Effective dates and member-level eligibility still require system-of-record verification."
        ),
        "requires_system_record_verification": True,
        "sections": sections,
        "policy_source": "claimiq_coverage_reference",
    }


def load_policy_evidence(intake: dict[str, Any], policy: dict[str, Any] | None) -> dict[str, Any]:
    """Build a compact policy evidence bundle from uploaded/local policy documents."""
    search_terms = _coverage_search_terms(intake, policy or {})
    catalog = load_policy_document_catalog()
    selected_documents = _candidate_policy_documents(intake, policy or {}, catalog)
    claim_type = _normalized_claim_type(intake, policy or {})
    reviewed_documents: list[dict[str, Any]] = []
    snippets: list[dict[str, Any]] = []

    for document in selected_documents:
        local_path = Path(document["local_path"])
        review = {
            "document_id": document["document_id"],
            "title": document["title"],
            "source_url": document["url"],
            "local_path": str(local_path),
            "claim_types": list(document.get("claim_types") or ()),
            "selection_reason": _selection_reason(document, claim_type),
            "catalog_source": document.get("catalog_source", "local"),
            "version": document.get("version"),
            "effective_from": document.get("effective_from"),
            "effective_to": document.get("effective_to"),
            "retrieved": local_path.exists(),
            "retrieval_status": "local_copy_found" if local_path.exists() else "not_found_locally",
        }
        reviewed_documents.append(review)
        snippets.extend(_extract_relevant_snippets(local_path, document, search_terms))

    snippets.extend(_structured_policy_snippets(policy or {}))
    ranked_snippets = _rank_policy_snippets(_dedupe_snippets(snippets), search_terms)
    return {
        "claim_type": claim_type or "unknown",
        "sources": reviewed_documents,
        "search_terms": search_terms,
        "snippets": ranked_snippets[:10],
    }


def reason_about_coverage(
    intake: dict[str, Any],
    policy: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = f"""You are the ClaimIQ Coverage Agent in a Track 1 insurance industry workflow.
Determine coverage using only the claim, policy data, and policy-document
evidence provided below. Do not approve, deny, or limit a claim from general
insurance knowledge. If policy evidence is missing or unclear, use
coverage_status = "needs_review".

Coverage status contract:
- Use "covered" when the policy is active, the claim type/peril is covered, no
  cited exclusion blocks the claim, and any deductible/sub-limit calculation is
  explainable from policy evidence.
- Use "covered" with calculation_methodology showing approved amount, shortfall,
  patient responsibility, and applied sub-limits when the claim is only partly
  payable but the payable portion is explicit.
- Use "not_covered" only when a specific cited exclusion, inactive policy,
  unsatisfied waiting period, exhausted sum insured, or non-covered peril clearly
  applies.
- Use "needs_review" when the policy is not found, evidence is ambiguous,
  endorsement/rider wording may change the result, a sub-limit cannot be
  calculated, required claim facts are missing, or a denial would rely on an
  inferred rather than explicit clause.

Decision tree:
1. Confirm policy record exists. If not found, set policy_status to "not_found",
   coverage_status to "needs_review", and list customer_policy_record as missing.
2. Confirm policy was active on incident_date. If not active and dates are clear,
   set not_covered with the policy date citation; if dates are missing or unclear,
   set needs_review.
3. Check endorsements, riders, renewals, amendments, and waiting-period language
   before applying base-policy exclusions. If any may override the base policy
   and evidence is absent, set needs_review.
4. Check explicit exclusions. A sufficient denial citation must include a section
   or clause reference plus the policy-document excerpt/source/page when
   available. Vague phrases such as "exclusion found" are not sufficient.
5. Check waiting periods. Show the calculation, for example: 60 days required,
   45 days elapsed, 15 days remaining.
6. Calculate payable amount against sum insured, remaining balance, deductible,
   co-pay, room-rent or procedure sub-limits, network/cashless constraints, and
   prior payouts. If any required limit is unavailable, set needs_review.
7. Produce final reasoning with cited policy evidence and no unsupported
   assumptions.

Calculation methodology must be rigorous:
- Include sum_insured, claimed_amount, previous_payouts, remaining_sum_insured,
  deductible, applied_limits, applicable_exclusions, calculation_steps,
  approved_amount, patient_responsibility, shortfall, network_applicable, and
  cashless_available when the data is available.
- For sub-limit breaches, show each applied limit and the net result.
- If approved amount is zero because of a cited exclusion, state the exact
  exclusion and citation in calculation_steps and denial_reason.

Regulatory compliance rules:
- Every coverage decision must cite specific policy sections or
  policy-document snippets.
- Do not deny claims without a cited exclusion, waiting-period clause, inactive
  policy clause/date evidence, exhausted-limit calculation, or non-covered peril
  clause.
- Do not apply age, gender, family-history, undisclosed limits, or general
  medical-necessity reasons unless a specific policy provision supports it.
- Allowed example: policy Section 6.2 excludes a diagnosis regardless of
  heredity, or the policy explicitly covers only ages 18-65.
- Not allowed: denied because claimant is female/male, older than 45, has family
  history, or lacks medical necessity without policy wording.
- If hospital name, procedure/code, endorsement/renewal wording, rider effect,
  or limit calculation is missing, set coverage_status to needs_review.
- Denials must include clear denial_reason and appeals_process.
- Include documents reviewed, calculation methodology, decision timestamp, and
  reviewing agent.
- Before returning not_covered, verify: specific exclusion/clause citation
  exists, appeals_process is present, no prohibited basis is used, and reasoning
  explains the policy link.

Return strict JSON with:
policy_number, policy_holder_name, policy_inception_date, policy_expiry_date,
policy_status, coverage_status, claim_type_covered,
policy_active_on_incident_date, waiting_period_breach, waiting_period_days,
days_since_inception_to_incident, applicable_exclusions, applicable_limits,
policy_sections_referenced, coverage_reasoning, coverage_confidence,
documents_reviewed, calculation_methodology, regulatory_findings,
manual_review_required, missing_information, denial_reason, appeals_process.

CLAIM:
{json.dumps(intake, indent=2, default=str)}

POLICY:
{json.dumps(policy or {"status": "not_found"}, indent=2, default=str)}

POLICY DOCUMENT EVIDENCE:
{json.dumps(evidence or {}, indent=2, default=str)}
"""
    return generate_json(
        prompt,
        temperature=0.05,
        max_tokens=4096,
        model=os.getenv("CLAIMIQ_COVERAGE_MODEL", settings.reasoning_model),
    )


def _coverage_search_terms(intake: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    terms = list(BASE_COVERAGE_TERMS)
    for key in ("claim_type", "request_type", "procedure", "diagnosis", "hospital_name"):
        value = intake.get(key)
        if value:
            terms.append(str(value))
    terms.extend(_targeted_policy_terms(intake))
    for key in ("product_name", "plan_name", "policy_type"):
        value = policy.get(key)
        if value:
            terms.append(str(value))
    return list(dict.fromkeys(term.strip() for term in terms if term and term.strip()))


def _candidate_policy_documents(
    intake: dict[str, Any],
    policy: dict[str, Any],
    catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    documents = catalog or load_policy_document_catalog()
    claim_type = _normalized_claim_type(intake, policy)
    if not claim_type:
        return documents

    matched = [
        document
        for document in documents
        if claim_type in {str(item).lower() for item in document.get("claim_types") or ()}
    ]
    return matched or documents


def _normalized_claim_type(intake: dict[str, Any], policy: dict[str, Any]) -> str:
    raw = (
        intake.get("claim_type")
        or intake.get("line_of_business")
        or policy.get("claim_type")
        or policy.get("product_type")
        or policy.get("policy_type")
        or ""
    )
    return _normalize_claim_type_text(raw)


def _normalize_claim_type_text(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    aliases = {
        "medical": "health",
        "health insurance": "health",
        "vehicle": "motor",
        "auto": "motor",
        "car": "motor",
        "home": "property",
        "house": "property",
        "trip": "travel",
    }
    return aliases.get(text, text)


def _claim_type_aliases(policy_type: str) -> tuple[str, ...]:
    aliases = {
        "health": ("health", "medical"),
        "motor": ("motor", "vehicle", "auto"),
        "property": ("property", "home"),
        "travel": ("travel", "trip"),
    }
    return aliases.get(policy_type, (policy_type,) if policy_type else ())


def _selection_reason(document: dict[str, Any], claim_type: str) -> str:
    claim_types = {str(item).lower() for item in document.get("claim_types") or ()}
    if claim_type and claim_type in claim_types:
        return f"matched_claim_type:{claim_type}"
    if not claim_type:
        return "fallback_unknown_claim_type"
    return "fallback_no_exact_policy_document"


def _reference_sections(evidence: dict[str, Any], policy_number: str) -> list[str]:
    sections: list[str] = []
    for snippet in evidence.get("snippets") or []:
        section = str(snippet.get("section_reference") or "").strip()
        title = str(snippet.get("document_title") or "").strip()
        if section and title:
            sections.append(f"{title} - {section}")
        elif section:
            sections.append(section)
    if not sections:
        sections.append(f"ClaimIQ coverage reference sample policy {policy_number}")
    return list(dict.fromkeys(sections))[:8]


def _targeted_policy_terms(intake: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        str(intake.get(key) or "")
        for key in ("claim_type", "request_type", "procedure", "diagnosis", "incident_description")
    ).lower()
    terms: list[str] = []
    if "acl" in haystack or "orthopedic" in haystack or "orthopaedic" in haystack:
        terms.extend(["ACL reconstruction", "sports injury", "orthopedic", "orthopaedic"])
    if "pregnancy" in haystack or "maternity" in haystack or "obstetric" in haystack:
        terms.extend(["pregnancy", "maternity", "obstetrics"])
    if "third party" in haystack or "vehicle" in haystack or "motor" in haystack:
        terms.extend(["third party", "liability", "own damage"])
    if "cashless" in haystack or "pre-author" in haystack or "preauthor" in haystack:
        terms.extend(["cashless", "network hospital", "pre-authorization", "pre-authorisation"])
    return terms


def _extract_relevant_snippets(
    local_path: Path,
    document: dict[str, Any],
    search_terms: list[str],
) -> list[dict[str, Any]]:
    if not local_path.exists():
        return []
    try:
        from pypdf import PdfReader
    except ImportError:
        return []

    snippets: list[dict[str, Any]] = []
    try:
        reader = PdfReader(str(local_path))
        for index, page in enumerate(reader.pages, start=1):
            text = _normalize_text(page.extract_text() or "")
            if not text:
                continue
            lower = text.lower()
            for term in search_terms:
                needle = term.lower()
                if needle not in lower:
                    continue
                start = max(lower.find(needle) - 180, 0)
                end = min(start + 520, len(text))
                snippets.append({
                    "document_id": document["document_id"],
                    "document_title": document["title"],
                    "source_url": document["url"],
                    "page": index,
                    "matched_term": term,
                    "section_reference": _nearest_section_reference(text, start, index),
                    "section_category": _snippet_category(text[start:end]),
                    "excerpt": text[start:end].strip(),
                })
                break
    except Exception as exc:
        log.warning("Policy PDF evidence extraction failed for %s: %s", local_path, exc)
    return snippets


def _structured_policy_snippets(policy: dict[str, Any]) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for section in policy.get("sections") or []:
        snippets.append({
            "document_id": "policy_record",
            "document_title": "Customer Policy Record",
            "section_reference": str(section),
            "section_category": _snippet_category(str(section)),
            "excerpt": f"Structured policy section referenced by policy record: {section}",
        })
    for exclusion in policy.get("exclusions") or []:
        snippets.append({
            "document_id": "policy_record",
            "document_title": "Customer Policy Record",
            "section_reference": "Policy exclusions",
            "section_category": "exclusion",
            "excerpt": str(exclusion),
        })
    return snippets


def _rank_policy_snippets(snippets: list[dict[str, Any]], search_terms: list[str]) -> list[dict[str, Any]]:
    scored = []
    for snippet in snippets:
        excerpt = str(snippet.get("excerpt") or "")
        section = str(snippet.get("section_reference") or "")
        category = str(snippet.get("section_category") or _snippet_category(" ".join([section, excerpt])))
        score = _snippet_score(section, excerpt, search_terms, category)
        enriched = dict(snippet)
        enriched["section_category"] = category
        enriched["relevance_score"] = round(score, 3)
        scored.append(enriched)

    scored.sort(key=lambda item: float(item.get("relevance_score") or 0), reverse=True)
    return _top_k_by_category(scored)


def _snippet_score(section: str, excerpt: str, search_terms: list[str], category: str) -> float:
    haystack = " ".join([section, excerpt]).lower()
    score = 0.0
    for term in search_terms:
        needle = str(term).lower()
        if not needle:
            continue
        if needle in haystack:
            score += 2.0 if len(needle) > 6 else 1.0
    if re.search(r"(?i)\b(section|clause|benefit|exclusion|limit|definition)\s+[A-Z0-9]", section):
        score += 1.5
    if category in {"exclusion", "limit", "coverage", "definition", "endorsement"}:
        score += 1.0
    if "policy_record" in str(section).lower():
        score += 0.5
    return score


def _snippet_category(text: str) -> str:
    lower = str(text or "").lower()
    for category, terms in SECTION_CATEGORY_TERMS.items():
        if any(term in lower for term in terms):
            return category
    return "general"


def _top_k_by_category(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limits = {
        "coverage": 2,
        "exclusion": 2,
        "limit": 2,
        "definition": 1,
        "endorsement": 1,
    }
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    for category, limit in limits.items():
        count = 0
        for index, snippet in enumerate(scored):
            if index in selected_ids or snippet.get("section_category") != category:
                continue
            selected.append(snippet)
            selected_ids.add(index)
            count += 1
            if count >= limit:
                break

    for index, snippet in enumerate(scored):
        if index in selected_ids:
            continue
        selected.append(snippet)
        selected_ids.add(index)
        if len(selected) >= 10:
            break
    return selected


def _dedupe_snippets(snippets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for snippet in snippets:
        key = (
            str(snippet.get("document_id")),
            str(snippet.get("page")),
            str(snippet.get("section_reference")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(snippet)
    return unique


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _nearest_section_reference(text: str, position: int, page: int) -> str:
    prefix = text[max(0, position - 500):position]
    matches = re.findall(
        r"(?i)\b(?:section|clause|part|benefit|exclusion)\s+[A-Z0-9][A-Z0-9.\-() ]{0,40}",
        prefix,
    )
    if matches:
        return matches[-1].strip()
    return f"Page {page}"
