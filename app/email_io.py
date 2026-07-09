"""
ClaimIQ — Email I/O
=====================
Two responsibilities:
  1. READ  — fetch unread claim emails from Gmail via IMAP
  2. SEND  — send status emails via Gmail SMTP (App Password)

Both use the Gmail App Password from .env — no OAuth, no Secret Manager.

To add a new email template:
  1. Write a build_<name>_email() function
  2. Call send() with it from run.py
"""

import email as _email_lib
import imaplib
import logging
import os
import re
import smtplib
import textwrap
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "claim.iq.ai.001@gmail.com")
GMAIL_APP_PW  = os.getenv("GMAIL_APP_PASSWORD", "")
FORM_URL_BASE = os.getenv(
    "FORM_URL_BASE",
    "https://docs.google.com/forms/d/14p1B6rH32q8Pf0iouEeWBcdRchyPUmVWY2xTJCv7xCU/viewform?usp=pp_url&entry.684140824=",
)

log = logging.getLogger("claimiq.email")


def _upper_label(value, default="N/A"):
    text = str(value if value not in (None, "") else default)
    return text.upper()


def _as_list(value):
    """Coerce optional list-like output without splitting plain strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
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


# ── READ: Gmail IMAP ──────────────────────────────────────────────────────────

def fetch_unread() -> list[dict]:
    """
    Fetch all unread emails from INBOX **without** marking them read.
    Returns list of dicts:
      {sender, subject, body, message_id, raw_bytes, uid}
    raw_bytes is the full RFC-822 message — pass to attachments.extract().
    Call mark_seen(uid) after the claim has been processed successfully so a
    crash mid-pipeline leaves the email unread and it is retried next poll.
    """
    if not GMAIL_APP_PW:
        log.error("GMAIL_APP_PASSWORD not set — cannot read Gmail")
        return []

    emails = []
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.login(GMAIL_ADDRESS, GMAIL_APP_PW)
        m.select("INBOX")
        # UID search/fetch: UIDs are stable across IMAP sessions, unlike
        # message sequence numbers, so mark_seen() can safely reconnect later.
        _, data = m.uid("search", None, "UNSEEN")
        uids = data[0].split()
        log.info("Found %d unread email(s)", len(uids))

        for uid in uids:
            # BODY.PEEK does NOT set \Seen — emails stay unread until the
            # pipeline finishes and poll() calls mark_seen(uid).
            _, msg_data = m.uid("fetch", uid, "(BODY.PEEK[])")
            raw_bytes = msg_data[0][1]                      # ← keep full bytes
            msg = _email_lib.message_from_bytes(raw_bytes)

            # Extract plain-text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                        break
            else:
                body = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="replace"
                )

            # Decode MIME-encoded subject
            raw_subject = msg.get("Subject", "(no subject)")
            decoded = _email_lib.header.decode_header(raw_subject)
            subject = "".join(
                part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
                for part, enc in decoded
            )

            emails.append({
                "sender":     _email_lib.utils.parseaddr(msg.get("From", ""))[1],
                "subject":    subject.strip(),
                "body":       body,
                "message_id": msg.get("Message-ID", ""),
                "raw_bytes":  raw_bytes,        # for attachments.extract()
                "uid":        uid.decode() if isinstance(uid, bytes) else str(uid),
            })

        m.logout()
    except Exception as e:
        log.error("IMAP error: %s", e)

    return emails


def mark_seen(uid: str) -> bool:
    """
    Mark one email as read after its claim has been processed.
    Opens a fresh IMAP connection so it can be called independently of
    fetch_unread(). Returns True on success.
    """
    if not GMAIL_APP_PW or not uid:
        log.warning("mark_seen skipped (missing app password or uid)")
        return False
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com")
        m.login(GMAIL_ADDRESS, GMAIL_APP_PW)
        m.select("INBOX")
        m.uid("store", uid, "+FLAGS", "\\Seen")
        m.logout()
        return True
    except Exception as e:
        log.error("IMAP mark_seen(%s) failed: %s", uid, e)
        return False


# ── SEND: Gmail SMTP ──────────────────────────────────────────────────────────

def send(to: str, subject: str, body: str, in_reply_to: str = "") -> bool:
    """
    Send a plain-text email via Gmail SMTP.
    Returns True on success, False on failure.
    """
    if not GMAIL_APP_PW:
        log.warning("GMAIL_APP_PASSWORD not set — skipping email to %s", to)
        return False

    msg = MIMEMultipart("alternative")
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = in_reply_to
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_ADDRESS, GMAIL_APP_PW)
            s.sendmail(GMAIL_ADDRESS, to, msg.as_string())
        log.info("Email sent → %s", to)
        return True
    except Exception as e:
        log.error("SMTP error: %s", e)
        return False


# ── Templates ─────────────────────────────────────────────────────────────────

def build_received_email(claim_id: str, claimant_name: str) -> str:
    return textwrap.dedent(f"""
    Dear {claimant_name},

    We have received your insurance claim and it is now being processed.

    Claim Reference : {claim_id}
    Status          : Under Review
    Expected SLA    : 48 hours

    Our AI pipeline will assess your claim and you will receive a full summary shortly.
    Please keep this Claim Reference for any future correspondence.

    Regards,
    ClaimIQ Automated Claims Team
    {GMAIL_ADDRESS}
    """).strip()


def build_summary_email(
    claim_id: str,
    agents: dict,
    drive_folder_url: str = "",
    attachment_count: int = 0,
) -> str:
    """
    Full AI assessment summary — sent after all 5 agents complete.
    agents: dict with keys intake, coverage, fraud, triage, copilot
    drive_folder_url: Google Drive link to uploaded documents (optional)
    """
    copilot = agents.get("copilot", {})
    triage  = agents.get("triage", {})
    fraud   = agents.get("fraud", {})
    intake  = agents.get("intake", {})

    routing_decision = copilot.get("routing_decision", {})
    approval = routing_decision.get("requires_human_approval") or triage.get("required_human_approval")
    status   = "⚠️  REQUIRES HUMAN ADJUSTER REVIEW" if approval else "✅ AUTO-PROCESSING ELIGIBLE"

    steps = "\n".join(
        f"  {i+1}. {s}"
        for i, s in enumerate(_as_list(triage.get("recommended_next_steps")))
    ) or "  An adjuster will contact you shortly."

    coverage_pos = copilot.get("coverage_position", {})
    coverage_str = (
        coverage_pos.get("summary", "Coverage assessment in progress.")
        if isinstance(coverage_pos, dict)
        else str(coverage_pos)
    )

    fraud_assess = copilot.get("fraud_assessment", {})
    fraud_str = (
        f"Score {fraud_assess.get('score','?')}/100 ({_upper_label(fraud_assess.get('risk_level'), '?')}) — "
        f"{fraud_assess.get('recommended_action','')}"
        if isinstance(fraud_assess, dict)
        else str(fraud_assess)
    ) or f"Score {fraud.get('fraud_score','?')}/100 — No significant signals."

    docs_line = (
        f"\n    Documents        : {attachment_count} file(s) attached"
        if attachment_count > 0 else ""
    )
    drive_line = (
        f"\n    Documents Folder : {drive_folder_url}"
        if drive_folder_url else ""
    )

    return textwrap.dedent(f"""
    Dear {intake.get("claimant_name", "Valued Customer")},

    Your insurance claim has completed our AI assessment. Here is your full summary:

    ─────────────────────────────────────────────────
    CLAIM REFERENCE : {claim_id}
    STATUS          : {status}
    PRIORITY        : {_upper_label(triage.get("priority"), "standard")}
    FRAUD RISK      : {_upper_label(fraud.get("risk_level"), "N/A")} (score {fraud.get("fraud_score", "?")}/100)
    SLA             : {triage.get("sla_hours", 48)} hours{docs_line}{drive_line}
    ─────────────────────────────────────────────────

    SUMMARY:
    {copilot.get("executive_summary", "Assessment complete.")}

    COVERAGE POSITION:
    {coverage_str}

    FRAUD ASSESSMENT:
    {fraud_str}

    NEXT STEPS:
    {steps}

    ─────────────────────────────────────────────────
    Claim Reference  : {claim_id}
    Claim Type       : {_upper_label(intake.get("claim_type"), "N/A")}
    Incident Date    : {intake.get("incident_date", "N/A")}
    Processed by     : ClaimIQ 5-Agent AI Pipeline
    Review Form      : {FORM_URL_BASE}{claim_id}
    ─────────────────────────────────────────────────

    For any questions, reply with your Claim Reference number.

    Regards,
    ClaimIQ Automated Claims Team
    {GMAIL_ADDRESS}
    """).strip()
