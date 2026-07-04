"""Generate ClaimIQ architecture diagrams as SVG assets.

The diagrams intentionally mirror the dark, layered visual style of the
website architecture SVG while staying dependency-free and reproducible.
Run from the repository root:

    python docs/architecture/generate_diagrams.py
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any


OUT_DIR = Path(__file__).resolve().parent


COLORS = {
    "flow": "#22c55e",
    "blue": "#3b82f6",
    "green": "#84cc16",
    "purple": "#a855f7",
    "amber": "#f59e0b",
    "teal": "#14b8a6",
    "pink": "#ec4899",
    "red": "#f43f5e",
    "muted": "#8593aa",
}

BANDS = {
    "blue": ("#0e1a2e", "#294a7a", "#7db3f0"),
    "green": ("#101d13", "#3f6b2a", "#a3e635"),
    "purple": ("#17112b", "#5b3a86", "#c4a0f5"),
    "amber": ("#1d1608", "#8a5a12", "#fbbf24"),
    "teal": ("#0b1f1c", "#1a6b62", "#2dd4bf"),
    "pink": ("#1d0f18", "#8a2b56", "#f472b6"),
    "red": ("#201016", "#7f1d1d", "#fb7185"),
}


@dataclass
class Card:
    id: str
    x: float
    y: float
    w: float
    h: float
    accent: str
    icon: str
    title: str
    lines: list[str]


class Svg:
    def __init__(self, width: int, height: int, title: str) -> None:
        self.width = width
        self.height = height
        self.parts: list[str] = []
        self.parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            'font-family="Inter, Segoe UI, Arial, sans-serif">'
        )
        self._defs()
        self.rect(0, 0, width, height, 0, "#0a0f1c")
        self.text(width / 2, 42, title, "#eef3fb", 30, 800, anchor="middle")

    def _defs(self) -> None:
        self.parts.append("<defs>")
        for name, color in COLORS.items():
            if name == "muted":
                continue
            self.parts.append(
                f'<marker id="arrow-{name}" markerWidth="9" markerHeight="9" '
                'refX="7" refY="3" orient="auto">'
                f'<path d="M0,0 L7,3 L0,6 Z" fill="{color}"/></marker>'
            )
        self.parts.append(
            '<filter id="soft-shadow" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#020617" flood-opacity="0.28"/>'
            "</filter>"
        )
        self.parts.append("</defs>")

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        rx: float,
        fill: str,
        stroke: str | None = None,
        stroke_width: float = 1.0,
        opacity: float | None = None,
        stroke_opacity: float | None = None,
        extra: str = "",
    ) -> None:
        attrs = [
            f'x="{x:g}"',
            f'y="{y:g}"',
            f'width="{w:g}"',
            f'height="{h:g}"',
            f'rx="{rx:g}"',
            f'fill="{fill}"',
        ]
        if stroke:
            attrs.append(f'stroke="{stroke}"')
            attrs.append(f'stroke-width="{stroke_width:g}"')
        if opacity is not None:
            attrs.append(f'opacity="{opacity:g}"')
        if stroke_opacity is not None:
            attrs.append(f'stroke-opacity="{stroke_opacity:g}"')
        if extra:
            attrs.append(extra)
        self.parts.append(f"<rect {' '.join(attrs)}/>")

    def text(
        self,
        x: float,
        y: float,
        value: str,
        fill: str,
        size: float,
        weight: int | str = 400,
        *,
        anchor: str = "start",
        opacity: float | None = None,
    ) -> None:
        attrs = [
            f'x="{x:g}"',
            f'y="{y:g}"',
            f'fill="{fill}"',
            f'font-size="{size:g}"',
            f'font-weight="{weight}"',
            f'text-anchor="{anchor}"',
        ]
        if opacity is not None:
            attrs.append(f'opacity="{opacity:g}"')
        self.parts.append(f"<text {' '.join(attrs)}>{escape(value)}</text>")

    def text_lines(
        self,
        x: float,
        y: float,
        lines: list[str],
        fill: str,
        size: float,
        weight: int | str = 400,
        *,
        line_height: float = 15,
        anchor: str = "start",
    ) -> None:
        for i, line in enumerate(lines):
            self.text(x, y + i * line_height, line, fill, size, weight, anchor=anchor)

    def path(
        self,
        d: str,
        kind: str = "flow",
        *,
        dashed: bool = False,
        width: float = 2.0,
        opacity: float = 1.0,
    ) -> None:
        color = COLORS[kind]
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width:g}"'
            f'{dash} opacity="{opacity:g}" marker-end="url(#arrow-{kind})"/>'
        )

    def band(self, number: str, label: list[str], y: float, h: float, scheme: str) -> None:
        fill, stroke, accent = BANDS[scheme]
        self.rect(22, y, self.width - 44, h, 14, fill, stroke, 1.6)
        box_y = y + h / 2 - 22
        self.rect(34, box_y, 44, 44, 11, "none", accent, 2)
        self.text(56, box_y + 30, number, accent, 24, 800, anchor="middle")
        self.text_lines(92, box_y + 14, label, accent, 17, 800, line_height=21)

    def card(self, c: Card) -> None:
        accent = COLORS[c.accent]
        self.rect(c.x, c.y, c.w, c.h, 11, "#0e1626", accent, 1.4, stroke_opacity=0.55, extra='filter="url(#soft-shadow)"')
        icon_size = 40
        icon_y = c.y + max(12, (c.h - icon_size) / 2)
        self.rect(c.x + 13, icon_y, icon_size, icon_size, 9, accent, accent, 1.1, opacity=0.16, stroke_opacity=0.55)
        self.text(c.x + 33, icon_y + 26, c.icon, "#dbe6f5", 14, 800, anchor="middle")
        self.text(c.x + 66, c.y + 27, c.title, "#eef3fb", 15.5, 700)
        self.text_lines(c.x + 66, c.y + 45, c.lines[:4], "#8593aa", 10.8, 500, line_height=13)

    def legend(self, y: float, items: list[tuple[str, str, bool]]) -> None:
        self.rect(22, y, self.width - 44, 58, 12, "#0c1322", "#20293c", 1.0)
        slot = (self.width - 240) / max(1, len(items))
        x = 110
        for kind, label, dashed in items:
            color = COLORS[kind]
            dash = ' stroke-dasharray="6 5"' if dashed else ""
            self.parts.append(
                f'<path d="M {x:g} {y + 30:g} h 34" stroke="{color}" '
                f'stroke-width="2.4"{dash} marker-end="url(#arrow-{kind})"/>'
            )
            self.text(x + 46, y + 34, label, "#c7d2e2", 12.5, 600)
            x += slot

    def finish(self) -> str:
        self.parts.append("</svg>")
        return "\n".join(self.parts) + "\n"


def anchor(card: Card, side: str) -> tuple[float, float]:
    if side == "left":
        return card.x, card.y + card.h / 2
    if side == "right":
        return card.x + card.w, card.y + card.h / 2
    if side == "top":
        return card.x + card.w / 2, card.y
    if side == "bottom":
        return card.x + card.w / 2, card.y + card.h
    if side == "center":
        return card.x + card.w / 2, card.y + card.h / 2
    raise ValueError(side)


def route(svg: Svg, points: list[tuple[float, float]], kind: str = "flow", dashed: bool = False, label: str | None = None) -> None:
    if len(points) < 2:
        return
    d = f"M {points[0][0]:g} {points[0][1]:g}"
    for x, y in points[1:]:
        d += f" L {x:g} {y:g}"
    svg.path(d, kind, dashed=dashed)
    if label:
        mid = points[len(points) // 2]
        svg.text(mid[0], mid[1] - 8, label, COLORS[kind], 10.5, 700, anchor="middle")


def connect(
    svg: Svg,
    cards: dict[str, Card],
    source: str,
    source_side: str,
    target: str,
    target_side: str,
    *,
    kind: str = "flow",
    dashed: bool = False,
    label: str | None = None,
    via: list[tuple[float, float]] | None = None,
) -> None:
    points = [anchor(cards[source], source_side)]
    points.extend(via or [])
    points.append(anchor(cards[target], target_side))
    route(svg, points, kind, dashed, label)


def render(spec: dict[str, Any]) -> None:
    svg = Svg(spec["width"], spec["height"], spec["title"])
    for band_spec in spec["bands"]:
        svg.band(*band_spec)
    cards = {data["id"]: Card(**data) for data in spec["cards"]}
    for card in cards.values():
        svg.card(card)
    for arrow in spec.get("arrows", []):
        if "points" in arrow:
            route(svg, arrow["points"], arrow.get("kind", "flow"), arrow.get("dashed", False), arrow.get("label"))
        else:
            connect(svg, cards, **arrow)
    svg.legend(spec.get("legend_y", spec["height"] - 76), spec["legend"])
    (OUT_DIR / spec["filename"]).write_text(svg.finish(), encoding="utf-8")


def overall_spec() -> dict[str, Any]:
    cards = [
        dict(id="claimant", x=218, y=80, w=235, h=68, accent="blue", icon="C", title="Claimant", lines=["claim email", "documents + photos"]),
        dict(id="gmail", x=520, y=80, w=235, h=68, accent="blue", icon="GM", title="Gmail Mailbox", lines=["IMAP unread poll", "threaded replies"]),
        dict(id="streamlit", x=822, y=80, w=250, h=68, accent="blue", icon="UI", title="Streamlit Console", lines=["live logs", "traceability JSON"]),
        dict(id="reviewer", x=1138, y=80, w=250, h=68, accent="blue", icon="HR", title="Adjuster / SIU", lines=["human review", "final authority"]),
        dict(id="runner", x=218, y=190, w=235, h=68, accent="blue", icon="PY", title="app/run.py", lines=["watch, demo, no-bq", "claim id + dedupe"]),
        dict(id="emailio", x=493, y=190, w=235, h=68, accent="blue", icon="EM", title="email_io.py", lines=["IMAP read", "SMTP send"]),
        dict(id="attach", x=768, y=190, w=265, h=68, accent="blue", icon="AT", title="attachments.py", lines=["extract files", "text, PDF, image, DOCX"]),
        dict(id="validator", x=1090, y=190, w=250, h=68, accent="blue", icon="IV", title="InputValidator", lines=["size + format", "prompt-injection scan"]),
        dict(id="orchestrator", x=205, y=312, w=250, h=66, accent="green", icon="00", title="Pipeline Orchestrator", lines=["session flow", "timed agent stages"]),
        dict(id="session", x=520, y=312, w=215, h=66, accent="green", icon="S", title="ClaimSession", lines=["versioned state", "guard, route, outputs"]),
        dict(id="guard", x=760, y=312, w=205, h=66, accent="green", icon="G", title="Mail Guard", lines=["front-door gate", "rewrite request"]),
        dict(id="router", x=1000, y=312, w=175, h=66, accent="green", icon="R", title="Router", lines=["fast path", "dependency order"]),
        dict(id="shared", x=1195, y=312, w=222, h=66, accent="green", icon="RT", title="Shared Runtime", lines=["config, audit", "openai_client"]),
        dict(id="intake", x=205, y=400, w=250, h=74, accent="green", icon="01", title="Intake", lines=["multimodal extraction", "30+ field contract"]),
        dict(id="coverage", x=478, y=400, w=255, h=74, accent="green", icon="03", title="Coverage", lines=["policy evidence", "compliance guardrail"]),
        dict(id="fraud", x=756, y=400, w=250, h=74, accent="green", icon="04", title="Fraud", lines=["SIU signals", "deterministic score"]),
        dict(id="triage", x=1028, y=400, w=180, h=74, accent="green", icon="05", title="Triage", lines=["SLA + routing", "hard overrides"]),
        dict(id="copilot", x=1230, y=400, w=187, h=74, accent="green", icon="06", title="Copilot", lines=["employee brief", "never decides"]),
        dict(id="openai", x=258, y=506, w=300, h=68, accent="purple", icon="AI", title="OpenAI JSON Layer", lines=["Responses API", "strict object outputs"]),
        dict(id="vision", x=600, y=506, w=225, h=68, accent="purple", icon="V", title="Vision Models", lines=["images", "scanned PDF page"]),
        dict(id="reasoning", x=850, y=506, w=225, h=68, accent="purple", icon="LM", title="Reasoning Models", lines=["agent synthesis", "router ambiguity"]),
        dict(id="fallback", x=1100, y=506, w=225, h=68, accent="purple", icon="FB", title="Fallback Rules", lines=["deterministic extract", "safe triage"]),
        dict(id="bq", x=258, y=616, w=268, h=68, accent="amber", icon="BQ", title="Google BigQuery", lines=["policies", "claims + audit"]),
        dict(id="drive", x=575, y=616, w=232, h=68, accent="amber", icon="DR", title="Google Drive", lines=["claim folders", "attachments + PDFs"]),
        dict(id="policydocs", x=858, y=616, w=222, h=68, accent="amber", icon="PD", title="Policy PDFs", lines=["local docs", "catalog fallback"]),
        dict(id="local", x=1128, y=616, w=238, h=68, accent="amber", icon="FS", title="Local Outputs", lines=["email_output", "report artifacts"]),
        dict(id="emailupdates", x=258, y=726, w=268, h=68, accent="teal", icon="SM", title="SMTP Email Updates", lines=["received", "coverage, fraud, route"]),
        dict(id="report", x=575, y=726, w=232, h=68, accent="teal", icon="PDF", title="PDF Report", lines=["ClaimIQ report", "adjuster guide"]),
        dict(id="console", x=858, y=726, w=232, h=68, accent="teal", icon="UI", title="Prototype Console", lines=["agent outputs", "terminal stream"]),
        dict(id="human", x=1128, y=726, w=238, h=68, accent="teal", icon="OK", title="Approval Gate", lines=["high risk", "high value"]),
        dict(id="audit", x=258, y=836, w=240, h=68, accent="pink", icon="AU", title="Audit Trail", lines=["event + agent rows", "timings"]),
        dict(id="schemas", x=528, y=836, w=222, h=68, accent="pink", icon="JS", title="Schema Guards", lines=["normalizers", "JSON retry"]),
        dict(id="secrets", x=790, y=836, w=235, h=68, accent="pink", icon="ENV", title="Secrets + Flags", lines=[".env controls", "safe local mode"]),
        dict(id="authority", x=1070, y=836, w=235, h=68, accent="pink", icon="HA", title="Human Authority", lines=["AI assists", "humans decide"]),
    ]
    return {
        "filename": "prototype_architecture.svg",
        "width": 1536,
        "height": 1024,
        "title": "ClaimIQ - Prototype Architecture - Agentic Claims Pipeline",
        "bands": [
            ("1", ["Sources &", "Channels"], 60, 104, "blue"),
            ("2", ["Ingestion &", "Guardrails"], 170, 104, "blue"),
            ("3", ["Agent", "Orchestration"], 282, 200, "green"),
            ("4", ["OpenAI", "Intelligence"], 490, 100, "purple"),
            ("5", ["Evidence &", "Data Plane"], 600, 100, "amber"),
            ("6", ["Outputs &", "Human Loop"], 710, 100, "teal"),
            ("7", ["Safety &", "Observability"], 820, 100, "pink"),
        ],
        "cards": cards,
        "arrows": [
            dict(source="claimant", source_side="bottom", target="runner", target_side="top", kind="flow", label="claim email", via=[(335, 160)]),
            dict(source="gmail", source_side="bottom", target="emailio", target_side="top", kind="flow", label="poll/read", via=[(638, 160)]),
            dict(source="runner", source_side="right", target="emailio", target_side="left", kind="flow"),
            dict(source="emailio", source_side="right", target="attach", target_side="left", kind="flow"),
            dict(source="attach", source_side="right", target="validator", target_side="left", kind="flow"),
            dict(source="runner", source_side="bottom", target="orchestrator", target_side="top", kind="flow", label="start session"),
            dict(source="orchestrator", source_side="right", target="session", target_side="left", kind="flow", label="set state"),
            dict(source="session", source_side="right", target="guard", target_side="left", kind="flow"),
            dict(source="guard", source_side="right", target="router", target_side="left", kind="flow", label="after intake"),
            dict(source="orchestrator", source_side="bottom", target="intake", target_side="top", kind="flow"),
            dict(source="intake", source_side="right", target="coverage", target_side="left", kind="flow"),
            dict(source="coverage", source_side="right", target="fraud", target_side="left", kind="flow"),
            dict(source="fraud", source_side="right", target="triage", target_side="left", kind="flow"),
            dict(source="triage", source_side="right", target="copilot", target_side="left", kind="flow"),
            dict(source="intake", source_side="bottom", target="vision", target_side="top", kind="blue", dashed=True),
            dict(source="coverage", source_side="bottom", target="reasoning", target_side="top", kind="blue", dashed=True),
            dict(source="fraud", source_side="bottom", target="reasoning", target_side="top", kind="blue", dashed=True),
            dict(source="triage", source_side="bottom", target="fallback", target_side="top", kind="blue", dashed=True),
            dict(source="orchestrator", source_side="bottom", target="bq", target_side="top", kind="amber", dashed=True, label="audit"),
            dict(source="coverage", source_side="bottom", target="policydocs", target_side="top", kind="amber", dashed=True, via=[(605, 585), (969, 585)]),
            dict(source="drive", source_side="bottom", target="report", target_side="top", kind="amber", dashed=True),
            dict(source="report", source_side="right", target="console", target_side="left", kind="teal", dashed=True),
            dict(source="emailupdates", source_side="right", target="report", target_side="left", kind="teal", dashed=True),
            dict(source="human", source_side="top", target="reviewer", target_side="bottom", kind="pink", dashed=True, label="human verdict", via=[(1247, 700), (1263, 160)]),
            dict(source="audit", source_side="right", target="schemas", target_side="left", kind="pink", dashed=True),
            dict(source="schemas", source_side="right", target="secrets", target_side="left", kind="pink", dashed=True),
            dict(source="secrets", source_side="right", target="authority", target_side="left", kind="pink", dashed=True),
        ],
        "legend_y": 946,
        "legend": [
            ("flow", "Primary data flow", False),
            ("blue", "LLM / inference flow", True),
            ("amber", "Evidence / audit flow", True),
            ("teal", "Notification / output flow", True),
            ("pink", "Control / escalation flow", True),
        ],
    }


def module_base(filename: str, title: str, cards: list[dict[str, Any]], arrows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "filename": filename,
        "width": 1400,
        "height": 900,
        "title": title,
        "bands": [
            ("1", ["Inputs"], 70, 112, "blue"),
            ("2", ["Core", "Processing"], 200, 148, "green"),
            ("3", ["Decision &", "Fallbacks"], 368, 148, "purple"),
            ("4", ["Outputs"], 536, 124, "teal"),
            ("5", ["Safety &", "Traceability"], 680, 112, "pink"),
        ],
        "cards": cards,
        "arrows": arrows,
        "legend_y": 822,
        "legend": [
            ("flow", "Primary data", False),
            ("blue", "Model call", True),
            ("amber", "Evidence / storage", True),
            ("teal", "Output", True),
            ("pink", "Guardrail", True),
        ],
    }


def orchestrator_spec() -> dict[str, Any]:
    cards = [
        dict(id="caller", x=220, y=93, w=250, h=68, accent="blue", icon="IN", title="Caller", lines=["app/run.py or CLI", "claim_id + email"]),
        dict(id="docs", x=535, y=93, w=250, h=68, accent="blue", icon="DOC", title="Document Context", lines=["documents_summary", "uploaded_documents"]),
        dict(id="options", x=850, y=93, w=250, h=68, accent="blue", icon="CFG", title="Runtime Options", lines=["send_emails", "thread id"]),
        dict(id="session", x=220, y=238, w=250, h=78, accent="green", icon="S", title="ClaimSession", lines=["frozen state object", "guard, route, outputs", "timings + errors"]),
        dict(id="validator", x=515, y=238, w=250, h=78, accent="green", icon="IV", title="InputValidator", lines=["non-fatal validation", "rewrite on bad input"]),
        dict(id="auditstart", x=810, y=238, w=250, h=78, accent="green", icon="AU", title="Audit Start", lines=["pipeline_started", "stage events"]),
        dict(id="guard", x=220, y=406, w=230, h=78, accent="purple", icon="G", title="Mail Guard", lines=["evaluate email", "stop if rewrite"]),
        dict(id="intake", x=495, y=406, w=230, h=78, accent="purple", icon="01", title="Intake", lines=["extract claim facts", "pause if error"]),
        dict(id="router", x=770, y=406, w=230, h=78, accent="purple", icon="R", title="Router", lines=["selected_agents", "dependency order"]),
        dict(id="loop", x=1045, y=406, w=230, h=78, accent="purple", icon="LO", title="Stage Loop", lines=["coverage -> fraud", "triage -> copilot"]),
        dict(id="emails", x=220, y=568, w=250, h=68, accent="teal", icon="SM", title="Stage Emails", lines=["coverage update", "fraud alert, route"]),
        dict(id="report", x=535, y=568, w=250, h=68, accent="teal", icon="PDF", title="Conditional PDF", lines=["human approval", "risk/value triggers"]),
        dict(id="summary", x=850, y=568, w=250, h=68, accent="teal", icon="OUT", title="Pipeline Summary", lines=["workflow_state", "outputs + errors"]),
        dict(id="boundary", x=220, y=706, w=250, h=60, accent="pink", icon="HA", title="Human Boundary", lines=["AI assists only", "no final settlement"]),
        dict(id="timing", x=535, y=706, w=250, h=60, accent="pink", icon="T", title="Per-Agent Timing", lines=["started/completed", "duration_ms"]),
        dict(id="finish", x=850, y=706, w=250, h=60, accent="pink", icon="AU", title="Audit Finish", lines=["pipeline_completed", "report flag"]),
    ]
    arrows = [
        dict(source="caller", source_side="bottom", target="session", target_side="top", kind="flow"),
        dict(source="docs", source_side="bottom", target="session", target_side="top", kind="flow"),
        dict(source="options", source_side="bottom", target="session", target_side="top", kind="flow"),
        dict(source="session", source_side="right", target="validator", target_side="left", kind="flow"),
        dict(source="validator", source_side="right", target="auditstart", target_side="left", kind="flow"),
        dict(source="auditstart", source_side="bottom", target="guard", target_side="top", kind="flow", via=[(935, 350), (335, 350)]),
        dict(source="guard", source_side="right", target="intake", target_side="left", kind="flow", label="proceed"),
        dict(source="intake", source_side="right", target="router", target_side="left", kind="flow"),
        dict(source="router", source_side="right", target="loop", target_side="left", kind="flow"),
        dict(source="loop", source_side="bottom", target="emails", target_side="top", kind="teal", dashed=True, via=[(1160, 520), (345, 520)]),
        dict(source="loop", source_side="bottom", target="report", target_side="top", kind="teal", dashed=True, via=[(1160, 520), (660, 520)]),
        dict(source="report", source_side="right", target="summary", target_side="left", kind="teal"),
        dict(source="summary", source_side="bottom", target="finish", target_side="top", kind="pink", dashed=True),
        dict(source="session", source_side="bottom", target="timing", target_side="top", kind="pink", dashed=True, via=[(345, 666), (660, 666)]),
        dict(source="guard", source_side="bottom", target="boundary", target_side="top", kind="pink", dashed=True, label="rewrite stop"),
    ]
    return module_base("orchestrator_architecture.svg", "ClaimIQ - Orchestrator Architecture", cards, arrows)


def mail_guard_spec() -> dict[str, Any]:
    cards = [
        dict(id="subject", x=220, y=93, w=230, h=68, accent="blue", icon="SB", title="Subject", lines=["email subject", "thread context"]),
        dict(id="body", x=500, y=93, w=230, h=68, accent="blue", icon="TXT", title="Email Body", lines=["free-form claim", "customer text"]),
        dict(id="date", x=780, y=93, w=230, h=68, accent="blue", icon="DT", title="Current Date", lines=["future-date check", "UTC date"]),
        dict(id="required", x=1060, y=93, w=230, h=68, accent="blue", icon="REQ", title="Required Fields", lines=["name, policy", "date, place, details"]),
        dict(id="prompt", x=220, y=238, w=260, h=78, accent="green", icon="P", title="Guard Prompt", lines=["binary proceed/rewrite", "spam + vague inquiry", "single-claim quality"]),
        dict(id="openai", x=535, y=238, w=260, h=78, accent="green", icon="AI", title="OpenAI Path", lines=["generate_json", "fixed schema"]),
        dict(id="normalize", x=850, y=238, w=260, h=78, accent="green", icon="N", title="Normalize Result", lines=["action defaults", "rewrite template", "empty text guard"]),
        dict(id="fallback", x=220, y=406, w=260, h=78, accent="purple", icon="FB", title="Deterministic Guard", lines=["keyword density", "policy/date regex", "general inquiry catch"]),
        dict(id="datefix", x=535, y=406, w=260, h=78, accent="purple", icon="FD", title="Date Correction", lines=["ordinal dates", "non-future override", "avoid false stop"]),
        dict(id="decision", x=850, y=406, w=260, h=78, accent="purple", icon="D", title="Guard Decision", lines=["proceed", "rewrite_request"]),
        dict(id="proceed", x=220, y=568, w=260, h=68, accent="teal", icon="GO", title="Proceed To Intake", lines=["orchestrator continues", "audit completed"]),
        dict(id="rewrite", x=535, y=568, w=260, h=68, accent="teal", icon="RW", title="Rewrite Reply", lines=["structured form", "missing fields"]),
        dict(id="stop", x=850, y=568, w=260, h=68, accent="teal", icon="ST", title="Pipeline Stop", lines=["status rewrite_required", "customer resubmits"]),
        dict(id="boundary", x=220, y=706, w=260, h=60, accent="pink", icon="BD", title="Boundary", lines=["no coverage/fraud", "front-door only"]),
        dict(id="trace", x=535, y=706, w=260, h=60, accent="pink", icon="AU", title="Traceability", lines=["reason + confidence", "missing fields"]),
        dict(id="safe", x=850, y=706, w=260, h=60, accent="pink", icon="SF", title="Safety Posture", lines=["reject spam/vague", "accept complete claims"]),
    ]
    arrows = [
        dict(source="subject", source_side="right", target="body", target_side="left", kind="flow"),
        dict(source="body", source_side="right", target="date", target_side="left", kind="flow"),
        dict(source="date", source_side="right", target="required", target_side="left", kind="flow"),
        dict(source="body", source_side="bottom", target="prompt", target_side="top", kind="flow", via=[(615, 190), (350, 190)]),
        dict(source="prompt", source_side="right", target="openai", target_side="left", kind="blue", dashed=True),
        dict(source="openai", source_side="right", target="normalize", target_side="left", kind="flow"),
        dict(source="openai", source_side="bottom", target="fallback", target_side="top", kind="blue", dashed=True, label="on error", via=[(665, 365), (350, 365)]),
        dict(source="fallback", source_side="right", target="datefix", target_side="left", kind="flow"),
        dict(source="datefix", source_side="right", target="decision", target_side="left", kind="flow"),
        dict(source="normalize", source_side="bottom", target="decision", target_side="top", kind="flow"),
        dict(source="decision", source_side="bottom", target="proceed", target_side="top", kind="teal", label="proceed", via=[(980, 525), (350, 525)]),
        dict(source="decision", source_side="bottom", target="rewrite", target_side="top", kind="teal", label="rewrite"),
        dict(source="rewrite", source_side="right", target="stop", target_side="left", kind="teal"),
        dict(source="decision", source_side="bottom", target="trace", target_side="top", kind="pink", dashed=True, via=[(980, 666), (665, 666)]),
        dict(source="fallback", source_side="bottom", target="safe", target_side="top", kind="pink", dashed=True, via=[(350, 666), (980, 666)]),
    ]
    return module_base("mail_guard_architecture.svg", "ClaimIQ - Mail Guard Architecture", cards, arrows)


def intake_spec() -> dict[str, Any]:
    cards = [
        dict(id="email", x=220, y=93, w=230, h=68, accent="blue", icon="EM", title="Claim Email", lines=["free-form text", "6000 char prompt cap"]),
        dict(id="uploaded", x=500, y=93, w=230, h=68, accent="blue", icon="UP", title="Uploaded Docs", lines=["bytes + mime", "images, PDF, text"]),
        dict(id="summaryin", x=780, y=93, w=230, h=68, accent="blue", icon="DS", title="Existing Summary", lines=["attachments.py output", "optional context"]),
        dict(id="schema", x=1060, y=93, w=230, h=68, accent="blue", icon="JS", title="Strict Schema", lines=["30+ fields", "no extra keys"]),
        dict(id="modality", x=220, y=238, w=240, h=78, accent="green", icon="M", title="Modality Split", lines=["image -> vision", "PDF/text -> text", "scanned PDF render"]),
        dict(id="perdoc", x=500, y=238, w=240, h=78, accent="green", icon="PD", title="Per-Document JSON", lines=["document_type", "fields, quality", "risk signals"]),
        dict(id="merge", x=780, y=238, w=240, h=78, accent="green", icon="MG", title="Merge Summaries", lines=["dedupe filenames", "preserve risk", "modalities"]),
        dict(id="reason", x=1060, y=238, w=240, h=78, accent="green", icon="AI", title="Reasoning Extract", lines=["claim facts", "conflicts", "next agent hint"]),
        dict(id="fallback", x=220, y=406, w=240, h=78, accent="purple", icon="FB", title="Deterministic Extract", lines=["policy/date/amount", "document aliases", "claim type"]),
        dict(id="enrich", x=500, y=406, w=240, h=78, accent="purple", icon="EN", title="Enrich Contract", lines=["backfill fields", "missing info logic", "risk merge"]),
        dict(id="reconcile", x=780, y=406, w=240, h=78, accent="purple", icon="RC", title="Reconcile Result", lines=["amount promotion", "document evidence", "status correction"]),
        dict(id="status", x=1060, y=406, w=240, h=78, accent="purple", icon="ST", title="Status Gate", lines=["complete", "needs_review", "incomplete"]),
        dict(id="fields", x=220, y=568, w=240, h=68, accent="teal", icon="OUT", title="Structured Claim", lines=["claimant, policy", "date, amount, type"]),
        dict(id="docsout", x=500, y=568, w=240, h=68, accent="teal", icon="DOC", title="Documents Summary", lines=["per_document", "quality + signals"]),
        dict(id="router", x=780, y=568, w=240, h=68, accent="teal", icon="R", title="Router Input", lines=["intake_status", "missing docs"]),
        dict(id="fraud", x=1060, y=568, w=240, h=68, accent="teal", icon="SIU", title="Fraud Evidence", lines=["risk_indicators", "document signals"]),
        dict(id="boundary", x=220, y=706, w=240, h=60, accent="pink", icon="BD", title="Boundary", lines=["extract facts only", "no adjudication"]),
        dict(id="quality", x=500, y=706, w=240, h=60, accent="pink", icon="Q", title="Quality Gate", lines=["missing docs", "low confidence"]),
        dict(id="audit", x=780, y=706, w=240, h=60, accent="pink", icon="AU", title="Audit Output", lines=["agent_started", "agent_completed"]),
    ]
    arrows = [
        dict(source="uploaded", source_side="bottom", target="modality", target_side="top", kind="flow", via=[(615, 190), (340, 190)]),
        dict(source="modality", source_side="right", target="perdoc", target_side="left", kind="blue", dashed=True),
        dict(source="perdoc", source_side="right", target="merge", target_side="left", kind="flow"),
        dict(source="summaryin", source_side="bottom", target="merge", target_side="top", kind="flow"),
        dict(source="email", source_side="bottom", target="reason", target_side="top", kind="flow", via=[(335, 190), (1180, 190)]),
        dict(source="merge", source_side="right", target="reason", target_side="left", kind="blue", dashed=True),
        dict(source="reason", source_side="bottom", target="enrich", target_side="top", kind="flow", via=[(1180, 365), (620, 365)]),
        dict(source="reason", source_side="bottom", target="fallback", target_side="top", kind="blue", dashed=True, label="on error", via=[(1180, 365), (340, 365)]),
        dict(source="fallback", source_side="right", target="enrich", target_side="left", kind="flow"),
        dict(source="enrich", source_side="right", target="reconcile", target_side="left", kind="flow"),
        dict(source="reconcile", source_side="right", target="status", target_side="left", kind="flow"),
        dict(source="status", source_side="bottom", target="fields", target_side="top", kind="teal", via=[(1180, 525), (340, 525)]),
        dict(source="status", source_side="bottom", target="docsout", target_side="top", kind="teal", via=[(1180, 525), (620, 525)]),
        dict(source="status", source_side="bottom", target="router", target_side="top", kind="teal", via=[(1180, 525), (900, 525)]),
        dict(source="docsout", source_side="right", target="fraud", target_side="left", kind="teal"),
        dict(source="status", source_side="bottom", target="quality", target_side="top", kind="pink", dashed=True, via=[(1180, 666), (620, 666)]),
        dict(source="fields", source_side="bottom", target="audit", target_side="top", kind="pink", dashed=True, via=[(340, 666), (900, 666)]),
    ]
    return module_base("intake_architecture.svg", "ClaimIQ - Intake Architecture", cards, arrows)


def router_spec() -> dict[str, Any]:
    cards = [
        dict(id="session", x=220, y=93, w=250, h=68, accent="blue", icon="S", title="ClaimSession", lines=["snapshot", "outputs + docs"]),
        dict(id="intake", x=535, y=93, w=250, h=68, accent="blue", icon="01", title="Intake Output", lines=["status", "missing info"]),
        dict(id="flags", x=850, y=93, w=250, h=68, accent="blue", icon="ENV", title="Router Flags", lines=["CLAIMIQ_ROUTER_ALWAYS_LLM", "model env vars"]),
        dict(id="pause", x=220, y=238, w=260, h=78, accent="green", icon="PA", title="Pause Check", lines=["intake_status incomplete", "no downstream agents", "customer document request"]),
        dict(id="fast", x=535, y=238, w=260, h=78, accent="green", icon="FP", title="Deterministic Fast Path", lines=["complete/needs_review", "select all four agents"]),
        dict(id="llm", x=850, y=238, w=260, h=78, accent="green", icon="AI", title="Ambiguous LLM Path", lines=["choose_with_openai", "session snapshot"]),
        dict(id="fallback", x=220, y=406, w=260, h=78, accent="purple", icon="FB", title="Fallback Route", lines=["policy present", "risk/amount/date", "human review if sparse"]),
        dict(id="deps", x=535, y=406, w=260, h=78, accent="purple", icon="DEP", title="Dependency Enforcer", lines=["triage needs coverage+fraud", "copilot needs triage"]),
        dict(id="normalize", x=850, y=406, w=260, h=78, accent="purple", icon="N", title="Normalize Route", lines=["next_agent", "claim_status", "confidence"]),
        dict(id="selected", x=220, y=568, w=260, h=68, accent="teal", icon="SEL", title="selected_agents", lines=["coverage, fraud", "triage, copilot"]),
        dict(id="docreq", x=535, y=568, w=260, h=68, accent="teal", icon="REQ", title="Document Request", lines=["pending_customer_documents", "missing_inputs"]),
        dict(id="orchestrator", x=850, y=568, w=260, h=68, accent="teal", icon="LO", title="Orchestrator Loop", lines=["runs in order", "records timing"]),
        dict(id="boundary", x=220, y=706, w=260, h=60, accent="pink", icon="BD", title="Boundary", lines=["selects agents only", "does not adjudicate"]),
        dict(id="determinism", x=535, y=706, w=260, h=60, accent="pink", icon="DT", title="Cost Control", lines=["skip LLM on fixed policy", "LLM only ambiguous"]),
        dict(id="audit", x=850, y=706, w=260, h=60, accent="pink", icon="AU", title="Audit", lines=["route_selected", "reason + confidence"]),
    ]
    arrows = [
        dict(source="session", source_side="right", target="intake", target_side="left", kind="flow"),
        dict(source="intake", source_side="right", target="flags", target_side="left", kind="flow"),
        dict(source="intake", source_side="bottom", target="pause", target_side="top", kind="flow", via=[(660, 190), (350, 190)]),
        dict(source="pause", source_side="right", target="fast", target_side="left", kind="flow", label="not incomplete"),
        dict(source="fast", source_side="right", target="llm", target_side="left", kind="blue", dashed=True, label="if forced/ambiguous"),
        dict(source="llm", source_side="bottom", target="fallback", target_side="top", kind="blue", dashed=True, label="on error", via=[(980, 365), (350, 365)]),
        dict(source="fallback", source_side="right", target="deps", target_side="left", kind="flow"),
        dict(source="fast", source_side="bottom", target="deps", target_side="top", kind="flow"),
        dict(source="llm", source_side="bottom", target="deps", target_side="top", kind="flow", via=[(980, 365), (665, 365)]),
        dict(source="deps", source_side="right", target="normalize", target_side="left", kind="flow"),
        dict(source="normalize", source_side="bottom", target="selected", target_side="top", kind="teal", via=[(980, 525), (350, 525)]),
        dict(source="pause", source_side="bottom", target="docreq", target_side="top", kind="teal", via=[(350, 525), (665, 525)]),
        dict(source="selected", source_side="right", target="orchestrator", target_side="left", kind="teal", via=[(500, 602), (850, 602)]),
        dict(source="normalize", source_side="bottom", target="audit", target_side="top", kind="pink", dashed=True, via=[(980, 666)]),
        dict(source="fast", source_side="bottom", target="determinism", target_side="top", kind="pink", dashed=True, via=[(665, 666)]),
    ]
    return module_base("router_architecture.svg", "ClaimIQ - Router Architecture", cards, arrows)


def coverage_spec() -> dict[str, Any]:
    cards = [
        dict(id="intake", x=220, y=93, w=250, h=68, accent="blue", icon="01", title="Intake Facts", lines=["policy, type, date", "amount + documents"]),
        dict(id="policyid", x=535, y=93, w=250, h=68, accent="blue", icon="POL", title="Policy Number", lines=["customer policy id", "reference profile id"]),
        dict(id="catalogcfg", x=850, y=93, w=250, h=68, accent="blue", icon="CFG", title="Catalog Source", lines=["bigquery/local/auto", "policy docs"]),
        dict(id="lookup", x=220, y=238, w=250, h=78, accent="green", icon="BQ", title="Policy Lookup", lines=["BigQuery policies", "safe empty fallback"]),
        dict(id="catalog", x=515, y=238, w=250, h=78, accent="green", icon="CAT", title="Policy Catalog", lines=["policy_documents table", "local PDF fallback"]),
        dict(id="evidence", x=810, y=238, w=250, h=78, accent="green", icon="E", title="Evidence Builder", lines=["claim-type match", "section snippets", "search terms"]),
        dict(id="derive", x=220, y=406, w=250, h=78, accent="purple", icon="REF", title="Reference Policy", lines=["sample profile", "only with citation"]),
        dict(id="reason", x=515, y=406, w=250, h=78, accent="purple", icon="AI", title="Coverage Reasoner", lines=["policy-only logic", "limits + exclusions", "strict JSON"]),
        dict(id="det", x=810, y=406, w=250, h=78, accent="purple", icon="FB", title="Deterministic Coverage", lines=["active dates", "covered peril", "waiting period"]),
        dict(id="compliance", x=220, y=568, w=250, h=68, accent="teal", icon="IR", title="Compliance Guard", lines=["citations required", "appeals process"]),
        dict(id="calc", x=515, y=568, w=250, h=68, accent="teal", icon="CAL", title="Calculation Method", lines=["sum insured", "deductible, limits"]),
        dict(id="out", x=810, y=568, w=250, h=68, accent="teal", icon="OUT", title="Coverage Output", lines=["covered/not/needs_review", "manual review flag"]),
        dict(id="boundary", x=220, y=706, w=250, h=60, accent="pink", icon="BD", title="Boundary", lines=["coverage only", "no fraud or triage"]),
        dict(id="deny", x=515, y=706, w=250, h=60, accent="pink", icon="DN", title="Denial Safeguard", lines=["specific clause required", "no prohibited basis"]),
        dict(id="audit", x=810, y=706, w=250, h=60, accent="pink", icon="AU", title="Audit", lines=["agent output", "duration_ms"]),
    ]
    arrows = [
        dict(source="intake", source_side="right", target="policyid", target_side="left", kind="flow"),
        dict(source="policyid", source_side="right", target="catalogcfg", target_side="left", kind="flow"),
        dict(source="policyid", source_side="bottom", target="lookup", target_side="top", kind="amber", dashed=True, via=[(660, 190), (345, 190)]),
        dict(source="catalogcfg", source_side="bottom", target="catalog", target_side="top", kind="amber", dashed=True, via=[(975, 190), (640, 190)]),
        dict(source="lookup", source_side="right", target="catalog", target_side="left", kind="flow"),
        dict(source="catalog", source_side="right", target="evidence", target_side="left", kind="flow"),
        dict(source="lookup", source_side="bottom", target="derive", target_side="top", kind="flow"),
        dict(source="evidence", source_side="bottom", target="reason", target_side="top", kind="blue", dashed=True, via=[(935, 365), (640, 365)]),
        dict(source="reason", source_side="right", target="det", target_side="left", kind="blue", dashed=True, label="fallback if error"),
        dict(source="reason", source_side="bottom", target="compliance", target_side="top", kind="flow", via=[(640, 525), (345, 525)]),
        dict(source="det", source_side="bottom", target="compliance", target_side="top", kind="flow", via=[(935, 525), (345, 525)]),
        dict(source="compliance", source_side="right", target="calc", target_side="left", kind="teal"),
        dict(source="calc", source_side="right", target="out", target_side="left", kind="teal"),
        dict(source="compliance", source_side="bottom", target="deny", target_side="top", kind="pink", dashed=True),
        dict(source="out", source_side="bottom", target="audit", target_side="top", kind="pink", dashed=True),
    ]
    return module_base("coverage_architecture.svg", "ClaimIQ - Coverage Architecture", cards, arrows)


def fraud_spec() -> dict[str, Any]:
    cards = [
        dict(id="intake", x=220, y=93, w=250, h=68, accent="blue", icon="01", title="Intake Evidence", lines=["facts + docs", "risk indicators"]),
        dict(id="coverage", x=535, y=93, w=250, h=68, accent="blue", icon="03", title="Coverage Context", lines=["policy dates", "limits"]),
        dict(id="claimid", x=850, y=93, w=250, h=68, accent="blue", icon="ID", title="Claim ID", lines=["exclude self", "duplicate lookup"]),
        dict(id="dupes", x=220, y=238, w=250, h=78, accent="green", icon="BQ", title="Duplicate Lookup", lines=["claims_master", "same sender/type/date", "90 day window"]),
        dict(id="signals", x=515, y=238, w=250, h=78, accent="green", icon="SIG", title="Signal Engine", lines=["weights by claim type", "identity, timeline", "document, billing"]),
        dict(id="watch", x=810, y=238, w=250, h=78, accent="green", icon="WL", title="Benchmarks + Watchlists", lines=["provider risk", "price outliers"]),
        dict(id="score", x=220, y=406, w=250, h=78, accent="purple", icon="100", title="Deterministic Score", lines=["cap at 100", "risk_level", "recommended_action"]),
        dict(id="synth", x=515, y=406, w=250, h=78, accent="purple", icon="AI", title="SIU Explanation", lines=["do not rescore", "explain evidence", "no accusation"]),
        dict(id="fallback", x=810, y=406, w=250, h=78, accent="purple", icon="FB", title="Deterministic Brief", lines=["if OpenAI fails", "same score/action"]),
        dict(id="outscore", x=220, y=568, w=250, h=68, accent="teal", icon="OUT", title="Fraud Output", lines=["score, level", "signals + duplicates"]),
        dict(id="action", x=515, y=568, w=250, h=68, accent="teal", icon="ACT", title="Investigation Action", lines=["continue, request docs", "refer, hold pending SIU"]),
        dict(id="downstream", x=810, y=568, w=250, h=68, accent="teal", icon="05", title="Triage Input", lines=["fraud_score", "human approval reasons"]),
        dict(id="boundary", x=220, y=706, w=250, h=60, accent="pink", icon="BD", title="Boundary", lines=["investigation priority", "not final fraud finding"]),
        dict(id="immut", x=515, y=706, w=250, h=60, accent="pink", icon="LK", title="Immutable Scoring", lines=["LLM cannot change", "signals preserved"]),
        dict(id="audit", x=810, y=706, w=250, h=60, accent="pink", icon="AU", title="Audit", lines=["agent_completed", "fraud_score"]),
    ]
    arrows = [
        dict(source="intake", source_side="right", target="coverage", target_side="left", kind="flow"),
        dict(source="coverage", source_side="right", target="claimid", target_side="left", kind="flow"),
        dict(source="claimid", source_side="bottom", target="dupes", target_side="top", kind="amber", dashed=True, via=[(975, 190), (345, 190)]),
        dict(source="dupes", source_side="right", target="signals", target_side="left", kind="flow"),
        dict(source="watch", source_side="left", target="signals", target_side="right", kind="flow"),
        dict(source="signals", source_side="bottom", target="score", target_side="top", kind="flow", via=[(640, 365), (345, 365)]),
        dict(source="score", source_side="right", target="synth", target_side="left", kind="blue", dashed=True),
        dict(source="synth", source_side="right", target="fallback", target_side="left", kind="blue", dashed=True, label="on error"),
        dict(source="synth", source_side="bottom", target="outscore", target_side="top", kind="teal", via=[(640, 525), (345, 525)]),
        dict(source="fallback", source_side="bottom", target="outscore", target_side="top", kind="teal", via=[(935, 525), (345, 525)]),
        dict(source="outscore", source_side="right", target="action", target_side="left", kind="teal"),
        dict(source="action", source_side="right", target="downstream", target_side="left", kind="teal"),
        dict(source="score", source_side="bottom", target="immut", target_side="top", kind="pink", dashed=True),
        dict(source="outscore", source_side="bottom", target="boundary", target_side="top", kind="pink", dashed=True),
        dict(source="downstream", source_side="bottom", target="audit", target_side="top", kind="pink", dashed=True),
    ]
    return module_base("fraud_architecture.svg", "ClaimIQ - Fraud Architecture", cards, arrows)


def triage_spec() -> dict[str, Any]:
    cards = [
        dict(id="intake", x=220, y=93, w=250, h=68, accent="blue", icon="01", title="Intake", lines=["claim type", "clinical facts"]),
        dict(id="coverage", x=535, y=93, w=250, h=68, accent="blue", icon="03", title="Coverage", lines=["status", "manual review"]),
        dict(id="fraud", x=850, y=93, w=250, h=68, accent="blue", icon="04", title="Fraud", lines=["score", "signals"]),
        dict(id="hard", x=220, y=238, w=250, h=78, accent="green", icon="HR", title="Approval Reasons", lines=["high fraud", "coverage review", "high value/type"]),
        dict(id="clinical", x=515, y=238, w=250, h=78, accent="green", icon="CL", title="Clinical Assessment", lines=["emergency terms", "vitals", "specialist mapping"]),
        dict(id="nonmedical", x=810, y=238, w=250, h=78, accent="green", icon="NM", title="Non-Medical Urgency", lines=["total loss", "stranded/displaced", "domain reviewer"]),
        dict(id="synth", x=220, y=406, w=250, h=78, accent="purple", icon="AI", title="Triage Synthesis", lines=["UM reviewer role", "clinical urgency", "not coverage/fraud"]),
        dict(id="safe", x=515, y=406, w=250, h=78, accent="purple", icon="FB", title="Safe Triage", lines=["hard-rule fallback", "SLA map", "priority/color"]),
        dict(id="override", x=810, y=406, w=250, h=78, accent="purple", icon="OV", title="Hard Overrides", lines=["no downgrades", "emergency stays red", "medical docs request"]),
        dict(id="routing", x=220, y=568, w=250, h=68, accent="teal", icon="OUT", title="Routing Output", lines=["route + priority", "triage_color"]),
        dict(id="sla", x=515, y=568, w=250, h=68, accent="teal", icon="SLA", title="SLA + Specialist", lines=["sla_hours", "reviewer type"]),
        dict(id="approval", x=810, y=568, w=250, h=68, accent="teal", icon="OK", title="Human Approval", lines=["required flag", "reason list"]),
        dict(id="boundary", x=220, y=706, w=250, h=60, accent="pink", icon="BD", title="Boundary", lines=["does not decide coverage", "does not decide fraud"]),
        dict(id="clinicalflags", x=515, y=706, w=250, h=60, accent="pink", icon="FL", title="Clinical Flags", lines=["mismatch, vitals", "missing evidence"]),
        dict(id="audit", x=810, y=706, w=250, h=60, accent="pink", icon="AU", title="Audit", lines=["routing payload", "duration_ms"]),
    ]
    arrows = [
        dict(source="intake", source_side="right", target="coverage", target_side="left", kind="flow"),
        dict(source="coverage", source_side="right", target="fraud", target_side="left", kind="flow"),
        dict(source="intake", source_side="bottom", target="hard", target_side="top", kind="flow", via=[(345, 190)]),
        dict(source="intake", source_side="bottom", target="clinical", target_side="top", kind="flow", via=[(345, 190), (640, 190)]),
        dict(source="clinical", source_side="right", target="nonmedical", target_side="left", kind="flow"),
        dict(source="hard", source_side="bottom", target="synth", target_side="top", kind="blue", dashed=True),
        dict(source="clinical", source_side="bottom", target="safe", target_side="top", kind="flow"),
        dict(source="nonmedical", source_side="bottom", target="override", target_side="top", kind="flow"),
        dict(source="synth", source_side="right", target="safe", target_side="left", kind="blue", dashed=True, label="fallback if error"),
        dict(source="safe", source_side="right", target="override", target_side="left", kind="flow"),
        dict(source="override", source_side="bottom", target="routing", target_side="top", kind="teal", via=[(935, 525), (345, 525)]),
        dict(source="routing", source_side="right", target="sla", target_side="left", kind="teal"),
        dict(source="sla", source_side="right", target="approval", target_side="left", kind="teal"),
        dict(source="override", source_side="bottom", target="clinicalflags", target_side="top", kind="pink", dashed=True, via=[(935, 666), (640, 666)]),
        dict(source="approval", source_side="bottom", target="audit", target_side="top", kind="pink", dashed=True),
    ]
    return module_base("triage_architecture.svg", "ClaimIQ - Triage Architecture", cards, arrows)


def copilot_spec() -> dict[str, Any]:
    cards = [
        dict(id="intake", x=220, y=93, w=220, h=68, accent="blue", icon="01", title="Intake", lines=["claim facts", "documents"]),
        dict(id="coverage", x=485, y=93, w=220, h=68, accent="blue", icon="03", title="Coverage", lines=["policy position", "citations"]),
        dict(id="fraud", x=750, y=93, w=220, h=68, accent="blue", icon="04", title="Fraud", lines=["signals", "risk action"]),
        dict(id="triage", x=1015, y=93, w=220, h=68, accent="blue", icon="05", title="Triage", lines=["route", "SLA + approval"]),
        dict(id="synth", x=220, y=238, w=250, h=78, accent="green", icon="AI", title="Brief Synthesis", lines=["employee copilot", "strict JSON", "use supplied outputs"]),
        dict(id="fallback", x=515, y=238, w=250, h=78, accent="green", icon="FB", title="Fallback Brief", lines=["claim details", "coverage/fraud/routing", "open questions"]),
        dict(id="evidence", x=810, y=238, w=250, h=78, accent="green", icon="EV", title="Evidence Log", lines=["agent status", "completed_at"]),
        dict(id="enrich", x=220, y=406, w=250, h=78, accent="purple", icon="EN", title="Enrich Contract", lines=["citations", "plain English", "role assistance"]),
        dict(id="timeline", x=515, y=406, w=250, h=78, accent="purple", icon="TL", title="Timeline + Next Steps", lines=["claim chronology", "missing items", "review actions"]),
        dict(id="letters", x=810, y=406, w=250, h=78, accent="purple", icon="LT", title="Generated Drafts", lines=["document request", "hospital clarification", "internal note"]),
        dict(id="markdown", x=220, y=568, w=250, h=68, accent="teal", icon="MD", title="Adjuster Markdown", lines=["human boundary", "claim snapshot"]),
        dict(id="report", x=515, y=568, w=250, h=68, accent="teal", icon="PDF", title="Report Input", lines=["PDF sections", "evidence/citations"]),
        dict(id="tools", x=810, y=568, w=250, h=68, accent="teal", icon="TO", title="Recommended Tools", lines=["RAG, calculator", "letters, timeline"]),
        dict(id="boundary", x=220, y=706, w=250, h=60, accent="pink", icon="BD", title="Decision Boundary", lines=["does not approve", "does not deny/settle"]),
        dict(id="roles", x=515, y=706, w=250, h=60, accent="pink", icon="RL", title="Role Views", lines=["claims, SIU", "medical, audit"]),
        dict(id="audit", x=810, y=706, w=250, h=60, accent="pink", icon="AU", title="Audit", lines=["agent_completed", "triage_color"]),
    ]
    arrows = [
        dict(source="intake", source_side="right", target="coverage", target_side="left", kind="flow"),
        dict(source="coverage", source_side="right", target="fraud", target_side="left", kind="flow"),
        dict(source="fraud", source_side="right", target="triage", target_side="left", kind="flow"),
        dict(source="coverage", source_side="bottom", target="synth", target_side="top", kind="blue", dashed=True, via=[(595, 190), (345, 190)]),
        dict(source="synth", source_side="right", target="fallback", target_side="left", kind="blue", dashed=True, label="on error"),
        dict(source="fallback", source_side="right", target="evidence", target_side="left", kind="flow"),
        dict(source="synth", source_side="bottom", target="enrich", target_side="top", kind="flow"),
        dict(source="evidence", source_side="bottom", target="enrich", target_side="top", kind="flow", via=[(935, 365), (345, 365)]),
        dict(source="enrich", source_side="right", target="timeline", target_side="left", kind="flow"),
        dict(source="timeline", source_side="right", target="letters", target_side="left", kind="flow"),
        dict(source="letters", source_side="bottom", target="markdown", target_side="top", kind="teal", via=[(935, 525), (345, 525)]),
        dict(source="markdown", source_side="right", target="report", target_side="left", kind="teal"),
        dict(source="report", source_side="right", target="tools", target_side="left", kind="teal"),
        dict(source="enrich", source_side="bottom", target="roles", target_side="top", kind="pink", dashed=True, via=[(345, 666), (640, 666)]),
        dict(source="markdown", source_side="bottom", target="boundary", target_side="top", kind="pink", dashed=True),
        dict(source="tools", source_side="bottom", target="audit", target_side="top", kind="pink", dashed=True),
    ]
    return module_base("copilot_architecture.svg", "ClaimIQ - Copilot Architecture", cards, arrows)


def write_readme() -> None:
    files = [
        ("prototype_architecture.svg", "End-to-end prototype pipeline"),
        ("orchestrator_architecture.svg", "Session orchestration, stage loop, finish policy"),
        ("mail_guard_architecture.svg", "Front-door email relevance and rewrite gate"),
        ("intake_architecture.svg", "Multimodal intake extraction and reconciliation"),
        ("router_architecture.svg", "Downstream agent selection and dependency enforcement"),
        ("coverage_architecture.svg", "Policy evidence, coverage reasoning, compliance guardrails"),
        ("fraud_architecture.svg", "SIU-style fraud scoring and explanation"),
        ("triage_architecture.svg", "Clinical/non-medical urgency, SLA, human approval"),
        ("copilot_architecture.svg", "Employee copilot brief, citations, role views"),
    ]
    lines = [
        "# ClaimIQ Architecture Diagrams",
        "",
        "Generated SVG assets for the ClaimIQ prototype. The visual style matches the dark layered architecture diagram used on the ClaimIQ website.",
        "",
        "Regenerate with:",
        "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe docs\\architecture\\generate_diagrams.py",
        "```",
        "",
        "| File | Purpose |",
        "| --- | --- |",
    ]
    lines.extend(f"| [{name}]({name}) | {purpose} |" for name, purpose in files)
    lines.append("")
    lines.append("Legend colors are consistent across files: solid green for primary data flow, dashed blue for model calls, dashed amber for evidence/storage, dashed teal for outputs, and dashed pink for control or guardrails.")
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    specs = [
        overall_spec(),
        orchestrator_spec(),
        mail_guard_spec(),
        intake_spec(),
        router_spec(),
        coverage_spec(),
        fraud_spec(),
        triage_spec(),
        copilot_spec(),
    ]
    for spec in specs:
        render(spec)
    write_readme()
    print(f"Generated {len(specs)} SVG diagrams in {OUT_DIR}")


if __name__ == "__main__":
    main()
