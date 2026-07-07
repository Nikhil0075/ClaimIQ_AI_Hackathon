"""
ClaimIQ -- Adjuster Guide PDF Generator
=======================================
Generates a per-claim instruction PDF for the human adjuster, uploaded to Drive
alongside the claim documents.

Design
------
Shares the unified "ClaimIQ Indigo" brand system with the Analysis Report:
  • Deep indigo hero header + violet accent rules
  • Colour-coded triage / coverage / risk chips
  • Glyph-free "accent bar" lists and wrapped table cells (no ■ boxes, no overflow)
  • Prettified labels (needs_review -> Needs Review, etc.)
  • Running page header/footer for a matched, professional look

Public API is unchanged:
    generate_adjuster_guide_pdf(claim_id, copilot, intake=None) -> bytes | None
"""
from __future__ import annotations
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("claimiq.adjuster_guide")

# ── ClaimIQ Indigo palette (hex) ──────────────────────────────────────────────
_INDIGO_900 = "#312E81"   # hero / header bars
_INDIGO_700 = "#4338CA"   # primary brand
_INDIGO_600 = "#4F46E5"
_VIOLET     = "#7C3AED"   # accent
_VIOLET_100 = "#EDE9FE"
_INDIGO_50  = "#EEF2FF"
_INK        = "#1F2937"
_SLATE      = "#475569"
_GRAY       = "#6B7280"
_MUTED      = "#9CA3AF"
_BORDER     = "#E5E7EB"
_ROW_ALT    = "#F8FAFC"
_WHITE      = "#FFFFFF"

_GREEN = "#15803D"; _GREEN_T = "#DCFCE7"
_AMBER = "#B45309"; _AMBER_T = "#FEF3C7"
_RED   = "#B91C1C"; _RED_T   = "#FEE2E2"

_TRIAGE_COLOURS = {"green": _GREEN, "amber": _AMBER, "yellow": _AMBER, "orange": _AMBER, "red": _RED}
_TRIAGE_TINTS   = {"green": _GREEN_T, "amber": _AMBER_T, "yellow": _AMBER_T, "orange": _AMBER_T, "red": _RED_T}
_STATUS_COLOURS = {"covered": _GREEN, "needs_review": _AMBER, "not_covered": _RED}
_STATUS_TINTS   = {"covered": _GREEN_T, "needs_review": _AMBER_T, "not_covered": _RED_T}
_RISK_COLOURS   = {"low": _GREEN, "medium": _AMBER, "high": _RED, "critical": _RED}
_RISK_TINTS     = {"low": _GREEN_T, "medium": _AMBER_T, "high": _RED_T, "critical": _RED_T}


# ── Text sanitisation (self-contained fallback) ───────────────────────────────

_UNICODE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "‒": "-", "‑": "-", "‐": "-",
    "•": "-", "‣": "-", "▪": "-", "●": "-", "·": "-", "…": "...",
    " ": " ", " ": " ", " ": " ", "​": "",
    "→": "->", "←": "<-", "⇒": "=>", "✓": "[ok]", "✔": "[ok]", "✗": "[x]", "✘": "[x]",
    "₹": "INR ", "€": "EUR ", "£": "GBP ", "≥": ">=", "≤": "<=", "≠": "!=", "×": "x",
}
_UNICODE_RE = re.compile("|".join(re.escape(k) for k in _UNICODE_MAP))


def _sanitize_str(text: str) -> str:
    if not text:
        return text
    text = _UNICODE_RE.sub(lambda m: _UNICODE_MAP[m.group(0)], text)
    try:
        text.encode("cp1252")
        return text
    except UnicodeEncodeError:
        out = []
        for c in text:
            try:
                c.encode("cp1252"); out.append(c)
            except UnicodeEncodeError:
                out.append("")
        return "".join(out)


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
    try:
        from claimiq.shared.pdf_text import sanitize_deep  # type: ignore
        return sanitize_deep(obj)
    except Exception:
        return _fallback_sanitize_deep(obj)


# ── Display helpers ───────────────────────────────────────────────────────────

_HIDDEN = {"", "none", "null", "n/a", "not_found", "false", "unknown"}


