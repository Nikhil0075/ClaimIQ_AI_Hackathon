"""Explainability timeline parsing and rendering."""

import html as html_mod
import json
import re
from typing import Any

import streamlit as st

from frontend.config import AGENT_COLORS
from frontend.utils import _ansi, _ts_from_line

_NODE_CFG = {
    "orchestrator": {"color": "#a142f4", "bg": "rgba(161,66,244,.1)",  "border": "rgba(161,66,244,.35)", "label": "ORCHESTRATOR"},
    "agent":        {"color": "#60a5fa", "bg": "rgba(96,165,250,.08)", "border": "rgba(96,165,250,.3)",  "label": "AGENT"},
    "tool":         {"color": "#34d399", "bg": "rgba(52,211,153,.07)", "border": "rgba(52,211,153,.3)",  "label": "TOOL"},
    "storage":      {"color": "#facc15", "bg": "rgba(250,204,21,.07)", "border": "rgba(250,204,21,.3)",  "label": "STORAGE"},
}

def _node(evts: list, type_: str, icon: str, name: str, ts: str,
          label: str, action: str, outputs: list,
          color_override: str = "") -> None:
    """Append one timeline event dict to evts."""
    evts.append({
        "type": type_, "icon": icon, "name": name, "ts": ts,
        "label": label, "action": action,
        "outputs": [(k, v) for k, v in outputs if v],
        "color": color_override,
    })

