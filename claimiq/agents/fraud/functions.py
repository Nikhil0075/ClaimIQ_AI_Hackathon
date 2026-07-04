"""Fraud Agent deterministic SIU-style rules."""

from __future__ import annotations

import re
from typing import Any

from claimiq.agents.coverage.functions import parse_date

WEIGHTS = {
    "NEW_POLICY_CLOSE_TO_INCIDENT": 30,
    "DUPLICATE_CLAIM_DETECTED": 35,
    "CLAIM_AMOUNT_OUTLIER": 15,
    "VENDOR_FLAGGED_IN_REGISTRY": 25,
    "DOCUMENT_RISK_SIGNAL": 20,
    "IDENTITY_MISMATCH": 25,
    "TIMELINE_INCONSISTENCY": 25,
    "MEDICAL_INCONSISTENCY": 20,
    "BILLING_ANOMALY": 20,
    "PROVIDER_RISK": 20,
    "BEHAVIORAL_PATTERN": 15,
    "AI_OR_TAMPERED_DOCUMENT": 25,
    "LOW_DOCUMENT_CONFIDENCE": 10,
}

FRAUD_WEIGHTS_BY_CLAIM_TYPE = {
    "health": {
        "NEW_POLICY_CLOSE_TO_INCIDENT": 40,
        "DUPLICATE_CLAIM_DETECTED": 35,
        "CLAIM_AMOUNT_OUTLIER": 20,
        "VENDOR_FLAGGED_IN_REGISTRY": 25,
        "DOCUMENT_RISK_SIGNAL": 25,
        "IDENTITY_MISMATCH": 30,
        "TIMELINE_INCONSISTENCY": 25,
        "MEDICAL_INCONSISTENCY": 30,
        "BILLING_ANOMALY": 25,
        "PROVIDER_RISK": 25,
        "BEHAVIORAL_PATTERN": 20,
        "AI_OR_TAMPERED_DOCUMENT": 30,
        "LOW_DOCUMENT_CONFIDENCE": 15,
    },
    "motor": {
        "NEW_POLICY_CLOSE_TO_INCIDENT": 35,
        "DUPLICATE_CLAIM_DETECTED": 40,
        "CLAIM_AMOUNT_OUTLIER": 25,
        "VENDOR_FLAGGED_IN_REGISTRY": 30,
        "DOCUMENT_RISK_SIGNAL": 20,
        "IDENTITY_MISMATCH": 20,
        "TIMELINE_INCONSISTENCY": 30,
        "MEDICAL_INCONSISTENCY": 5,
        "BILLING_ANOMALY": 30,
        "PROVIDER_RISK": 35,
        "BEHAVIORAL_PATTERN": 25,
        "AI_OR_TAMPERED_DOCUMENT": 35,
        "LOW_DOCUMENT_CONFIDENCE": 20,
    },
    "property": {
        "NEW_POLICY_CLOSE_TO_INCIDENT": 40,
        "DUPLICATE_CLAIM_DETECTED": 35,
        "CLAIM_AMOUNT_OUTLIER": 25,
        "VENDOR_FLAGGED_IN_REGISTRY": 25,
        "DOCUMENT_RISK_SIGNAL": 30,
        "IDENTITY_MISMATCH": 20,
        "TIMELINE_INCONSISTENCY": 25,
        "MEDICAL_INCONSISTENCY": 5,
        "BILLING_ANOMALY": 25,
        "PROVIDER_RISK": 25,
        "BEHAVIORAL_PATTERN": 25,
        "AI_OR_TAMPERED_DOCUMENT": 35,
        "LOW_DOCUMENT_CONFIDENCE": 20,
    },
    "travel": {
        "NEW_POLICY_CLOSE_TO_INCIDENT": 10,
        "DUPLICATE_CLAIM_DETECTED": 25,
        "CLAIM_AMOUNT_OUTLIER": 20,
        "VENDOR_FLAGGED_IN_REGISTRY": 20,
        "DOCUMENT_RISK_SIGNAL": 25,
        "IDENTITY_MISMATCH": 25,
        "TIMELINE_INCONSISTENCY": 30,
        "MEDICAL_INCONSISTENCY": 10,
        "BILLING_ANOMALY": 20,
        "PROVIDER_RISK": 15,
        "BEHAVIORAL_PATTERN": 25,
        "AI_OR_TAMPERED_DOCUMENT": 30,
        "LOW_DOCUMENT_CONFIDENCE": 15,
    },
    "life": {
        "NEW_POLICY_CLOSE_TO_INCIDENT": 45,
        "DUPLICATE_CLAIM_DETECTED": 35,
        "CLAIM_AMOUNT_OUTLIER": 20,
        "VENDOR_FLAGGED_IN_REGISTRY": 20,
        "DOCUMENT_RISK_SIGNAL": 35,
        "IDENTITY_MISMATCH": 35,
        "TIMELINE_INCONSISTENCY": 35,
        "MEDICAL_INCONSISTENCY": 20,
        "BILLING_ANOMALY": 10,
        "PROVIDER_RISK": 20,
        "BEHAVIORAL_PATTERN": 30,
        "AI_OR_TAMPERED_DOCUMENT": 40,
        "LOW_DOCUMENT_CONFIDENCE": 25,
    },
}

