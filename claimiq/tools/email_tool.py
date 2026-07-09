"""
ClaimIQ Email Tool
==================
A general-purpose email tool callable by the pipeline orchestrator or any agent.

Two modes:
  1. Stage-based  — send_claim_update(stage="coverage_verified", ...)
                    Uses built-in professional templates. No extra LLM call.
  2. AI-drafted   — send_claim_update(stage="custom", instruction="...", ...)
                    GPT composes the full email from the orchestrator instruction
                    plus available claim context.  Falls back to a template on failure.

Auto-trigger stages wired into the orchestrator:
  • coverage_verified / coverage_needs_review  — after Coverage Agent
  • fraud_alert                                — after Fraud Agent (score >= 50 only)
  • routing_assigned                           — after Triage Agent

Manual / custom usage:
    from claimiq.tools.email_tool import send_claim_update

    send_claim_update(
        stage="custom",
        claim_id="CLM-20260627-ABCD",
        to_email="customer@example.com",
        context={"intake": {...}, "fraud": {...}},
        instruction=(
            "The fraud score is 75 and the claim needs specialist review. "
            "Tell the customer politely that additional checks are required "
            "and give a 120-hour SLA. Do not mention fraud score numbers."
        ),
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import textwrap
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger(__name__)

# ── Runtime config ────────────────────────────────────────────────────────────

GMAIL_ADDRESS        = os.getenv("GMAIL_ADDRESS", "claim.iq.ai.001@gmail.com")
GMAIL_APP_PW         = os.getenv("GMAIL_APP_PASSWORD", "")
FRAUD_EMAIL_THRESHOLD = int(os.getenv("FRAUD_EMAIL_THRESHOLD", "50"))  # send alert at >= this score


def _upper_label(value: Any, default: str = "N/A") -> str:
    text = str(value if value not in (None, "") else default)
    return text.upper()


def _as_list(value: Any) -> list[Any]:
    """Coerce optional list-like output without splitting plain strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        lines = [
            re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            for line in text.splitlines()
        ]
        lines = [line for line in lines if line]
        return lines if len(lines) > 1 else [text]
    return [value]

# ── Known pipeline stages ──────────────────────────────────────────────────────

KNOWN_STAGES = frozenset({
    "claim_received",       # instant acknowledgment on email arrival
    "coverage_verified",    # policy active and covers the claim
    "coverage_needs_review",# policy unclear, not found, or not covered
    "fraud_alert",          # HIGH or CRITICAL risk — specialist review triggered
    "routing_assigned",     # triage complete — priority, queue, and SLA assigned
    "pipeline_complete",    # all 5 agents done — full summary
    "custom",               # orchestrator-driven: instruction → AI-drafted body
})


# ── Public API ────────────────────────────────────────────────────────────────

def send_claim_update(
    stage: str,
    claim_id: str,
    to_email: str,
    context: dict[str, Any],
    *,
    instruction: str | None = None,
    in_reply_to: str = "",
    subject_override: str | None = None,
    attachments: list[dict] | None = None,
) -> bool:
    """
    Send a claim status update email to the claimant.

    Parameters
    ----------
    stage : str
        Pipeline stage identifier.  One of KNOWN_STAGES.
        Pass "custom" together with an `instruction` for AI-generated emails.
    claim_id : str
        Claim reference ID (e.g. CLM-20260627-ABCD1234).
    to_email : str
        Recipient email address.
    context : dict
        Any combination of agent outputs available at call time:
        {"intake": {...}, "coverage": {...}, "fraud": {...}, "triage": {...}, "copilot": {...}}
    instruction : str, optional
        Natural-language orchestrator instruction.  When present, GPT composes
        the email body from the instruction + claim context.
        Example: "The fraud score is 75.  Warn the customer their claim needs
                  specialist review and give a 120-hour SLA.  Be empathetic."
    in_reply_to : str, optional
        Message-ID of the original claim email for Gmail thread linking.
    subject_override : str, optional
        Override the auto-generated subject line.
    attachments : list[dict], optional
        Optional file attachments.  Each dict must have:
          {"filename": "report.pdf", "data": bytes, "mime_type": "application/pdf"}
        "mime_type" defaults to "application/octet-stream" if omitted.

    Returns
    -------
    bool
        True on successful send, False on failure.
    """
    if not to_email:
        log.warning("[EmailTool] No recipient — skipping email stage=%s claim=%s", stage, claim_id)
        return False

    if stage not in KNOWN_STAGES:
        log.warning("[EmailTool] Unknown stage '%s' — using generic update template", stage)
        stage = "custom"

    # ── Compose ───────────────────────────────────────────────────────────────
    if instruction:
        subject, body = _compose_with_ai(stage, claim_id, context, instruction)
    else:
        subject, body = _get_template(stage, claim_id, context)

    if subject_override:
        subject = subject_override

    # ── Send ──────────────────────────────────────────────────────────────────
    ok = _smtp_send(to_email, subject, body, in_reply_to, attachments)
    log.info(
        "[EmailTool] stage=%-22s claim=%s to=%s sent=%s",
        stage, claim_id, to_email, ok,
    )
    return ok


