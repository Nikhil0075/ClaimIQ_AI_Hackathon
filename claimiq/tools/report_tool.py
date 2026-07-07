"""
ClaimIQ PDF Report Generator
=============================
Generates a professional multi-page PDF claim analysis report by stitching
outputs from all 5 agents into one cohesive, branded document.

Design
------
Unified "ClaimIQ Indigo" brand system (shared with the Adjuster Guide):
  • Deep indigo hero header + violet accent rules
  • Colour-coded status chips (triage / coverage / fraud risk)
  • Snapshot "stat cards" on the cover so page 1 reads like a dashboard
  • Fully wrapped table cells (no text overflow) and prettified labels
  • 100% cp1252-safe typography — no glyph renders as a ■ box

Pages
-----
  1  Cover — hero, status ribbon, stat cards, snapshot, executive summary
  2  Claim details (Intake) + Coverage analysis (Coverage Agent)
  3  Fraud analysis — donut + signal bar chart + signals table (Fraud Agent)
  4  Routing & adjuster decision (Triage + Copilot) + checklist
  5  Pipeline audit trail (agent status + evidence log + output summary)

Orchestrator policy (via should_generate_report):
  Report is generated when ANY condition is true:
    • required_human_approval = True
    • fraud_score >= REPORT_FRAUD_THRESHOLD (default 30 -> medium risk or above)
    • claim_amount >= REPORT_AMOUNT_THRESHOLD (default 100,000 INR)
    • coverage_status is needs_review or not_covered

Dependencies (optional -- graceful fallback if missing):
    pip install reportlab matplotlib

Usage:
    from claimiq.tools.report_tool import generate_claim_report, should_generate_report

    if should_generate_report(pipeline_outputs):
        pdf_bytes = generate_claim_report(claim_id, pipeline_outputs)
        # Returns bytes -- pass to email_tool as attachment, or None on failure
"""

from __future__ import annotations

import io
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# ── Orchestrator thresholds (env-configurable) ────────────────────────────────

REPORT_FRAUD_THRESHOLD  = int(os.getenv("REPORT_FRAUD_THRESHOLD",  "30"))
REPORT_AMOUNT_THRESHOLD = float(os.getenv("REPORT_AMOUNT_THRESHOLD", "100000"))


# ══════════════════════════════════════════════════════════════════════════════
# Text sanitisation  (self-contained; prefers the project sanitizer if present)
# ══════════════════════════════════════════════════════════════════════════════

# Common Unicode punctuation the LLM emits, mapped to cp1252-safe equivalents so
# nothing renders as a ■ box in the built-in Helvetica font.
_UNICODE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "‒": "-", "‑": "-", "‐": "-",
    "•": "-", "‣": "-", "▪": "-", "●": "-", "·": "-",
    "…": "...",
    " ": " ", " ": " ", " ": " ", "​": "",
    "→": "->", "←": "<-", "⇒": "=>",
    "✓": "[ok]", "✔": "[ok]", "✗": "[x]", "✘": "[x]",
    "₹": "INR ", "€": "EUR ", "£": "GBP ",
    "≥": ">=", "≤": "<=", "≠": "!=", "×": "x",
}
_UNICODE_RE = re.compile("|".join(re.escape(k) for k in _UNICODE_MAP))


def _sanitize_str(text: str) -> str:
    """Make a string safe for cp1252/Helvetica rendering."""
    if not text:
        return text
    text = _UNICODE_RE.sub(lambda m: _UNICODE_MAP[m.group(0)], text)
    # Drop any residual char that cp1252 cannot encode (emoji, exotic symbols).
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        return "".join(c if _cp1252_ok(c) else "" for c in text)