def parse_execution_timeline(stdout: str, summary: dict) -> list[dict]:
    """
    Walk the stdout line-by-line and emit structured timeline events.
    Ordering follows EmailTool stage markers as the primary boundaries.
    """
    lines = [_ansi(l).strip() for l in stdout.splitlines() if l.strip()]
    evts: list[dict] = []

    att_files:    list[str] = []
    att_analyzed: list[str] = []
    bq_rows:      list[str] = []
    copilot_done              = False
    intake_added              = False

    for line in lines:
        ll  = line.lower()
        ts  = _ts_from_line(line) or ""

        # ── Email polling ─────────────────────────────────────
        m = re.search(r'found (\d+) unread email', ll)
        if m:
            n = int(m.group(1))
            _node(evts, "orchestrator", "🧠", "Orchestrator", ts,
                  "ORCHESTRATOR",
                  f"Polled Gmail inbox — found {n} unread email(s)",
                  [("Result", "No emails — idle" if n == 0 else f"{n} claim(s) queued for processing")])
            continue

        # ── New claim received ────────────────────────────────
        m = re.search(r'new claim from:\s*(.+)', ll)
        if m:
            _node(evts, "orchestrator", "🧠", "Orchestrator", ts,
                  "ORCHESTRATOR",
                  f"Received new claim from {m.group(1).strip()}",
                  [("Next step", "Mail guard validation → claim intake")])
            continue

        # ── Mail guard ────────────────────────────────────────
        if "[1/6] checking" in ll:
            _node(evts, "tool", "🛡️", "Mail Guard", ts,
                  "TOOL",
                  "Validated email format and claim completeness",
                  [("Result", "Valid claim email — proceeding to pipeline")])
            continue

        # ── EmailTool: claim_received → also emit Intake Agent ─
        m = re.search(r'\[emailtool\] stage=claim_received.*?claim=(\S+).*?sent=(\w+)', ll)
        if m and not intake_added:
            intake_added = True
            _node(evts, "tool", "📧", "Email Tool", ts,
                  "TOOL · claim_received",
                  "Sent acknowledgement email to claimant",
                  [("Claim ID", m.group(1)), ("Delivered", m.group(2))])
            # Intake agent synthesised from summary (no explicit log line)
            _node(evts, "agent", "🔍", "Intake Agent", ts,
                  "AGENT",
                  "Parsed claim email — extracted claimant identity, policy reference, incident details, and claimed amount",
                  [
                      ("Claim ID",  summary.get("claim_id",  "")),
                      ("Claimant",  summary.get("claimant",  "")),
                      ("Type",      summary.get("claim_type","")),
                      ("Amount",    summary.get("amount",    "")),
                      ("Sent to orchestrator", "Structured intake JSON"),
                  ],
                  color_override=AGENT_COLORS[0])
            continue

        # ── Attachment extraction (accumulate, emit on synthesis) ──
        m = re.search(r'\[attachments\] extracted:\s*(.+?)\s*\(', line, re.I)
        if m:
            att_files.append(m.group(1).strip())

        m = re.search(r'\[attachments\] analyzed:\s*(.+?)\s*\|', line, re.I)
        if m:
            att_analyzed.append(m.group(1).strip())

        m = re.search(r'synthesis complete.*?risk_signals=(\d+)', ll)
        if m:
            n_risk = m.group(1)
            _node(evts, "tool", "📎", "Attachments Tool", ts,
                  "TOOL",
                  f"Extracted {len(att_files)} document(s) and ran OpenAI analysis on each",
                  (
                      [("Extracted", f) for f in att_files[:5]]
                      + [("Analyzed", a) for a in att_analyzed[:5]]
                      + [("Risk Signals", f"{n_risk} signals detected across all documents")]
                  ))
            continue

        # ── Coverage Agent ────────────────────────────────────
        m = re.search(r'\[emailtool\] stage=coverage_needs_review.*?claim=(\S+).*?sent=(\w+)', ll)
        if m:
            _node(evts, "agent", "📋", "Coverage Agent", ts,
                  "AGENT",
                  "Verified policy coverage, deductibles, applicable exclusions, and benefit limits against the claim",
                  [
                      ("Policy checked", summary.get("claim_id", m.group(1))),
                      ("Stage emitted",  "coverage_needs_review"),
                      ("Adjuster email", f"Sent ✓ → {m.group(2)}"),
                      ("Passed to",      "Fraud Agent"),
                  ],
                  color_override=AGENT_COLORS[1])
            _node(evts, "tool", "📧", "Email Tool", ts,
                  "TOOL · coverage_needs_review",
                  "Notified adjuster of coverage review requirement",
                  [("Claim ID", m.group(1)), ("Delivered", m.group(2))])
            continue

        # ── Fraud Agent ───────────────────────────────────────
        m = re.search(r'\[emailtool\] stage=fraud_alert.*?claim=(\S+).*?sent=(\w+)', ll)
        if m:
            _node(evts, "agent", "🚨", "Fraud Agent", ts,
                  "AGENT",
                  "Ran anomaly detection against historical claim patterns, flagged duplicate signals and risk indicators",
                  [
                      ("Fraud Score",      summary.get("fraud", "")),
                      ("Doc Risk Signals", summary.get("doc_risks", "")),
                      ("Stage emitted",    "fraud_alert"),
                      ("Passed to",        "Triage / Priority Agent"),
                  ],
                  color_override=AGENT_COLORS[2])
            _node(evts, "tool", "📧", "Email Tool", ts,
                  "TOOL · fraud_alert",
                  "Sent fraud alert notification to adjuster",
                  [("Claim ID", m.group(1)), ("Delivered", m.group(2))])
            continue

        # ── Triage / Priority Agent ───────────────────────────
        m = re.search(r'\[emailtool\] stage=routing_assigned.*?claim=(\S+).*?sent=(\w+)', ll)
        if m:
            _node(evts, "agent", "⚡", "Triage / Priority Agent", ts,
                  "AGENT",
                  "Evaluated urgency, SLA tier, and claim complexity — assigned routing queue",
                  [
                      ("Priority",      summary.get("priority", "")),
                      ("Routing Queue", summary.get("routing",  "")),
                      ("Stage emitted", "routing_assigned"),
                      ("Passed to",     "Copilot Agent"),
                  ],
                  color_override=AGENT_COLORS[3])
            _node(evts, "tool", "📧", "Email Tool", ts,
                  "TOOL · routing_assigned",
                  "Sent routing assignment notification to adjuster",
                  [("Claim ID", m.group(1)), ("Delivered", m.group(2))])
            continue

        # ── Report Tool → Copilot synthesis ──────────────────
        m = re.search(r'\[reporttool\] pdf generated.*?(\d[\d,]+)\s*bytes', ll)
        if m and not copilot_done:
            copilot_done = True
            dec = summary.get("decision", "")
            _node(evts, "agent", "📝", "Copilot Agent", ts,
                  "AGENT",
                  "Synthesised all agent outputs into a final adjuster brief with approve/review recommendation",
                  [
                      ("Decision",  dec),
                      ("Claimant",  summary.get("claimant", "")),
                      ("Amount",    summary.get("amount",   "")),
                      ("Output",    "Structured brief + PDF report"),
                  ],
                  color_override=AGENT_COLORS[4])
            _node(evts, "tool", "📄", "Report Tool", ts,
                  "TOOL",
                  "Generated PDF assessment report for adjuster",
                  [("PDF size", f"{int(m.group(1).replace(',','')):,} bytes"),
                   ("Attached to", "pipeline_complete email")])
            continue

        # ── Drive Tool ────────────────────────────────────────
        m = re.search(r'\[drive\] upload complete.*?(\d+)/(\d+) files.*?(https://\S+)', ll)
        if m:
            url = m.group(3).rstrip(')')
            _node(evts, "tool", "📁", "Drive Tool", ts,
                  "TOOL",
                  "Uploaded claim documents to Google Drive folder",
                  [("Files uploaded", f"{m.group(1)} / {m.group(2)}"),
                   ("Drive folder",   url)])
            continue

        # ── BigQuery (accumulate both rows, emit on agent_outputs) ─
        m = re.search(r'bq: inserted (\d+) row.*?into (\w+)', ll)
        if m:
            bq_rows.append(f"{m.group(1)} row(s) → {m.group(2)}")

        if "agent_outputs" in ll and "bq:" in ll and bq_rows:
            _node(evts, "storage", "🗄️", "BigQuery", ts,
                  "STORAGE",
                  "Persisted claim record and per-agent outputs to BigQuery",
                  [("Written", r) for r in bq_rows])
            bq_rows = []
            continue

        # ── EmailTool: pipeline_complete ──────────────────────
        m = re.search(r'\[emailtool\] stage=pipeline_complete.*?claim=(\S+).*?sent=(\w+)', ll)
        if m:
            _node(evts, "tool", "📧", "Email Tool", ts,
                  "TOOL · pipeline_complete",
                  "Sent complete AI assessment with PDF report to claimant — pipeline done",
                  [("Claim ID",   m.group(1)),
                   ("Delivered",  m.group(2)),
                   ("Includes",   "PDF report + Drive link + approval form")])
            continue

    return evts