def should_send_fraud_alert(fraud_output: dict[str, Any]) -> bool:
    """
    Return True when the fraud score warrants sending a customer alert email.
    Threshold controlled by FRAUD_EMAIL_THRESHOLD env var (default 50).
    """
    score = int(fraud_output.get("fraud_score") or 0)
    return score >= FRAUD_EMAIL_THRESHOLD


# ── AI-drafted composition ────────────────────────────────────────────────────

def _compose_with_ai(
    stage: str,
    claim_id: str,
    context: dict[str, Any],
    instruction: str,
) -> tuple[str, str]:
    """
    Ask GPT to draft a professional email from the orchestrator instruction.
    Falls back to the matching template if the LLM call fails.
    """
    # Lazy import to avoid circular deps at module load
    import os
    from claimiq.shared.config import settings
    from claimiq.shared.openai_client import generate_json

    intake      = context.get("intake", {})
    claimant    = intake.get("claimant_name") or "Valued Customer"
    claim_type  = _upper_label(intake.get("claim_type"), "insurance")
    policy_num  = intake.get("policy_number") or "N/A"
    currency    = intake.get("currency", "INR")
    amount      = intake.get("claim_amount")
    amount_str  = f"{currency} {float(amount):,.0f}" if amount else "as stated"

    # Strip copilot from context (too large) — agents are enough
    slim_ctx = {k: v for k, v in context.items() if k not in ("copilot",)}

    prompt = f"""You are the email composer for ClaimIQ, an AI insurance claims platform.
Draft a professional, empathetic, customer-facing email based on the orchestrator instruction.

ORCHESTRATOR INSTRUCTION:
{instruction}

CLAIM SNAPSHOT:
  Claim ID     : {claim_id}
  Claimant     : {claimant}
  Claim Type   : {claim_type}
  Policy No.   : {policy_num}
  Amount       : {amount_str}
  Incident Date: {intake.get("incident_date", "N/A")}

AGENT DATA (for context):
{json.dumps(slim_ctx, indent=2, default=str)[:3500]}

RULES:
1. Address the claimant by name ({claimant}).
2. Include the Claim Reference ({claim_id}) in a clearly visible summary block.
3. Never expose raw fraud scores, internal routing names, or system terminology.
   Translate to customer-friendly language (e.g. "specialist review" not "SIU referral").
4. Keep tone professional, calm, and empathetic — never alarming without reason.
5. End with a clear next step or expectation for the customer.
6. Sign off as "ClaimIQ Automated Claims Team".

Return ONLY valid JSON:
{{
  "subject": "string — email subject line, include claim type and [{claim_id}]",
  "body": "string — full plain-text email body, use \\n for newlines"
}}"""

    try:
        result = generate_json(
            prompt,
            temperature=0.25,
            max_tokens=1800,
            model=os.getenv("CLAIMIQ_EMAIL_MODEL", settings.lightweight_model),
        )
        subject = (result.get("subject") or "").strip()
        body    = (result.get("body") or "").strip()
        if subject and body:
            log.info("[EmailTool] AI-composed email for stage=%s claim=%s", stage, claim_id)
            return subject, body
        log.warning("[EmailTool] AI returned empty subject/body — using template")
    except Exception as exc:
        log.warning("[EmailTool] AI composition failed (%s) — falling back to template", exc)

    return _get_template(stage, claim_id, context)


# ── Template dispatcher ───────────────────────────────────────────────────────