def _pretty(value: Any, default: str = "-") -> str:
    """snake_case sentinel -> readable Title Case."""
    if value in (None, "", [], {}):
        return default
    s = str(value).strip()
    if "_" in s and " " not in s:
        s = s.replace("_", " ")
    if s.islower() or s.isupper():
        s = s.title()
    return s or default


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def generate_adjuster_guide_pdf(
    claim_id: str,
    copilot: dict,
    intake: dict | None = None,
) -> bytes | None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm, cm
        from reportlab.lib import colors
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether,
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_JUSTIFY
    except ImportError:
        log.warning("[AdjusterGuide] reportlab not installed")
        return None

    # ── Defensive guards + sanitise ───────────────────────────────────────────
    if not isinstance(copilot, dict):
        copilot = {}
    if not isinstance(intake, dict):
        intake = {}
    copilot = _sanitize_deep(copilot)
    intake  = _sanitize_deep(intake)

    def C(hex_or_rgb):
        return HexColor(hex_or_rgb) if isinstance(hex_or_rgb, str) else colors.Color(*hex_or_rgb)

    def _as_dict(v: Any) -> dict:
        return v if isinstance(v, dict) else {}

    def _as_list(v: Any) -> list:
        return v if isinstance(v, list) else []

    def _val(v, default="-"):
        if v in (None, "", [], {}):
            return default
        return str(v)

    def _money(v, currency="INR"):
        try:
            return f"{currency} {float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v) if v else "-"

    base = getSampleStyleSheet()

    def S(name, **kw):
        return ParagraphStyle(f"ag_{claim_id[:8]}_{name}", parent=base["Normal"], **kw)

    # ── Page geometry ─────────────────────────────────────────────────────────
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 17 * mm
    CW = PAGE_W - 2 * MARGIN
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=22 * mm, bottomMargin=16 * mm,
        title=f"ClaimIQ Adjuster Guide - {claim_id}", author="ClaimIQ AI System",
    )
    story: list = []

    # ── Reusable styles ───────────────────────────────────────────────────────
    body   = S("bd", fontSize=9.5, textColor=C(_INK), leading=14, spaceAfter=4, alignment=TA_JUSTIFY)
    body_l = S("bdl", fontSize=9.5, textColor=C(_INK), leading=14, spaceAfter=4)
    cell   = S("cl", fontSize=9, textColor=C(_INK), leading=12)
    cell_b = S("clb", fontSize=9, textColor=C(_INK), leading=12, fontName="Helvetica-Bold")
    kicker = S("kk", fontSize=8, textColor=C(_VIOLET), fontName="Helvetica-Bold", spaceAfter=1)

    def hr(color=_VIOLET, t=1.3, sa=8, sb=3):
        return HRFlowable(width="100%", thickness=t, color=C(color), spaceAfter=sa, spaceBefore=sb)

    def sp(h=4):
        return Spacer(1, h)

    def P(text, style=cell):
        return Paragraph("" if text is None else str(text), style)

    def section(num, title):
        return KeepTogether([
            Paragraph(f"SECTION {num}", kicker),
            Paragraph(title, S("sh", fontSize=13, textColor=C(_INDIGO_700),
                               spaceBefore=2, spaceAfter=2, fontName="Helvetica-Bold", leading=16)),
            hr(),
        ])

    def chip_full(text, fg, bg):
        return Table(
            [[Paragraph(text, S("chf", fontSize=11, fontName="Helvetica-Bold",
                                 textColor=C(fg), alignment=TA_CENTER))]],
            colWidths=[CW],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), C(bg)),
                ("BOX",        (0, 0), (-1, -1), 1.0, C(fg)),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ]),
        )

    def data_table(rows, col_widths):
        t = Table(rows, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C(_INDIGO_700)),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 9.5),
            ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",   (0, 1), (-1, -1), 9),
            ("TEXTCOLOR",  (0, 1), (-1, -1), C(_INK)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C(_WHITE), C(_ROW_ALT)]),
            ("GRID",       (0, 0), (-1, -1), 0.4, C(_BORDER)),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        return t

    def accent_list(items, accent=_VIOLET, tint=_INDIGO_50, style=None, max_items=None):
        style = style or body_l
        src = items if max_items is None else items[:max_items]
        rows = [["", Paragraph(str(it), style)] for it in src if str(it).strip()]
        if not rows:
            return Spacer(1, 0)
        t = Table(rows, colWidths=[3, CW - 3])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), C(accent)),
            ("BACKGROUND", (1, 0), (1, -1), C(tint)),
            ("LINEBELOW",  (1, 0), (1, -1), 2, C(_WHITE)),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (1, 0), (1, -1), 9),
            ("RIGHTPADDING", (1, 0), (1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ]))
        return t

    # ── Pull data ─────────────────────────────────────────────────────────────
    generated_at  = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    triage_color  = str(copilot.get("triage_color") or "amber").lower()
    triage_rgb    = _TRIAGE_COLOURS.get(triage_color, _AMBER)
    triage_tint   = _TRIAGE_TINTS.get(triage_color, _AMBER_T)
    exec_summary  = _val(copilot.get("executive_summary"), "See claim documents in this Drive folder.")

    claim_details = _as_dict(copilot.get("claim_details"))
    cov_pos       = _as_dict(copilot.get("coverage_position"))
    fraud_asmt    = _as_dict(copilot.get("fraud_assessment"))
    routing       = _as_dict(copilot.get("routing_decision"))
    explanations  = _as_dict(copilot.get("plain_english_explanations"))
    role_views    = _as_dict(copilot.get("role_assistance"))
    checklist     = _as_list(copilot.get("approval_checklist"))
    open_qs       = _as_list(copilot.get("open_questions"))
    next_steps    = _as_list(copilot.get("suggested_next_steps"))
    guardrails    = _as_list(copilot.get("decision_guardrails"))
    exclusions    = _as_list(cov_pos.get("exclusions_identified"))
    signals       = _as_list(fraud_asmt.get("key_signals"))

    # ══════════════════════════════════════════════════════════════════════════
    # COVER
    # ══════════════════════════════════════════════════════════════════════════
    hero = Table(
        [[Paragraph("ClaimIQ", S("b1", fontSize=24, fontName="Helvetica-Bold",
                                 textColor=C(_WHITE), leading=26)),
          Paragraph("ADJUSTER GUIDE", S("b2", fontSize=12, textColor=C("#C7D2FE"),
                                        fontName="Helvetica-Bold", alignment=TA_RIGHT, leading=15))]],
        colWidths=[CW * 0.5, CW * 0.5],
    )
    hero.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C(_INDIGO_900)),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 15),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 15),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(hero)
    story.append(Table([[""]], colWidths=[CW], rowHeights=[4],
                       style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), C(_VIOLET))])))
    story.append(sp(14))

    story.append(Paragraph("HUMAN ADJUSTER ACTION FILE",
                           S("cs", fontSize=10, textColor=C(_VIOLET),
                             fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=6)))
    story.append(Paragraph(claim_id,
                           S("ct", fontSize=19, textColor=C(_INDIGO_700),
                             fontName="Helvetica-Bold", alignment=TA_CENTER, leading=23, spaceAfter=6)))
    story.append(Paragraph(f"Generated {generated_at}    |    Confidential - Internal Use Only",
                           S("cm", fontSize=9, textColor=C(_GRAY), alignment=TA_CENTER, spaceAfter=12)))

    story.append(chip_full(f"TRIAGE STATUS:  {triage_color.upper()}", triage_rgb, triage_tint))
    story.append(sp(14))

    # ── Section 1: Executive Summary ─────────────────────────────────────────
    story.append(section("1", "Executive Summary"))
    story.append(Table(
        [["", Paragraph(exec_summary, body)]],
        colWidths=[3.5, CW - 3.5],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), C(_VIOLET)),
            ("BACKGROUND", (1, 0), (1, -1), C(_INDIGO_50)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (1, 0), (1, -1), 10),
            ("RIGHTPADDING", (1, 0), (1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (0, -1), 0),
        ]),
    ))

    # ── Section 2: How to Use This Drive Folder ──────────────────────────────
    story.append(sp(6))
    story.append(section("2", "How to Use This Drive Folder"))
    instructions = [
        ("Open the Adjuster Guide (this PDF)",
         "Start here. Read the summary, todo list, and coverage notes before reviewing documents."),
        ("Review the claim documents",
         "All claimant attachments are in this folder. Cross-reference with Section 3 facts."),
        ("Work through the Todo List",
         "Section 4 has a structured checklist. Complete each item before closing the file."),
        ("Check Coverage & Fraud notes",
         "Section 5 has AI plain-English analysis. Verify cited policy wording independently."),
        ("Record your decision externally",
         "Log your final approval, rejection, or follow-up in the claims management system."),
    ]
    inst_rows = [[
        Paragraph(f"Step {i+1}", S(f"is{i}", fontSize=9, fontName="Helvetica-Bold",
                                   textColor=C(_WHITE), alignment=TA_CENTER)),
        Paragraph(title, S(f"it{i}", fontSize=9.5, fontName="Helvetica-Bold",
                           textColor=C(_INDIGO_700), leading=12)),
        Paragraph(desc, S(f"id{i}", fontSize=9, textColor=C(_INK), leading=12)),
    ] for i, (title, desc) in enumerate(instructions)]
    inst_table = Table(inst_rows, colWidths=[15 * mm, 52 * mm, None])
    inst_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), C(_INDIGO_600)),
        ("ROWBACKGROUNDS", (1, 0), (-1, -1), [C(_WHITE), C(_ROW_ALT)]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.4, C(_BORDER)),
    ]))
    story.append(inst_table)

    # ── Section 3: Claim Snapshot ─────────────────────────────────────────────
    story.append(sp(6))
    story.append(section("3", "Claim Snapshot"))
    cov_status = str(cov_pos.get("status") or "needs_review")
    fraud_score = fraud_asmt.get("score", 0)
    fraud_level = str(fraud_asmt.get("risk_level") or "low")
    requires_approval = routing.get("requires_human_approval", True)

    snap_rows = [
        ["Field", "Value"],
        ["Claimant",        P(_val(claim_details.get("claimant_name") or intake.get("claimant_name")))],
        ["Policy Number",   P(_val(claim_details.get("policy_number") or intake.get("policy_number")))],
        ["Claim Type",      P(_pretty(claim_details.get("claim_type") or intake.get("claim_type")))],
        ["Diagnosis/Procedure", P(_val(claim_details.get("procedure") or intake.get("procedure")))],
        ["Incident Date",   P(_val(claim_details.get("incident_date") or intake.get("incident_date")))],
        ["Claim Amount",    P(_money(claim_details.get("claim_amount") or intake.get("claim_amount"),
                                     str(claim_details.get("currency") or "INR")))],
        ["Coverage Status", P(_pretty(cov_status))],
        ["Fraud Score",     P(f"{fraud_score}/100  ({_pretty(fraud_level)})")],
        ["Priority",        P(_pretty(routing.get("priority")))],
        ["Routing",         P(_pretty(routing.get("routing")))],
        ["SLA",             P(f"{routing.get('sla_hours', '-')} hours")],
        ["Human Approval",  "REQUIRED" if requires_approval else "Auto-eligible"],
    ]
    approval_row = len(snap_rows) - 1
    snap_table = Table(snap_rows, colWidths=[CW * 0.38, CW * 0.62])
    snap_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C(_INDIGO_700)),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9.5),
        ("FONTSIZE",   (0, 1), (-1, -1), 9),
        ("BACKGROUND", (0, 1), (0, -1), C(_INDIGO_50)),
        ("FONTNAME",   (0, 1), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",  (0, 1), (0, -1), C(_INDIGO_700)),
        ("GRID",       (0, 0), (-1, -1), 0.4, C(_BORDER)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (1, approval_row), (1, approval_row),
         C(_RED) if requires_approval else C(_GREEN)),
        ("TEXTCOLOR",  (1, approval_row), (1, approval_row), colors.white),
        ("FONTNAME",   (1, approval_row), (1, approval_row), "Helvetica-Bold"),
    ]))
    story.append(snap_table)

    # ── Section 4: Adjuster Todo List ────────────────────────────────────────
    story.append(sp(6))
    story.append(section("4", "Adjuster Todo List"))
    story.append(Paragraph(
        "Work through each item below. Items marked 'Ready' still require independent verification. "
        "No decision should be communicated until all items are resolved.",
        body))
    story.append(sp(4))

    if not checklist:
        checklist = [
            {"item": "Confirm customer identity, policy number, and incident date.", "status": "needs_review"},
            {"item": "Verify coverage position against cited policy wording.",        "status": "needs_review"},
            {"item": "Review document authenticity and fraud signals.",               "status": "needs_review"},
            {"item": "Confirm medical necessity and specialist routing.",             "status": "needs_review"},
            {"item": "Record final decision in claims management system.",            "status": "required"},
        ]

    def checkbox(status):
        return {"ready": "[x]", "required": "[!]"}.get(status, "[ ]")

    def scolor(status):
        return {"ready": _GREEN, "needs_review": _AMBER, "required": _RED}.get(status, _INK)

    todo_rows = [["", "Action Item", "Status"]]
    status_cells = []  # (row_index, color)
    for item in checklist:
        st = str(item.get("status") or "needs_review") if isinstance(item, dict) else "needs_review"
        txt = str(item.get("item") or item) if isinstance(item, dict) else str(item)
        ri = len(todo_rows)
        todo_rows.append([
            Paragraph(checkbox(st), S(f"ck{ri}", fontSize=11, alignment=TA_CENTER,
                                      textColor=C(scolor(st)), fontName="Helvetica-Bold")),
            Paragraph(txt, S(f"ti{ri}", fontSize=9.5, textColor=C(_INK), leading=12)),
            Paragraph(_pretty(st), S(f"ts{ri}", fontSize=8.5, alignment=TA_CENTER,
                                     textColor=C(scolor(st)), fontName="Helvetica-Bold")),
        ])
        status_cells.append((ri, scolor(st)))
    for q in open_qs[:8]:
        q_text = str(q).strip()
        if not q_text:
            continue
        ri = len(todo_rows)
        todo_rows.append([
            Paragraph("[ ]", S(f"ckoq{ri}", fontSize=11, alignment=TA_CENTER,
                               textColor=C(_AMBER), fontName="Helvetica-Bold")),
            Paragraph(f"Resolve: {q_text}", S(f"tioq{ri}", fontSize=9.5, textColor=C(_INK), leading=12)),
            Paragraph("Open", S(f"tsoq{ri}", fontSize=8.5, alignment=TA_CENTER,
                                textColor=C(_AMBER), fontName="Helvetica-Bold")),
        ])
        status_cells.append((ri, _AMBER))
    todo_table = Table(todo_rows, colWidths=[11 * mm, None, 26 * mm])
    todo_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C(_INDIGO_700)),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9.5),
        ("ALIGN",      (0, 0), (0, -1), "CENTER"),
        ("ALIGN",      (2, 0), (2, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("GRID",       (0, 0), (-1, -1), 0.4, C(_BORDER)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C(_WHITE), C(_ROW_ALT)]),
    ]))
    story.append(todo_table)

    # ── Section 5: Coverage & Fraud Analysis ─────────────────────────────────
    story.append(sp(6))
    story.append(section("5", "Coverage & Fraud Analysis  (AI-Generated -- Verify Independently)"))

    cov_text    = _val(explanations.get("coverage") or cov_pos.get("summary"),
                       "Coverage reasoning not available.")
    fraud_text  = _val(explanations.get("fraud") or str(fraud_asmt.get("key_signals") or ""),
                       "Fraud analysis not available.")
    triage_text = _val(explanations.get("triage") or str(routing.get("approval_reasons") or ""),
                       "Routing explanation not available.")
    calc_text   = _val(explanations.get("payable_calculation"), "")
    med_text    = _val(explanations.get("medical"), "")

    cov_color  = _STATUS_COLOURS.get(cov_status, _AMBER)
    risk_color = _RISK_COLOURS.get(fraud_level, _GREEN)

    def av(text):
        return Paragraph(text, S(f"av{len(story)}_{hash(text)&0xfff}", fontSize=9.5,
                                 textColor=C(_INK), leading=14))

    def ah(text):
        return Paragraph(text, S(f"ah{len(story)}_{hash(text)&0xfff}", fontSize=9.5,
                                 fontName="Helvetica-Bold", textColor=C(_WHITE), alignment=TA_CENTER))

    analysis_rows = [
        [ah("Coverage"), av(cov_text)],
        [ah("Fraud"),    av(fraud_text)],
        [ah("Routing"),  av(triage_text)],
    ]
    label_colors = [cov_color, risk_color, _INDIGO_600]
    if calc_text:
        analysis_rows.append([ah("Payable"), av(calc_text)]); label_colors.append(_INDIGO_700)
    if med_text:
        analysis_rows.append([ah("Medical"), av(med_text)]);  label_colors.append(_VIOLET)

    analysis_table = Table(analysis_rows, colWidths=[26 * mm, None])
    a_ts = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.4, C(_BORDER)),
        ("BACKGROUND", (1, 0), (1, -1), C(_ROW_ALT)),
    ])
    for i, lc in enumerate(label_colors[:len(analysis_rows)]):
        a_ts.add("BACKGROUND", (0, i), (0, i), C(lc))
    analysis_table.setStyle(a_ts)
    story.append(analysis_table)

    if exclusions:
        story.append(sp(6))
        story.append(Paragraph("Policy Exclusions Identified",
                               S("eb", fontSize=9.5, fontName="Helvetica-Bold",
                                 textColor=C(_INK), spaceAfter=3)))
        story.append(accent_list([_pretty(ex) for ex in exclusions[:6]], accent=_RED, tint=_RED_T))

    if signals:
        story.append(sp(6))
        story.append(Paragraph("Fraud Risk Signals  (investigation triggers, not proof)",
                               S("sb", fontSize=9.5, fontName="Helvetica-Bold",
                                 textColor=C(_INK), spaceAfter=3)))
        sig_items = []
        for sig in signals[:6]:
            label = sig.get("description") if isinstance(sig, dict) else str(sig)
            sig_items.append(str(label))
        story.append(accent_list(sig_items, accent=_AMBER, tint=_AMBER_T))

    # ── Section 6: Suggested Next Steps ──────────────────────────────────────
    story.append(sp(6))
    story.append(section("6", "Suggested Next Steps"))
    if not next_steps:
        next_steps = [
            "Review all claim documents in this Drive folder.",
            "Confirm coverage and policy wording with the policy administration team.",
            "Record your decision in the claims management system.",
        ]
    story.append(accent_list([str(s) for s in next_steps[:10]], accent=_GREEN, tint=_GREEN_T))

    if role_views:
        story.append(sp(8))
        story.append(Paragraph("Role-Specific Guidance",
                               S("rvb", fontSize=9.5, fontName="Helvetica-Bold",
                                 textColor=C(_INK), spaceAfter=4)))
        for ri, (role, points) in enumerate(list(role_views.items())[:4]):
            story.append(Paragraph(_pretty(role),
                                   S(f"rh{ri}", fontSize=9.5, fontName="Helvetica-Bold",
                                     textColor=C(_INDIGO_700), spaceAfter=2, spaceBefore=3)))
            story.append(accent_list([str(pt) for pt in _as_list(points)[:3]],
                                     accent=_INDIGO_600, tint=_INDIGO_50,
                                     style=S(f"rp{ri}", fontSize=9, textColor=C(_INK), leading=12)))

    # ── Section 7: Decision Guardrails ───────────────────────────────────────
    story.append(sp(6))
    story.append(section("7", "Decision Guardrails"))
    story.append(Paragraph(
        "The ClaimIQ AI system has assisted with analysis. All final decisions remain with you, "
        "the authorized human adjuster.",
        body))
    story.append(sp(4))
    if not guardrails:
        guardrails = [
            "Copilot may recommend evidence to review, but final claim decisions remain with authorized humans.",
            "No denial should be communicated without cited policy wording and a human review.",
            "Fraud signals explain investigation triggers; they are not proof of fraud by themselves.",
        ]
    story.append(accent_list([str(g) for g in guardrails], accent=_RED, tint=_RED_T,
                             style=S("gr", fontSize=9, textColor=C(_RED), leading=12,
                                     fontName="Helvetica-Bold")))

    # ── Build with running header/footer ──────────────────────────────────────
    def _decorate(canvas, d):
        canvas.saveState()
        pw, ph = d.pagesize
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(C(_INDIGO_700))
        canvas.drawString(MARGIN, ph - 12 * mm, "ClaimIQ  |  Adjuster Guide")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(C(_GRAY))
        canvas.drawRightString(pw - MARGIN, ph - 12 * mm, claim_id)
        canvas.setStrokeColor(C(_VIOLET)); canvas.setLineWidth(1.0)
        canvas.line(MARGIN, ph - 13.5 * mm, pw - MARGIN, ph - 13.5 * mm)

        canvas.setStrokeColor(C(_BORDER)); canvas.setLineWidth(0.4)
        canvas.line(MARGIN, 12 * mm, pw - MARGIN, 12 * mm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(C(_GRAY))
        canvas.drawString(MARGIN, 9 * mm, f"Confidential - Internal Use Only   |   Generated {generated_at}")
        canvas.drawRightString(pw - MARGIN, 9 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    pdf_bytes = buf.getvalue()
    log.info("[AdjusterGuide] PDF generated for %s -- %d bytes", claim_id, len(pdf_bytes))
    return pdf_bytes