def render_explainability_timeline(evts: list[dict]) -> None:
    """Render the execution timeline as a vertical call graph (single st.markdown call)."""
    parts: list[str] = []

    for j, evt in enumerate(evts):
        t   = evt.get("type", "tool")
        cfg = _NODE_CFG.get(t, _NODE_CFG["tool"]).copy()
        if evt.get("color"):
            c = evt["color"]
            try:
                r2, g2, b2 = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
                cfg["color"]  = c
                cfg["bg"]     = f"rgba({r2},{g2},{b2},.09)"
                cfg["border"] = f"rgba({r2},{g2},{b2},.32)"
            except Exception:
                pass

        color  = cfg["color"]
        bg     = cfg["bg"]
        border = cfg["border"]
        label  = evt.get("label", cfg["label"])
        ts_str = html_mod.escape(evt.get("ts", ""))
        ts_html = (
            f'<span style="font-size:11px;color:#4b4568;font-family:JetBrains Mono,monospace;">'
            f'{ts_str}</span>'
        ) if ts_str else ""

        # Output rows
        outputs = evt.get("outputs", [])
        out_html = ""
        if outputs:
            rows_html = "".join(
                f'<div style="display:flex;gap:10px;align-items:flex-start;margin-bottom:5px;">'
                f'<span style="font-size:11px;color:{color};opacity:.7;min-width:120px;'
                f'flex-shrink:0;padding-top:1px;">{html_mod.escape(str(k))}</span>'
                f'<span style="font-size:12.5px;color:#c8c3d8;font-family:JetBrains Mono,'
                f'monospace;word-break:break-all;">{html_mod.escape(str(v))}</span>'
                f'</div>'
                for k, v in outputs
            )
            out_html = (
                f'<div style="margin-top:12px;padding:12px 14px;background:rgba(5,5,14,.85);'
                f'border-radius:10px;border:1px solid rgba(255,255,255,.04);">'
                f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:.1em;color:{color};opacity:.6;margin-bottom:10px;">&#9658; Output</div>'
                f'{rows_html}</div>'
            )

        connector = (
            "" if j == len(evts) - 1 else
            f'<div style="margin-left:19px;width:2px;height:22px;'
            f'background:linear-gradient(180deg,{color}80,rgba(161,66,244,.12));'
            f'border-radius:1px;"></div>'
        )

        parts.append(
            f'<div style="display:flex;gap:16px;align-items:flex-start;">'
            f'<div style="flex-shrink:0;width:40px;height:40px;border-radius:50%;'
            f'background:{bg};border:2px solid {color};'
            f'display:flex;align-items:center;justify-content:center;'
            f'font-size:17px;box-shadow:0 0 16px {color}44;margin-top:2px;">'
            f'{evt["icon"]}'
            f'</div>'
            f'<div style="flex:1;background:{bg};border:1px solid {border};'
            f'border-radius:14px;padding:16px 18px;">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'margin-bottom:6px;flex-wrap:wrap;gap:8px;">'
            f'<div style="display:flex;align-items:center;gap:10px;">'
            f'<span style="font-size:14px;font-weight:800;color:{color};">'
            f'{html_mod.escape(evt["name"])}</span>'
            f'<span style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.08em;padding:2px 9px;border-radius:999px;'
            f'background:rgba(255,255,255,.05);color:{color};'
            f'border:1px solid {color}33;opacity:.9;">'
            f'{html_mod.escape(label)}</span>'
            f'</div>'
            f'{ts_html}'
            f'</div>'
            f'<div style="font-size:13px;color:#9f98b8;line-height:1.55;">'
            f'{html_mod.escape(evt["action"])}</div>'
            f'{out_html}'
            f'</div>'
            f'</div>'
            f'{connector}'
        )

    st.markdown("".join(parts), unsafe_allow_html=True)