PROVIDER_WATCHLIST = {
    "health": {
        "abc hospital": {
            "risk_score": 72,
            "severity": "medium",
            "city": "Bangalore",
            "reason": "Provider appears on the internal demo SIU watchlist.",
            "added_date": "2025-02-01",
        },
        "xyz care": {
            "risk_score": 82,
            "severity": "high",
            "city": "Delhi",
            "reason": "Provider has elevated historical fraud rate in demo watchlist.",
            "added_date": "2025-01-15",
        },
        "shady care": {
            "risk_score": 90,
            "severity": "high",
            "city": "Mumbai",
            "reason": "Provider has repeated suspicious billing patterns in demo watchlist.",
            "added_date": "2024-12-15",
        },
    },
    "motor": {
        "quick fix garage": {
            "risk_score": 78,
            "severity": "medium",
            "city": "Mumbai",
            "reason": "Inflated repair invoices suspected in internal demo watchlist.",
            "added_date": "2024-12-15",
        },
    },
}

PRICE_BENCHMARKS = {
    "health": {
        "acl reconstruction": {"low": 150000, "avg": 250000, "high": 400000, "outlier_threshold": 500000},
        "mri": {"low": 3000, "avg": 5000, "high": 8000, "outlier_threshold": 10000},
        "appendectomy": {"low": 100000, "avg": 180000, "high": 300000, "outlier_threshold": 400000},
        "cesarean delivery": {"low": 150000, "avg": 250000, "high": 400000, "outlier_threshold": 550000},
        "iccu per day": {"low": 10000, "avg": 15000, "high": 25000, "outlier_threshold": 35000},
    },
    "motor": {
        "small car repair": {"low": 50000, "avg": 100000, "high": 150000, "outlier_threshold": 200000},
        "large car repair": {"low": 100000, "avg": 200000, "high": 350000, "outlier_threshold": 500000},
        "two wheeler repair": {"low": 10000, "avg": 25000, "high": 50000, "outlier_threshold": 70000},
        "vehicle repair": {"low": 10000, "avg": 85000, "high": 250000, "outlier_threshold": 300000},
    },
}

MEDICAL_CONFLICTS = (
    (("minor sprain", "sprain", "strain"), ("reconstruction", "replacement", "surgery")),
    (("migraine", "headache"), ("heart surgery", "cardiac", "angioplasty")),
    (("normal vitals", "stable vitals"), ("icu", "ventilator")),
)

TAMPER_TERMS = (
    "edited",
    "tamper",
    "photoshop",
    "font mismatch",
    "metadata",
    "forged",
    "signature pasted",
    "signature missing",
    "stamp missing",
    "ai generated",
    "generated document",
    "inconsistent formatting",
    "digital-only",
    "terminology inconsistency",
)

IDENTITY_TERMS = ("name mismatch", "identity mismatch", "age mismatch", "aadhaar mismatch", "kyc mismatch")
TIMELINE_TERMS = (
    "timeline",
    "date mismatch",
    "after discharge",
    "before admission",
    "admitted before",
    "discharged before",
    "inconsistent date",
    "chronology",
)
BILLING_TERMS = ("duplicate charge", "overbilling", "inflated", "exceeds benchmark", "unusually high")
NETWORK_TERMS = ("same doctor", "same pharmacy", "repeated provider", "organized", "network")


