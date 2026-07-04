"""Session-based ClaimIQ pipeline orchestrator."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

from claimiq.agents import copilot, coverage, fraud, intake, triage
from claimiq.shared.audit import write_audit_event
from claimiq.shared.validation import InputValidator
from claimiq.pipeline.mail_guard import evaluate_email
from claimiq.pipeline.router import choose_agents
from claimiq.pipeline.session import ClaimSession
from claimiq.tools.email_tool import send_claim_update, should_send_fraud_alert
from claimiq.tools.report_tool import generate_claim_report, should_generate_report

log = logging.getLogger(__name__)


def run_pipeline(
    *,
    claim_id: str,
    email_body: str,
    sender_email: str = "",
    subject: str = "",
    documents_summary: dict[str, Any] | None = None,
    uploaded_documents: list[dict[str, Any]] | None = None,
    guard_result: dict[str, Any] | None = None,
    # ── Email update options ───────────────────────────────────────────────
    send_emails: bool = False,
    in_reply_to: str = "",
) -> dict[str, Any]:
    """
    Run the full 5-agent ClaimIQ pipeline.

    Parameters
    ----------
    send_emails : bool
        When True, the orchestrator sends mid-pipeline status emails to the
        claimant after Coverage, Fraud (HIGH/CRITICAL only), and Triage agents.
        Also exposes send_update() on the returned result for post-pipeline
        custom emails driven by an orchestrator instruction.
    in_reply_to : str
        Gmail Message-ID of the original claim email. Used to thread all
        outbound updates in the same inbox conversation.
    """
    start = time.time()
    session = ClaimSession(
        claim_id=claim_id,
        email_body=email_body,
        sender_email=sender_email,
        subject=subject,
        documents_summary=documents_summary,
        uploaded_documents=uploaded_documents,
        send_emails=send_emails,
        in_reply_to=in_reply_to,
    )

    # ── Input validation (non-fatal) ──────────────────────────────────────────
    # Oversized or malformed inputs are a customer-communication problem, not a
    # system crash: route them through the rewrite_request path so run.py sends
    # the structured resend form instead of the whole poll cycle blowing up.
    try:
        InputValidator.validate_pipeline_inputs(
            email_body=email_body,
            subject=subject,
            documents_summary=documents_summary,
            uploaded_documents=uploaded_documents,
        )
    except ValueError as exc:
        from claimiq.pipeline.mail_guard import _rewrite_body
        validation_guard = {
            "action": "rewrite_request",
            "is_relevant": True,
            "missing_fields": [],
            "reason": f"Input validation failed: {exc}",
            "reply_subject": "",
            "reply_body": _rewrite_body([]),
            "confidence": 1.0,
            "_validation_error": str(exc),
        }
        write_audit_event(claim_id, "input_validation_failed", "orchestrator", payload={"error": str(exc)})
        session = session.set_guard(validation_guard).transition_state("guard_passed")
        return _finish(session.transition_state("complete"), start, "rewrite_required")

    write_audit_event(claim_id, "pipeline_started", "orchestrator", payload={"sender_email": sender_email, "subject": subject})

    session = session.set_guard(guard_result or evaluate_email(email_body, subject))
    session = session.transition_state("guard_passed")
    write_audit_event(claim_id, "mail_guard_completed", "orchestrator", payload=session.guard)
    if session.guard.get("action") == "rewrite_request":
        return _finish(session.transition_state("complete"), start, "rewrite_required")

    intake_started_at, intake_t0 = _stage_clock()
    try:
        intake_output = intake.run(claim_id, email_body, documents_summary, uploaded_documents)
        intake_output["sender_email"] = sender_email
        session = session.add_agent_output("intake", intake_output)
        session = session.add_agent_timing("intake", intake_started_at, *_stage_elapsed(intake_t0))
        session = session.transition_state("intake_complete")
    except Exception as exc:
        session = session.add_agent_timing("intake", intake_started_at, *_stage_elapsed(intake_t0))
        session = session.add_agent_error("intake", str(exc)).transition_state("failed")
        return _finish(session, start, "error")

    session = session.set_route(choose_agents(session))
    session = session.transition_state("routing_decided")
    write_audit_event(claim_id, "route_selected", "orchestrator", payload=session.route)

    if not session.route.get("selected_agents"):
        return _finish(session.transition_state("complete"), start, "intake_only")

    session = session.transition_state("agents_running")
    for agent_name in session.route.get("selected_agents", []):
        session = _run_selected_stage(session, agent_name)

    status = "partial" if session.errors else "complete"
    terminal_state = "failed" if session.errors else "complete"
    return _finish(session.transition_state(terminal_state), start, status)


def _run_stage(name: str, fn) -> tuple[dict[str, Any], str | None]:
    try:
        return fn(), None
    except Exception as exc:
        log.exception("Stage %s failed", name)
        return {"error": str(exc)}, str(exc)


def _stage_clock() -> tuple[str, float]:
    """Return (ISO start timestamp, monotonic-ish reference) for stage timing."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(), time.time()


