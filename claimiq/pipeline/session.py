"""State container for one ClaimIQ processing session."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal


WorkflowState = Literal[
    "initialized",
    "guard_passed",
    "intake_complete",
    "routing_decided",
    "agents_running",
    "complete",
    "failed",
]

AGENT_OUTPUT_FIELDS = {
    "guard": "guard_output",
    "intake": "intake_output",
    "coverage": "coverage_output",
    "fraud": "fraud_output",
    "triage": "triage_output",
    "copilot": "copilot_output",
}

VALID_TRANSITIONS: dict[str, set[str]] = {
    "initialized": {"guard_passed", "failed"},
    "guard_passed": {"intake_complete", "complete", "failed"},
    "intake_complete": {"routing_decided", "complete", "failed"},
    "routing_decided": {"agents_running", "complete", "failed"},
    "agents_running": {"complete", "failed"},
    "complete": set(),
    "failed": set(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ClaimSession:
    claim_id: str
    email_body: str
    sender_email: str = ""
    subject: str = ""
    documents_summary: dict[str, Any] | None = None
    uploaded_documents: list[dict[str, Any]] | None = None

    workflow_state: WorkflowState = "initialized"
    workflow_version: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    guard_output: dict[str, Any] = field(default_factory=dict)
    route: dict[str, Any] = field(default_factory=dict)
    intake_output: dict[str, Any] = field(default_factory=dict)
    coverage_output: dict[str, Any] = field(default_factory=dict)
    fraud_output: dict[str, Any] = field(default_factory=dict)
    triage_output: dict[str, Any] = field(default_factory=dict)
    copilot_output: dict[str, Any] = field(default_factory=dict)
    agent_errors: dict[str, list[str]] = field(default_factory=dict)
    agent_timings: dict[str, dict[str, Any]] = field(default_factory=dict)

    send_emails: bool = False
    in_reply_to: str = ""

    @property
    def guard(self) -> dict[str, Any]:
        return self.guard_output

    @property
    def outputs(self) -> dict[str, dict[str, Any]]:
        ordered = {
            "intake": self.intake_output,
            "coverage": self.coverage_output,
            "fraud": self.fraud_output,
            "triage": self.triage_output,
            "copilot": self.copilot_output,
        }
        return {name: output for name, output in ordered.items() if output}

    @property
    def errors(self) -> dict[str, str]:
        return {
            agent: "; ".join(messages)
            for agent, messages in self.agent_errors.items()
            if messages
        }

    def document_context(self) -> dict[str, Any]:
        return self.documents_summary or {}

    def transition_state(self, new_state: WorkflowState) -> "ClaimSession":
        allowed = VALID_TRANSITIONS.get(self.workflow_state, set())
        if new_state not in allowed:
            raise ValueError(f"Invalid transition: {self.workflow_state} -> {new_state}")
        return replace(
            self,
            workflow_state=new_state,
            workflow_version=self.workflow_version + 1,
            updated_at=_utcnow(),
        )

    def set_guard(self, output: dict[str, Any]) -> "ClaimSession":
        return replace(self, guard_output=dict(output or {}), updated_at=_utcnow())

    def set_route(self, route: dict[str, Any]) -> "ClaimSession":
        return replace(self, route=dict(route or {}), updated_at=_utcnow())

    def add_agent_output(self, agent_name: str, output: dict[str, Any]) -> "ClaimSession":
        if agent_name not in AGENT_OUTPUT_FIELDS or agent_name == "guard":
            raise ValueError(f"Unknown agent: {agent_name}")
        return replace(
            self,
            **{AGENT_OUTPUT_FIELDS[agent_name]: dict(output or {})},
            updated_at=_utcnow(),
        )

    def add_agent_timing(
        self,
        agent_name: str,
        started_at: str,
        completed_at: str,
        duration_ms: int,
    ) -> "ClaimSession":
        """Record real per-agent execution timestamps for audit trails."""
        timings = {name: dict(entry) for name, entry in self.agent_timings.items()}
        timings[agent_name] = {
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": int(duration_ms),
        }
        return replace(self, agent_timings=timings, updated_at=_utcnow())

    def add_agent_error(self, agent_name: str, error: str) -> "ClaimSession":
        new_errors = {name: list(messages) for name, messages in self.agent_errors.items()}
        new_errors.setdefault(agent_name, []).append(str(error))
        return replace(self, agent_errors=new_errors, updated_at=_utcnow())

    def snapshot(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "sender_email": self.sender_email,
            "subject": self.subject,
            "workflow_state": self.workflow_state,
            "workflow_version": self.workflow_version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "guard": self.guard_output,
            "route": self.route,
            "outputs": self.outputs,
            "errors": self.errors,
            "agent_errors": self.agent_errors,
            "documents_summary": self.documents_summary or {},
            "uploaded_document_count": len(self.uploaded_documents or []),
        }
