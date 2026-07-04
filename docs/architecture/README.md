# ClaimIQ Architecture Diagrams

Generated SVG assets for the ClaimIQ prototype. The visual style matches the dark layered architecture diagram used on the ClaimIQ website.

Regenerate with:

```powershell
.\.venv\Scripts\python.exe docs\architecture\generate_diagrams.py
```

| File | Purpose |
| --- | --- |
| [prototype_architecture.svg](prototype_architecture.svg) | End-to-end prototype pipeline |
| [orchestrator_architecture.svg](orchestrator_architecture.svg) | Session orchestration, stage loop, finish policy |
| [mail_guard_architecture.svg](mail_guard_architecture.svg) | Front-door email relevance and rewrite gate |
| [intake_architecture.svg](intake_architecture.svg) | Multimodal intake extraction and reconciliation |
| [router_architecture.svg](router_architecture.svg) | Downstream agent selection and dependency enforcement |
| [coverage_architecture.svg](coverage_architecture.svg) | Policy evidence, coverage reasoning, compliance guardrails |
| [fraud_architecture.svg](fraud_architecture.svg) | SIU-style fraud scoring and explanation |
| [triage_architecture.svg](triage_architecture.svg) | Clinical/non-medical urgency, SLA, human approval |
| [copilot_architecture.svg](copilot_architecture.svg) | Employee copilot brief, citations, role views |

Legend colors are consistent across files: solid green for primary data flow, dashed blue for model calls, dashed amber for evidence/storage, dashed teal for outputs, and dashed pink for control or guardrails.