def risk_level(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def recommended_action(score: int, signals: list[dict[str, Any]] | None = None) -> str:
    """Map score to investigator action without rejecting the claim."""
    signal_list = signals or []
    signal_ids = {str(signal.get("signal_id")) for signal in signal_list}
    has_high_severity = any(int(signal.get("score_contribution") or 0) >= 35 for signal in signal_list)
    medium_or_higher_count = sum(1 for signal in signal_list if int(signal.get("score_contribution") or 0) >= 20)

    if has_high_severity and score >= 75:
        return "hold_processing_pending_investigation"
    if has_high_severity and score >= 60:
        return "refer_to_siu"
    if medium_or_higher_count >= 3 and score >= 70:
        return "refer_to_siu"
    if medium_or_higher_count >= 3 and score >= 50:
        return "request_additional_documents"
    if {"DUPLICATE_CLAIM_DETECTED", "NEW_POLICY_CLOSE_TO_INCIDENT"}.issubset(signal_ids) and score >= 60:
        return "refer_to_siu"
    if score >= 85 or "DUPLICATE_CLAIM_DETECTED" in signal_ids and score >= 70:
        return "hold_processing_pending_investigation"
    if score >= 70:
        return "refer_to_siu"
    if score >= 40:
        return "request_additional_documents"
    return "continue_processing"


def compute_signals(intake: dict[str, Any], coverage: dict[str, Any], duplicate_ids: list[str] | None = None) -> tuple[list[dict[str, Any]], int]:
    signals: list[dict[str, Any]] = []
    claim_type = _claim_type(intake)

    inception = parse_date(coverage.get("policy_inception_date"))
    incident = parse_date(intake.get("incident_date"))
    if inception and incident:
        days = (incident - inception).days
        if 0 <= days <= 30:
            weight = _weight("NEW_POLICY_CLOSE_TO_INCIDENT", claim_type)
            signals.append({
                "signal_id": "NEW_POLICY_CLOSE_TO_INCIDENT",
                "description": f"Policy started {days} day(s) before incident.",
                "severity": "critical" if days <= 7 else "high",
                "score_contribution": weight,
                "evidence": {"days_since_policy_inception": days, "claim_type": claim_type},
            })

    if duplicate_ids:
        weight = _weight("DUPLICATE_CLAIM_DETECTED", claim_type)
        signals.append({
            "signal_id": "DUPLICATE_CLAIM_DETECTED",
            "description": "Similar prior claim ids found.",
            "severity": "critical",
            "score_contribution": weight,
            "evidence": {"duplicate_claim_ids": duplicate_ids, "claim_type": claim_type},
            })

    amount = float(intake.get("claim_amount") or 0)
    limit = coverage.get("applicable_limits", {}).get("max_claim_amount") if isinstance(coverage.get("applicable_limits"), dict) else None
    if limit and amount > float(limit):
        _add_signal(signals, {
            "signal_id": "CLAIM_AMOUNT_OUTLIER",
            "category": "billing_fraud",
            "description": "Claim amount exceeds configured policy limit.",
            "severity": "high",
            "score_contribution": _weight("CLAIM_AMOUNT_OUTLIER", claim_type),
            "evidence": {"claim_amount": amount, "policy_limit": limit},
        })

    _add_document_signals(signals, intake, claim_type)
    _add_identity_signals(signals, intake, claim_type)
    _add_timeline_signals(signals, intake, claim_type)
    _add_medical_signals(signals, intake, claim_type)
    _add_billing_signals(signals, intake, amount, claim_type)
    _add_provider_signals(signals, intake, claim_type)
    _add_behavioral_signals(signals, intake, claim_type)

    score = sum(int(signal.get("score_contribution") or 0) for signal in signals)
    return signals, min(score, 100)


def _add_signal(signals: list[dict[str, Any]], signal: dict[str, Any]) -> None:
    signal.setdefault("category", _category_for(signal.get("signal_id")))
    signal.setdefault("evidence", {})
    signals.append(signal)


def _add_document_signals(signals: list[dict[str, Any]], intake: dict[str, Any], claim_type: str) -> None:
    risk_items = _list_values(intake.get("risk_indicators")) + _list_values(intake.get("basic_red_flags"))
    docs = intake.get("documents_summary") if isinstance(intake.get("documents_summary"), dict) else {}
    if docs:
        risk_items.extend(_list_values(docs.get("risk_signals")))

    risk_text = " ".join(risk_items).lower()
    if risk_items:
        weight = _weight("DOCUMENT_RISK_SIGNAL", claim_type)
        _add_signal(signals, {
            "signal_id": "DOCUMENT_RISK_SIGNAL",
            "category": "document_fraud",
            "description": "Intake or document analysis surfaced suspicious document risk signals.",
            "severity": "high" if any(term in risk_text for term in TAMPER_TERMS) else "medium",
            "score_contribution": weight,
            "evidence": {"risk_signals": risk_items[:8], "claim_type": claim_type},
        })

    tamper_matches = _matching_terms(risk_text, TAMPER_TERMS)
    ai_confidence = _ai_document_confidence(tamper_matches, risk_text)
    if tamper_matches:
        _add_signal(signals, {
            "signal_id": "AI_OR_TAMPERED_DOCUMENT",
            "category": "ai_generated_or_tampered_document",
            "description": "Document evidence mentions editing, metadata, forged signature, or AI-generated content.",
            "severity": "critical",
            "score_contribution": _weight("AI_OR_TAMPERED_DOCUMENT", claim_type),
            "confidence": ai_confidence,
            "evidence": {
                "matching_terms": tamper_matches,
                "claim_type": claim_type,
                "heuristic": "0-3 flags low, 4-5 flags medium, 6+ flags high",
            },
        })

    low_confidence_docs = [
        str(item.get("filename") or "document")
        for item in _per_document_items(intake)
        if float(item.get("confidence") or 1.0) < 0.45
    ]
    if low_confidence_docs:
        _add_signal(signals, {
            "signal_id": "LOW_DOCUMENT_CONFIDENCE",
            "category": "document_fraud",
            "description": "One or more claim documents have low extraction confidence and need manual verification.",
            "severity": "medium",
            "score_contribution": _weight("LOW_DOCUMENT_CONFIDENCE", claim_type),
            "evidence": {"documents": low_confidence_docs[:5], "claim_type": claim_type},
        })


def _add_identity_signals(signals: list[dict[str, Any]], intake: dict[str, Any], claim_type: str) -> None:
    names = {
        "claimant_name": intake.get("claimant_name"),
        "patient_name": intake.get("patient_name"),
    }
    clean_names = {key: _normalize_name(value) for key, value in names.items() if value}
    if len(set(clean_names.values())) > 1:
        _add_signal(signals, {
            "signal_id": "IDENTITY_MISMATCH",
            "category": "identity_fraud",
            "description": "Claimant and patient identity fields do not match.",
            "severity": "high",
            "score_contribution": _weight("IDENTITY_MISMATCH", claim_type),
            "evidence": {**names, "claim_type": claim_type},
        })
        return

    risk_text = _risk_text(intake)
    if any(term in risk_text for term in IDENTITY_TERMS):
        _add_signal(signals, {
            "signal_id": "IDENTITY_MISMATCH",
            "category": "identity_fraud",
            "description": "Document or intake analysis reported an identity mismatch.",
            "severity": "high",
            "score_contribution": _weight("IDENTITY_MISMATCH", claim_type),
            "evidence": {"matching_terms": _matching_terms(risk_text, IDENTITY_TERMS)},
        })


def _add_timeline_signals(signals: list[dict[str, Any]], intake: dict[str, Any], claim_type: str) -> None:
    risk_text = _risk_text(intake)
    if any(term in risk_text for term in TIMELINE_TERMS):
        _add_signal(signals, {
            "signal_id": "TIMELINE_INCONSISTENCY",
            "category": "timing_fraud",
            "description": "Timeline or date sequence appears inconsistent.",
            "severity": "high",
            "score_contribution": _weight("TIMELINE_INCONSISTENCY", claim_type),
            "evidence": {"matching_terms": _matching_terms(risk_text, TIMELINE_TERMS)},
        })

    incident = parse_date(intake.get("incident_date"))
    doc_dates = []
    for item in _per_document_items(intake):
        fields = item.get("extracted_fields") if isinstance(item.get("extracted_fields"), dict) else {}
        for key in ("admission_date", "document_date", "discharge_date", "surgery_date"):
            parsed = parse_date(fields.get(key))
            if parsed:
                doc_dates.append((key, parsed.isoformat()))
    future_or_before_incident = [
        {"field": key, "value": date_value}
        for key, date_value in doc_dates
        if parse_date(date_value) and (
            key in {"discharge_date", "surgery_date"} and parse_date(date_value) < incident
            if incident
            else False
        )
    ]
    if future_or_before_incident:
        _add_signal(signals, {
            "signal_id": "TIMELINE_INCONSISTENCY",
            "category": "timing_fraud",
            "description": "Document date sequence appears chronologically impossible.",
            "severity": "high",
            "score_contribution": _weight("TIMELINE_INCONSISTENCY", claim_type),
            "evidence": {"incident_date": intake.get("incident_date"), "document_dates": future_or_before_incident},
        })


def _add_medical_signals(signals: list[dict[str, Any]], intake: dict[str, Any], claim_type: str) -> None:
    text = " ".join(str(intake.get(key) or "") for key in ("diagnosis", "procedure", "incident_description", "claim_summary")).lower()
    for diagnosis_terms, procedure_terms in MEDICAL_CONFLICTS:
        if any(term in text for term in diagnosis_terms) and any(term in text for term in procedure_terms):
            _add_signal(signals, {
                "signal_id": "MEDICAL_INCONSISTENCY",
                "category": "medical_fraud",
                "description": "Diagnosis and billed treatment appear clinically inconsistent and need SIU review.",
                "severity": "high",
                "score_contribution": _weight("MEDICAL_INCONSISTENCY", claim_type),
                "evidence": {"diagnosis": intake.get("diagnosis"), "procedure": intake.get("procedure")},
            })
            return


def _add_billing_signals(signals: list[dict[str, Any]], intake: dict[str, Any], amount: float, claim_type: str) -> None:
    risk_text = _risk_text(intake)
    procedure_text = " ".join(str(intake.get(key) or "") for key in ("procedure", "diagnosis", "claim_summary", "incident_description")).lower()
    for label, benchmark in _benchmarks_for_claim_type(claim_type).items():
        if label in procedure_text and amount > float(benchmark["outlier_threshold"]):
            _add_signal(signals, {
                "signal_id": "BILLING_ANOMALY",
                "category": "billing_fraud",
                "description": f"Claim amount exceeds internal benchmark for {label}.",
                "severity": "high" if amount > float(benchmark["outlier_threshold"]) * 1.25 else "medium",
                "score_contribution": _weight("BILLING_ANOMALY", claim_type),
                "confidence": 0.75,
                "evidence": {
                    "claim_amount": amount,
                    "benchmark_low": benchmark["low"],
                    "benchmark_high": benchmark["high"],
                    "benchmark_avg": benchmark["avg"],
                    "outlier_threshold": benchmark["outlier_threshold"],
                    "claim_type": claim_type,
                },
            })
            return

    if any(term in risk_text for term in BILLING_TERMS):
        _add_signal(signals, {
            "signal_id": "BILLING_ANOMALY",
            "category": "billing_fraud",
            "description": "Billing evidence suggests duplicate charges, inflation, or abnormal pricing.",
            "severity": "high",
            "score_contribution": _weight("BILLING_ANOMALY", claim_type),
            "evidence": {"matching_terms": _matching_terms(risk_text, BILLING_TERMS)},
        })


def _add_provider_signals(signals: list[dict[str, Any]], intake: dict[str, Any], claim_type: str) -> None:
    provider = str(intake.get("hospital_name") or intake.get("vendor_name") or "").strip()
    watch = _lookup_provider_in_watchlist(provider, claim_type)
    if watch:
        _add_signal(signals, {
            "signal_id": "PROVIDER_RISK",
            "category": "provider_fraud",
            "description": watch["reason"],
            "severity": "critical" if watch["risk_score"] >= 80 else "high",
            "score_contribution": _weight("PROVIDER_RISK", claim_type),
            "confidence": 0.85,
            "evidence": {
                "provider": provider,
                "provider_risk_score": watch["risk_score"],
                "watchlist_severity": watch.get("severity"),
                "city": watch.get("city"),
                "added_date": watch.get("added_date"),
                "claim_type": claim_type,
            },
        })


def _add_behavioral_signals(signals: list[dict[str, Any]], intake: dict[str, Any], claim_type: str) -> None:
    previous_claims = int(float(intake.get("previous_claim_count_90d") or intake.get("recent_claim_count") or 0))
    risk_text = _risk_text(intake)
    if previous_claims >= 3 or any(term in risk_text for term in NETWORK_TERMS):
        _add_signal(signals, {
            "signal_id": "BEHAVIORAL_PATTERN",
            "category": "behavioral_or_network_fraud",
            "description": "Claim history or network clues indicate an unusual repeated pattern.",
            "severity": "medium" if previous_claims < 5 else "high",
            "score_contribution": _weight("BEHAVIORAL_PATTERN", claim_type),
            "evidence": {"previous_claim_count_90d": previous_claims, "matching_terms": _matching_terms(risk_text, NETWORK_TERMS)},
        })


def _risk_text(intake: dict[str, Any]) -> str:
    values = (
        _list_values(intake.get("risk_indicators"))
        + _list_values(intake.get("basic_red_flags"))
        + _list_values(intake.get("quality_issues"))
        + [str(item) for item in intake.get("consistency_issues") or []]
    )
    return " ".join(values).lower()


def _claim_type(intake: dict[str, Any]) -> str:
    claim_type = str(intake.get("claim_type") or "other").strip().lower()
    return claim_type if claim_type in FRAUD_WEIGHTS_BY_CLAIM_TYPE else "other"


def _weight(signal_id: str, claim_type: str) -> int:
    return FRAUD_WEIGHTS_BY_CLAIM_TYPE.get(claim_type, {}).get(signal_id, WEIGHTS[signal_id])


def _benchmarks_for_claim_type(claim_type: str) -> dict[str, dict[str, int]]:
    if claim_type in PRICE_BENCHMARKS:
        return PRICE_BENCHMARKS[claim_type]
    merged: dict[str, dict[str, int]] = {}
    for benchmarks in PRICE_BENCHMARKS.values():
        merged.update(benchmarks)
    return merged


def _lookup_provider_in_watchlist(provider: str, claim_type: str) -> dict[str, Any] | None:
    provider_key = provider.lower().strip()
    if not provider_key:
        return None
    claim_watchlist = PROVIDER_WATCHLIST.get(claim_type, {})
    if provider_key in claim_watchlist:
        return claim_watchlist[provider_key]
    for watchlist in PROVIDER_WATCHLIST.values():
        if provider_key in watchlist:
            return watchlist[provider_key]
    return None


def _ai_document_confidence(matches: list[str], risk_text: str) -> float:
    contextual_flags = 0
    for phrase in (
        "formal tone",
        "repeated phrase",
        "repeated sentence",
        "medical jargon",
        "grammatical perfection",
        "created date",
        "document date",
    ):
        if phrase in risk_text:
            contextual_flags += 1
    flag_count = len(set(matches)) + contextual_flags
    if flag_count >= 6:
        return 0.9
    if flag_count >= 4:
        return 0.6
    return 0.2


def _list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _per_document_items(intake: dict[str, Any]) -> list[dict[str, Any]]:
    docs = intake.get("documents_summary") if isinstance(intake.get("documents_summary"), dict) else {}
    return [item for item in docs.get("per_document") or [] if isinstance(item, dict)]


def _matching_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def _normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").lower())


def _category_for(signal_id: Any) -> str:
    return {
        "NEW_POLICY_CLOSE_TO_INCIDENT": "policy_fraud",
        "DUPLICATE_CLAIM_DETECTED": "duplicate_claim_fraud",
        "CLAIM_AMOUNT_OUTLIER": "billing_fraud",
        "VENDOR_FLAGGED_IN_REGISTRY": "provider_fraud",
    }.get(str(signal_id), "fraud_signal")