def _stage_elapsed(t0: float) -> tuple[str, int]:
    """Return (ISO completion timestamp, duration_ms) since t0."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(), int((time.time() - t0) * 1000)


def _run_selected_stage(session: ClaimSession, agent_name: str) -> ClaimSession:
    stage_map = {
        "coverage": lambda: coverage.run(session.claim_id, session.outputs["intake"]),
        "fraud": lambda: fraud.run(session.claim_id, session.outputs["intake"], session.outputs.get("coverage", {})),
        "triage": lambda: triage.run(
            session.claim_id,
            session.outputs["intake"],
            session.outputs.get("coverage", {}),
            session.outputs.get("fraud", {}),
        ),
        "copilot": lambda: copilot.run(
            session.claim_id,
            session.outputs["intake"],
            session.outputs.get("coverage", {}),
            session.outputs.get("fraud", {}),
            session.outputs.get("triage", {}),
        ),
    }
    started_at, t0 = _stage_clock()
    output, error = _run_stage(agent_name, stage_map[agent_name])
    session = session.add_agent_output(agent_name, output)
    session = session.add_agent_timing(agent_name, started_at, *_stage_elapsed(t0))
    if error:
        session = session.add_agent_error(agent_name, error)

    # ── Auto email updates ────────────────────────────────────────────────────
    if session.send_emails and session.sender_email:
        _maybe_send_stage_email(session, agent_name)
    return session


def _maybe_send_stage_email(session: ClaimSession, completed_agent: str) -> None:
    """
    Fire a customer email update after a specific agent completes.

    Triggered automatically:
      coverage → coverage_verified  or coverage_needs_review
      fraud    → fraud_alert         (only when score >= FRAUD_EMAIL_THRESHOLD)
      triage   → routing_assigned

    All updates use "Re: {original subject}" so Gmail threads them into the
    original claim conversation instead of creating new inbox entries.
    """
    to_email    = session.sender_email
    claim_id    = session.claim_id
    in_reply_to = session.in_reply_to
    outputs     = session.outputs

    # Thread all replies under the original email's subject
    orig_subject   = session.subject or ""
    reply_subject  = f"Re: {orig_subject}" if orig_subject else None

    ctx = {k: outputs[k] for k in ("intake", "coverage", "fraud", "triage", "copilot") if k in outputs}

    try:
        if completed_agent == "coverage":
            cov_status = outputs.get("coverage", {}).get("coverage_status", "needs_review")
            stage = "coverage_verified" if cov_status == "covered" else "coverage_needs_review"
            send_claim_update(stage, claim_id, to_email, ctx,
                              in_reply_to=in_reply_to, subject_override=reply_subject)

        elif completed_agent == "fraud":
            if should_send_fraud_alert(outputs.get("fraud", {})):
                send_claim_update("fraud_alert", claim_id, to_email, ctx,
                                  in_reply_to=in_reply_to, subject_override=reply_subject)

        elif completed_agent == "triage":
            send_claim_update("routing_assigned", claim_id, to_email, ctx,
                              in_reply_to=in_reply_to, subject_override=reply_subject)

    except Exception as exc:
        log.warning("[EmailTool] Failed to send %s update for %s: %s", completed_agent, claim_id, exc)


def send_orchestrator_email(
    claim_id: str,
    to_email: str,
    instruction: str,
    context: dict[str, Any],
    *,
    in_reply_to: str = "",
) -> bool:
    """
    Convenience function for the orchestrator (or external callers) to send a
    custom AI-drafted email at any point in or after the pipeline.

    Parameters
    ----------
    claim_id    : Claim reference ID.
    to_email    : Recipient address.
    instruction : Natural-language description of what the email should say.
                  Example: "The fraud score is 75. Tell the customer their claim needs
                  specialist review and the SLA is 120 hours. Be empathetic."
    context     : Dict with any available agent outputs keyed by agent name.
    in_reply_to : Message-ID for Gmail thread linking.

    Returns
    -------
    bool — True if the email was sent successfully.
    """
    return send_claim_update(
        stage="custom",
        claim_id=claim_id,
        to_email=to_email,
        context=context,
        instruction=instruction,
        in_reply_to=in_reply_to,
    )


def _finish(session: ClaimSession, start: float, status: str) -> dict[str, Any]:
    duration_ms = int((time.time() - start) * 1000)
    outputs = session.outputs

    # ── Conditional PDF report generation ─────────────────────────────────────
    # The orchestrator decides whether a detailed PDF brief is warranted.
    # Generated when: human approval required, medium+ fraud, high-value claim,
    # or uncertain coverage.  Returned as bytes so callers can attach to email.
    report_pdf_bytes: bytes | None = None
    if status in ("complete", "partial", "intake_only") and should_generate_report(outputs):
        try:
            report_pdf_bytes = generate_claim_report(
                session.claim_id, outputs, agent_timings=session.agent_timings,
            )
            if report_pdf_bytes:
                log.info(
                    "[Orchestrator] PDF report generated for %s — %d bytes",
                    session.claim_id, len(report_pdf_bytes),
                )
        except Exception as exc:
            log.warning("[Orchestrator] PDF report generation failed for %s: %s",
                        session.claim_id, exc)

    summary = {
        "claim_id": session.claim_id,
        "status": status,
        "workflow_state": _workflow_state(session, status),
        "session": {
            "workflow_state": session.workflow_state,
            "workflow_version": session.workflow_version,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        },
        "guard": session.guard,
        "route": session.route,
        "triage_color": outputs.get("triage", {}).get("triage_color"),
        "fraud_score": outputs.get("fraud", {}).get("fraud_score"),
        "required_human_approval": outputs.get("triage", {}).get("required_human_approval", True),
        "outputs": outputs,
        "errors": session.errors,
        "agent_errors": session.agent_errors,
        "agent_timings": session.agent_timings,
        "duration_ms": duration_ms,
        # Callers (e.g. app/run.py) should attach this to the pipeline_complete email
        "report_pdf_bytes": report_pdf_bytes,
    }
    write_audit_event(session.claim_id, "pipeline_completed", "orchestrator", payload={
        "status": status,
        "errors": session.errors,
        "selected_agents": session.route.get("selected_agents", []),
        "claim_status": session.route.get("claim_status"),
        "next_agent": session.route.get("next_agent"),
        "triage_color": summary["triage_color"],
        "fraud_score": summary["fraud_score"],
        "report_generated": report_pdf_bytes is not None,
        "workflow_state": session.workflow_state,
        "workflow_version": session.workflow_version,
    }, duration_ms=duration_ms)
    return summary


def _workflow_state(session: ClaimSession, status: str) -> dict[str, Any]:
    intake = session.outputs.get("intake", {})
    selected = session.route.get("selected_agents", [])
    if status == "rewrite_required":
        current_stage = "mail_guard"
        previous_stage = "claim_received"
        next_stage = "customer_rewrite_request"
    elif intake.get("intake_status") == "incomplete":
        current_stage = "intake_validation"
        previous_stage = "claim_received"
        next_stage = "customer_document_request"
    elif selected:
        current_stage = selected[-1] if selected[-1] in session.outputs else "downstream_review"
        previous_stage = "intake_validation"
        next_stage = session.route.get("next_agent") or selected[0]
    else:
        current_stage = "intake_validation"
        previous_stage = "claim_received"
        next_stage = session.route.get("next_agent", "human_reviewer")

    return {
        "claim_id": session.claim_id,
        "session_state": session.workflow_state,
        "workflow_version": session.workflow_version,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "current_stage": current_stage,
        "previous_stage": previous_stage,
        "next_stage": next_stage,
        "status": session.route.get("claim_status") or status,
        "responsible_agent": session.route.get("next_agent") or next_stage,
        "completed_agents": list(session.outputs.keys()),
        "pending_agents": [agent for agent in selected if agent not in session.outputs],
        "required_action": session.route.get("required_action", ""),
    }


def _load_sample(path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    sample = _load_sample(args.sample)
    result = run_pipeline(
        claim_id=sample["claim_id"],
        email_body=sample["email_body"],
        sender_email=sample.get("sender_email", ""),
        subject=sample.get("subject", ""),
        documents_summary=sample.get("documents_summary"),
    )
    print(json.dumps(result, indent=2 if args.pretty else None, default=str))


if __name__ == "__main__":
    main()
