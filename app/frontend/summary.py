"""Final analysis tab rendering."""

import html as html_mod
import re

import streamlit as st

from frontend.config import AGENT_COLORS, AGENTS
from frontend.utils import segment_stdout

def render_final_summary(entry: dict) -> None:
    summary  = entry.get("summary", {})
    stdout   = entry.get("stdout", "")
    status   = entry.get("status", "")
    duration = entry.get("duration_sec", 0)
    ts       = entry.get("time", "")

    if not summary and not stdout:
        st.markdown(
            '<div class="no-run"><div class="no-run-icon">📊</div>'
            '<div class="no-run-title">No analysis yet</div>'
            '<div class="no-run-sub">Complete a pipeline run to see the final analysis</div></div>',
            unsafe_allow_html=True,
        )
        return

    # "0 unread emails" run — nothing to display
    if not summary.get("claim_id") and not summary.get("claimant"):
        st.markdown(
            '<div class="no-run"><div class="no-run-icon">📭</div>'
            '<div class="no-run-title">No claims this run</div>'
            '<div class="no-run-sub">Inbox was empty — no claims to analyse</div></div>',
            unsafe_allow_html=True,
        )
        return

    claim_id    = summary.get("claim_id", "—")
    claimant    = summary.get("claimant", "Unknown")
    claim_type  = summary.get("claim_type", "Insurance").upper()
    amount      = summary.get("amount", "—")
    fraud       = summary.get("fraud", "")
    priority    = summary.get("priority", "")
    routing     = summary.get("routing", "")
    decision    = summary.get("decision", "")
    attachments = summary.get("attachments", "")
    doc_risks   = summary.get("doc_risks", "")
    form_url    = summary.get("approval_url", "")
    drive_url   = summary.get("drive_url", "")

    # Parse fraud score number
    fraud_num = 0.0
    fm = re.search(r'(\d+(?:\.\d+)?)\s*/\s*100', fraud)
    if fm:
        try: fraud_num = float(fm.group(1))
        except: pass

    # ── Claim hero ────────────────────────────────────────────
    st.markdown(f"""
    <div class="fs-hero">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;
                  flex-wrap:wrap;gap:20px;position:relative;">
        <div>
          <div class="fs-claim-id">Claim ID · {html_mod.escape(claim_id)}</div>
          <div class="fs-claimant">{html_mod.escape(claimant)}</div>
          <div style="margin-top:10px;">
            <span class="fs-type-pill">🏷 {html_mod.escape(claim_type)}</span>
            <span style="font-size:12px;color:#6b7280;margin-left:14px;">
              🕐 {html_mod.escape(ts)} &nbsp;·&nbsp; ⏱ {duration}s
            </span>
          </div>
        </div>
        <div style="text-align:right;">
          <div class="fs-amount-lbl">Claimed Amount</div>
          <div class="fs-amount">{html_mod.escape(str(amount))}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Quick stats row ───────────────────────────────────────
    stat_items = []
    if attachments: stat_items.append(("📎 Attachments", attachments, "files processed"))
    if doc_risks:   stat_items.append(("⚠️ Risk Signals", doc_risks, "from docs"))
    if fraud:       stat_items.append(("🚨 Fraud Score", fraud.split("(")[0].strip(), ""))
    if priority:    stat_items.append(("⚡ Priority", priority.split("[")[0].strip(), routing or ""))

    if stat_items:
        cards_html = "".join(
            f'<div class="stat-card">'
            f'<div class="stat-lbl">{html_mod.escape(lbl)}</div>'
            f'<div class="stat-val">{html_mod.escape(str(val))}</div>'
            f'<div class="stat-sub">{html_mod.escape(str(sub))}</div>'
            f'</div>'
            for lbl, val, sub in stat_items
        )
        st.markdown(f'<div class="stat-grid">{cards_html}</div>', unsafe_allow_html=True)

    # ── Decision banner ───────────────────────────────────────
    if decision == "HUMAN APPROVAL REQUIRED":
        st.markdown("""
        <div class="decision-banner human">
          <div class="decision-icon">⚠️</div>
          <div>
            <div class="decision-title">Human Approval Required</div>
            <div class="decision-desc">
              One or more agents detected signals that require manual adjuster review.
              Use the approval form below to action this claim.
            </div>
          </div>
        </div>""", unsafe_allow_html=True)
    elif decision == "AUTO-ELIGIBLE":
        st.markdown("""
        <div class="decision-banner auto">
          <div class="decision-icon">✅</div>
          <div>
            <div class="decision-title">Auto-Eligible for Processing</div>
            <div class="decision-desc">
              All agents cleared this claim. No anomalies detected — eligible for straight-through processing.
            </div>
          </div>
        </div>""", unsafe_allow_html=True)

    # ── Action links ──────────────────────────────────────────
    link_cols = []
    if form_url:
        link_cols.append(
            f'<a class="link-btn link-btn-form" href="{html_mod.escape(form_url)}" '
            f'target="_blank" rel="noopener">📋 Approval Form ↗</a>'
        )
    if drive_url:
        link_cols.append(
            f'<a class="link-btn link-btn-drive" href="{html_mod.escape(drive_url)}" '
            f'target="_blank" rel="noopener">📁 View Documents on Drive ↗</a>'
        )
    if link_cols:
        st.markdown(
            f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px;">'
            + "".join(link_cols) + "</div>",
            unsafe_allow_html=True,
        )

    # ── Verdict cards row ─────────────────────────────────────
    fraud_color = "#f87171" if fraud_num > 60 else "#facc15" if fraud_num > 30 else "#4ade80"
    fraud_risk  = "HIGH RISK" if fraud_num > 60 else "MEDIUM" if fraud_num > 30 else "LOW RISK"
    pri_color   = {"critical":"#f87171","high":"#facc15","medium":"#60a5fa","low":"#4ade80"}.get(
        next(iter((priority or "").lower().split()), ""), "#9f98b8")

    st.markdown(f"""
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px;">
      <div class="verdict-card">
        <div class="vc-title">🚨 Fraud Score</div>
        <div class="vc-score" style="color:{fraud_color};">{html_mod.escape(fraud.split("(")[0].strip()) if fraud else "—"}</div>
        <div class="vc-label">{fraud_risk if fraud_num else "Not assessed"}</div>
        <div class="vc-bar-bg">
          <div class="vc-bar-fill" style="width:{min(fraud_num,100):.0f}%;
               background:{fraud_color};box-shadow:0 0 10px {fraud_color}66;"></div>
        </div>
      </div>
      <div class="verdict-card">
        <div class="vc-title">⚡ Priority &amp; Routing</div>
        <div class="vc-score" style="color:{pri_color};font-size:26px;">
          {html_mod.escape(priority.split("[")[0].strip().upper()) if priority else "—"}
        </div>
        <div class="vc-label">{html_mod.escape(routing) if routing else "Routing not assigned"}</div>
      </div>
      <div class="verdict-card">
        <div class="vc-title">🔄 Pipeline Result</div>
        <div class="vc-score" style="font-size:24px;color:{'#4ade80' if status=='success' else '#f87171' if status=='failed' else '#facc15'};">
          {'✓ Success' if status=='success' else '✗ Failed' if status=='failed' else status.upper() if status else '—'}
        </div>
        <div class="vc-label">{duration}s · {entry.get('mode','manual').upper()} run</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Per-agent verdict rows ────────────────────────────────
    st.markdown(
        '<div class="sec-header" style="margin-top:8px;">'
        '<span>🤖</span> Agent Verdicts'
        '<div class="sec-header-line"></div></div>',
        unsafe_allow_html=True,
    )

    segs = segment_stdout(stdout)

    agent_rows = [
        {
            "topic": "Claim Intake",
            "summary": (
                f"Parsed claim for {claimant}. "
                f"Identified as {claim_type} claim for {amount}."
                if claimant != "Unknown" else "Intake analysis in progress."
            ),
            "chips": [
                ("avc-b", claim_type)    if claim_type else None,
                ("avc-g", amount)        if amount else None,
                ("avc-b", attachments)   if attachments else None,
            ],
        },
        {
            "topic": "Coverage Assessment",
            "summary": _best_line(segs.get(1, []),
                ["coverage", "covered", "exclusion", "deductible", "needs_review"],
                "Coverage terms verified against policy."),
            "chips": [
                ("avc-g", "✓ Coverage Verified") if segs.get(1) else ("avc-p", "No data"),
            ],
        },
        {
            "topic": "Fraud Detection",
            "summary": (
                f"Fraud risk assessed at {fraud}."
                if fraud else
                _best_line(segs.get(2, []), ["fraud", "risk", "score", "signal"], "Fraud check complete.")
            ),
            "chips": [
                (("avc-r" if fraud_num > 60 else "avc-y" if fraud_num > 30 else "avc-g"),
                 f"Score: {fraud}") if fraud else None,
            ],
        },
        {
            "topic": "Triage & Routing",
            "summary": (
                f"Priority set to {priority.split('[')[0].strip().upper()}, "
                f"routing: {routing}."
                if priority else
                _best_line(segs.get(3, []), ["priority", "routing", "triage", "sla"], "Triage complete.")
            ),
            "chips": [
                (("avc-r" if "critical" in (priority or "").lower() else
                  "avc-y" if "high" in (priority or "").lower() else "avc-b"),
                 priority.split("[")[0].strip().upper()) if priority else None,
                ("avc-b", routing) if routing else None,
            ],
        },
        {
            "topic": "Orchestrator Decision",
            "summary": (
                f"Final decision: {decision}. "
                + (f"PDF report generated. " if "pdf" in stdout.lower() else "")
                + (f"Claim uploaded to Drive. " if drive_url else "")
                + (f"{doc_risks} document risk signals flagged." if doc_risks else "")
            ),
            "chips": [
                ("avc-r", "⚠ Human Review") if decision == "HUMAN APPROVAL REQUIRED"
                else ("avc-g", "✓ Auto-Eligible") if decision == "AUTO-ELIGIBLE"
                else None,
                ("avc-b", f"{attachments} attached") if attachments else None,
            ],
        },
    ]

    for meta, (icon, name, _) in zip(agent_rows, AGENTS):
        color = AGENT_COLORS[AGENTS.index((icon, name, _))]
        chips_html = "".join(
            f'<span class="avc {cls}">{html_mod.escape(str(lbl))}</span>'
            for cls, lbl in [c for c in meta["chips"] if c and c[1]]
        )
        st.markdown(f"""
        <div class="av-row">
          <div class="av-icon">{icon}</div>
          <div style="flex:1;">
            <div class="av-name" style="color:{color};">{name} — {meta['topic']}</div>
            <div class="av-text">{html_mod.escape(meta['summary'])}</div>
            <div class="av-chips">{chips_html}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

def _best_line(lines: list[str], keywords: list[str], fallback: str) -> str:
    """Return the most relevant line from a list, or fallback."""
    for l in reversed(lines):
        if any(k in l.lower() for k in keywords):
            return l
    return lines[-1] if lines else fallback
