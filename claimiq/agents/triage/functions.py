"""Triage hard rules."""

from __future__ import annotations

import re
from typing import Any

from claimiq.agents.coverage.functions import parse_date
from claimiq.shared.config import settings

SLA_MAP = {
    "medical_emergency_review": 0.25,
    "urgent_medical_review": 2,
    "medical_document_request": 24,
    "urgent_claim_review": 8,
    "auto_approve": 24,
    "standard_review": 48,
    "senior_review": 72,
    "special_investigation": 120,
    "legal": 168,
}
MANDATORY_REVIEW_TYPES = {"health", "medical", "legal", "life"}
PRIORITY_LEVELS = {"low", "medium", "high", "critical"}
MEDICAL_CLAIM_TYPES = {"health", "medical"}
# Signals that a travel (or other) claim has a medical dimension and should be
# triaged clinically even though the claim type itself is not "health".
MEDICAL_CONTEXT_TERMS = (
    "hospital", "diagnos", "surgery", "treatment", "doctor", "icu",
    "medical emergency", "admitted", "emergency room",
)
# ── Non-medical urgency (motor / property / travel) ──────────────────────────
NONMEDICAL_EMERGENCY_TERMS = (
    "uninhabitable",
    "family displaced",
    "displaced from home",
    "complete destruction",
    "completely destroyed",
    "total loss",
    "totaled",
    "structure collapse",
    "collapsed",
    "still burning",
    "gas leak",
    "medical evacuation",
    "emergency evacuation",
    "repatriation",
)
NONMEDICAL_URGENT_TERMS = (
    "undrivable",
    "not drivable",
    "not roadworthy",
    "vehicle towed",
    "stranded",
    "no accommodation",
    "temporary accommodation",
    "water damage spreading",
    "passport stolen",
    "all documents stolen",
    "hospitalized abroad",
    "injured",
    "passenger injured",
)
NONMEDICAL_SPECIALIST_MAP = {
    "motor": "Motor Assessor",
    "property": "Property Loss Surveyor",
    "travel": "Travel Claims Reviewer",
    "life": "Life Claims Reviewer",
    "legal": "Legal Reviewer",
}
NON_MEDICAL_NA = "N/A (non-medical claim)"
EMERGENCY_TERMS = (
    "heart attack",
    "myocardial infarction",
    "stemi",
    "nstemi",
    "st elevation mi",
    "non st elevation mi",
    "acute coronary syndrome",
    "acute mi",
    "stroke",
    "acute stroke",
    "cva",
    "pulmonary embolism",
    "embolism",
    "meningitis",
    "anaphylaxis",
    "major trauma",
    "polytrauma",
    "severe hemorrhage",
    "haemorrhage",
    "severe bleeding",
    "severe burn",
    "sepsis",
    "severe sepsis",
    "septic shock",
    "internal bleeding",
    "respiratory failure",
    "loss of consciousness",
    "unconscious",
    "ventilator",
    "cardiac arrest",
    "emergency angioplasty",
)
URGENT_TERMS = (
    "acute abdomen",
    "displaced fracture",
    "compound fracture",
    "open fracture",
    "femur fracture",
    "hip fracture",
    "fracture with neurovascular compromise",
    "appendicitis",
    "high fever",
    "pneumonia",
    "kidney failure",
    "acute kidney injury",
    "acute pancreatitis",
    "post operative day 1",
    "post operative day 2",
    "post-op day 1",
    "post-op day 2",
    "severe trauma",
    "icu",
    "critical care",
)
STANDARD_TERMS = (
    "elective surgery",
    "diagnostic procedure",
    "mri",
    "ct scan",
    "ultrasound",
    "routine hospitalization",
    "chronic disease management",
)
ELECTIVE_TERMS = ("elective", "scheduled", "planned", "pre-planned", "routine")
ICU_TERMS = ("icu", "intensive care", "critical care", "ventilator")
NORMAL_VITAL_TERMS = ("normal bp", "normal pulse", "normal oxygen", "stable vitals", "vitals normal")
COMORBIDITY_TERMS = ("diabetes", "hypertension", "ckd", "chronic kidney", "copd", "heart failure", "immunosuppressed")
MISSING_ICU_NOTE_TERMS = ("no icu note", "icu notes missing", "missing icu", "without icu notes")
RARE_PROCEDURE_TERMS = ("neurosurgery", "brain surgery", "transplant", "cardiac bypass", "angioplasty")
GENERALIST_TERMS = ("general physician", "general practitioner", "gp")
SPECIALIST_MAP = (
    (("heart", "cardiac", "angioplasty", "myocardial", "bypass", "stemi", "nstemi", "acute coronary", "pci"), "Cardiology Reviewer"),
    (("stroke", "brain", "neurology", "neuro", "seizure"), "Neurology Reviewer"),
    (("cancer", "tumor", "chemotherapy", "oncology"), "Oncology Reviewer"),
    (("acl", "knee", "arthroscopy", "fracture", "orthopedic"), "Orthopedic Reviewer"),
    (("pregnancy", "obstetric", "delivery", "maternity"), "Obstetrics Reviewer"),
    (("appendicitis", "appendectomy", "hernia", "laparoscopic"), "General Surgery Reviewer"),
    (("colonoscopy", "gastro", "pancreatitis", "liver"), "Gastroenterology Reviewer"),
    (("cataract", "retina", "ophthalm"), "Ophthalmology Reviewer"),
    (("mri", "ct scan", "ultrasound", "radiology"), "Radiology Reviewer"),
    (("child", "pediatric", "paediatric", "infant"), "Pediatric Reviewer"),
)
NECESSITY_MISMATCHES = (
    (("common cold", "cold", "viral fever"), ("heart surgery", "angioplasty", "transplant")),
    (("gastritis", "acidity"), ("liver transplant", "transplant")),
    (("minor sprain", "sprain", "strain"), ("replacement", "reconstruction", "major surgery")),
    (("mild back pain",), ("icu", "ventilator", "critical care")),
)