def _get_template(
    stage: str,
    claim_id: str,
    context: dict[str, Any],
) -> tuple[str, str]:
    intake    = context.get("intake", {})
    coverage  = context.get("coverage", {})
    fraud     = context.get("fraud", {})
    triage    = context.get("triage", {})
    copilot   = context.get("copilot", {})

    claimant   = intake.get("claimant_name") or "Valued Customer"
    claim_type = _upper_label(intake.get("claim_type"), "insurance")
    policy_num = intake.get("policy_number") or "N/A"
    currency   = intake.get("currency", "INR")
    amount     = intake.get("claim_amount")
    amount_str = f"{currency} {float(amount):,.0f}" if amount else "as stated"

    dispatch = {
        "claim_received":        _tpl_received,
        "coverage_verified":     _tpl_coverage_verified,
        "coverage_needs_review": _tpl_coverage_needs_review,
        "fraud_alert":           _tpl_fraud_alert,
        "routing_assigned":      _tpl_routing_assigned,
        "pipeline_complete":     _tpl_pipeline_complete,
    }
    fn = dispatch.get(stage, _tpl_generic)
    return fn(claim_id, claimant, claim_type, policy_num, amount_str, coverage, fraud, triage, copilot)


# ── Individual templates ──────────────────────────────────────────────────────

def _tpl_received(claim_id, claimant, claim_type, policy_num, amount_str, *_):
    subject = f"Claim Received — {claim_type} Claim [{claim_id}]"
    # Avoid "insurance insurance claim" when claim_type is already "insurance"
    claim_label = claim_type.lower()
    claim_phrase = claim_label if claim_label == "insurance" else f"{claim_label} insurance"
    body = textwrap.dedent(f"""
    Dear {claimant},

    We have received your {claim_phrase} claim and our AI pipeline has
    begun reviewing it immediately.

    ─────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Policy Number    : {policy_num}
    Claimed Amount   : {amount_str}
    Status           : Under Review
    ─────────────────────────────────────────────

    You will receive progress updates at each stage of the review process. Our standard
    response time is 48 hours, though complex cases may require additional time.

    Please keep this Claim Reference number for all correspondence.

    Regards,
    ClaimIQ Automated Claims Team
    """).strip()
    return subject, body


def _tpl_coverage_verified(claim_id, claimant, claim_type, policy_num, amount_str, coverage, *_):
    status     = coverage.get("coverage_status", "needs_review")
    reasoning  = (coverage.get("coverage_reasoning") or "").strip()
    exclusions = coverage.get("applicable_exclusions") or []
    limits     = coverage.get("applicable_limits") or {}
    max_amt    = limits.get("max_claim_amount")
    deductible = limits.get("deductible")

    if status == "covered":
        status_line  = "✅  Your policy is active and covers this claim type."
        next_line    = "We are now completing risk and compliance checks before finalising your case."
    elif status == "not_covered":
        status_line  = "⚠️   Based on an initial review, this claim type may fall outside your policy terms."
        next_line    = "A senior adjuster will review this personally and contact you with full details."
    else:
        status_line  = "Our team is conducting a detailed review of the applicable policy coverage."
        next_line    = "You do not need to take any action at this time."

    extras = ""
    if exclusions:
        extras += f"\nPolicy Exclusions Noted : {', '.join(str(e) for e in exclusions[:4])}"
    if max_amt:
        extras += f"\nMax Claimable Amount    : {max_amt:,}"
    if deductible:
        extras += f"\nApplicable Deductible   : {deductible:,}"

    subject = f"Coverage Verified — {claim_type} Claim [{claim_id}]"
    body = textwrap.dedent(f"""
    Dear {claimant},

    We have completed the policy coverage verification for your {claim_type.lower()} claim.

    ─────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Policy Number    : {policy_num}
    Coverage Status  : {_upper_label(status).replace("_", " ")}
    {extras.strip()}
    ─────────────────────────────────────────────

    {status_line}

    {reasoning}

    Next Step: {next_line}

    We will continue to keep you updated as your claim progresses.

    Regards,
    ClaimIQ Automated Claims Team
    """).strip()
    return subject, body