def _pipeline_result(summary: dict) -> dict[str, Any]:
    payload = summary.get("pipeline_result")
    if isinstance(payload, dict):
        return payload
    return {
        "status": summary.get("status_detail"),
        "route": summary.get("route", {}),
        "workflow_state": summary.get("workflow_state", {}),
        "outputs": summary.get("outputs", {}),
        "document_summary": summary.get("document_summary", {}),
    }


def _outputs(result: dict, summary: dict) -> dict[str, dict[str, Any]]:
    outputs = result.get("outputs") or summary.get("outputs") or {}
    return outputs if isinstance(outputs, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _text(value: Any, default: str = "-") -> str:
    if value in (None, "", [], {}):
        return default
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _money(value: Any, currency: str = "INR") -> str:
    if value in (None, ""):
        return "-"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{currency} {amount:,.0f}" if currency == "INR" else f"{currency} {amount:,.2f}"


def _render_kv(rows: list[tuple[str, Any]], columns: int = 2) -> None:
    rows = [(label, value) for label, value in rows if value not in (None, "", [], {})]
    if not rows:
        st.caption("No structured facts captured for this section.")
        return
    cols = st.columns(columns)
    for idx, (label, value) in enumerate(rows):
        with cols[idx % columns]:
            st.markdown(f"**{label}**")
            st.code(_text(value), language=None)


def _render_items(items: list[Any], *, empty: str = "None captured.") -> None:
    items = [item for item in items if item not in (None, "", [], {})]
    if not items:
        st.caption(empty)
        return
    for item in items:
        if isinstance(item, dict):
            title = (
                item.get("signal_id")
                or item.get("flag_id")
                or item.get("section_reference")
                or item.get("document_id")
                or item.get("item")
                or item.get("filename")
                or "finding"
            )
            detail = item.get("description") or item.get("supports") or item.get("summary") or item.get("status") or ""
            st.markdown(f"- **{html_mod.escape(str(title))}**: {html_mod.escape(str(detail))}")
            extra = {
                k: v
                for k, v in item.items()
                if k not in {"signal_id", "flag_id", "section_reference", "document_id", "item", "filename", "description", "supports", "summary", "status"}
                and v not in (None, "", [], {})
            }
            if extra:
                st.json(extra, expanded=False)
        else:
            st.markdown(f"- {html_mod.escape(str(item))}")


def _render_orchestrator(result: dict[str, Any]) -> None:
    route    = result.get("route") if isinstance(result.get("route"), dict) else {}
    workflow = result.get("workflow_state") if isinstance(result.get("workflow_state"), dict) else {}
    errors   = result.get("errors") if isinstance(result.get("errors"), dict) else {}
    selected  = _as_list(route.get("selected_agents"))
    completed = _as_list(workflow.get("completed_agents"))
    pending   = _as_list(workflow.get("pending_agents"))

    status        = _text(result.get("status"), "unknown")
    current_stage = _text(workflow.get("current_stage"), "—")
    next_stage    = _text(workflow.get("next_stage") or route.get("next_agent"), "—")
    confidence    = _text(route.get("confidence"), "—")
    reason        = _text(route.get("reason"), "")
    req_action    = _text(route.get("required_action"), "")
    claim_status  = _text(route.get("claim_status"), "")
    fallback      = _text(route.get("_fallback_reason"), "")
    missing       = ", ".join(str(i) for i in _as_list(route.get("missing_inputs")))

    # status colour
    sl = status.lower()
    st_color = "#4ade80" if any(x in sl for x in ("complete","success","done")) else "#f87171" if any(x in sl for x in ("fail","error")) else "#facc15"

    # ── section header ─────────────────────────────────────────
    st.markdown(
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">'
        '<div style="width:4px;height:28px;border-radius:2px;background:linear-gradient(180deg,#a142f4,#7c3aed);flex-shrink:0;"></div>'
        '<span style="font-size:16px;font-weight:900;color:#fff;letter-spacing:-.2px;">&#x1F9E0; Orchestrator Decision Ledger</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── 4 metric pills ─────────────────────────────────────────
    def _pill(icon: str, label: str, value: str, color: str) -> str:
        return (
            f'<div style="flex:1;min-width:140px;background:rgba(10,10,22,.9);'
            f'border:1px solid {color}44;border-radius:16px;padding:16px 18px;">'
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:{color};opacity:.7;margin-bottom:8px;">{icon} {label}</div>'
            f'<div style="font-size:17px;font-weight:800;color:{color};word-break:break-word;">{html_mod.escape(value)}</div>'
            f'</div>'
        )

    pills = (
        _pill("&#x26A1;", "Pipeline Status", status, st_color)
        + _pill("&#x1F4CD;", "Current Stage",  current_stage, "#a78bfa")
        + _pill("&#x27A1;", "Next Stage",      next_stage,    "#60a5fa")
        + _pill("&#x1F916;", "Agents Selected", str(len(selected)), "#34d399")
    )
    st.markdown(
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px;">{pills}</div>',
        unsafe_allow_html=True,
    )

    # ── route reasoning callout ────────────────────────────────
    if reason:
        st.markdown(
            '<div style="background:rgba(161,66,244,.07);border-left:3px solid #a142f4;'
            'border-radius:0 12px 12px 0;padding:14px 18px;margin-bottom:16px;">'
            '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#a142f4;margin-bottom:6px;">&#x1F4AC; Routing Rationale</div>'
            f'<div style="font-size:13px;color:#c8c3d8;line-height:1.6;">{html_mod.escape(reason)}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── agent pipeline flow ────────────────────────────────────
    if selected or completed:
        all_agents = ["intake"] + [str(a) for a in selected]
        completed_set = {str(c) for c in completed}
        pending_set   = {str(p) for p in pending}
        sep = '<span style="color:#4b4568;font-size:13px;margin:0 4px;">&#x2192;</span>'
        bubbles = sep.join(
            f'<span style="display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border-radius:999px;'
            f'font-size:11px;font-weight:700;'
            f'background:{"rgba(74,222,128,.12)" if a in completed_set else "rgba(250,204,21,.1)" if a in pending_set else "rgba(255,255,255,.05)"};'
            f'border:1px solid {"rgba(74,222,128,.4)" if a in completed_set else "rgba(250,204,21,.3)" if a in pending_set else "rgba(255,255,255,.1)"};'
            f'color:{"#4ade80" if a in completed_set else "#facc15" if a in pending_set else "#9f98b8"};">'
            f'{"&#x2713;" if a in completed_set else "&#x23F3;" if a in pending_set else "&#x25CB;"} {html_mod.escape(a)}'
            f'</span>'
            for a in all_agents
        )
        st.markdown(
            '<div style="background:rgba(10,10,22,.85);border:1px solid rgba(161,66,244,.15);'
            'border-radius:14px;padding:14px 18px;margin-bottom:16px;">'
            '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#6b5fa0;margin-bottom:10px;">Agent Execution Flow</div>'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px;">{bubbles}</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── detail kv pairs ────────────────────────────────────────
    detail_rows = [
        ("Required action",   req_action),
        ("Claim status",      claim_status),
        ("Router confidence", confidence),
        ("Missing inputs",    missing),
        ("Fallback reason",   fallback),
    ]
    detail_rows = [(k, v) for k, v in detail_rows if v and v != "—"]
    if detail_rows or errors:
        def _kv_item(k: str, v: str) -> str:
            return (
                f'<div style="background:rgba(5,5,14,.8);border:1px solid rgba(161,66,244,.1);'
                f'border-radius:10px;padding:12px 14px;">'
                f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#6b5fa0;margin-bottom:4px;">{html_mod.escape(k)}</div>'
                f'<div style="font-size:12.5px;color:#c8c3d8;word-break:break-word;">{html_mod.escape(v)}</div>'
                f'</div>'
            )
        items_html = "".join(_kv_item(k, v) for k, v in detail_rows)
        st.markdown(
            f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;">{items_html}</div>',
            unsafe_allow_html=True,
        )
        if errors:
            st.markdown("**Errors**")
            st.json(errors, expanded=False)


def _render_document_analysis(result: dict[str, Any], outputs: dict[str, dict[str, Any]]) -> None:
    intake = outputs.get("intake", {})
    docs = (
        result.get("document_summary")
        or intake.get("documents_summary")
        or {}
    )
    if not isinstance(docs, dict):
        docs = {}

    st.markdown("#### Document analysis findings")
    _render_kv([
        ("Total documents", docs.get("total_documents") or result.get("attachment_count")),
        ("Documents analyzed", ", ".join(str(item) for item in _as_list(docs.get("documents_analyzed")))),
        ("Modalities", ", ".join(str(item) for item in _as_list(docs.get("modalities")))),
        ("Aggregate summary", docs.get("aggregate_summary") or docs.get("summary")),
        ("Analyst notes", docs.get("analyst_notes")),
        ("Risk signals", ", ".join(str(item) for item in _as_list(docs.get("risk_signals")))),
    ])

    per_doc = [item for item in _as_list(docs.get("per_document")) if isinstance(item, dict)]
    if not per_doc:
        st.caption("No per-document analysis was captured for this run.")
        return

    for index, doc in enumerate(per_doc, start=1):
        title = doc.get("filename") or doc.get("document_id") or f"document {index}"
        with st.expander(f"Document {index}: {title}", expanded=index == 1):
            _render_kv([
                ("Type", doc.get("document_type")),
                ("Modality", doc.get("modality")),
                ("MIME type", doc.get("mime_type")),
                ("Confidence", doc.get("confidence")),
                ("Supports claim", doc.get("supports_claim")),
                ("Summary", doc.get("summary") or doc.get("analysis_summary")),
                ("Extracted fields", doc.get("extracted_fields")),
                ("Key findings", doc.get("key_findings") or doc.get("findings")),
                ("Risk signals", doc.get("risk_signals")),
                ("Quality issues", doc.get("quality_issues")),
                ("Consistency issues", doc.get("consistency_issues")),
            ])


def _render_agent_cards(outputs: dict[str, dict[str, Any]]) -> None:
    intake = outputs.get("intake", {})
    coverage = outputs.get("coverage", {})
    fraud = outputs.get("fraud", {})
    triage = outputs.get("triage", {})
    copilot = outputs.get("copilot", {})

    st.markdown("#### Agent findings and reasoning")
    with st.expander("Intake Agent - extracted claim facts", expanded=True):
        _render_kv([
            ("Intake status", intake.get("intake_status")),
            ("Claimant", intake.get("claimant_name")),
            ("Patient", intake.get("patient_name")),
            ("Policy number", intake.get("policy_number")),
            ("Claim type", intake.get("claim_type")),
            ("Request type", intake.get("request_type")),
            ("Incident/admission date", intake.get("incident_date") or intake.get("admission_date")),
            ("Diagnosis", intake.get("diagnosis")),
            ("Procedure", intake.get("procedure")),
            ("Hospital/provider", intake.get("hospital_name") or intake.get("vendor_name")),
            ("Claim amount", _money(intake.get("claim_amount") or intake.get("estimated_amount"), intake.get("currency", "INR"))),
            ("Claim summary", intake.get("claim_summary")),
            ("Missing information", ", ".join(str(item) for item in _as_list(intake.get("missing_information")))),
            ("Missing documents", ", ".join(str(item) for item in _as_list(intake.get("missing_documents")))),
            ("Risk indicators", ", ".join(str(item) for item in _as_list(intake.get("risk_indicators")))),
            ("Fallback reason", intake.get("_fallback_reason")),
        ])

    with st.expander("Coverage Agent - policy and compliance reasoning", expanded=True):
        _render_kv([
            ("Coverage status", coverage.get("coverage_status")),
            ("Policy status", coverage.get("policy_status")),
            ("Reasoning", coverage.get("coverage_reasoning")),
            ("Manual review required", coverage.get("manual_review_required")),
            ("Manual review reasons", ", ".join(str(item) for item in _as_list(coverage.get("manual_review_reasons")))),
            ("Claim type covered", coverage.get("claim_type_covered")),
            ("Policy active on incident date", coverage.get("policy_active_on_incident_date")),
            ("Waiting period breach", coverage.get("waiting_period_breach")),
            ("Decision due date", coverage.get("decision_due_date")),
            ("Calculation methodology", coverage.get("calculation_methodology")),
            ("Prohibited actions checked", coverage.get("prohibited_actions_checked")),
            ("Fallback reason", coverage.get("_fallback_reason")),
        ])
        st.markdown("**Policy citations and documents reviewed**")
        _render_items(_as_list(coverage.get("policy_sections_referenced")) + _as_list(coverage.get("documents_reviewed")))
        checklist = coverage.get("regulatory_compliance_checklist")
        if checklist:
            st.markdown("**Compliance checklist**")
            st.json(checklist, expanded=False)

    with st.expander("Fraud Agent - SIU investigation signals", expanded=True):
        _render_kv([
            ("Fraud score", fraud.get("fraud_score")),
            ("Risk level", fraud.get("risk_level")),
            ("Recommended action", fraud.get("recommended_action")),
            ("Duplicate claim IDs", ", ".join(str(item) for item in _as_list(fraud.get("duplicate_claim_ids")))),
            ("Invoice anomaly", fraud.get("invoice_anomaly")),
            ("Vendor flagged", fraud.get("vendor_flagged")),
            ("Fallback reason", fraud.get("_fallback_reason")),
        ])
        st.markdown("**Signals and evidence**")
        _render_items(_as_list(fraud.get("signals")), empty="No fraud signals captured.")

    with st.expander("Triage Agent - priority, routing, and medical review", expanded=True):
        _render_kv([
            ("Priority", triage.get("priority")),
            ("Triage color", triage.get("triage_color")),
            ("Routing", triage.get("routing")),
            ("SLA hours", triage.get("sla_hours")),
            ("Human approval required", triage.get("required_human_approval")),
            ("Human approval reasons", ", ".join(str(item) for item in _as_list(triage.get("human_approval_reasons")))),
            ("Clinical priority", triage.get("clinical_priority")),
            ("Urgency", triage.get("urgency")),
            ("Medical necessity", triage.get("medical_necessity")),
            ("Severity score", triage.get("severity_score")),
            ("Recommended specialist", triage.get("recommended_specialist")),
            ("Next steps", triage.get("recommended_next_steps")),
            ("Summary", triage.get("triage_summary")),
            ("Fallback reason", triage.get("_fallback_reason")),
        ])
        st.markdown("**Clinical flags**")
        _render_items(_as_list(triage.get("clinical_flags")), empty="No clinical flags captured.")

    with st.expander("Copilot Agent - final explanation and guardrails", expanded=True):
        _render_kv([
            ("Copilot role", copilot.get("copilot_role")),
            ("Executive summary", copilot.get("executive_summary")),
            ("Coverage position", copilot.get("coverage_position")),
            ("Fraud assessment", copilot.get("fraud_assessment")),
            ("Routing decision", copilot.get("routing_decision")),
            ("Open questions", copilot.get("open_questions")),
            ("Suggested next steps", copilot.get("suggested_next_steps")),
            ("Knowledge sources used", copilot.get("knowledge_sources_used")),
            ("Recommended tools", copilot.get("recommended_tools")),
            ("Fallback reason", copilot.get("_fallback_reason")),
        ])
        st.markdown("**Decision guardrails**")
        _render_items(_as_list(copilot.get("decision_guardrails")))
        st.markdown("**Citations and evidence references**")
        _render_items(_as_list(copilot.get("citations")), empty="No copilot citations captured.")
        evidence_log = copilot.get("evidence_log")
        if evidence_log:
            st.markdown("**Evidence log**")
            st.json(evidence_log, expanded=False)


def _render_raw_evidence(result: dict[str, Any], stdout: str) -> None:
    with st.expander("Raw structured pipeline result", expanded=False):
        st.json(result, expanded=False)
    with st.expander("Raw terminal trace", expanded=False):
        st.code(_ansi(stdout), language="text")


def render_structured_explainability(entry: dict, evts: list[dict]) -> None:
    summary = entry.get("summary", {})
    stdout = entry.get("stdout", "")
    result = _pipeline_result(summary)
    outputs = _outputs(result, summary)

    if not result.get("route") and not outputs and not result.get("document_summary"):
        return

    st.markdown(
        '<div style="height:32px;"></div>'
        '<div style="height:1px;background:linear-gradient(90deg,transparent,rgba(161,66,244,.3),transparent);margin-bottom:28px;"></div>',
        unsafe_allow_html=True,
    )
    _render_orchestrator(result)
    st.divider()
    _render_document_analysis(result, outputs)
    st.divider()
    _render_agent_cards(outputs)
    st.divider()
    _render_raw_evidence(result, stdout)

def render_explainability(entry: dict) -> None:
    stdout  = entry.get("stdout", "")
    summary = entry.get("summary", {})

    if not stdout:
        st.markdown(
            '<div class="no-run"><div class="no-run-icon">🔬</div>'
            '<div class="no-run-title">No agent data yet</div>'
            '<div class="no-run-sub">Run the pipeline to see the execution call graph</div></div>',
            unsafe_allow_html=True,
        )
        return

    evts = parse_execution_timeline(stdout, summary)

    if not evts:
        st.markdown(
            '<div class="no-run"><div class="no-run-icon">🔬</div>'
            '<div class="no-run-title">No events parsed</div>'
            '<div class="no-run-sub">Complete a full pipeline run to populate this view</div></div>',
            unsafe_allow_html=True,
        )
        return

    # Summary chips
    n_agents  = sum(1 for e in evts if e["type"] == "agent")
    n_tools   = sum(1 for e in evts if e["type"] == "tool")
    n_storage = sum(1 for e in evts if e["type"] == "storage")
    n_orch    = sum(1 for e in evts if e["type"] == "orchestrator")

    chips = [
        ("#a142f4", "rgba(161,66,244,.1)",  "rgba(161,66,244,.35)", f"🧠 {n_orch} Orchestrator call{'s' if n_orch!=1 else ''}"),
        ("#60a5fa", "rgba(96,165,250,.08)", "rgba(96,165,250,.3)",  f"🤖 {n_agents} Agent{'s' if n_agents!=1 else ''}"),
        ("#34d399", "rgba(52,211,153,.07)", "rgba(52,211,153,.3)",  f"🔧 {n_tools} Tool call{'s' if n_tools!=1 else ''}"),
        ("#facc15", "rgba(250,204,21,.07)", "rgba(250,204,21,.3)",  f"🗄️ {n_storage} Storage write{'s' if n_storage!=1 else ''}"),
    ]
    chips_html = "".join(
        f'<span style="font-size:12px;font-weight:700;padding:6px 14px;border-radius:999px;'
        f'background:{bg};border:1px solid {bd};color:{c};">{label}</span>'
        for c, bg, bd, label in chips
    )
    st.markdown(
        f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px;">{chips_html}</div>',
        unsafe_allow_html=True,
    )

    render_explainability_timeline(evts)
    render_structured_explainability(entry, evts)