def _is_medical_claim(claim_type: str, text: str) -> bool:
    """Medical triage applies to health/medical claims, and to any claim whose
    facts show a medical dimension (e.g. travel claim with hospitalization)."""
    if claim_type in MEDICAL_CLAIM_TYPES:
        return True
    return _has_any(text, MEDICAL_CONTEXT_TERMS)


def approval_reasons(intake: dict[str, Any], coverage: dict[str, Any], fraud: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    fraud_score = int(fraud.get("fraud_score") or 0)
    coverage_status = str(coverage.get("coverage_status") or "needs_review")
    claim_amount = float(intake.get("claim_amount") or 0)
    claim_type = str(intake.get("claim_type") or "").lower()
    text = _clinical_text(intake)

    if fraud_score >= settings.fraud_high_threshold:
        reasons.append(f"Fraud score {fraud_score} exceeds threshold {settings.fraud_high_threshold}")
    if coverage_status in {"needs_review", "not_covered"}:
        reasons.append(f"Coverage status is {coverage_status}")
    if claim_amount >= settings.high_value_threshold:
        reasons.append(f"Claim amount exceeds high-value threshold {settings.high_value_threshold:.0f}")
    if claim_type in MANDATORY_REVIEW_TYPES:
        reasons.append(f"Claim type {claim_type} requires human review")
    if claim_type == "travel" and _is_medical_claim(claim_type, text):
        reasons.append("Travel claim with medical treatment requires human review")
    if not _is_medical_claim(claim_type, text) and _has_any(text, NONMEDICAL_EMERGENCY_TERMS):
        reasons.append("Severe incident impact (total loss/displacement/evacuation) requires priority handling")
    if fraud.get("duplicate_claim_ids"):
        reasons.append("Duplicate claim detected")
    reasons.extend(flag["description"] for flag in clinical_flags(intake))
    return sorted(set(reasons))


def safe_triage(intake: dict[str, Any], coverage: dict[str, Any], fraud: dict[str, Any]) -> dict[str, Any]:
    reasons = approval_reasons(intake, coverage, fraud)
    score = int(fraud.get("fraud_score") or 0)
    coverage_status = str(coverage.get("coverage_status") or "needs_review")
    assessment = clinical_assessment(intake, coverage, fraud)

    routing = assessment["routing"]
    color = assessment["triage_color"]
    priority = assessment["priority"]

    if score >= 70 and routing != "medical_emergency_review":
        routing, color, priority = "special_investigation", "red", "critical"
    elif score >= 50 and priority not in {"critical"}:
        routing, color, priority = "special_investigation", "red", "high"
    elif routing == "standard_review" and (coverage_status == "needs_review" or reasons):
        routing, color, priority = "senior_review", "amber", "high"
    elif coverage_status == "covered" and routing == "standard_review":
        routing = "standard_review"
        color = "green" if not reasons and color == "green" else color
    elif routing == "standard_review":
        color, priority = "amber", "medium"

    return {
        "triage_color": color,
        "priority": priority,
        "routing": routing,
        "required_human_approval": bool(reasons),
        "human_approval_reasons": reasons,
        "clinical_priority": assessment["clinical_priority"],
        "urgency": assessment["urgency"],
        "medical_necessity": assessment["medical_necessity"],
        "severity_score": assessment["severity_score"],
        "expected_hospital_stay": assessment["expected_hospital_stay"],
        "expected_rehabilitation": assessment["expected_rehabilitation"],
        "recommended_specialist": assessment["recommended_specialist"],
        "requires_manual_medical_review": bool(
            assessment.get("is_medical", True) and (reasons or assessment["clinical_flags"])
        ),
        "clinical_flags": assessment["clinical_flags"],
        # Settlement estimate derived from the routing SLA (the old fixed 1/2/7
        # implied a red fraud investigation settles in 1 day). Investigation and
        # legal queues get an extra evidence-gathering window.
        "estimated_settlement_days": _estimated_settlement_days(routing),
        "recommended_next_steps": _next_steps(routing, assessment, score),
        "triage_summary": _summary(routing, color, assessment),
        "fraud_score": score,
        "coverage_status": coverage_status,
        "sla_hours": SLA_MAP[routing],
    }


def clinical_assessment(
    intake: dict[str, Any],
    coverage: dict[str, Any] | None = None,
    fraud: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess clinical urgency without making coverage or fraud decisions."""
    text = _clinical_text(intake)
    claim_type = str(intake.get("claim_type") or "").lower()
    is_medical = _is_medical_claim(claim_type, text)
    flags = clinical_flags(intake)
    priority = "medium"
    color = "green"
    routing = "standard_review"
    urgency = "Routine"
    medical_necessity = "Supported" if is_medical else NON_MEDICAL_NA

    emergency = is_medical and (any(term in text for term in EMERGENCY_TERMS) or _emergency_vitals(text))
    urgent = is_medical and any(term in text for term in URGENT_TERMS)
    # Non-medical severity: total loss, displacement, evacuation, stranded, etc.
    # Gated on non-medical claims so broad terms ("injured") cannot sidestep
    # the clinical rules on health claims.
    nonmed_emergency = not is_medical and not emergency and _has_any(text, NONMEDICAL_EMERGENCY_TERMS)
    nonmed_urgent = not is_medical and not urgent and _has_any(text, NONMEDICAL_URGENT_TERMS)
    standard = any(term in text for term in STANDARD_TERMS)
    elective = any(term in text for term in ELECTIVE_TERMS)
    missing_evidence = _missing_medical_evidence(intake) if is_medical else []
    mismatch = [flag for flag in flags if flag["category"] in {"clinical_mismatch", "impossible_demographics", "timeline"}]

    if emergency:
        priority, color, routing, urgency = "critical", "red", "medical_emergency_review", "Immediate"
    elif urgent:
        priority, color, routing, urgency = "high", "amber", "urgent_medical_review", "Urgent"
    elif nonmed_emergency:
        priority, color, routing, urgency = "critical", "red", "urgent_claim_review", "Immediate"
    elif nonmed_urgent:
        priority, color, routing, urgency = "high", "amber", "urgent_claim_review", "Urgent"
    elif elective or standard:
        priority, color, routing, urgency = "medium", "green", "standard_review", "Elective"

    if missing_evidence:
        flags.extend(missing_evidence)
        medical_necessity = "Needs evidence"
        if not emergency:
            priority, color, routing = "high", "amber", "medical_document_request"

    if mismatch and not emergency:
        if is_medical:
            medical_necessity = "Requires medical review"
        priority, color, routing = "high", "amber", "senior_review"

    if claim_type in {"health", "medical"} and not intake.get("diagnosis") and not intake.get("procedure"):
        flags.append(_flag("missing_clinical_facts", "medical_documentation", "Diagnosis and procedure are missing for a medical claim.", confidence=0.95, severity="medium"))
        medical_necessity = "Needs evidence"
        if not emergency:
            priority, color, routing = "high", "amber", "medical_document_request"

    flags = _dedupe_flags(flags)
    severity_score = _severity_score(
        intake, coverage or {}, fraud or {}, flags,
        emergency or nonmed_emergency, urgent or nonmed_urgent, elective or standard,
    )
    has_medical_dimension = is_medical or emergency or urgent
    return {
        "is_medical": has_medical_dimension,
        "clinical_priority": priority.title(),
        "urgency": urgency,
        "medical_necessity": medical_necessity,
        "severity_score": severity_score,
        "triage_color": color,
        "priority": priority,
        "routing": routing,
        "expected_hospital_stay": _expected_stay(text) if has_medical_dimension else NON_MEDICAL_NA,
        "expected_rehabilitation": _expected_rehabilitation(text) if has_medical_dimension else NON_MEDICAL_NA,
        "recommended_specialist": _recommended_specialist(text, intake),
        "clinical_flags": flags,
    }


def clinical_flags(intake: dict[str, Any]) -> list[dict[str, Any]]:
    text = _clinical_text(intake)
    claim_type = str(intake.get("claim_type") or "").lower()
    if not _is_medical_claim(claim_type, text):
        return []
    flags: list[dict[str, Any]] = []
    patient_age = int(float(intake.get("patient_age") or 0))

    if _has_any(text, ELECTIVE_TERMS) and ("emergency admission" in text or "admission type emergency" in text):
        flags.append(_flag("elective_marked_emergency", "clinical_mismatch", "Elective or scheduled care is marked as emergency admission.", confidence=0.9, severity="medium"))
    for diagnosis_terms, procedure_terms in NECESSITY_MISMATCHES:
        if _has_any(text, diagnosis_terms) and _has_any(text, procedure_terms):
            flags.append(_flag("diagnosis_procedure_mismatch", "clinical_mismatch", "Diagnosis and requested treatment appear clinically inconsistent.", confidence=0.85, severity="high"))
    if "male" in text and _has_any(text, ("pregnancy", "maternity", "delivery")):
        flags.append(_flag("male_pregnancy", "impossible_demographics", "Pregnancy-related claim conflicts with male patient gender.", confidence=1.0, severity="critical"))
    if (0 < patient_age <= 12 or re.search(r"\b(?:1[0-2]|[0-9])\s*(?:year|yr)s?\b", text)) and "age-related cataract" in text:
        flags.append(_flag("child_adult_disease", "impossible_demographics", "Child patient has an age-related adult diagnosis.", confidence=0.95, severity="critical"))
    if _has_any(text, ("right knee", "right acl", "right side")) and _has_any(text, ("left knee", "left acl", "left side")):
        flags.append(_flag("laterality_conflict", "clinical_mismatch", "Clinical documents conflict on left/right body side.", confidence=0.8, severity="medium"))
    if _timeline_inconsistent(intake):
        flags.append(_flag("admission_after_discharge", "timeline", "Admission and discharge dates are inconsistent.", confidence=0.9, severity="high"))
    if _has_any(text, ICU_TERMS) and _has_any(text, NORMAL_VITAL_TERMS):
        flags.append(_flag("normal_vitals_icu", "clinical_mismatch", "ICU or critical care is claimed while vitals are described as normal.", confidence=0.75, severity="medium"))
    if _has_any(text, ICU_TERMS) and (_has_any(text, MISSING_ICU_NOTE_TERMS) or _icu_days(text) >= 7 and "icu note" not in text):
        flags.append(_flag("icu_notes_missing", "medical_documentation", "Extended ICU stay lacks ICU notes or critical-care documentation.", confidence=0.85, severity="high"))
    if _has_any(text, RARE_PROCEDURE_TERMS) and _has_any(text, GENERALIST_TERMS):
        flags.append(_flag("specialist_credential_check", "clinical_mismatch", "Highly specialized procedure appears tied to a general practitioner.", confidence=0.75, severity="medium"))
    if int(float(intake.get("same_day_hospital_visits") or 0)) >= 3:
        flags.append(_flag("duplicate_emergency_pattern", "investigation_signal", "Same-day emergency visits across multiple hospitals need investigation.", confidence=0.85, severity="high"))
    if _emergency_vitals(text):
        flags.append(_flag("critical_vital_threshold", "clinical_acuity", "Vital signs cross emergency threshold and require immediate clinical review.", confidence=0.95, severity="critical"))
    return _dedupe_flags(flags)


def apply_hard_overrides(result: dict[str, Any], intake: dict[str, Any], coverage: dict[str, Any], fraud: dict[str, Any]) -> dict[str, Any]:
    """Preserve non-negotiable clinical and compliance rules after AI synthesis."""
    safe = safe_triage(intake, coverage, fraud)
    merged = dict(result or {})
    safe_is_non_medical = safe.get("medical_necessity") == NON_MEDICAL_NA
    for key in (
        "clinical_priority",
        "urgency",
        "medical_necessity",
        "severity_score",
        "expected_hospital_stay",
        "expected_rehabilitation",
        "recommended_specialist",
        "requires_manual_medical_review",
    ):
        merged[key] = merged.get(key) or safe[key]

    merged["clinical_flags"] = _dedupe_flags((merged.get("clinical_flags") or []) + safe["clinical_flags"])
    if safe_is_non_medical and _is_medical_route(merged.get("routing")):
        for key in ("triage_color", "priority", "routing", "sla_hours"):
            merged[key] = safe[key]
        merged["human_approval_reasons"] = _non_medical_reasons(safe.get("human_approval_reasons") or [])
        merged["clinical_flags"] = safe["clinical_flags"]
        merged["requires_manual_medical_review"] = False
    elif safe["priority"] == "critical" or safe["routing"] in {
        "medical_emergency_review", "medical_document_request", "urgent_claim_review",
    }:
        # Deterministic urgency (medical or severe non-medical impact) may not be
        # downgraded by AI synthesis.
        for key in ("triage_color", "priority", "routing", "sla_hours"):
            merged[key] = safe[key]
    if safe_is_non_medical:
        merged["human_approval_reasons"] = _non_medical_reasons(merged.get("human_approval_reasons") or [])
        merged["requires_manual_medical_review"] = False
    merged["priority"] = _priority_label(merged.get("priority"), safe["priority"])
    merged["triage_color"] = str(merged.get("triage_color") or safe["triage_color"]).lower()
    merged["routing"] = str(merged.get("routing") or safe["routing"])
    merged.setdefault("recommended_next_steps", safe["recommended_next_steps"])
    merged["sla_hours"] = SLA_MAP.get(merged.get("routing"), merged.get("sla_hours", 48))
    return merged


def _is_medical_route(value: Any) -> bool:
    return str(value or "").lower() in {
        "medical_emergency_review",
        "urgent_medical_review",
        "medical_document_request",
    }


def _non_medical_reasons(reasons: list[Any]) -> list[str]:
    blocked = ("vital", "clinical", "medical", "hospital", "diagnosis", "procedure")
    return [
        str(reason)
        for reason in reasons
        if reason and not any(term in str(reason).lower() for term in blocked)
    ]


def _clinical_text(intake: dict[str, Any]) -> str:
    docs = intake.get("documents_summary") if isinstance(intake.get("documents_summary"), dict) else {}
    parts = [
        intake.get("claim_type"),
        intake.get("request_type"),
        intake.get("admission_type"),
        intake.get("diagnosis"),
        intake.get("procedure"),
        intake.get("claim_summary"),
        intake.get("incident_description"),
        intake.get("gender"),
        intake.get("patient_age"),
        intake.get("vitals"),
        " ".join(str(item) for item in intake.get("risk_indicators") or []),
        " ".join(str(item) for item in intake.get("quality_issues") or []),
        str(intake.get("consistency_issues") or ""),
        docs.get("aggregate_summary", ""),
        docs.get("analyst_notes", ""),
        " ".join(str(item) for item in docs.get("risk_signals") or []),
        " ".join(str(item) for item in docs.get("documents_analyzed") or []),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _missing_medical_evidence(intake: dict[str, Any]) -> list[dict[str, str]]:
    missing = {str(item).lower() for item in intake.get("missing_documents") or []}
    text = _clinical_text(intake)
    flags = []
    if ("acl" in text or "ligament" in text) and "reconstruction" in text and "mri_report" in missing:
        flags.append(_flag("mri_required_for_acl", "medical_documentation", "ACL reconstruction requires MRI or radiology evidence before authorization.", confidence=0.9, severity="medium"))
    if _has_any(text, ("surgery", "operation", "reconstruction", "replacement")) and "doctor_prescription" in missing:
        flags.append(_flag("prescription_required", "medical_documentation", "Surgical request is missing doctor prescription.", confidence=0.9, severity="medium"))
    if "icu" in text and not _has_any(text, ("icu note", "critical care note", "ventilator chart")):
        flags.append(_flag("icu_notes_missing", "medical_documentation", "ICU claim needs ICU notes, vitals, and critical-care charting.", confidence=0.85, severity="high"))
    return flags


def _timeline_inconsistent(intake: dict[str, Any]) -> bool:
    docs = intake.get("documents_summary") if isinstance(intake.get("documents_summary"), dict) else {}
    candidates: list[tuple[str, Any]] = [
        ("admission_date", intake.get("admission_date")),
        ("discharge_date", intake.get("discharge_date")),
    ]
    for item in docs.get("per_document") or []:
        if not isinstance(item, dict):
            continue
        fields = item.get("extracted_fields") if isinstance(item.get("extracted_fields"), dict) else {}
        candidates.extend((key, fields.get(key)) for key in ("admission_date", "discharge_date"))
    admissions = [parse_date(value) for key, value in candidates if key == "admission_date"]
    discharges = [parse_date(value) for key, value in candidates if key == "discharge_date"]
    admissions = [value for value in admissions if value]
    discharges = [value for value in discharges if value]
    return bool(admissions and discharges and min(admissions) > max(discharges))


def _severity_score(
    intake: dict[str, Any],
    coverage: dict[str, Any],
    fraud: dict[str, Any],
    flags: list[dict[str, Any]],
    emergency: bool,
    urgent: bool,
    standard_or_elective: bool,
) -> int:
    acuity_score = 40 if emergency else 30 if urgent else 10 if standard_or_elective else 15
    complexity_score = min(_procedure_count(intake) * 10, 30)
    risk_score = 0

    age = int(float(intake.get("patient_age") or 0))
    if 0 < age < 5 or age > 75:
        risk_score += 15
    if _has_any(_clinical_text(intake), COMORBIDITY_TERMS) or intake.get("comorbidities"):
        risk_score += 10
    if str(coverage.get("coverage_status") or "").lower() == "needs_review":
        risk_score += 5
    if int(fraud.get("fraud_score") or 0) >= 60:
        risk_score += 5

    flag_score = 0
    for flag in flags:
        severity = str(flag.get("severity") or "").lower()
        if severity == "critical":
            flag_score += 15
        elif severity == "high":
            flag_score += 10
        elif severity == "medium":
            flag_score += 5

    score = min(100, acuity_score + complexity_score + risk_score + min(flag_score, 20))
    if emergency:
        score = max(score, 85)
    elif urgent:
        score = max(score, 65)
    return score


def _procedure_count(intake: dict[str, Any]) -> int:
    value = intake.get("procedure")
    if isinstance(value, list):
        return len([item for item in value if item])
    text = str(value or "")
    if not text:
        return 0
    parts = re.split(r"\s*(?:,|;|\+|\band\b)\s*", text, flags=re.IGNORECASE)
    return max(1, len([part for part in parts if part.strip()]))


def _emergency_vitals(text: str) -> bool:
    systolic = _first_number_after(text, ("bp", "systolic", "blood pressure"))
    heart_rate = _first_number_after(text, ("hr", "heart rate", "pulse"))
    respiratory_rate = _first_number_after(text, ("rr", "respiratory rate"))
    oxygen = _first_number_after(text, ("spo2", "oxygen saturation", "oxygen"))
    temperature = _first_number_after(text, ("temp", "temperature"))
    return any((
        systolic is not None and systolic < 90,
        heart_rate is not None and (heart_rate > 120 or heart_rate < 40),
        respiratory_rate is not None and (respiratory_rate > 30 or respiratory_rate < 8),
        oxygen is not None and oxygen < 90,
        temperature is not None and (temperature > 39 or temperature < 35),
    ))


def _first_number_after(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\b\s*[:=]?\s*(\d{{1,3}}(?:\.\d+)?)", text)
        if match:
            return float(match.group(1))
    return None


def _expected_stay(text: str) -> str:
    if _has_any(text, EMERGENCY_TERMS) or _has_any(text, ICU_TERMS):
        return "3-7 days or per critical-care notes"
    if "acl" in text or "arthroscopy" in text:
        return "1-3 days"
    if _has_any(text, ELECTIVE_TERMS):
        return "0-2 days"
    return "To be determined from clinical notes"


def _expected_rehabilitation(text: str) -> str:
    if "acl" in text:
        return "3-6 months physiotherapy"
    if "fracture" in text:
        return "4-12 weeks follow-up"
    if _has_any(text, ("stroke", "major trauma")):
        return "Specialist rehabilitation likely"
    return "Not established"


def _recommended_specialist(text: str, intake: dict[str, Any]) -> str:
    claim_type = str(intake.get("claim_type") or "").lower()
    if not _is_medical_claim(claim_type, text):
        # Non-medical claims get a domain reviewer, not a Medical Reviewer.
        return NONMEDICAL_SPECIALIST_MAP.get(claim_type, "Claims Reviewer")
    age = int(float(intake.get("patient_age") or 0))
    if 0 < age <= 12:
        return "Pediatric Reviewer"
    if _has_any(text, ("mri", "ct scan", "ultrasound", "radiology")) and not _has_any(
        text, ("reconstruction", "replacement", "surgery", "operation", "fracture")
    ):
        return "Radiology Reviewer"
    for terms, reviewer in SPECIALIST_MAP:
        if _has_any(text, terms):
            return reviewer
    return "Medical Reviewer"


def _estimated_settlement_days(routing: str) -> int:
    sla_hours = SLA_MAP.get(routing, 48)
    days = max(1, int(-(-sla_hours // 24)))  # ceil without importing math
    if routing in {"special_investigation", "legal"}:
        days += 7  # investigation/legal evidence-gathering window
    return days


def _next_steps(routing: str, assessment: dict[str, Any], fraud_score: int) -> list[str]:
    steps = []
    if routing == "medical_emergency_review":
        steps.append("Bypass routine queue for immediate clinical authorization review.")
    if routing == "medical_document_request":
        steps.append("Request missing clinical evidence before authorization.")
    if routing == "urgent_claim_review":
        steps.append("Expedite assessment: claimant faces severe incident impact (loss of home, vehicle, or travel disruption).")
    if assessment["clinical_flags"]:
        steps.append("Resolve clinical inconsistency or documentation flag.")
    if fraud_score >= 50 or any(flag["category"] == "investigation_signal" for flag in assessment["clinical_flags"]):
        steps.append("Coordinate with Fraud Agent for investigation signals.")
    steps.append("Keep coverage decision separate from clinical urgency.")
    return list(dict.fromkeys(steps))


def _summary(routing: str, color: str, assessment: dict[str, Any]) -> str:
    kind = "Clinical triage" if assessment.get("is_medical", True) else "Claim triage"
    necessity = (
        f"necessity: {assessment['medical_necessity']}."
        if assessment.get("is_medical", True)
        else "no medical dimension."
    )
    return (
        f"{kind} routed to {routing} with {color} status. "
        f"Urgency: {assessment['urgency']}; {necessity}"
    )


def _flag(
    flag_id: str,
    category: str,
    description: str,
    *,
    confidence: float = 0.8,
    severity: str = "medium",
) -> dict[str, Any]:
    return {
        "flag_id": flag_id,
        "category": category,
        "description": description,
        "confidence": confidence,
        "severity": severity,
    }


def _dedupe_flags(flags: list[Any]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in flags:
        if isinstance(item, dict):
            flag = {
                "flag_id": str(item.get("flag_id") or item.get("id") or item.get("description") or "clinical_flag"),
                "category": str(item.get("category") or "clinical"),
                "description": str(item.get("description") or item),
                "confidence": _confidence_value(item.get("confidence"), 0.8),
                "severity": str(item.get("severity") or "medium"),
            }
        else:
            flag = _flag(str(item), "clinical", str(item))
        unique.setdefault(flag["flag_id"], flag)
    return list(unique.values())


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _confidence_value(value: Any, default: float = 0.8) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    text = str(value or "").strip().lower()
    label_map = {
        "very low": 0.1,
        "low": 0.3,
        "medium": 0.55,
        "moderate": 0.55,
        "high": 0.85,
        "very high": 0.95,
    }
    if text in label_map:
        return label_map[text]
    try:
        parsed = float(text)
    except ValueError:
        return default
    if parsed > 1:
        parsed = parsed / 100
    return max(0.0, min(parsed, 1.0))


def _priority_label(value: Any, default: str = "medium") -> str:
    text = str(value or "").strip().lower()
    if text in PRIORITY_LEVELS:
        return text
    numeric_map = {
        1: "low",
        2: "medium",
        3: "high",
        4: "critical",
    }
    try:
        parsed = int(float(text))
    except ValueError:
        return default
    return numeric_map.get(parsed, default)


def _icu_days(text: str) -> int:
    match = re.search(r"\bicu\s*(?:stay)?\s*(?:for)?\s*(\d{1,2})\s*days?\b|\b(\d{1,2})\s*days?\s*(?:in\s*)?icu\b", text)
    if not match:
        return 0
    return int(match.group(1) or match.group(2) or 0)