def _tpl_coverage_needs_review(claim_id, claimant, claim_type, policy_num, amount_str, coverage, *_):
    subject = f"Coverage Under Additional Review — {claim_type} Claim [{claim_id}]"
    body = textwrap.dedent(f"""
    Dear {claimant},

    We are conducting an additional review of the coverage applicable to your
    {claim_type.lower()} claim. This is a standard step we take when more detailed
    verification is required.

    ─────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Policy Number    : {policy_num}
    Status           : Coverage Under Additional Review
    ─────────────────────────────────────────────

    A qualified adjuster has been assigned to verify the policy terms that apply to your
    claim. You do not need to take any action at this time.

    If we require any additional information from you, we will reach out directly.
    We aim to complete this review within 24–48 hours.

    Regards,
    ClaimIQ Automated Claims Team
    """).strip()
    return subject, body


def _tpl_fraud_alert(claim_id, claimant, claim_type, policy_num, amount_str, coverage, fraud, triage, *_):
    risk_level = (fraud.get("risk_level") or "high").lower()
    sla        = triage.get("sla_hours") or 120

    # Customer-safe language — never expose raw fraud score or SIU terminology
    if risk_level == "critical":
        review_msg = (
            "Your claim has been referred to our specialist investigations team. "
            "This is a precautionary step we take on certain claims to ensure we "
            "complete a thorough and fair review before making any decision."
        )
        contact_msg = (
            "A specialist may contact you to discuss the details of your claim or "
            "to request additional documentation."
        )
    else:
        review_msg = (
            "Your claim requires an additional review by a senior adjuster before "
            "we can proceed. This is a standard precautionary measure for claims "
            "of this type and value."
        )
        contact_msg = (
            "We may reach out to you if we need any further information to support your claim."
        )

    subject = f"Additional Review Required — {claim_type} Claim [{claim_id}]"
    body = textwrap.dedent(f"""
    Dear {claimant},

    We are writing to let you know that your {claim_type.lower()} claim requires an
    additional specialist review before a decision can be reached.

    ─────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Policy Number    : {policy_num}
    Status           : Specialist Review Required
    Expected Response: Within {sla} hours
    ─────────────────────────────────────────────

    {review_msg}

    What this means for you:
      • Your claim has not been rejected.
      • A specialist is now reviewing the details carefully.
      • {contact_msg}
      • We will update you within {sla} hours or sooner.

    If you have any questions in the meantime, please reply to this email quoting
    your Claim Reference number.

    Regards,
    ClaimIQ Automated Claims Team
    """).strip()
    return subject, body


def _tpl_routing_assigned(claim_id, claimant, claim_type, policy_num, amount_str, coverage, fraud, triage, *_):
    priority     = _upper_label(triage.get("priority"), "medium")
    routing      = (triage.get("routing") or "standard_review").replace("_", " ").title()
    sla          = triage.get("sla_hours") or 48
    triage_color = (triage.get("triage_color") or "amber").lower()
    next_steps   = _as_list(triage.get("recommended_next_steps"))
    human_flag   = triage.get("required_human_approval", True)
    cov_status   = coverage.get("coverage_status", "needs_review")

    priority_label = {
        "LOW":      "Standard",
        "MEDIUM":   "Standard",
        "HIGH":     "Elevated — Senior Adjuster Assigned",
        "CRITICAL": "Urgent — Specialist Team Assigned",
    }.get(priority, priority)

    decision_line = (
        "A qualified human adjuster has been assigned and will make the final decision."
        if human_flag
        else "Your claim is being processed for automated approval."
    )

    steps_block = ""
    if next_steps:
        steps_block = "\nNext Steps:\n" + "\n".join(
            f"  {i+1}. {s}" for i, s in enumerate(next_steps[:4])
        )

    subject = f"Claim Assigned for Review — {claim_type} Claim [{claim_id}]"
    body = textwrap.dedent(f"""
    Dear {claimant},

    Your {claim_type.lower()} claim has been fully assessed by our AI pipeline and has
    now been assigned for review.

    ─────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Policy Number    : {policy_num}
    Coverage Status  : {_upper_label(cov_status).replace("_", " ")}
    Priority Level   : {priority_label}
    Expected Response: Within {sla} hours
    ─────────────────────────────────────────────

    {decision_line}
    {steps_block}

    You will receive a final decision or further contact within the timeframe shown above.
    If you need to provide additional documents, please reply with your Claim Reference number.

    Regards,
    ClaimIQ Automated Claims Team
    """).strip()
    return subject, body