def _cp1252_ok(ch: str) -> bool:
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _fallback_sanitize_deep(obj: Any) -> Any:
    if isinstance(obj, str):
        return _sanitize_str(obj)
    if isinstance(obj, dict):
        return {k: _fallback_sanitize_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fallback_sanitize_deep(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_fallback_sanitize_deep(v) for v in obj)
    return obj


def _sanitize_deep(obj: Any) -> Any:
    """Use the project's sanitizer when importable; otherwise fall back."""
    try:
        from claimiq.shared.pdf_text import sanitize_deep  # type: ignore
        return sanitize_deep(obj)
    except Exception:
        return _fallback_sanitize_deep(obj)


# ══════════════════════════════════════════════════════════════════════════════
# Display helpers
# ══════════════════════════════════════════════════════════════════════════════

_HIDDEN_SENTINELS = {"", "none", "null", "n/a", "not_found", "false", "unknown"}


def _pretty(value: Any, default: str = "N/A") -> str:
    """
    Convert internal snake_case sentinels into human-readable Title Case for
    display (e.g. 'needs_review' -> 'Needs Review', 'special_investigation' ->
    'Special Investigation'). Leaves already-readable text untouched.
    """
    if value in (None, ""):
        return default
    s = str(value).strip()
    if s.lower() in _HIDDEN_SENTINELS - {"n/a"}:  # keep behaviour explicit
        pass
    if "_" in s and " " not in s:
        s = s.replace("_", " ")
    # Title-case only if it looks like a machine token (all one case)
    if s.islower() or s.isupper():
        s = s.title()
    return s or default


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


def _str_field(val: Any, prefer_key: str = "summary") -> str:
    """Coerce a field that may be a string, dict, or list to plain text."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
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
    """Sanitise a field value for display; hide internal sentinels."""
    if val is None:
        return default
    s = str(val).strip()
    if s.lower() in ("", "none", "needs_review", "not_found", "n/a", "false"):
        return default
    return _pretty(s, default)


def _fmt_policy_sections(secs: list) -> str:
    """Compact, readable label string for policy-section dicts / strings."""
    labels = []
    for s in secs[:6]:
        if isinstance(s, dict):
            doc  = s.get("document_title") or s.get("document_id") or ""
            ref  = s.get("section_reference") or (f"p.{s.get('page')}" if s.get("page") else "")
            label = f"{doc} - {ref}" if doc and ref else doc or ref
            if not label:
                label = str(s)[:60]
        else:
            label = str(s)[:60]
        if label:
            labels.append(label)
    return "   |   ".join(labels) if labels else ""


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def should_generate_report(outputs: dict[str, Any]) -> bool:
    """Orchestrator policy: decide whether a PDF report is needed for this claim."""
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
    """Generate a multi-page PDF report for one claim. Returns bytes or None."""
    rl_ok, mpl_ok = _check_deps()
    if not rl_ok:
        log.warning(
            "[ReportTool] reportlab not installed -- PDF skipped. "
            "Run: pip install reportlab matplotlib"
        )
        return None
    if not mpl_ok:
        log.warning(
            "[ReportTool] matplotlib not installed -- charts will be omitted. "
            "Run: pip install matplotlib"
        )

    ts = generated_at or _utc_now()
    try:
        pdf_bytes = _build_pdf(claim_id, outputs, ts, mpl_ok, agent_timings=agent_timings)
        log.info("[ReportTool] PDF generated for %s -- %d bytes", claim_id, len(pdf_bytes))
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


# ══════════════════════════════════════════════════════════════════════════════
# PDF builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_pdf(
    claim_id: str,
    outputs: dict[str, Any],
    generated_at: str,
    mpl_ok: bool,
    agent_timings: dict[str, dict[str, Any]] | None = None,
) -> bytes:
    """Build the full PDF and return bytes."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        HRFlowable, Image, KeepTogether, PageBreak, Paragraph,
        SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    # ── ClaimIQ Indigo palette ────────────────────────────────────────────────
    INDIGO_900  = HexColor("#312E81")   # hero / header bars
    INDIGO_700  = HexColor("#4338CA")   # primary brand
    INDIGO_600  = HexColor("#4F46E5")   # bright primary
    VIOLET      = HexColor("#7C3AED")   # accent (rules, headings)
    VIOLET_100  = HexColor("#EDE9FE")   # table header tint
    INDIGO_50   = HexColor("#EEF2FF")   # panel / soft tint
    INK         = HexColor("#1F2937")   # body text
    SLATE       = HexColor("#475569")   # secondary text
    GRAY        = HexColor("#6B7280")
    MUTED       = HexColor("#9CA3AF")
    BORDER      = HexColor("#E5E7EB")
    ROW_ALT     = HexColor("#F8FAFC")
    WHITE       = colors.white

    GREEN       = HexColor("#15803D");  GREEN_T = HexColor("#DCFCE7")
    AMBER       = HexColor("#B45309");  AMBER_T = HexColor("#FEF3C7")
    RED         = HexColor("#B91C1C");  RED_T   = HexColor("#FEE2E2")
    SLATE_T     = HexColor("#F1F5F9")

    TRIAGE_CMAP = {"RED": RED, "AMBER": AMBER, "GREEN": GREEN}
    TRIAGE_TINT = {"RED": RED_T, "AMBER": AMBER_T, "GREEN": GREEN_T}
    RISK_CMAP   = {"LOW": GREEN, "MEDIUM": AMBER, "HIGH": RED, "CRITICAL": RED}
    RISK_TINT   = {"LOW": GREEN_T, "MEDIUM": AMBER_T, "HIGH": RED_T, "CRITICAL": RED_T}

    # ── Unpack agent outputs (deep-sanitised) ─────────────────────────────────
    outputs  = _sanitize_deep(outputs)
    intake   = outputs.get("intake",   {}) or {}
    coverage = outputs.get("coverage", {}) or {}
    fraud    = outputs.get("fraud",    {}) or {}
    triage   = outputs.get("triage",   {}) or {}
    copilot  = outputs.get("copilot",  {}) or {}

    claimant    = intake.get("claimant_name") or "Unknown"
    claim_type  = _pretty(intake.get("claim_type"), "General")
    policy_num  = intake.get("policy_number") or "N/A"
    currency    = intake.get("currency", "INR")
    raw_amount  = intake.get("claim_amount")
    est_suffix  = ""
    if not raw_amount and intake.get("estimated_amount"):
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
    routing      = _pretty(triage.get("routing") or "standard_review")

    banner_color = TRIAGE_CMAP.get(triage_color, AMBER)
    banner_tint  = TRIAGE_TINT.get(triage_color, AMBER_T)
    risk_color   = RISK_CMAP.get(risk_level, AMBER)
    risk_tint    = RISK_TINT.get(risk_level, AMBER_T)
    cov_color    = GREEN if "COVERED" == cov_status else RED if "NOT COVERED" == cov_status else AMBER
    cov_tint     = GREEN_T if "COVERED" == cov_status else RED_T if "NOT COVERED" == cov_status else AMBER_T

    # ── Derived / cross-referenced fields (hoisted so the cover can use them) ──
    excls    = coverage.get("applicable_exclusions") or []
    limits   = coverage.get("applicable_limits") or {}
    max_amt  = limits.get("max_claim_amount") if isinstance(limits, dict) else None
    deduct   = limits.get("deductible")       if isinstance(limits, dict) else None
    reasons  = triage.get("human_approval_reasons") or []
    rec_action = _pretty(str(fraud.get("recommended_action") or "proceed"))

    # Rough pre-adjudication payable ceiling: min(claimed, limit) - deductible.
    est_payable = None
    try:
        claimed_f = float(raw_amount) if raw_amount else None
        limit_f   = float(max_amt) if max_amt else None
        ded_f     = float(deduct) if deduct else 0.0
        if limit_f is not None or claimed_f is not None:
            base = min([v for v in (claimed_f, limit_f) if v is not None])
            est_payable = max(0.0, base - ded_f)
    except (TypeError, ValueError):
        est_payable = None

    # Copilot extras (same object the Adjuster Guide consumes) -- surfaced here too.
    explanations = copilot.get("plain_english_explanations") if isinstance(
        copilot.get("plain_english_explanations"), dict) else {}
    guardrails   = copilot.get("decision_guardrails") or []
    cop_next     = copilot.get("suggested_next_steps") or []

    # ── Document setup ────────────────────────────────────────────────────────
    buf = io.BytesIO()
    page_w, page_h = A4
    margin = 1.7 * cm
    cw = page_w - 2 * margin

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=margin, leftMargin=margin,
        topMargin=2.35 * cm, bottomMargin=1.7 * cm,
        title=f"ClaimIQ Report - {claim_id}",
        author="ClaimIQ AI Pipeline",
        subject=f"{claim_type} Claim Analysis",
    )

    # ── ParagraphStyles ───────────────────────────────────────────────────────
    def ps(name, **kw):
        return ParagraphStyle(name, **kw)

    h1    = ps("h1",    fontSize=13, textColor=INDIGO_700, fontName="Helvetica-Bold",
                        spaceBefore=2, spaceAfter=2, leading=16)
    h2    = ps("h2",    fontSize=10.5, textColor=INK, fontName="Helvetica-Bold",
                        spaceBefore=8, spaceAfter=3, leading=13)
    body  = ps("body",  fontSize=9,  textColor=INK, fontName="Helvetica",
                        leading=13.5, spaceAfter=3, alignment=TA_JUSTIFY)
    body_l= ps("bodyl", fontSize=9,  textColor=INK, fontName="Helvetica", leading=13.5)
    small = ps("small", fontSize=7.5, textColor=GRAY, fontName="Helvetica",
                        spaceAfter=2, leading=10)
    cap   = ps("cap",   fontSize=8, textColor=GRAY, fontName="Helvetica-Oblique",
                        alignment=TA_CENTER, spaceAfter=2)
    disc  = ps("disc",  fontSize=7, textColor=GRAY, fontName="Helvetica-Oblique",
                        alignment=TA_JUSTIFY, leading=10)
    cell  = ps("cell",  fontSize=9, textColor=INK, fontName="Helvetica", leading=12)
    cell_b= ps("cellb", fontSize=9, textColor=INK, fontName="Helvetica-Bold", leading=12)
    kicker= ps("kick",  fontSize=8, textColor=VIOLET, fontName="Helvetica-Bold",
                        leading=10, spaceAfter=1)

    def P(text, style=cell):
        return Paragraph("" if text is None else str(text), style)

    # ── Reusable builders ─────────────────────────────────────────────────────
    def section_header(text, kick=None):
        """Accent kicker + heading + violet rule, kept together."""
        items = []
        if kick:
            items.append(Paragraph(kick.upper(), kicker))
        items.append(Paragraph(text, h1))
        items.append(HRFlowable(width="100%", thickness=1.4, color=VIOLET,
                                spaceBefore=3, spaceAfter=8))
        return KeepTogether(items)

    def chip(text, fg, bg):
        """A compact rounded-look status chip (single-cell table)."""
        return Table(
            [[Paragraph(text.upper(), ps("chip", fontSize=8.5, textColor=fg,
                                         fontName="Helvetica-Bold", alignment=TA_CENTER))]],
            style=TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), bg),
                ("BOX",          (0, 0), (-1, -1), 0.7, fg),
                ("TOPPADDING",   (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ("LEFTPADDING",  (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ]),
        )

    def banner(text, bg, fg=WHITE, size=10):
        return Table(
            [[Paragraph(text, ps("bn", fontSize=size, textColor=fg,
                                  fontName="Helvetica-Bold", leading=size + 3))]],
            colWidths=[cw],
            style=TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), bg),
                ("TOPPADDING",   (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
                ("LEFTPADDING",  (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ]),
        )

    def data_table(rows, col_widths, header=True):
        """Standard data table: violet header, zebra rows, wrapped cells."""
        t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
        sty = [
            ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("TEXTCOLOR",  (0, 0), (-1, -1), INK),
            ("GRID",       (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ]
        if header:
            sty += [
                ("BACKGROUND", (0, 0), (-1, 0), INDIGO_700),
                ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, 0), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ROW_ALT]),
            ]
        else:
            sty += [("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, ROW_ALT])]
        t.setStyle(TableStyle(sty))
        return t

    def accent_list(items, accent=VIOLET, tint=INDIGO_50, style=None, max_items=None):
        """Clean glyph-free 'bulleted' list: a colour bar + wrapped text per row."""
        style = style or body_l
        rows = []
        src = items if max_items is None else items[:max_items]
        for it in src:
            rows.append(["", Paragraph(str(it), style)])
        t = Table(rows, colWidths=[3, cw - 3])
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (0, -1), accent),
            ("BACKGROUND",   (1, 0), (1, -1), tint),
            ("LINEBELOW",    (1, 0), (1, -1), 2, WHITE),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (1, 0), (1, -1), 9),
            ("RIGHTPADDING", (1, 0), (1, -1), 9),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ]))
        return t

    def stat_card(label, value, sub, accent, tint):
        """A single dashboard stat card."""
        return Table(
            [[Paragraph(label.upper(), ps("scl", fontSize=7.5, textColor=GRAY,
                                          fontName="Helvetica-Bold", alignment=TA_CENTER))],
             [Paragraph(str(value), ps("scv", fontSize=16, textColor=accent,
                                       fontName="Helvetica-Bold", alignment=TA_CENTER, leading=18))],
             [Paragraph(sub, ps("scs", fontSize=7.5, textColor=SLATE,
                                fontName="Helvetica", alignment=TA_CENTER, leading=9))]],
            style=TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), tint),
                ("LINEABOVE",    (0, 0), (-1, 0), 2.2, accent),
                ("BOX",          (0, 0), (-1, -1), 0.4, BORDER),
                ("TOPPADDING",   (0, 0), (-1, 0), 7),
                ("TOPPADDING",   (0, 1), (-1, 1), 1),
                ("TOPPADDING",   (0, 2), (-1, 2), 1),
                ("BOTTOMPADDING",(0, 2), (-1, 2), 8),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]),
        )

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 1 -- COVER
    # ═════════════════════════════════════════════════════════════════════════
    story: list = []

    # Hero header (brand mark + title + violet accent stripe underneath)
    hero = Table(
        [[Paragraph("ClaimIQ", ps("logo", fontSize=22, textColor=WHITE,
                                  fontName="Helvetica-Bold", leading=24)),
          Paragraph("AI CLAIMS ANALYSIS REPORT", ps("subt", fontSize=10, textColor=HexColor("#C7D2FE"),
                                  fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=13))]],
        colWidths=[cw * 0.5, cw * 0.5],
        style=TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), INDIGO_900),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 14),
            ("LEFTPADDING",  (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ]),
    )
    story.append(hero)
    story.append(Table([[""]], colWidths=[cw], rowHeights=[4],
                       style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), VIOLET)])))
    story.append(Spacer(1, 12))

    # Status ribbon: three chips in a row
    human_str = "HUMAN REVIEW REQUIRED" if human_flag else "AUTO-ELIGIBLE"
    ribbon = Table(
        [[chip(f"{triage_color} TRIAGE", banner_color, banner_tint),
          chip(f"{priority} PRIORITY", INDIGO_700, INDIGO_50),
          chip(human_str, (RED if human_flag else GREEN), (RED_T if human_flag else GREEN_T))]],
        colWidths=[cw / 3.0] * 3,
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]),
    )
    story.append(ribbon)
    story.append(Spacer(1, 14))

    # Dashboard stat cards
    gap = 10
    card_w = (cw - 2 * gap) / 3.0
    cards = Table(
        [[stat_card("Fraud Risk", f"{fraud_score}", f"{risk_level} - out of 100", risk_color, risk_tint),
          "",
          stat_card("Coverage", cov_status.title(), "Coverage Agent finding", cov_color, cov_tint),
          "",
          stat_card("Claimed Amount", amount_str.replace(f"{currency} ", ""),
                    f"{currency}  -  SLA {sla}h", INDIGO_700, INDIGO_50)]],
        colWidths=[card_w, gap, card_w, gap, card_w],
        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                          ("LEFTPADDING", (0, 0), (-1, -1), 0),
                          ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                          ("TOPPADDING", (0, 0), (-1, -1), 0),
                          ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]),
    )
    story.append(cards)
    story.append(Spacer(1, 16))

    # Claim snapshot (4-col, all values wrapped)
    story.append(Paragraph("CLAIM SNAPSHOT", kicker))
    story.append(HRFlowable(width="100%", thickness=1.2, color=VIOLET, spaceBefore=2, spaceAfter=7))
    snap = [
        ["Claim Reference", P(claim_id, cell_b), "Report Generated", P(generated_at)],
        ["Claimant",        P(claimant, cell_b), "Claim Type",       P(claim_type)],
        ["Policy Number",   P(policy_num),       "Incident Date",    P(incident_dt)],
        ["Claimed Amount",  P(amount_str, cell_b),"Processing SLA",  P(f"{sla} hours")],
        ["Coverage Status", P(cov_status.title()),"Fraud Risk",      P(f"{risk_level.title()} ({fraud_score}/100)")],
    ]
    snap_tbl = Table(snap, colWidths=[cw*0.20, cw*0.30, cw*0.20, cw*0.30])
    snap_tbl.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",   (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",  (0, 0), (0, -1), INDIGO_700),
        ("TEXTCOLOR",  (2, 0), (2, -1), INDIGO_700),
        ("BACKGROUND", (0, 0), (0, -1), INDIGO_50),
        ("BACKGROUND", (2, 0), (2, -1), INDIGO_50),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [WHITE, ROW_ALT]),
        ("ROWBACKGROUNDS", (3, 0), (3, -1), [WHITE, ROW_ALT]),
        ("GRID",       (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]))
    story.append(snap_tbl)
    story.append(Spacer(1, 16))

    # Executive Summary (in a soft panel)
    story.append(Paragraph("EXECUTIVE SUMMARY", kicker))
    story.append(HRFlowable(width="100%", thickness=1.2, color=VIOLET, spaceBefore=2, spaceAfter=7))
    exec_summ = _str_field(
        copilot.get("executive_summary") or intake.get("claim_summary")
    ) or "No executive summary available from Adjuster Copilot."
    summ_panel = Table(
        [["", Paragraph(exec_summ[:1200], body)]],
        colWidths=[3.5, cw - 3.5],
        style=TableStyle([
            ("BACKGROUND",   (0, 0), (0, -1), VIOLET),
            ("BACKGROUND",   (1, 0), (1, -1), INDIGO_50),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (1, 0), (1, -1), 10),
            ("RIGHTPADDING", (1, 0), (1, -1), 10),
            ("TOPPADDING",   (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
            ("LEFTPADDING",  (0, 0), (0, -1), 0),
        ]),
    )
    story.append(summ_panel)

    desc = intake.get("incident_description") or ""
    if len(desc) < 60:
        desc = intake.get("claim_summary") or desc
    if desc:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Incident Description", h2))
        story.append(Paragraph(desc[:1500], body))

    # Key Findings -- a scannable synthesis of the pipeline's conclusions.
    kf: list = []
    if signals:
        kf.append(f"<b>Fraud:</b> {risk_level.title()} risk ({fraud_score}/100) -- "
                  f"lead signal '{_pretty(signals[0].get('signal_id'))}'"
                  + (f" and {len(signals)-1} more" if len(signals) > 1 else "") + ".")
    else:
        kf.append(f"<b>Fraud:</b> {risk_level.title()} risk ({fraud_score}/100) -- no signals detected.")
    kf.append(f"<b>Coverage:</b> {cov_status.title()}"
              + (f" -- {len(excls)} exclusion(s) to verify." if excls else "."))
    if max_amt or raw_amount:
        fin = f"<b>Financial:</b> Claimed {amount_str}"
        if max_amt:
            fin += f" against policy limit {currency} {float(max_amt):,.0f}"
        if est_payable is not None:
            fin += f"; est. max payable {currency} {est_payable:,.0f}"
        kf.append(fin + ".")
    kf.append(f"<b>Routing:</b> {routing} -- {priority.title()} priority, {sla}h SLA.")
    if human_flag:
        kf.append("<b>Approval:</b> Human review required -- "
                  + (reasons[0] if reasons else "see routing triggers.")
                  + ("" if str(reasons[0] if reasons else "").endswith(".") else "."))
    kf.append(f"<b>Recommended action:</b> {rec_action}.")

    story.append(Spacer(1, 12))
    story.append(Paragraph("KEY FINDINGS", kicker))
    story.append(HRFlowable(width="100%", thickness=1.2, color=VIOLET, spaceBefore=2, spaceAfter=7))
    story.append(accent_list(kf, accent=INDIGO_600, tint=INDIGO_50))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 2 -- CLAIM DETAILS + COVERAGE
    # ═════════════════════════════════════════════════════════════════════════

    story.append(section_header("Claim Details", "Intake Agent"))

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
        ("Police Report Filed",  _pretty(intake.get("police_report_filed"), "N/A")),
        ("Police Report No.",    intake.get("police_report_number")),
        ("Contact Phone",        intake.get("contact_phone")),
        ("Third Party Involved", _pretty(intake.get("third_party_involved"), "N/A")),
        ("Intake Confidence",    _format_confidence(intake.get("confidence_score"))),
    ]
    det_rows = [["Field", "Value"]] + [
        [lbl, P(val)] for lbl, val in field_map
        if val and str(val) not in ("None", "N/A", "False")
    ]
    story.append(data_table(det_rows, [cw * 0.38, cw * 0.62]))

    missing = intake.get("missing_information") or []
    if missing:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Missing Information", h2))
        story.append(accent_list([str(m) for m in missing[:6]], accent=AMBER, tint=AMBER_T))

    docs = intake.get("documents_mentioned") or []
    if docs:
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "Documents Referenced: " + ", ".join(str(d) for d in docs[:8]), small,
        ))

    story.append(Spacer(1, 14))
    story.append(section_header("Coverage Analysis", "Coverage Agent"))

    story.append(chip(f"Coverage Status: {cov_status.title()}", cov_color, cov_tint))
    story.append(Spacer(1, 8))

    cov_fields = [
        ("Policy Holder",         _clean(coverage.get("policy_holder_name"))),
        ("Policy Status",         _pretty(_clean(coverage.get("policy_status"), "Not Found"))),
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
        [lbl, P(val)] for lbl, val in cov_fields if val and val != "N/A"
    ]
    story.append(data_table(cov_rows, [cw * 0.42, cw * 0.58]))

    # ── Financial Summary ─────────────────────────────────────────────────────
    if raw_amount or max_amt or deduct:
        try:
            claimed_v = float(raw_amount) if raw_amount else None
        except (TypeError, ValueError):
            claimed_v = None
        util = None
        if claimed_v is not None and max_amt:
            try:
                util = f"{min(claimed_v / float(max_amt), 9.99):.0%} of limit"
            except (TypeError, ValueError, ZeroDivisionError):
                util = None
        fin_rows = [["Financial Field", "Amount"]]
        fin_rows.append(["Claimed Amount", P(amount_str, cell_b)])
        if max_amt:
            fin_rows.append(["Policy Maximum Limit", P(f"{currency} {float(max_amt):,.0f}")])
        if deduct:
            fin_rows.append(["Deductible", P(f"{currency} {float(deduct):,.0f}")])
        if est_payable is not None:
            fin_rows.append(["Estimated Max Payable (pre-adjudication)",
                             P(f"{currency} {est_payable:,.0f}", cell_b)])
        if util:
            fin_rows.append(["Limit Utilisation", P(util)])
        if len(fin_rows) > 1:
            story.append(Spacer(1, 10))
            story.append(Paragraph("Financial Summary", h2))
            story.append(data_table(fin_rows, [cw * 0.55, cw * 0.45]))
            story.append(Paragraph(
                "Estimated payable is an indicative pre-adjudication ceiling "
                "(lesser of claimed amount and policy limit, less deductible). "
                "Final settlement is subject to survey, coverage confirmation, and adjuster approval.",
                small))

    reasoning = coverage.get("coverage_reasoning") or ""
    if reasoning:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Coverage Reasoning", h2))
        story.append(Paragraph(reasoning[:2000], body))

    if excls:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Applicable Exclusions", h2))
        story.append(accent_list([_pretty(e) for e in excls[:6]], accent=RED, tint=RED_T))

    secs = coverage.get("policy_sections_referenced") or []
    if secs:
        sec_text = _fmt_policy_sections(secs)
        if sec_text:
            story.append(Spacer(1, 4))
            story.append(Paragraph("Policy Sections:  " + sec_text, small))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 3 -- FRAUD ANALYSIS
    # ═════════════════════════════════════════════════════════════════════════

    story.append(section_header("Fraud Risk Analysis", "Fraud Agent"))

    # Score + risk banner
    story.append(Table(
        [[
            Paragraph(f"Fraud Score:  {fraud_score} / 100",
                      ps("fsc", fontSize=15, textColor=WHITE, fontName="Helvetica-Bold")),
            Paragraph(f"Risk Level:  {risk_level}",
                      ps("frl", fontSize=12, textColor=WHITE, fontName="Helvetica-Bold",
                         alignment=TA_RIGHT)),
        ]],
        colWidths=[cw * 0.55, cw * 0.45],
        style=TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), risk_color),
            ("TOPPADDING",   (0, 0), (-1, -1), 11),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 11),
            ("LEFTPADDING",  (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ]),
    ))
    story.append(Spacer(1, 12))

    # Charts (side by side)
    if mpl_ok:
        donut_buf = _chart_fraud_donut(fraud_score, signals, risk_level)
        bar_buf   = _chart_signal_bars(signals, fraud_score) if signals else None

        if donut_buf and bar_buf:
            ch_w = cw * 0.48
            story.append(Table(
                [[Image(donut_buf, width=ch_w, height=ch_w * 0.80),
                  Image(bar_buf,   width=ch_w, height=ch_w * 0.80)]],
                colWidths=[cw * 0.5, cw * 0.5],
                style=TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
            ))
            story.append(Paragraph(
                "Left: fraud score composition by signal severity.   "
                "Right: score contribution of each detected signal.", cap))
        elif donut_buf:
            ch_w = cw * 0.55
            story.append(Table([[Image(donut_buf, width=ch_w, height=ch_w * 0.80)]],
                               colWidths=[cw],
                               style=TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")])))
            story.append(Paragraph("Fraud score composition by signal severity.", cap))
        story.append(Spacer(1, 8))

    # Signals table
    if signals:
        story.append(Paragraph("Detected Fraud Signals", h2))
        SIG_SEV_COLORS = {"CRITICAL": RED, "HIGH": AMBER, "MEDIUM": HexColor("#CA8A04"), "LOW": GRAY}
        sig_rows = [["Signal", "Severity", "Score", "Description"]]
        for s in signals:
            severity = _upper_label(s.get("severity"), "")
            sig_rows.append([
                P(_pretty(s.get("signal_id") or "Unknown"), cell_b),
                severity,
                f"+{s.get('score_contribution', 0)}",
                P((str(s.get("description") or ""))[:220]),
            ])
        st = data_table(sig_rows, [cw*0.28, cw*0.14, cw*0.10, cw*0.48])
        # Re-apply severity colours on top of the base data_table style
        extra = TableStyle()
        for i, s in enumerate(signals, 1):
            c = SIG_SEV_COLORS.get(_upper_label(s.get("severity"), ""), GRAY)
            extra.add("TEXTCOLOR", (1, i), (2, i), c)
            extra.add("FONTNAME",  (1, i), (2, i), "Helvetica-Bold")
            extra.add("ALIGN",     (2, i), (2, i), "CENTER")
        st.setStyle(extra)
        story.append(st)
    else:
        story.append(Paragraph("No fraud signals were detected for this claim.", body))

    fraud_reasoning = fraud.get("fraud_reasoning") or ""
    if fraud_reasoning:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Analysis Reasoning", h2))
        story.append(Paragraph(fraud_reasoning[:2000], body))

    ru = rec_action.upper()
    ac_color, ac_tint = (
        (RED, RED_T) if any(k in ru for k in ("SIU", "REFER", "ESCALAT", "HOLD", "INVESTIG"))
        else (AMBER, AMBER_T) if "FLAG" in ru
        else (GREEN, GREEN_T)
    )
    story.append(Spacer(1, 8))
    story.append(banner(f"Recommended Action:  {rec_action}", ac_color, size=10))

    dup_ids = fraud.get("duplicate_claim_ids") or []
    if dup_ids:
        story.append(Spacer(1, 8))
        story.append(accent_list(
            [f"Duplicate Claim IDs Detected: {', '.join(str(d) for d in dup_ids)}"],
            accent=RED, tint=RED_T,
            style=ps("dup", fontSize=9, textColor=RED, fontName="Helvetica-Bold", leading=12)))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 4 -- ROUTING & ADJUSTER DECISION
    # ═════════════════════════════════════════════════════════════════════════

    story.append(section_header("Routing & Adjuster Decision", "Triage + Copilot"))

    routing_data = [
        ("Triage Color",    triage_color),
        ("Priority Level",  priority),
        ("Routing Queue",   routing),
        ("SLA (hours)",     str(sla)),
        ("Human Approval",  "REQUIRED" if human_flag else "NOT REQUIRED"),
        ("Est. Settlement", f"{triage.get('estimated_settlement_days')} days"
                            if triage.get("estimated_settlement_days") else "N/A"),
    ]
    rt_rows = [["Routing Field", "Value"]] + [[lbl, P(val)] for lbl, val in routing_data]
    rt = data_table(rt_rows, [cw * 0.42, cw * 0.58])
    extra = TableStyle()
    for i, (lbl, val) in enumerate(routing_data, 1):
        if lbl == "Human Approval":
            c = RED if val == "REQUIRED" else GREEN
            extra.add("TEXTCOLOR", (1, i), (1, i), c)
            extra.add("FONTNAME",  (1, i), (1, i), "Helvetica-Bold")
        if lbl == "Triage Color":
            extra.add("TEXTCOLOR", (1, i), (1, i), TRIAGE_CMAP.get(val, AMBER))
            extra.add("FONTNAME",  (1, i), (1, i), "Helvetica-Bold")
    rt.setStyle(extra)
    story.append(rt)

    if reasons:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Human Approval Triggers", h2))
        story.append(accent_list([str(r) for r in reasons[:6]], accent=RED, tint=RED_T,
                                 style=ps("rsn", fontSize=9, textColor=RED,
                                          fontName="Helvetica-Bold", leading=12)))

    triage_summ = triage.get("triage_summary") or ""
    if triage_summ:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Triage Summary", h2))
        story.append(Paragraph(triage_summ, body))

    # ── Plain-English Analysis (from Adjuster Copilot) ────────────────────────
    PE_ORDER = [
        ("coverage", "Coverage", cov_color),
        ("fraud", "Fraud", risk_color),
        ("triage", "Routing", INDIGO_600),
        ("payable_calculation", "Payable", INDIGO_700),
        ("medical", "Medical", VIOLET),
    ]
    pe_rows, pe_colors = [], []
    for key, label, lc in PE_ORDER:
        txt = _str_field(explanations.get(key)) if explanations else ""
        if txt and txt.strip():
            pe_rows.append([
                Paragraph(label, ps(f"pel{key}", fontSize=9, textColor=WHITE,
                                    fontName="Helvetica-Bold", alignment=TA_CENTER)),
                Paragraph(txt[:900], ps(f"pev{key}", fontSize=9, textColor=INK, leading=13)),
            ])
            pe_colors.append(lc)
    if pe_rows:
        story.append(Spacer(1, 14))
        story.append(section_header("Plain-English Analysis", "Adjuster Copilot"))
        pe_tbl = Table(pe_rows, colWidths=[cw * 0.16, cw * 0.84])
        pe_sty = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("BACKGROUND", (1, 0), (1, -1), ROW_ALT),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]
        for i, lc in enumerate(pe_colors):
            pe_sty.append(("BACKGROUND", (0, i), (0, i), lc))
        pe_tbl.setStyle(TableStyle(pe_sty))
        story.append(pe_tbl)

    checklist = copilot.get("approval_checklist") or []
    if checklist:
        story.append(Spacer(1, 14))
        story.append(section_header("Adjuster Checklist", "Adjuster Copilot"))
        chk_rows = [["#", "Item", "Status"]]
        for i, item in enumerate(checklist, 1):
            if isinstance(item, dict):
                chk_rows.append([
                    str(i),
                    P(str(item.get("item") or item.get("check") or item)),
                    _pretty(item.get("status") or "Pending"),
                ])
            else:
                chk_rows.append([str(i), P(str(item)), "Pending"])
        story.append(data_table(chk_rows, [cw*0.07, cw*0.68, cw*0.25]))

    open_qs = copilot.get("open_questions") or []
    if open_qs:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Open Questions for Adjuster", h2))
        story.append(accent_list(
            [f"{i}.  {q}" for i, q in enumerate(open_qs[:8], 1)], accent=INDIGO_600, tint=INDIGO_50))

    next_steps = list(triage.get("recommended_next_steps") or [])
    for s in cop_next:
        if str(s) not in {str(x) for x in next_steps}:
            next_steps.append(s)
    if next_steps:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Recommended Next Steps", h2))
        story.append(accent_list(
            [f"{i}.  {s}" for i, s in enumerate(next_steps[:7], 1)], accent=GREEN, tint=GREEN_T))

    if guardrails:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Decision Guardrails", h2))
        story.append(accent_list([str(g) for g in guardrails[:6]], accent=RED, tint=RED_T,
                                 style=ps("grd", fontSize=9, textColor=RED,
                                          fontName="Helvetica-Bold", leading=12)))

    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 5 -- AUDIT TRAIL
    # ═════════════════════════════════════════════════════════════════════════

    story.append(section_header("Pipeline Audit Trail", "Orchestrator"))

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
            duration = f"{dur_ms/1000:.1f}s" if isinstance(dur_ms, (int, float)) else "-"
            ev_rows.append([
                str(ev.get("agent") or "").title(),
                str(ev.get("status") or "unknown").upper(),
                P(str(completed)),
                duration,
            ])
        ev_tbl = data_table(ev_rows, [cw*0.20, cw*0.16, cw*0.50, cw*0.14])
        extra = TableStyle()
        for i, ev in enumerate(evidence, 1):
            c = GREEN if str(ev.get("status")).lower() == "success" else RED
            extra.add("TEXTCOLOR", (1, i), (1, i), c)
            extra.add("FONTNAME",  (1, i), (1, i), "Helvetica-Bold")
        ev_tbl.setStyle(extra)
        story.append(ev_tbl)
        story.append(Spacer(1, 12))

    story.append(Paragraph("Agent Output Summary", h2))
    as_rows = [["Agent", "Key Output", "Confidence"]]
    agent_rows_data = [
        ("intake",  f"Type: {claim_type}   |   Amount: {amount_str}   |   Policy: {policy_num}",
         _format_confidence(intake.get("confidence_score"))),
        ("coverage", f"Status: {cov_status.title()}   |   Active on date: "
                     f"{_clean(coverage.get('policy_active_on_incident_date'),'N/A')}",
         _format_confidence(coverage.get("coverage_confidence"))),
        ("fraud",   f"Score: {fraud_score}/100   |   Level: {risk_level.title()}   |   Action: {rec_action}",
         _format_confidence(fraud.get("fraud_confidence"))),
        ("triage",  f"Queue: {routing}   |   SLA: {sla}h   |   Color: {triage_color.title()}", "-"),
        ("copilot", f"Brief: ready   |   Open Qs: {len(open_qs)}   |   Checklist: {len(checklist)} items", "-"),
    ]
    for name, summary, conf in agent_rows_data:
        if name in outputs:
            has_error = "error" in (outputs.get(name) or {})
            as_rows.append([
                P(("[ERR] " if has_error else "") + name.title(), cell_b),
                P(summary), conf,
            ])
    story.append(data_table(as_rows, [cw*0.15, cw*0.69, cw*0.16]))

    # Disclaimer footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.4, color=BORDER))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        f"This report was automatically generated by the ClaimIQ AI Pipeline on {generated_at}. "
        "All decisions flagged 'HUMAN REVIEW REQUIRED' must be confirmed by a qualified adjuster "
        "before action is taken. AI-generated analysis is decision-support only and must be "
        "independently verified against source documents and policy wording. This document is "
        "confidential and intended solely for authorised insurance personnel. Do not distribute externally.",
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

        INDIGO = HexColor("#4338CA")
        VIOLET = HexColor("#7C3AED")
        GRAY   = HexColor("#6B7280")
        BORDER = HexColor("#E5E7EB")
        pw, ph = doc.pagesize

        canvas.saveState()

        # ── Header ────────────────────────────────────────────────────────
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(INDIGO)
        canvas.drawString(1.7 * cm, ph - 1.35 * cm, "ClaimIQ  |  Confidential Claim Report")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAY)
        canvas.drawRightString(pw - 1.7 * cm, ph - 1.35 * cm, claim_id)
        canvas.setStrokeColor(VIOLET)
        canvas.setLineWidth(1.0)
        canvas.line(1.7 * cm, ph - 1.55 * cm, pw - 1.7 * cm, ph - 1.55 * cm)

        # ── Footer ────────────────────────────────────────────────────────
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(1.7 * cm, 1.35 * cm, pw - 1.7 * cm, 1.35 * cm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(GRAY)
        canvas.drawString(1.7 * cm, 1.05 * cm,
                          f"Generated {generated_at}   |   For authorised personnel only")
        canvas.drawRightString(pw - 1.7 * cm, 1.05 * cm, f"Page {doc.page}")

        canvas.restoreState()

    return _draw


# ------------------------------------------------------------------------------
# Chart: Fraud Score Donut
# ------------------------------------------------------------------------------

def _chart_fraud_donut(fraud_score: int, signals: list[dict], risk_level: str) -> "io.BytesIO | None":
    """Donut chart: each signal as a severity-coloured wedge + safe remainder."""
    try:
        import matplotlib
        if matplotlib.get_backend().lower() != "agg":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        SEV_COLORS = {"critical": "#B91C1C", "high": "#D97706",
                      "medium": "#F59E0B", "low": "#86EFAC"}
        RISK_COLORS = {"CRITICAL": "#B91C1C", "HIGH": "#D97706",
                       "MEDIUM": "#F59E0B", "LOW": "#15803D"}
        SAFE_CLR = "#E5E7EB"

        def _label(sid):
            return (sid or "Unknown").replace("_", " ").title()

        if signals:
            sizes  = [max(0, int(s.get("score_contribution", 0))) for s in signals]
            clrs   = [SEV_COLORS.get((s.get("severity") or "medium").lower(), "#D97706") for s in signals]
            labels = [_label(s.get("signal_id"))[:22] for s in signals]
            safe = max(0, 100 - sum(sizes))
            if safe > 0:
                sizes.append(safe); clrs.append(SAFE_CLR); labels.append("Safe / unscored")
        else:
            safe_val = max(0, 100 - fraud_score)
            sizes  = [fraud_score or 1, safe_val or 99]
            clrs   = [RISK_COLORS.get(risk_level, "#D97706"), SAFE_CLR]
            labels = [f"Risk ({fraud_score})", "Safe / unscored"]

        fig, ax = plt.subplots(figsize=(4.3, 3.7), facecolor="white")
        ax.pie(sizes, colors=clrs, startangle=90,
               wedgeprops={"width": 0.40, "edgecolor": "white", "linewidth": 1.6},
               counterclock=False)

        center_color = RISK_COLORS.get(risk_level, "#D97706")
        ax.text(0,  0.12, str(fraud_score), ha="center", va="center",
                fontsize=26, fontweight="bold", color=center_color)
        ax.text(0, -0.14, risk_level, ha="center", va="center",
                fontsize=9, fontweight="bold", color=center_color)
        ax.text(0, -0.30, "out of 100", ha="center", va="center", fontsize=7, color="#9CA3AF")
        ax.set_title("Fraud Score Composition", fontsize=10.5, fontweight="bold",
                     color="#1F2937", pad=8)

        patches = [mpatches.Patch(color=clrs[i], label=labels[i])
                   for i in range(min(len(labels), 6))]
        ax.legend(handles=patches, loc="upper center", bbox_to_anchor=(0.5, -0.02),
                  ncol=2, fontsize=6.5, frameon=False, handlelength=1.2,
                  columnspacing=1.0, labelspacing=0.35)

        fig.subplots_adjust(top=0.86, bottom=0.24, left=0.04, right=0.96)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=170, facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as exc:
        log.warning("[ReportTool] Donut chart error: %s", exc)
        return None


# ------------------------------------------------------------------------------
# Chart: Signal Score Bar Chart
# ------------------------------------------------------------------------------

def _chart_signal_bars(signals: list[dict], total_score: int) -> "io.BytesIO | None":
    """Vertical bar chart of each signal's score contribution."""
    if not signals:
        return None
    try:
        import matplotlib
        if matplotlib.get_backend().lower() != "agg":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import textwrap

        SEV_COLORS = {"critical": "#B91C1C", "high": "#D97706",
                      "medium": "#F59E0B", "low": "#86EFAC"}

        def _wrap(sid):
            txt = (sid or "Unknown").replace("_", " ").title()
            return "\n".join(textwrap.wrap(txt, 12))[:40]

        labels = [_wrap(s.get("signal_id")) for s in signals]
        values = [int(s.get("score_contribution", 0)) for s in signals]
        clrs   = [SEV_COLORS.get((s.get("severity") or "medium").lower(), "#D97706") for s in signals]

        fig, ax = plt.subplots(figsize=(4.3, 3.7), facecolor="white")
        x = np.arange(len(labels))
        bars = ax.bar(x, values, color=clrs, edgecolor="white", linewidth=1.2, width=0.62)

        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.6,
                        f"+{val}", ha="center", va="bottom", fontsize=8.5,
                        fontweight="bold", color="#374151")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=6.5, color="#374151")
        ax.set_ylabel("Score Contribution", fontsize=8, color="#6B7280")
        ax.set_title("Signal Contributions", fontsize=10.5, fontweight="bold",
                     color="#1F2937", pad=8)
        ax.set_ylim(0, max(max(values, default=0) + 12, 35))
        ax.yaxis.grid(True, alpha=0.35, color="#E5E7EB", linewidth=0.6)
        ax.set_axisbelow(True)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.spines["left"].set_color("#E5E7EB")
        ax.spines["bottom"].set_color("#E5E7EB")
        ax.tick_params(colors="#6B7280", length=0)

        ax.axhline(total_score, color="#7C3AED", linestyle="--", alpha=0.6, linewidth=1.0)
        ax.text(len(labels) - 0.45, total_score + 1, f"Total: {total_score}",
                ha="right", fontsize=7, color="#7C3AED", fontstyle="italic")

        fig.subplots_adjust(top=0.86, bottom=0.20, left=0.13, right=0.97)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=170, facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as exc:
        log.warning("[ReportTool] Bar chart error: %s", exc)
        return None
