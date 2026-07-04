"""
ClaimIQ — Adjuster Guide PDF Generator
Generates a per-claim instruction PDF for the human adjuster uploaded to Drive.
"""
from __future__ import annotations
import io, logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("claimiq.adjuster_guide")

_BRAND_BLUE = (0.11, 0.33, 0.60)
_BRAND_TEAL = (0.06, 0.62, 0.62)
_GREEN      = (0.10, 0.62, 0.29)
_AMBER      = (0.85, 0.55, 0.05)
_RED        = (0.78, 0.14, 0.14)
_LIGHT_GREY = (0.94, 0.94, 0.96)
_MID_GREY   = (0.55, 0.55, 0.60)
_WHITE      = (1.0,  1.0,  1.0)
_BLACK      = (0.10, 0.10, 0.12)

_TRIAGE_COLOURS = {"green": _GREEN, "amber": _AMBER, "yellow": _AMBER, "orange": _AMBER, "red": _RED}
_STATUS_COLOURS = {"covered": _GREEN, "needs_review": _AMBER, "not_covered": _RED}
_RISK_COLOURS   = {"low": _GREEN, "medium": _AMBER, "high": _RED, "critical": _RED}


def generate_adjuster_guide_pdf(
    claim_id: str,
    copilot: dict,
    intake: dict | None = None,
) -> bytes | None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
    except ImportError:
        log.warning("[AdjusterGuide] reportlab not installed")
        return None

    # ── Defensive guards ──────────────────────────────────────────────────────
    if not isinstance(copilot, dict):
        copilot = {}
    if not isinstance(intake, dict):
        intake = {}

    # Deep-sanitize LLM text: characters outside cp1252 (non-breaking hyphens,
    # emoji, ₹ …) render as ■ in Helvetica.
    try:
        from claimiq.shared.pdf_text import sanitize_deep
        copilot = sanitize_deep(copilot)
        intake = sanitize_deep(intake)
    except ImportError:
        log.warning("[AdjusterGuide] pdf_text sanitizer unavailable — non-latin glyphs may render as boxes")

    def _as_dict(v: Any) -> dict:
        return v if isinstance(v, dict) else {}

    def _as_list(v: Any) -> list:
        return v if isinstance(v, list) else []

    def _val(v, default="—"):
        if v in (None, "", [], {}):
            return default
        return str(v)

    def _money(v, currency="INR"):
        try:
            return f"{currency} {float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v) if v else "—"

    # ── Style helpers ─────────────────────────────────────────────────────────
    base = getSampleStyleSheet()

    def S(name, **kw):
        return ParagraphStyle(f"ag_{claim_id[:8]}_{name}", parent=base["Normal"], **kw)

    def hr(color=_BRAND_TEAL, t=0.8):
        return HRFlowable(width="100%", thickness=t, color=colors.Color(*color), spaceAfter=6, spaceBefore=2)

    def sp(h=4):
        return Spacer(1, h)

    def C(*rgb):
        return colors.Color(*rgb)

    def section(title, story):
        story.append(sp(6))
        story.append(Paragraph(title, S("sh", fontSize=13, textColor=C(*_BRAND_BLUE),
                                        spaceBefore=4, spaceAfter=4, fontName="Helvetica-Bold")))
        story.append(hr())

    # ── Pull data ─────────────────────────────────────────────────────────────
    generated_at  = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    triage_color  = str(copilot.get("triage_color") or "amber").lower()
    triage_rgb    = _TRIAGE_COLOURS.get(triage_color, _AMBER)
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

    # ── Build PDF ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 18 * mm
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=MARGIN,
                            title=f"ClaimIQ Adjuster Guide — {claim_id}",
                            author="ClaimIQ AI System")
    story = []

    # Cover banner
    banner_data = [[
        Paragraph("ClaimIQ", S("b1", fontSize=26, fontName="Helvetica-Bold",
                               textColor=C(*_WHITE), alignment=TA_CENTER)),
        Paragraph("Adjuster Guide", S("b2", fontSize=13, textColor=C(*_WHITE),
                                      alignment=TA_CENTER)),
    ]]
    banner = Table(banner_data, colWidths=["50%", "50%"])
    banner.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C(*_BRAND_BLUE)),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (-1, -1), 16),
    ]))
    story.append(banner)
    story.append(sp(8))
    story.append(Paragraph(f"Claim Reference: {claim_id}",
                           S("ct", fontSize=20, textColor=C(*_BRAND_BLUE),
                             spaceAfter=4, fontName="Helvetica-Bold", alignment=TA_CENTER)))
    story.append(Paragraph("Human Adjuster Action File",
                           S("cs", fontSize=11, textColor=C(*_BRAND_TEAL),
                             spaceAfter=2, alignment=TA_CENTER)))
    story.append(Paragraph(f"Generated: {generated_at}  |  Confidential — Internal Use Only",
                           S("cm", fontSize=9, textColor=C(*_MID_GREY), alignment=TA_CENTER)))
    story.append(sp(6))

    # Triage badge
    badge = Table([[Paragraph(f"Triage Status: {triage_color.upper()}",
                              S("tb", fontSize=11, fontName="Helvetica-Bold",
                                textColor=C(*_WHITE), alignment=TA_CENTER))]],
                  colWidths=["100%"])
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C(*triage_rgb)),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(badge)
    story.append(sp(10))

    # ── Section 1: Executive Summary ─────────────────────────────────────────
    section("1. Executive Summary", story)
    story.append(Paragraph(exec_summary,
                           S("bd", fontSize=9.5, textColor=C(*_BLACK), spaceAfter=4, leading=14)))

    # ── Section 2: How to Use This Drive Folder ──────────────────────────────
    section("2. How to Use This Drive Folder", story)
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
                                   textColor=C(*_WHITE), alignment=TA_CENTER)),
        Paragraph(title, S(f"it{i}", fontSize=9.5, fontName="Helvetica-Bold",
                           textColor=C(*_BRAND_BLUE))),
        Paragraph(desc, S(f"id{i}", fontSize=9, textColor=C(*_BLACK))),
    ] for i, (title, desc) in enumerate(instructions)]
    inst_table = Table(inst_rows, colWidths=[14*mm, 55*mm, None])
    inst_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, -1), C(*_BRAND_TEAL)),
        ("BACKGROUND",    (1, 0), (-1, 0), C(*_LIGHT_GREY)),
        ("BACKGROUND",    (1, 2), (-1, 2), C(*_LIGHT_GREY)),
        ("BACKGROUND",    (1, 4), (-1, 4), C(*_LIGHT_GREY)),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("GRID",          (0, 0), (-1, -1), 0.4, C(0.85, 0.85, 0.88)),
    ]))
    story.append(inst_table)

    # ── Section 3: Claim Snapshot ─────────────────────────────────────────────
    section("3. Claim Snapshot", story)
    cov_status = str(cov_pos.get("status") or "needs_review")
    fraud_score = fraud_asmt.get("score", 0)
    fraud_level = str(fraud_asmt.get("risk_level") or "low")
    requires_approval = routing.get("requires_human_approval", True)

    snap_rows = [
        ["Field", "Value"],
        ["Claimant",       _val(claim_details.get("claimant_name") or intake.get("claimant_name"))],
        ["Policy Number",  _val(claim_details.get("policy_number") or intake.get("policy_number"))],
        ["Claim Type",     _val(claim_details.get("claim_type")    or intake.get("claim_type"))],
        ["Diagnosis/Procedure", _val(claim_details.get("procedure") or intake.get("procedure"))],
        ["Incident Date",  _val(claim_details.get("incident_date") or intake.get("incident_date"))],
        ["Claim Amount",   _money(claim_details.get("claim_amount") or intake.get("claim_amount"),
                                  str(claim_details.get("currency") or "INR"))],
        ["Coverage Status", cov_status],
        ["Fraud Score",    f"{fraud_score}/100  ({fraud_level})"],
        ["Priority",       _val(routing.get("priority"))],
        ["Routing",        _val(routing.get("routing"))],
        ["SLA",            f"{routing.get('sla_hours', '—')} hours"],
        ["Human Approval", "REQUIRED" if requires_approval else "Auto-eligible"],
    ]
    approval_row = len(snap_rows) - 1
    snap_ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C(*_BRAND_BLUE)),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9.5),
        ("FONTSIZE",   (0, 1), (-1, -1), 9),
        ("BACKGROUND", (0, 1), (0, -1), C(*_LIGHT_GREY)),
        ("FONTNAME",   (0, 1), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR",  (0, 1), (0, -1), C(*_BRAND_BLUE)),
        ("GRID",       (0, 0), (-1, -1), 0.4, C(0.85, 0.85, 0.88)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (1, approval_row), (1, approval_row),
         C(*_RED) if requires_approval else C(*_GREEN)),
        ("TEXTCOLOR",  (1, approval_row), (1, approval_row), colors.white),
        ("FONTNAME",   (1, approval_row), (1, approval_row), "Helvetica-Bold"),
    ])
    snap_table = Table(snap_rows, colWidths=["38%", "62%"])
    snap_table.setStyle(snap_ts)
    story.append(snap_table)

    # ── Section 4: Adjuster Todo List ────────────────────────────────────────
    section("4. Adjuster Todo List", story)
    story.append(Paragraph(
        "Work through each item below. Items marked 'ready' still require independent verification. "
        "No decision should be communicated until all items are resolved.",
        S("bd4", fontSize=9.5, textColor=C(*_BLACK), spaceAfter=4, leading=14)))
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
        # cp1252-safe markers (☑/★/☐ render as ■ in Helvetica)
        return {"ready": "[x]", "required": "[!]"}.get(status, "[ ]")

    def scolor(status):
        return {"ready": C(*_GREEN), "needs_review": C(*_AMBER), "required": C(*_RED)}.get(
            status, C(*_BLACK))

    todo_rows = [["", "Action Item", "Status"]]
    for item in checklist:
        st = str(item.get("status") or "needs_review") if isinstance(item, dict) else "needs_review"
        txt = str(item.get("item") or item) if isinstance(item, dict) else str(item)
        todo_rows.append([
            Paragraph(checkbox(st), S(f"ck{len(todo_rows)}", fontSize=12,
                                      alignment=TA_CENTER, textColor=scolor(st))),
            Paragraph(txt, S(f"ti{len(todo_rows)}", fontSize=9.5, textColor=C(*_BLACK))),
            Paragraph(st.replace("_", " ").title(),
                      S(f"ts{len(todo_rows)}", fontSize=8.5, alignment=TA_CENTER,
                        textColor=scolor(st), fontName="Helvetica-Bold")),
        ])
    for q in open_qs[:8]:
        q_text = str(q).replace("_", " ").strip()
        if not q_text:
            continue
        todo_rows.append([
            Paragraph("[ ]", S(f"ckoq{len(todo_rows)}", fontSize=12,
                             alignment=TA_CENTER, textColor=C(*_AMBER))),
            Paragraph(f"Resolve: {q_text}",
                      S(f"tioq{len(todo_rows)}", fontSize=9.5, textColor=C(*_BLACK))),
            Paragraph("Open", S(f"tsoq{len(todo_rows)}", fontSize=8.5,
                                alignment=TA_CENTER, textColor=C(*_AMBER),
                                fontName="Helvetica-Bold")),
        ])
    todo_table = Table(todo_rows, colWidths=[10*mm, None, 28*mm])
    todo_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), C(*_BRAND_BLUE)),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9.5),
        ("ALIGN",         (0, 0), (0, -1), "CENTER"),
        ("ALIGN",         (2, 0), (2, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.4, C(0.85, 0.85, 0.88)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C(*_WHITE), C(*_LIGHT_GREY)]),
    ]))
    story.append(todo_table)

    # ── Section 5: Coverage & Fraud Analysis ─────────────────────────────────
    section("5. Coverage & Fraud Analysis (AI-Generated — Verify Independently)", story)

    cov_text   = _val(explanations.get("coverage")  or cov_pos.get("summary"),
                      "Coverage reasoning not available.")
    fraud_text = _val(explanations.get("fraud")     or str(fraud_asmt.get("key_signals") or ""),
                      "Fraud analysis not available.")
    triage_text= _val(explanations.get("triage")    or str(routing.get("approval_reasons") or ""),
                      "Routing explanation not available.")
    calc_text  = _val(explanations.get("payable_calculation"), "")
    med_text   = _val(explanations.get("medical"), "")

    cov_color  = _STATUS_COLOURS.get(cov_status, _AMBER)
    risk_color = _RISK_COLOURS.get(fraud_level, _GREEN)

    analysis_rows = [
        [Paragraph("Coverage",  S("ah1", fontSize=9.5, fontName="Helvetica-Bold",
                                   textColor=C(*_WHITE), alignment=TA_CENTER)),
         Paragraph(cov_text,   S("av1", fontSize=9.5, textColor=C(*_BLACK), leading=14))],
        [Paragraph("Fraud",     S("ah2", fontSize=9.5, fontName="Helvetica-Bold",
                                   textColor=C(*_WHITE), alignment=TA_CENTER)),
         Paragraph(fraud_text, S("av2", fontSize=9.5, textColor=C(*_BLACK), leading=14))],
        [Paragraph("Routing",   S("ah3", fontSize=9.5, fontName="Helvetica-Bold",
                                   textColor=C(*_WHITE), alignment=TA_CENTER)),
         Paragraph(triage_text,S("av3", fontSize=9.5, textColor=C(*_BLACK), leading=14))],
    ]
    if calc_text:
        analysis_rows.append([
            Paragraph("Payable", S("ah4", fontSize=9.5, fontName="Helvetica-Bold",
                                   textColor=C(*_WHITE), alignment=TA_CENTER)),
            Paragraph(calc_text, S("av4", fontSize=9.5, textColor=C(*_BLACK), leading=14)),
        ])
    if med_text:
        analysis_rows.append([
            Paragraph("Medical", S("ah5", fontSize=9.5, fontName="Helvetica-Bold",
                                   textColor=C(*_WHITE), alignment=TA_CENTER)),
            Paragraph(med_text,  S("av5", fontSize=9.5, textColor=C(*_BLACK), leading=14)),
        ])

    label_colors = [cov_color, risk_color, _BRAND_TEAL, _BRAND_TEAL, _BRAND_BLUE]
    analysis_ts = TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
        ("GRID",          (0, 0), (-1, -1), 0.4, C(0.85, 0.85, 0.88)),
        ("ALIGN",         (0, 0), (0, -1), "CENTER"),
    ])
    for i, lc in enumerate(label_colors[:len(analysis_rows)]):
        analysis_ts.add("BACKGROUND", (0, i), (0, i), C(*lc))
    analysis_table = Table(analysis_rows, colWidths=[28*mm, None])
    analysis_table.setStyle(analysis_ts)
    story.append(analysis_table)

    if exclusions:
        story.append(sp(6))
        story.append(Paragraph("Policy Exclusions Identified:",
                               S("eb", fontSize=9.5, fontName="Helvetica-Bold",
                                 textColor=C(*_BLACK), spaceAfter=3)))
        for ex in exclusions[:6]:
            story.append(Paragraph(str(ex),
                                   S(f"ex{exclusions.index(ex)}", fontSize=9.5,
                                     textColor=C(*_BLACK), leftIndent=12,
                                     spaceAfter=3, leading=14, bulletText="•", bulletIndent=4)))

    if signals:
        story.append(sp(6))
        story.append(Paragraph("Fraud Risk Signals (investigation triggers, not proof):",
                               S("sb", fontSize=9.5, fontName="Helvetica-Bold",
                                 textColor=C(*_BLACK), spaceAfter=3)))
        for sig in signals[:6]:
            label = sig.get("description") if isinstance(sig, dict) else str(sig)
            story.append(Paragraph(str(label),
                                   S(f"sig{signals.index(sig)}", fontSize=9.5,
                                     textColor=C(*_BLACK), leftIndent=12,
                                     spaceAfter=3, leading=14, bulletText="•", bulletIndent=4)))

    # ── Section 6: Suggested Next Steps ──────────────────────────────────────
    section("6. Suggested Next Steps", story)
    if not next_steps:
        next_steps = [
            "Review all claim documents in this Drive folder.",
            "Confirm coverage and policy wording with the policy administration team.",
            "Record your decision in the claims management system.",
        ]
    for i, step in enumerate(next_steps[:10]):
        story.append(Paragraph(str(step),
                               S(f"ns{i}", fontSize=9.5, textColor=C(*_BLACK),
                                 leftIndent=12, spaceAfter=3, leading=14,
                                 bulletText="•", bulletIndent=4)))

    if role_views:
        story.append(sp(6))
        story.append(Paragraph("Role-Specific Guidance:",
                               S("rvb", fontSize=9.5, fontName="Helvetica-Bold",
                                 textColor=C(*_BLACK), spaceAfter=3)))
        for ri, (role, points) in enumerate(list(role_views.items())[:4]):
            story.append(Paragraph(role.replace("_", " ").title() + ":",
                                   S(f"rh{ri}", fontSize=9.5, fontName="Helvetica-Bold",
                                     textColor=C(*_BRAND_BLUE), spaceAfter=2)))
            for pi, pt in enumerate((_as_list(points))[:3]):
                story.append(Paragraph(str(pt),
                                       S(f"rp{ri}{pi}", fontSize=9, textColor=C(*_BLACK),
                                         leftIndent=12, spaceAfter=2, leading=13,
                                         bulletText="•", bulletIndent=4)))

    # ── Section 7: Decision Guardrails ────────────────────────────────────────
    section("7. Decision Guardrails", story)
    story.append(Paragraph(
        "The ClaimIQ AI system has assisted with analysis. "
        "All final decisions remain with you, the authorized human adjuster.",
        S("gbi", fontSize=9.5, textColor=C(*_BLACK), spaceAfter=4, leading=14)))
    story.append(sp(4))
    if not guardrails:
        guardrails = [
            "Copilot may recommend evidence to review, but final claim decisions remain with authorized humans.",
            "No denial should be communicated without cited policy wording and a human review.",
            "Fraud signals explain investigation triggers; they are not proof of fraud by themselves.",
        ]
    for gi, g in enumerate(guardrails):
        story.append(Paragraph(str(g),
                               S(f"gr{gi}", fontSize=9, textColor=C(*_RED),
                                 leftIndent=12, spaceAfter=3, leading=13,
                                 bulletText="!", bulletIndent=4)))

    story.append(sp(8))
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=C(*_MID_GREY), spaceAfter=4, spaceBefore=2))
    story.append(Paragraph(
        f"ClaimIQ Adjuster Guide  |  {claim_id}  |  Generated {generated_at}  |  Confidential",
        S("ft", fontSize=7.5, textColor=C(*_MID_GREY), alignment=TA_CENTER)))

    doc.build(story)
    pdf_bytes = buf.getvalue()
    log.info("[AdjusterGuide] PDF generated for %s — %d bytes", claim_id, len(pdf_bytes))
    return pdf_bytes