def _tpl_pipeline_complete(claim_id, claimant, claim_type, policy_num, amount_str, coverage, fraud, triage, copilot):
    sla       = triage.get("sla_hours") or 48
    human     = triage.get("required_human_approval", True)
    cov_st    = _upper_label(coverage.get("coverage_status"), "needs_review").replace("_", " ")
    _raw_summ = copilot.get("executive_summary")
    exec_summ = (
        _raw_summ.get("summary") if isinstance(_raw_summ, dict)
        else str(_raw_summ) if _raw_summ
        else ""
    )
    open_qs   = copilot.get("open_questions") or []

    # Coverage position from copilot if richer
    cov_pos = copilot.get("coverage_position") or {}
    _cov_s = cov_pos.get("summary") if isinstance(cov_pos, dict) else ""
    cov_summ = _cov_s if isinstance(_cov_s, str) else ""

    open_q_block = ""
    if open_qs:
        open_q_block = "\nWe may follow up with you on the following:\n" + "\n".join(
            f"  • {q}" for q in open_qs[:3]
        )

    subject = f"Claim Assessment Complete — {claim_type} Claim [{claim_id}]"
    body = textwrap.dedent(f"""
    Dear {claimant},

    Your {claim_type.lower()} insurance claim has completed our full AI assessment.
    Here is your summary:

    ─────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Policy Number    : {policy_num}
    Coverage Status  : {cov_st}
    Expected Response: Within {sla} hours
    Decision Path    : {"Human Adjuster Review" if human else "Automated Processing"}
    ─────────────────────────────────────────────

    {exec_summ or "Your claim has been assessed and is progressing to the next stage."}

    {("Coverage Note: " + cov_summ) if cov_summ else ""}
    {open_q_block}

    {"A qualified adjuster will contact you within the timeframe above." if human else "You will receive a decision notification within the timeframe above."}

    For any questions, please reply quoting your Claim Reference number.

    Regards,
    ClaimIQ Automated Claims Team
    """).strip()
    return subject, body


def _tpl_generic(claim_id, claimant, claim_type, policy_num, amount_str, *_):
    subject = f"Claim Update — {claim_type} Claim [{claim_id}]"
    body = textwrap.dedent(f"""
    Dear {claimant},

    This is a progress update on your {claim_type.lower()} insurance claim.

    ─────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Policy Number    : {policy_num}
    Status           : In Progress
    ─────────────────────────────────────────────

    Your claim is being reviewed by our team. We will send you a further update shortly.

    For any questions, please reply quoting your Claim Reference number.

    Regards,
    ClaimIQ Automated Claims Team
    """).strip()
    return subject, body


# ── SMTP send ─────────────────────────────────────────────────────────────────

def _smtp_send(
    to: str,
    subject: str,
    body: str,
    in_reply_to: str = "",
    attachments: list[dict] | None = None,
) -> bool:
    """
    Send a plain-text email via Gmail SMTP SSL (port 465).

    attachments : list of {"filename": str, "data": bytes, "mime_type": str}
        When present the message is wrapped in multipart/mixed so the PDF
        (or any other file) is included as a MIME attachment.
    """
    if not GMAIL_APP_PW:
        att_note = f" + {len(attachments)} attachment(s)" if attachments else ""
        log.warning(
            "[EmailTool] GMAIL_APP_PASSWORD not set — email NOT sent (logged only).\n"
            "  To: %s\n  Subject: %s%s\n  Preview: %s…",
            to, subject, att_note, body[:120],
        )
        return False

    # Use multipart/mixed when we have attachments; otherwise plain alternative
    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        for att in attachments:
            mime_type = att.get("mime_type", "application/octet-stream")
            main, sub = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")
            part = MIMEBase(main, sub)
            part.set_payload(att["data"])
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=att.get("filename", "attachment"),
            )
            msg.attach(part)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))

    msg["From"]    = f"ClaimIQ Claims <{GMAIL_ADDRESS}>"
    msg["To"]      = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = in_reply_to

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(GMAIL_ADDRESS, GMAIL_APP_PW)
            s.sendmail(GMAIL_ADDRESS, to, msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError:
        log.error("[EmailTool] Gmail authentication failed — check GMAIL_APP_PASSWORD")
        return False
    except smtplib.SMTPException as exc:
        log.error("[EmailTool] SMTP error: %s", exc)
        return False
    except Exception as exc:
        log.error("[EmailTool] Unexpected send error: %s", exc)
        return False
