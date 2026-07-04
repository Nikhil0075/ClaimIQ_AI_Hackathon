"""
ClaimIQ PDF Report Generator
=============================
Generates a professional multi-page PDF claim analysis report by stitching
outputs from all 5 agents into one cohesive document.

Includes:
  • Cover page with claim snapshot and coloured status banner
  • Claim details table (from Intake Agent)
  • Coverage analysis (from Coverage Agent)
  • Fraud analysis page — donut chart + signal bar chart + signals table
  • Routing & adjuster decision section (from Triage + Copilot)
  • Audit trail (agent status + evidence log)

Orchestrator policy (via should_generate_report):
  Report is generated when ANY condition is true:
    • required_human_approval = True
    • fraud_score >= REPORT_FRAUD_THRESHOLD (default 30 → medium risk or above)
    • claim_amount >= REPORT_AMOUNT_THRESHOLD (default 100,000 INR)
    • coverage_status is needs_review or not_covered

Dependencies (optional — graceful fallback if missing):
    pip install reportlab matplotlib

Usage:
    from claimiq.tools.report_tool import generate_claim_report, should_generate_report

    if should_generate_report(pipeline_outputs):
        pdf_bytes = generate_claim_report(claim_id, pipeline_outputs)
        # Returns bytes — pass to email_tool as attachment, or None on failure
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Orchestrator thresholds (env-configurable) ────────────────────────────────

REPORT_FRAUD_THRESHOLD  = int(os.getenv("REPORT_FRAUD_THRESHOLD",  "30"))
REPORT_AMOUNT_THRESHOLD = float(os.getenv("REPORT_AMOUNT_THRESHOLD", "100000"))


def _format_confidence(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    if isinstance(value, str):
        label = value.strip()
        try:
            value = float(label)
        except ValueError:
            return label.title()
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if numeric > 1:
        numeric = numeric / 100
    return f"{numeric:.0%}"


def _upper_label(value: Any, default: str = "N/A") -> str:
    text = str(value if value not in (None, "") else default)
    return text.upper()


# ── Public API ────────────────────────────────────────────────────────────────

def should_generate_report(outputs: dict[str, Any]) -> bool:
    """
    Orchestrator policy: decide whether a PDF report is needed for this claim.

    Triggers when ANY of:
      • required_human_approval = True  (adjuster needs the full brief)
      • fraud_score >= REPORT_FRAUD_THRESHOLD   (default 30 — medium+)
      • claim_amount >= REPORT_AMOUNT_THRESHOLD  (default 100,000 INR)
      • coverage_status in {needs_review, not_covered}
    """
    triage   = outputs.get("triage",   {})
    fraud    = outputs.get("fraud",    {})
    intake   = outputs.get("intake",   {})
    coverage = outputs.get("coverage", {})

    fraud_score      = int(fraud.get("fraud_score") or 0)
    required_human   = bool(triage.get("required_human_approval", False))
    claim_amount     = float(intake.get("claim_amount") or 0)
    coverage_status  = str(coverage.get("coverage_status") or "needs_review")

    return (
        required_human
        or fraud_score >= REPORT_FRAUD_THRESHOLD
        or claim_amount >= REPORT_AMOUNT_THRESHOLD
        or coverage_status in {"needs_review", "not_covered"}
    )


def generate_claim_report(
    claim_id: str,
    outputs: dict[str, Any],
    *,
    generated_at: str | None = None,
    agent_timings: dict[str, dict[str, Any]] | None = None,
) -> bytes | None:
    """
    Generate a multi-page PDF report for one claim.

    Parameters
    ----------
    claim_id     : Claim reference ID (e.g. CLM-20260627-ABCD1234).
    outputs      : Dict of agent outputs keyed by agent name.
    generated_at : ISO timestamp for the report header. Defaults to now (UTC).

    Returns
    -------
    bytes — raw PDF content ready to send as an email attachment, or None if
    reportlab is not installed or generation fails.
    """
    rl_ok, mpl_ok = _check_deps()
    if not rl_ok:
        log.warning(
            "[ReportTool] reportlab not installed — PDF skipped. "
            "Run: pip install reportlab matplotlib"
        )
        return None
    if not mpl_ok:
        log.warning(
            "[ReportTool] matplotlib not installed — charts will be omitted. "
            "Run: pip install matplotlib"
        )

    ts = generated_at or _utc_now()
    try:
        pdf_bytes = _build_pdf(claim_id, outputs, ts, mpl_ok, agent_timings=agent_timings)
        log.info("[ReportTool] PDF generated for %s — %d bytes", claim_id, len(pdf_bytes))
        return pdf_bytes
    except Exception as exc:
        log.error("[ReportTool] PDF generation failed for %s: %s", claim_id, exc, exc_info=True)
        return None


# ── Dependency check ──────────────────────────────────────────────────────────

def _check_deps() -> tuple[bool, bool]:
    rl_ok = mpl_ok = False
    try:
        import reportlab  # noqa: F401
        rl_ok = True
    except ImportError:
        pass
    try:
        import matplotlib  # noqa: F401
        mpl_ok = True
    except ImportError:
        pass
    return rl_ok, mpl_ok


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _str_field(val: Any, prefer_key: str = "summary") -> str:
    """
    Coerce a field that may be a string or a dict to a plain string.
    When the AI returns a structured sub-object (e.g. executive_summary as a
    dict with 'summary', 'claim_id', 'non_decision_statement' keys), extract
    the most readable text instead of repr-ing the whole dict.
    """
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        # Prefer the key named by prefer_key, fall back to any str value
        if prefer_key in val and isinstance(val[prefer_key], str):
            return val[prefer_key]
        for v in val.values():
            if isinstance(v, str) and len(v) > 20:
                return v
        return str(val)
    if isinstance(val, list):
        return " ".join(str(item) for item in val)
    return str(val)


def _clean(val: Any, default: str = "N/A") -> str:
    """
    Sanitise a field value for display in the PDF.
    Returns `default` for None, empty strings, and internal sentinel strings
    like 'needs_review' or 'not_found' that should not be shown to readers.
    """
    if val is None:
        return default
    s = str(val).strip()
    if s.lower() in ("", "none", "needs_review", "not_found", "n/a", "false"):
        return default
    return s


def _fmt_policy_sections(secs: list) -> str:
    """
    Convert a list of policy-section dicts (or strings) into a compact,
    readable label string without raw Python dict / URL noise.
    """
    labels = []
    for s in secs[:6]:
        if isinstance(s, dict):
            doc  = s.get("document_title") or s.get("document_id") or ""
            ref  = s.get("section_reference") or (f"p.{s.get('page')}" if s.get("page") else "")
            label = f"{doc} § {ref}" if doc and ref else doc or ref
            if not label:
                label = str(s)[:60]
        else:
            label = str(s)[:60]
        if label:
            labels.append(label)
    return " | ".join(labels) if labels else ""


# ── PDF builder ───────────────────────────────────────────────────────────────

def _build_pdf(
    claim_id: str,
    outputs: dict[str, Any],
    generated_at: str,
    mpl_ok: bool,
    agent_timings: dict[str, dict[str, Any]] | None = None,
) -> bytes:
    """Build the full PDF and return bytes."""
    # ── reportlab imports (inside function — lazy) ────────────────────────────
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        HRFlowable, Image, PageBreak, Paragraph,
        SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    # ── Colour palette ────────────────────────────────────────────────────────
    PURPLE      = HexColor("#7C3AED")
    RED         = HexColor("#DC2626")
    ORANGE      = HexColor("#D97706")
    GREEN       = HexColor("#16A34A")
    DARK        = HexColor("#111827")
    GRAY        = HexColor("#6B7280")
    LIGHT_PURP  = HexColor("#EDE9FE")
    LIGHT_GRAY  = HexColor("#F9FAFB")
    MID_GRAY    = HexColor("#E5E7EB")
    TRIAGE_CMAP = {"RED": RED, "AMBER": ORANGE, "GREEN": GREEN}
    RISK_CMAP   = {"LOW": GREEN, "MEDIUM": ORANGE, "HIGH": RED, "CRITICAL": RED}

    # ── Unpack agent outputs ──────────────────────────────────────────────────
    # Deep-sanitize all agent text so LLM-emitted characters outside cp1252
    # (non-breaking hyphens, emoji, ₹ …) don't render as ■ in Helvetica.
    from claimiq.shared.pdf_text import sanitize_deep
    outputs  = sanitize_deep(outputs)
    intake   = outputs.get("intake",   {})
    coverage = outputs.get("coverage", {})
    fraud    = outputs.get("fraud",    {})
    triage   = outputs.get("triage",   {})
    copilot  = outputs.get("copilot",  {})

    claimant    = intake.get("claimant_name") or "Unknown"
    claim_type  = _upper_label(intake.get("claim_type"), "general")
    policy_num  = intake.get("policy_number") or "N/A"
    currency    = intake.get("currency", "INR")
    raw_amount  = intake.get("claim_amount")
    est_suffix  = ""
    if not raw_amount and intake.get("estimated_amount"):
        # Fall back to the estimate rather than printing N/A next to a report
        # that cites a concrete figure elsewhere (e.g. repair estimate).
        raw_amount = intake.get("estimated_amount")
        est_suffix = " (est.)"
    try:
        amount_str = f"{currency} {float(raw_amount):,.0f}{est_suffix}" if raw_amount else "N/A"
    except (TypeError, ValueError):
        amount_str = str(raw_amount) if raw_amount else "N/A"
    incident_dt = intake.get("incident_date") or "N/A"

    fraud_score  = int(fraud.get("fraud_score") or 0)
    risk_level   = _upper_label(fraud.get("risk_level"), "low")
    signals      = fraud.get("signals") or []
    cov_status   = _upper_label(coverage.get("coverage_status"), "needs_review").replace("_", " ")
    triage_color = _upper_label(triage.get("triage_color"), "amber")
    priority     = _upper_label(triage.get("priority"), "medium")
    sla          = triage.get("sla_hours") or 48
    human_flag   = bool(triage.get("required_human_approval", True))
    routing      = (triage.get("routing") or "standard_review").replace("_", " ").title()

    banner_color = TRIAGE_CMAP.get(triage_color, ORANGE)
    risk_color   = RISK_CMAP.get(risk_level, ORANGE)

    # ── Document setup ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    page_w, page_h = A4  # 595.27 × 841.89 pt
    margin = 1.8 * cm
    cw = page_w - 2 * margin   # content width ≈ 487 pt

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=margin, leftMargin=margin,
        topMargin=2.4 * cm, bottomMargin=1.8 * cm,
        title=f"ClaimIQ Report — {claim_id}",
        author="ClaimIQ AI Pipeline",
        subject=f"{claim_type} Claim Analysis",
    )

    # ── ParagraphStyles ───────────────────────────────────────────────────────
    def ps(name, **kw):
        return ParagraphStyle(name, **kw)

    h1    = ps("h1",    fontSize=13, textColor=PURPLE, fontName="Helvetica-Bold",
                        spaceBefore=14, spaceAfter=4)
    h2    = ps("h2",    fontSize=11, textColor=DARK,   fontName="Helvetica-Bold",
                        spaceBefore=8,  spaceAfter=3)
    body  = ps("body",  fontSize=9,  textColor=DARK,   fontName="Helvetica",
                        leading=14, spaceAfter=4)
    small = ps("small", fontSize=7.5, textColor=GRAY,  fontName="Helvetica",
                        spaceAfter=2)
    cap   = ps("cap",   fontSize=8, textColor=GRAY,    fontName="Helvetica-Oblique",
                        alignment=TA_CENTER, spaceAfter=4)
    disc  = ps("disc",  fontSize=7, textColor=GRAY,    fontName="Helvetica-Oblique",
                        alignment=TA_JUSTIFY)
    white_bold = ps("wb", fontSize=11, textColor=colors.white, fontName="Helvetica-Bold")
    white_sm   = ps("ws", fontSize=9,  textColor=HexColor("#C4B5FD"), fontName="Helvetica",
                          alignment=TA_RIGHT)

    # ── Shared table style ────────────────────────────────────────────────────
    def tbl_style(hdr_bg=LIGHT_PURP, hdr_fg=PURPLE):
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),  hdr_bg),
            ("TEXTCOLOR",  (0, 0), (-1, 0),  hdr_fg),
            ("FONTNAME",   (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0),  9),
            ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",   (0, 1), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("GRID",       (0, 0), (-1, -1), 0.4, MID_GRAY),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ])

    def hr():
        return HRFlowable(width="100%", thickness=0.5, color=MID_GRAY,
                          spaceBefore=6, spaceAfter=10)

    def banner_table(text, bg, font_size=10):
        return Table(
            [[Paragraph(text, ps("bn", fontSize=font_size, textColor=colors.white,
                                  fontName="Helvetica-Bold"))]],
            colWidths=[cw],
            style=TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), bg),
                ("TOPPADDING",   (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
                ("LEFTPADDING",  (0, 0), (-1, -1), 10),
            ]),
        )

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 1 — COVER
    # ═════════════════════════════════════════════════════════════════════════
    story: list = []

    # Header bar
    story.append(Table(
        [[Paragraph("ClaimIQ", white_bold),
          Paragraph("AI Claims Analysis Report", white_sm)]],
        colWidths=[cw * 0.45, cw * 0.55],
        style=TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), PURPLE),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
            ("LEFTPADDING",  (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]),
    ))
    story.append(Spacer(1, 10))

    # Status banner (banner background already carries the triage colour;
    # "•" is cp1252-safe, unlike the emoji circles that rendered as ■)
    human_str = "HUMAN REVIEW REQUIRED" if human_flag else "AUTO-ELIGIBLE"
    story.append(banner_table(
        f"•  {triage_color} — {priority} PRIORITY  |  {human_str}",
        banner_color, font_size=10,
    ))
    story.append(Spacer(1, 12))

    # Claim snapshot
    snap = [
        ["Claim Reference", claim_id,      "Report Generated", generated_at],
        ["Claimant",        claimant,       "Claim Type",       claim_type],
        ["Policy Number",   policy_num,     "Incident Date",    incident_dt],
        ["Claimed Amount",  amount_str,     "Processing SLA",   f"{sla} hours"],
        ["Coverage Status", cov_status,     "Fraud Risk",       f"{risk_level} ({fraud_score}/100)"],
    ]
    snap_tbl = Table(snap, colWidths=[cw*0.22, cw*0.28, cw*0.22, cw*0.28])
    snap_sty = TableStyle([
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",   (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME",   (1, 0), (1, -1), "Helvetica"),
        ("FONTNAME",   (3, 0), (3, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",  (0, 0), (0, -1), PURPLE),
        ("TEXTCOLOR",  (2, 0), (2, -1), PURPLE),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GRAY]),
        ("GRID",       (0, 0), (-1, -1), 0.4, MID_GRAY),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ])
    snap_tbl.setStyle(snap_sty)
    story.append(snap_tbl)
    story.append(Spacer(1, 14))

    # Executive Summary
    story.append(Paragraph("Executive Summary", h1))
    story.append(hr())
    exec_summ = _str_field(
        copilot.get("executive_summary") or intake.get("claim_summary")
    ) or "No executive summary available from Adjuster Copilot."
    story.append(Paragraph(exec_summ[:1200], body))

    desc = intake.get("incident_description") or ""
    # If AI returned a very short description, supplement with claim_summary
    if len(desc) < 60:
        desc = intake.get("claim_summary") or desc
    if desc:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Incident Description", h2))
        story.append(Paragraph(desc[:1500], body))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 2 — CLAIM DETAILS + COVERAGE
    # ═════════════════════════════════════════════════════════════════════════

    story.append(Paragraph("Claim Details", h1))
    story.append(hr())

    field_map = [
        ("Claimant Name",        claimant),
        ("Claim Type",           claim_type),
        ("Policy Number",        policy_num),
        ("Incident Date",        incident_dt),
        ("Incident Time",        intake.get("incident_time")),
        ("Location",             intake.get("location_of_incident")),
        ("Claimed Amount",       amount_str),
        ("Vehicle Registration", intake.get("vehicle_registration")),
        ("Hospital Name",        intake.get("hospital_name")),
        ("Police Report Filed",  str(intake.get("police_report_filed", "N/A"))),
        ("Police Report No.",    intake.get("police_report_number")),
        ("Contact Phone",        intake.get("contact_phone")),
        ("Third Party Involved", str(intake.get("third_party_involved", "N/A"))),
        ("Intake Confidence",    _format_confidence(intake.get("confidence_score"))),
    ]
    det_rows = [["Field", "Value"]] + [
        [lbl, str(val)] for lbl, val in field_map if val and val not in ("None", "N/A", "False")
    ]
    dt = Table(det_rows, colWidths=[cw * 0.38, cw * 0.62])
    dt.setStyle(tbl_style())
    story.append(dt)

    missing = intake.get("missing_information") or []
    if missing:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Missing Information", h2))
        for item in missing[:6]:
            story.append(Paragraph(f"• {item}", body))

    docs = intake.get("documents_mentioned") or []
    if docs:
        story.append(Paragraph(
            "Documents Referenced: " + ", ".join(str(d) for d in docs[:8]), small,
        ))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Coverage Analysis", h1))
    story.append(hr())

    cov_color = GREEN if "COVERED" == cov_status else RED if "NOT COVERED" == cov_status else ORANGE
    story.append(banner_table(f"Coverage Status: {cov_status}", cov_color))
    story.append(Spacer(1, 8))

    limits = coverage.get("applicable_limits") or {}
    max_amt = limits.get("max_claim_amount") if isinstance(limits, dict) else None
    deduct  = limits.get("deductible")       if isinstance(limits, dict) else None
    cov_fields = [
        ("Policy Holder",         _clean(coverage.get("policy_holder_name"))),
        ("Policy Status",         _upper_label(_clean(coverage.get("policy_status"), "Not Found"))),
        ("Inception Date",        _clean(coverage.get("policy_inception_date"))),
        ("Expiry Date",           _clean(coverage.get("policy_expiry_date"))),
        ("Claim Type Covered",    _clean(coverage.get("claim_type_covered"))),
        ("Active on Incident",    _clean(coverage.get("policy_active_on_incident_date"), "Pending Review")),
        ("Waiting Period (days)", _clean(coverage.get("waiting_period_days"), "N/A")),
        ("Waiting Period Breach", _clean(coverage.get("waiting_period_breach"), "N/A")),
        ("Max Claim Amount",      f"{currency} {float(max_amt):,.0f}" if max_amt else "N/A"),
        ("Deductible",            f"{currency} {float(deduct):,.0f}"  if deduct  else "N/A"),
        ("Coverage Confidence",   _format_confidence(coverage.get("coverage_confidence"))),
    ]
    cov_rows = [["Coverage Field", "Detail"]] + [
        [lbl, val] for lbl, val in cov_fields if val and val != "N/A"
    ]
    ct = Table(cov_rows, colWidths=[cw * 0.42, cw * 0.58])
    ct.setStyle(tbl_style())
    story.append(ct)

    reasoning = coverage.get("coverage_reasoning") or ""
    if reasoning:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Coverage Reasoning", h2))
        story.append(Paragraph(reasoning[:2000], body))

    excls = coverage.get("applicable_exclusions") or []
    if excls:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Applicable Exclusions", h2))
        for e in excls[:5]:
            story.append(Paragraph(f"• {e}", body))

    secs = coverage.get("policy_sections_referenced") or []
    if secs:
        sec_text = _fmt_policy_sections(secs)
        if sec_text:
            story.append(Paragraph("Policy Sections: " + sec_text, small))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 3 — FRAUD ANALYSIS
    # ═════════════════════════════════════════════════════════════════════════

    story.append(Paragraph("Fraud Risk Analysis", h1))
    story.append(hr())

    # Score + risk banner
    story.append(Table(
        [[
            Paragraph(f"Fraud Score: {fraud_score} / 100",
                      ps("fsc", fontSize=14, textColor=colors.white,
                         fontName="Helvetica-Bold")),
            Paragraph(f"Risk Level: {risk_level}",
                      ps("frl", fontSize=12, textColor=colors.white,
                         fontName="Helvetica-Bold", alignment=TA_RIGHT)),
        ]],
        colWidths=[cw * 0.55, cw * 0.45],
        style=TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), risk_color),
            ("TOPPADDING",   (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
            ("LEFTPADDING",  (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]),
    ))
    story.append(Spacer(1, 10))

    # Charts (side by side)
    if mpl_ok:
        donut_buf = _chart_fraud_donut(fraud_score, signals, risk_level)
        bar_buf   = _chart_signal_bars(signals, fraud_score) if signals else None

        if donut_buf and bar_buf:
            ch_w = cw * 0.47
            story.append(Table(
                [[Image(donut_buf, width=ch_w, height=ch_w * 0.78),
                  Image(bar_buf,   width=ch_w, height=ch_w * 0.78)]],
                colWidths=[cw * 0.5, cw * 0.5],
            ))
            story.append(Paragraph(
                "Left: fraud score breakdown (donut) — Right: signal score contributions (bar)",
                cap,
            ))
        elif donut_buf:
            ch_w = cw * 0.55
            story.append(Table(
                [[Image(donut_buf, width=ch_w, height=ch_w * 0.80)]],
                colWidths=[cw],
            ))
            story.append(Paragraph("Fraud score breakdown", cap))
        story.append(Spacer(1, 8))

    # Signals table
    if signals:
        story.append(Paragraph("Detected Fraud Signals", h2))
        SIG_SEV_COLORS = {
            "CRITICAL": RED, "HIGH": ORANGE, "MEDIUM": HexColor("#CA8A04"), "LOW": GRAY
        }
        sig_rows = [["Signal ID", "Severity", "Score +", "Description"]]
        for s in signals:
            severity = _upper_label(s.get("severity"), "")
            sig_rows.append([
                s.get("signal_id") or "UNKNOWN",
                severity,
                f"+{s.get('score_contribution', 0)}",
                Paragraph((str(s.get("description") or ""))[:200], body),
            ])
        st = Table(sig_rows, colWidths=[cw*0.30, cw*0.14, cw*0.10, cw*0.46])
        sty = tbl_style()
        for i, s in enumerate(signals, 1):
            c = SIG_SEV_COLORS.get(_upper_label(s.get("severity"), ""), GRAY)
            sty.add("TEXTCOLOR", (1, i), (1, i), c)
            sty.add("FONTNAME",  (1, i), (1, i), "Helvetica-Bold")
            sty.add("TEXTCOLOR", (2, i), (2, i), c)
            sty.add("FONTNAME",  (2, i), (2, i), "Helvetica-Bold")
        st.setStyle(sty)
        story.append(st)
    else:
        story.append(Paragraph("No fraud signals detected for this claim.", body))

    fraud_reasoning = fraud.get("fraud_reasoning") or ""
    if fraud_reasoning:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Analysis Reasoning", h2))
        story.append(Paragraph(fraud_reasoning[:2000], body))

    rec_action = _upper_label(str(fraud.get("recommended_action") or "proceed").replace("_", " "))
    ac_color = RED if any(k in rec_action for k in ("SIU", "REFER", "ESCALAT")) \
               else ORANGE if "FLAG" in rec_action else GREEN
    story.append(Spacer(1, 6))
    story.append(banner_table(f"Recommended Action: {rec_action}", ac_color, font_size=9))

    dup_ids = fraud.get("duplicate_claim_ids") or []
    if dup_ids:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"!  Duplicate Claim IDs Detected: {', '.join(dup_ids)}",
            ps("dup", fontSize=9, textColor=RED, fontName="Helvetica-Bold"),
        ))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 4 — ROUTING & ADJUSTER DECISION
    # ═════════════════════════════════════════════════════════════════════════

    story.append(Paragraph("Routing & Adjuster Decision", h1))
    story.append(hr())

    routing_data = [
        ("Triage Color",         triage_color),
        ("Priority Level",       priority),
        ("Routing Queue",        routing),
        ("SLA (hours)",          str(sla)),
        ("Human Approval",       "REQUIRED" if human_flag else "NOT REQUIRED"),
        ("Est. Settlement",      f"{triage.get('estimated_settlement_days')} days"
                               if triage.get("estimated_settlement_days") else "N/A"),
    ]
    cell_body = ps("cb", fontSize=9, textColor=DARK, fontName="Helvetica", leading=13)
    rt_rows = [["Routing Field", "Value"]] + [
        [lbl, Paragraph(val, cell_body)] for lbl, val in routing_data
    ]
    rt = Table(rt_rows, colWidths=[cw * 0.42, cw * 0.58])
    rt_sty = tbl_style()
    for i, (lbl, val) in enumerate(routing_data, 1):
        if lbl == "Human Approval":
            c = RED if val == "REQUIRED" else GREEN
            rt_sty.add("TEXTCOLOR", (1, i), (1, i), c)
            rt_sty.add("FONTNAME",  (1, i), (1, i), "Helvetica-Bold")
        if lbl == "Triage Color":
            rt_sty.add("TEXTCOLOR", (1, i), (1, i), TRIAGE_CMAP.get(val, ORANGE))
            rt_sty.add("FONTNAME",  (1, i), (1, i), "Helvetica-Bold")
    rt.setStyle(rt_sty)
    story.append(rt)

    # Human approval triggers
    reasons = triage.get("human_approval_reasons") or []
    if reasons:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Human Approval Triggers", h2))
        for r in reasons[:6]:
            story.append(Paragraph(
                f"!  {r}",
                ps("rsn", fontSize=9, textColor=RED, fontName="Helvetica-Bold", leftIndent=8),
            ))

    triage_summ = triage.get("triage_summary") or ""
    if triage_summ:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Triage Summary", h2))
        story.append(Paragraph(triage_summ, body))

    # Adjuster Checklist
    checklist = copilot.get("approval_checklist") or []
    if checklist:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Adjuster Checklist", h1))
        story.append(hr())
        chk_cell = ps("chkc", fontSize=8, textColor=DARK, fontName="Helvetica", leading=12)
        chk_rows = [["#", "Item", "Status"]]
        for i, item in enumerate(checklist, 1):
            if isinstance(item, dict):
                chk_rows.append([
                    str(i),
                    Paragraph(str(item.get("item") or item.get("check") or item), chk_cell),
                    str(item.get("status") or "PENDING"),
                ])
            else:
                chk_rows.append([str(i), Paragraph(str(item), chk_cell), "PENDING"])
        chkt = Table(chk_rows, colWidths=[cw*0.07, cw*0.65, cw*0.28])
        chkt.setStyle(tbl_style())
        story.append(chkt)

    # Open questions
    open_qs = copilot.get("open_questions") or []
    if open_qs:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Open Questions for Adjuster", h2))
        for i, q in enumerate(open_qs[:8], 1):
            story.append(Paragraph(f"{i}.  {q}", body))

    next_steps = triage.get("recommended_next_steps") or []
    if next_steps:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Recommended Next Steps", h2))
        for i, s in enumerate(next_steps[:5], 1):
            story.append(Paragraph(f"{i}.  {s}", body))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 5 — AUDIT TRAIL
    # ═════════════════════════════════════════════════════════════════════════

    story.append(Paragraph("Pipeline Audit Trail", h1))
    story.append(hr())

    # Build audit trail. Real per-agent timings from the orchestrator take
    # precedence; copilot's evidence_log (stamped all-at-once at copilot time)
    # and the generated_at fallback are only used when timings are absent.
    timings = agent_timings or {}
    evidence = copilot.get("evidence_log") or []
    logged_agents = {str(ev.get("agent", "")).lower() for ev in evidence}
    AGENT_ORDER = ("intake", "coverage", "fraud", "triage", "copilot")
    for agent_name in AGENT_ORDER:
        if agent_name not in logged_agents and agent_name in outputs:
            evidence = list(evidence) + [{
                "agent": agent_name,
                "status": "error" if "error" in outputs[agent_name] else "success",
                "completed_at": generated_at,
            }]

    if evidence:
        ev_rows = [["Agent", "Status", "Completed At", "Duration"]]
        for ev in evidence:
            agent_key = str(ev.get("agent") or "").lower()
            timing = timings.get(agent_key) or {}
            completed = timing.get("completed_at") or ev.get("completed_at") or generated_at
            dur_ms = timing.get("duration_ms")
            duration = f"{dur_ms/1000:.1f}s" if isinstance(dur_ms, (int, float)) else "—"
            ev_rows.append([
                str(ev.get("agent") or "").title(),
                str(ev.get("status") or "unknown").upper(),
                str(completed),
                duration,
            ])
        ev_tbl = Table(ev_rows, colWidths=[cw*0.20, cw*0.16, cw*0.50, cw*0.14])
        ev_sty = tbl_style()
        for i, ev in enumerate(evidence, 1):
            c = GREEN if str(ev.get("status")).lower() == "success" else RED
            ev_sty.add("TEXTCOLOR", (1, i), (1, i), c)
            ev_sty.add("FONTNAME",  (1, i), (1, i), "Helvetica-Bold")
        ev_tbl.setStyle(ev_sty)
        story.append(ev_tbl)
        story.append(Spacer(1, 12))

    # Agent output summary
    story.append(Paragraph("Agent Output Summary", h2))
    as_rows = [["Agent", "Key Output", "Confidence"]]
    agent_rows_data = [
        ("intake",  f"Type: {claim_type}  |  Amount: {amount_str}  |  Policy: {policy_num}",
         _format_confidence(intake.get("confidence_score"))),
        ("coverage", f"Status: {cov_status}  |  Active on date: {coverage.get('policy_active_on_incident_date','N/A')}",
         _format_confidence(coverage.get("coverage_confidence"))),
        ("fraud",   f"Score: {fraud_score}/100  |  Level: {risk_level}  |  Action: {rec_action}",
         _format_confidence(fraud.get("fraud_confidence"))),
        ("triage",  f"Queue: {routing}  |  SLA: {sla}h  |  Color: {triage_color}", "—"),
        ("copilot", f"Brief: ready  |  Open Qs: {len(open_qs)}  |  Checklist: {len(checklist)} items", "—"),
    ]
    for name, summary, conf in agent_rows_data:
        if name in outputs:
            has_error = "error" in outputs.get(name, {})
            as_rows.append([
                ("[ERR] " if has_error else "• ") + name.title(),
                summary,
                conf,
            ])
    as_tbl = Table(as_rows, colWidths=[cw*0.14, cw*0.70, cw*0.16])
    as_tbl.setStyle(tbl_style())
    story.append(as_tbl)

    # Disclaimer footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.4, color=MID_GRAY))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        f"This report was automatically generated by ClaimIQ AI Pipeline on {generated_at}. "
        "All decisions flagged 'HUMAN REVIEW REQUIRED' must be confirmed by a qualified "
        "adjuster before action is taken. This document is confidential and intended solely "
        "for authorised insurance personnel. Do not distribute externally.",
        disc,
    ))

    # ── Build ─────────────────────────────────────────────────────────────────
    decorator = _make_page_decorator(claim_id, generated_at)
    doc.build(story, onFirstPage=decorator, onLaterPages=decorator)
    return buf.getvalue()


# ── Page header / footer decorator ───────────────────────────────────────────

def _make_page_decorator(claim_id: str, generated_at: str):
    """Return a (canvas, doc) callback that draws the page header and footer."""
    def _draw(canvas, doc):
        from reportlab.lib.units import cm
        from reportlab.lib.colors import HexColor

        PURPLE = HexColor("#7C3AED")
        GRAY   = HexColor("#6B7280")
        pw, ph = doc.pagesize

        canvas.saveState()

        # ── Header ────────────────────────────────────────────────────────
        canvas.setStrokeColor(PURPLE)
        canvas.setLineWidth(0.8)
        canvas.line(1.8 * cm, ph - 1.7 * cm, pw - 1.8 * cm, ph - 1.7 * cm)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(PURPLE)
        canvas.drawString(1.8 * cm, ph - 1.45 * cm, "ClaimIQ — Confidential Claim Report")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAY)
        canvas.drawRightString(pw - 1.8 * cm, ph - 1.45 * cm, claim_id)

        # ── Footer ────────────────────────────────────────────────────────
        canvas.setStrokeColor(HexColor("#E5E7EB"))
        canvas.setLineWidth(0.4)
        canvas.line(1.8 * cm, 1.4 * cm, pw - 1.8 * cm, 1.4 * cm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(GRAY)
        canvas.drawString(
            1.8 * cm, 1.1 * cm,
            f"Generated: {generated_at}  |  For authorised personnel only",
        )
        canvas.drawRightString(pw - 1.8 * cm, 1.1 * cm, f"Page {doc.page}")

        canvas.restoreState()

    return _draw


# ── Chart: Fraud Score Donut ──────────────────────────────────────────────────

def _chart_fraud_donut(
    fraud_score: int,
    signals: list[dict],
    risk_level: str,
) -> io.BytesIO | None:
    """
    Donut chart showing:
      • Each detected signal as a coloured wedge (by severity)
      • Remaining safe portion in light gray
      • Centre label: score + risk level
    """
    try:
        import matplotlib
        if matplotlib.get_backend().lower() != "agg":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        SEV_COLORS = {
            "critical": "#DC2626",
            "high":     "#D97706",
            "medium":   "#FBBF24",
            "low":      "#86EFAC",
        }
        RISK_COLORS = {
            "CRITICAL": "#DC2626", "HIGH": "#D97706",
            "MEDIUM":   "#FBBF24", "LOW": "#16A34A",
        }
        SAFE_CLR = "#E5E7EB"

        if signals:
            sizes  = [max(0, int(s.get("score_contribution", 0))) for s in signals]
            clrs   = [SEV_COLORS.get((s.get("severity") or "medium").lower(), "#D97706") for s in signals]
            labels = [
                (s.get("signal_id") or "UNKNOWN").replace("_", " ").title()[:20]
                for s in signals
            ]
            safe = max(0, 100 - sum(sizes))
            if safe > 0:
                sizes.append(safe);  clrs.append(SAFE_CLR);  labels.append("Safe")
        else:
            safe_val = max(0, 100 - fraud_score)
            sizes  = [fraud_score or 1, safe_val or 99]
            clrs   = [RISK_COLORS.get(risk_level, "#D97706"), SAFE_CLR]
            labels = [f"Risk ({fraud_score})", "Safe"]

        fig, ax = plt.subplots(figsize=(4.2, 3.5), facecolor="white")

        wedges, _ = ax.pie(
            sizes,
            colors=clrs,
            startangle=90,
            wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1.5},
            counterclock=False,
        )

        center_color = RISK_COLORS.get(risk_level, "#D97706")
        ax.text(0,  0.10, str(fraud_score),
                ha="center", va="center", fontsize=22, fontweight="bold", color=center_color)
        ax.text(0, -0.16, risk_level,
                ha="center", va="center", fontsize=8,  fontweight="bold", color=center_color)
        ax.text(0, -0.34, "out of 100",
                ha="center", va="center", fontsize=6.5, color="#9CA3AF")

        ax.set_title("Fraud Score Breakdown", fontsize=9.5, fontweight="bold",
                     color="#111827", pad=6)

        patches = [mpatches.Patch(color=clrs[i], label=labels[i])
                   for i in range(min(len(labels), 5))]
        ax.legend(handles=patches, loc="lower center", bbox_to_anchor=(0.5, -0.22),
                  ncol=3, fontsize=6, frameon=False)

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf

    except Exception as exc:
        log.warning("[ReportTool] Donut chart error: %s", exc)
        return None


# ── Chart: Signal Score Bar Chart ─────────────────────────────────────────────

def _chart_signal_bars(
    signals: list[dict],
    total_score: int,
) -> io.BytesIO | None:
    """
    Horizontal bar chart showing each fraud signal's score contribution,
    coloured by severity.  Returns None when there are no signals.
    """
    if not signals:
        return None

    try:
        import matplotlib
        if matplotlib.get_backend().lower() != "agg":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        SEV_COLORS = {
            "critical": "#DC2626",
            "high":     "#D97706",
            "medium":   "#FBBF24",
            "low":      "#86EFAC",
        }

        labels = [
            (s.get("signal_id") or "UNKNOWN").replace("_", "\n")[:18]
            for s in signals
        ]
        values = [int(s.get("score_contribution", 0)) for s in signals]
        clrs   = [SEV_COLORS.get((s.get("severity") or "medium").lower(), "#D97706")
                  for s in signals]

        fig, ax = plt.subplots(figsize=(4.2, 3.5), facecolor="white")

        x    = np.arange(len(labels))
        bars = ax.bar(x, values, color=clrs, edgecolor="white", linewidth=1.2, width=0.6)

        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.4,
                    f"+{val}",
                    ha="center", va="bottom", fontsize=8, fontweight="bold", color="#374151",
                )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=6.5, color="#374151")
        ax.set_ylabel("Score Contribution", fontsize=7.5, color="#6B7280")
        ax.set_title("Signal Contributions", fontsize=9.5, fontweight="bold",
                     color="#111827", pad=6)
        ax.set_ylim(0, max(max(values, default=0) + 12, 35))
        ax.yaxis.grid(True, alpha=0.35, color="#E5E7EB", linewidth=0.6)
        ax.set_axisbelow(True)

        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_color("#E5E7EB")
        ax.spines["bottom"].set_color("#E5E7EB")
        ax.tick_params(colors="#6B7280", length=0)

        # Total score reference line
        ax.axhline(total_score, color="#7C3AED", linestyle="--", alpha=0.55, linewidth=0.9)
        ax.text(len(labels) - 0.45, total_score + 1,
                f"Total: {total_score}", ha="right", fontsize=6.5,
                color="#7C3AED", fontstyle="italic")

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf

    except Exception as exc:
        log.warning("[ReportTool] Bar chart error: %s", exc)
        return None
