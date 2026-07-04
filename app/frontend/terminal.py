"""Live terminal rendering helpers."""

import html as html_mod
import re

from frontend.config import AGENT_COLORS, AGENTS
from frontend.utils import _ansi, _ts_from_line, detect_agent_live

def render_terminal_html(live_lines: list[tuple], running: bool = False) -> str:
    """
    live_lines: list of (timestamp_str, agent_idx, raw_line)
    Renders a dark terminal panel using only CSS (no JS — Streamlit strips scripts).
    """
    if not live_lines:
        body = """
        <div class="term-empty">
          <div class="term-empty-icon">⚡</div>
          <div class="term-empty-title">No output yet</div>
          <div class="term-empty-sub">Trigger a run above to see live logs</div>
        </div>"""
    else:
        rows = []
        for ts, aidx, raw in live_lines:
            clean = _ansi(raw).strip()
            if not clean:
                continue

            # Separator lines (═══ or ───)
            stripped = re.sub(r'[═─= \-]', '', clean)
            if not stripped:
                rows.append(
                    '<div class="ll sep">'
                    '<span class="ll-ts"></span>'
                    '<span class="ll-tag"></span>'
                    '<span class="ll-txt">──────────────────────────────────────────────</span>'
                    '</div>'
                )
                continue

            if aidx >= 0 and aidx < len(AGENTS):
                icon, name, _ = AGENTS[aidx]
                color = AGENT_COLORS[aidx]
                tag = f'<span class="ll-tag" style="color:{color};">{icon} {name[:9]}</span>'
            else:
                tag = '<span class="ll-tag" style="color:#4b4568;">SYS</span>'
                color = "#555070"

            # Colourise key lines
            cl = clean.lower()
            if any(x in cl for x in ["✅", "pipeline complete", "done", "success", "sent=true", "uploaded"]):
                txt_style = "color:#4ade80;font-weight:600;"
            elif any(x in cl for x in ["❌", "error", "failed", "fail"]):
                txt_style = "color:#f87171;"
            elif any(x in cl for x in ["⚠", "warning", "flag", "critical", "human approval"]):
                txt_style = "color:#facc15;"
            elif any(x in cl for x in ["http request", "info", "[emailtool]", "[drive]",
                                         "[attachments]", "[reporttool]", "[orchestrator]", "bq:"]):
                txt_style = f"color:{color};opacity:.75;"
            else:
                txt_style = f"color:{color};"

            safe = html_mod.escape(clean)
            ts_disp = ts if ts else _ts_from_line(clean)

            rows.append(
                f'<div class="ll">'
                f'<span class="ll-ts">{ts_disp}</span>'
                f'{tag}'
                f'<span class="ll-txt" style="{txt_style}">{safe}</span>'
                f'</div>'
            )

        cursor = '<div class="ll"><span class="ll-ts"></span><span class="ll-tag"></span>'
        cursor += '<span class="term-cursor"></span></div>' if running else ""
        body = "\n".join(rows) + cursor

    status_html = (
        '<span class="term-status-run" style="margin-left:auto;">● RUNNING</span>'
        if running else
        '<span class="term-status-ok"  style="margin-left:auto;">● COMPLETE</span>'
    )

    return f"""
    <div class="terminal-outer">
      <div class="terminal-titlebar">
        <span class="tdot" style="background:#f87171;"></span>
        <span class="tdot" style="background:#facc15;"></span>
        <span class="tdot" style="background:#4ade80;"></span>
        <span style="font-size:12px;color:#4b4568;font-family:'JetBrains Mono',monospace;margin-left:8px;">
          claimiq · pipeline · live output
        </span>
        {status_html}
      </div>
      <div class="terminal-body">{body}</div>
    </div>
    """

def rebuild_live_log(entry: dict) -> list[tuple]:
    """Reconstruct (ts, agent_idx, line) tuples from a stored log entry."""
    stdout = entry.get("stdout", "")
    if not stdout:
        return []
    current = 0
    result = []
    for raw in stdout.splitlines():
        line_clean = _ansi(raw).strip()
        if not line_clean:
            continue
        ts = _ts_from_line(line_clean)
        current = detect_agent_live(raw, current)
        result.append((ts, current, raw))
    return result
