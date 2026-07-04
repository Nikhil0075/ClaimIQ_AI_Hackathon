"""
ClaimIQ — Local Pipeline Runner
=================================
Chains all 5 agents and handles email + BigQuery I/O.

Usage (from the project root):
  python app/run.py              # process unread Gmail
  python app/run.py --demo      # run built-in demo claim (no Gmail needed)
  python app/run.py --watch     # poll Gmail every 60s
  python app/run.py --no-bq     # skip BigQuery writes

Modules:
  claimiq/agents/*  — 5 OpenAI-backed agents (intake, coverage, fraud, triage, copilot)
  email_io.py — Gmail IMAP read + SMTP send
  bq.py       — BigQuery streaming writes

Requirements:
  pip install -e .
  set OPENAI_API_KEY plus Google service credentials in .env
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

RUN_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(RUN_DIR, ".."))

load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, ".env"))

os.environ.setdefault("GCP_PROJECT_ID", "claimiq-ai-demo")
os.environ.setdefault("GCP_REGION", "us-central1")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "claimiq-ai-demo")
# The app runner uses app/bq.py for the dashboard tables. Keep the package-level
# agent audit writer off here so it does not write duplicate rows to older BQ schemas.
os.environ["CLAIMIQ_WRITE_BQ"] = "false"

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, RUN_DIR)

import email_io as em
import bq
import attachments as att_mod
from claimiq.pipeline.mail_guard import evaluate_email
from claimiq.pipeline.orchestrator import run_pipeline as run_claim_session
from claimiq.shared.config import settings
from claimiq.tools.email_tool import send_claim_update as _send_update

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("claimiq")

# Colour helpers (terminal only)
G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; B = "\033[1m"; X = "\033[0m"


def _upper_label(value, default="?"):
    text = str(value if value not in (None, "") else default)
    return text.upper()

FORM_URL_BASE = os.getenv(
    "FORM_URL_BASE",
    "https://docs.google.com/forms/d/14p1B6rH32q8Pf0iouEeWBcdRchyPUmVWY2xTJCv7xCU/viewform?usp=pp_url&entry.684140824=",
)

# ── Claim idempotency (resubmission detection) ───────────────────────────────
# Identical resends previously minted a fresh claim_id each time, which then
# tripped the fraud agent's duplicate-claim signal against our own test runs.
# A content fingerprint maps a resubmitted email back to its original claim.

DEDUP_REGISTRY_PATH = os.getenv(
    "CLAIMIQ_DEDUP_REGISTRY",
    os.path.join(RUN_DIR, ".claimiq_seen.json"),
)
DEDUP_WINDOW_DAYS = int(os.getenv("CLAIMIQ_DEDUP_WINDOW_DAYS", "30"))


def _claim_fingerprint(sender: str, subject: str, body: str) -> str:
    """Stable content hash for one claim submission (whitespace-insensitive)."""
    normalized = " ".join(f"{sender}|{subject}|{body}".lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_seen_claims() -> dict:
    try:
        with open(DEDUP_REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _remember_claim(fingerprint: str, claim_id: str) -> None:
    seen = _load_seen_claims()
    seen[fingerprint] = {
        "claim_id": claim_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    # Drop entries older than the dedup window to keep the file small
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEDUP_WINDOW_DAYS)
    pruned = {}
    for fp, entry in seen.items():
        try:
            if datetime.fromisoformat(entry["processed_at"]) >= cutoff:
                pruned[fp] = entry
        except (KeyError, TypeError, ValueError):
            continue
    try:
        with open(DEDUP_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=2)
    except OSError as exc:
        log.warning("Could not persist dedup registry: %s", exc)


def _find_duplicate_claim(fingerprint: str) -> str | None:
    """Return the original claim_id if this exact submission was already processed."""
    entry = _load_seen_claims().get(fingerprint)
    if not entry:
        return None
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["processed_at"])
        if age.days > DEDUP_WINDOW_DAYS:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return entry.get("claim_id")


# ── Demo claim ────────────────────────────────────────────────────────────────

DEMO_INCIDENT_DATE = (datetime.now(timezone.utc).date() - timedelta(days=7)).strftime("%d %B %Y")

DEMO_CLAIM = {
    "sender":  "nikhilranjanmurmu75@gmail.com",
    "subject": "Motor Insurance Claim — Policy INS-2024-00421",
    "body": f"""\
Dear Claims Team,

I am filing a motor insurance claim under Policy No: INS-2024-00421.

Incident: {DEMO_INCIDENT_DATE}, NH-48 Bengaluru-Mysuru Highway near Ramanagara.
My vehicle (KA-05-MF-9234, 2022 Toyota Fortuner) was rear-ended by a truck
(KA-14-ZZ-0012) at 9:15 AM while stationary in traffic. Repair estimate: Rs 2,85,000.

Documents: Police FIR (RMG-2025-0821), garage estimate (Nippon Toyota), damage photos.
No prior claims in 3 years.

Claimant: John Smith | +91-9876543210 | Policy: INS-2024-00421
""",
    "message_id": "",
}


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(
    email_body: str,
    sender: str,
    subject: str,
    message_id: str = "",
    write_bq: bool = True,
    raw_email_bytes: bytes = b"",
) -> str:
    """
    Full E2E pipeline for one claim. Steps:
      1. Received confirmation email
      2. Extract + analyze attachments
      3. Run 5 agents (intake receives document summary)
      4. Upload attachments to Google Drive
      5. Write to BigQuery
      6. Send full assessment email (with Drive link)
    Returns the claim_id.
    """
    # ── Resubmission check ────────────────────────────────────────────────────
    fingerprint = _claim_fingerprint(sender, subject, email_body)
    original_claim_id = _find_duplicate_claim(fingerprint)
    if original_claim_id:
        print(f"{Y}Duplicate submission detected — already processed as {original_claim_id}{X}")
        em.send(
            sender,
            f"Re: {subject}",
            (
                "Dear Customer,\n\n"
                "We received this claim email earlier and it is already being processed.\n\n"
                f"Claim Reference : {original_claim_id}\n\n"
                "There is no need to resend the same claim. If you want to add documents\n"
                "or information, please reply to the original claim thread quoting the\n"
                "Claim Reference above.\n\n"
                "Regards,\nClaimIQ Automated Claims Team"
            ),
            message_id,
        )
        return original_claim_id

    claim_id = f"CLM-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    print(f"\n{B}{C}{'═'*60}{X}")
    print(f"{B}{C}  ClaimIQ Pipeline  —  {claim_id}{X}")
    orchestrator_model = os.getenv("CLAIMIQ_ORCHESTRATOR_MODEL", os.getenv("CLAIMIQ_ROUTER_MODEL", settings.openai_model))
    print(f"{C}  Default Model: {settings.openai_model}  |  Orchestrator: {orchestrator_model}  |  Project: {settings.project_id or 'local'}{X}")
    print(f"{C}{'═'*60}{X}\n")

    # Step 1 — Received confirmation
    print(f"{B}[1/6] Checking claim email format...{X}")
    guard = evaluate_email(email_body, subject)
    if guard.get("action") == "rewrite_request":
        print(f"  {Y}Mail guard requested rewrite: {guard.get('reason', 'format issue')}{X}")
        em.send(
            sender,
            f"Re: {subject}",   # always "Re: <original>" so Gmail threads as a reply
            guard.get("reply_body") or "Please resend your claim in the required format.",
            message_id,
        )
        _emit_explainability_payload(
            {
                "claim_id": claim_id,
                "status": "rewrite_required",
                "guard": guard,
                "route": {
                    "selected_agents": [],
                    "next_agent": "customer_rewrite_request",
                    "reason": guard.get("reason", "Mail guard found the claim email is not ready for processing."),
                    "required_action": guard.get("reply_body") or "Ask the customer to resend the claim in the required format.",
                    "claim_status": "rewrite_required",
                    "confidence": guard.get("confidence"),
                },
                "workflow_state": {
                    "claim_id": claim_id,
                    "current_stage": "mail_guard",
                    "previous_stage": "claim_received",
                    "next_stage": "customer_rewrite_request",
                    "status": "rewrite_required",
                    "responsible_agent": "mail_guard",
                    "completed_agents": [],
                    "pending_agents": [],
                    "required_action": guard.get("reply_body") or "Ask the customer to resend the claim in the required format.",
                },
                "outputs": {},
                "errors": {},
            },
            attachment_count=0,
            document_summary={},
            drive_url="",
            approval_url=f"{FORM_URL_BASE}{claim_id}",
        )
        return claim_id

    print(f"{B}[1/6] Sending received confirmation...{X}")
    # Extract basic info from email body for the ack email (intake not yet run)
    _policy_re   = re.compile(r"\b(?:POL|CLM|HLTH?|MTR|INS|LIFE|TRV|PROP)[- ]?\d{4,}(?:[- ]?\w+)*\b", re.IGNORECASE)
    _claimant_re = re.compile(r"\bClaimant\s*:\s*([^\n\r|]+)", re.IGNORECASE)
    _policy_match   = _policy_re.search(email_body)
    _claimant_match = _claimant_re.search(email_body)

    # Infer claim type from policy prefix or keywords
    _policy_str = (_policy_match.group(0).upper() if _policy_match else "").replace("-", "")
    if "HLTH" in _policy_str or any(w in email_body.lower() for w in ("hospital", "medical", "surgery", "health")):
        _ack_type = "health"
    elif "MTR" in _policy_str or any(w in email_body.lower() for w in ("vehicle", "motor", "car", "accident")):
        _ack_type = "motor"
    elif "LIFE" in _policy_str or "life" in email_body.lower():
        _ack_type = "life"
    elif "TRV" in _policy_str or "travel" in email_body.lower():
        _ack_type = "travel"
    else:
        _ack_type = "insurance"

    _ack_context = {
        "intake": {
            "policy_number":  _policy_match.group(0).upper() if _policy_match else None,
            "claimant_name":  _claimant_match.group(1).strip() if _claimant_match else None,
            "claim_type":     _ack_type,
            "claim_amount":   None,
        }
    }
    _send_update(
        stage="claim_received",
        claim_id=claim_id,
        to_email=sender,
        context=_ack_context,
        in_reply_to=message_id,
        subject_override=f"Re: {subject}",
    )

    # Step 2 — Extract + analyze attachments
    print(f"\n{B}[2/6] Extracting and analyzing attachments...{X}")
    attachments   = att_mod.extract(raw_email_bytes) if raw_email_bytes else []
    doc_summary   = att_mod.analyze(attachments)
    att_count     = len(attachments)
    doc_risks     = doc_summary.get("risk_signals", [])
    if att_count:
        print(f"  {G}✅ {att_count} attachment(s) extracted | {len(doc_risks)} risk signal(s){X}")
    else:
        print(f"  {Y}No attachments found{X}")

    # Step 3 — Run 5 agents (intake gets document summary)
    # send_emails=True enables mid-pipeline updates after Coverage, Fraud, Triage
    print(f"\n{B}[3/6] Running routed ClaimIQ session...{X}")
    pipeline_result = run_claim_session(
        claim_id=claim_id,
        email_body=email_body,
        sender_email=sender,
        subject=subject,
        documents_summary=doc_summary,
        uploaded_documents=_uploaded_documents_for_intake(attachments),
        guard_result=guard,
        send_emails=True,
        in_reply_to=message_id,
    )
    if pipeline_result["status"] == "rewrite_required":
        guard = pipeline_result.get("guard", {})
        print(f"  {Y}Mail guard requested rewrite: {guard.get('reason', 'format issue')}{X}")
        em.send(
            sender,
            f"Re: {subject}",   # always "Re: <original>" so Gmail threads as a reply
            guard.get("reply_body") or "Please resend your claim in the required format.",
            message_id,
        )
        _emit_explainability_payload(
            pipeline_result,
            attachment_count=att_count,
            document_summary=doc_summary,
            drive_url="",
            approval_url=f"{FORM_URL_BASE}{claim_id}",
        )
        return claim_id

    all_agents = pipeline_result["outputs"]
    selected_agents = pipeline_result.get("route", {}).get("selected_agents", [])
    print(f"  {G}Selected agents: {', '.join(['intake'] + selected_agents)}{X}")
    intake = all_agents.get("intake", {})
    coverage = all_agents.get("coverage", {})
    fraud = all_agents.get("fraud", {})
    triage = all_agents.get("triage", {})
    copilot = all_agents.get("copilot", {})
    doc_summary = intake.get("documents_summary") or doc_summary
    doc_risks = doc_summary.get("risk_signals", [])

    # Step 4 — Upload to Google Drive
    print(f"\n{B}[4/6] Uploading documents to Google Drive...{X}")
    drive_url = ""
    if attachments:
        drive_url = att_mod.upload_to_drive(claim_id, attachments)
        if drive_url:
            print(f"  {G}✅ Drive folder: {drive_url}{X}")
        else:
            print(f"  {Y}Drive upload skipped (auth failed, credentials missing, or upload failed){X}")
    else:
        print(f"  {Y}No attachments to upload{X}")

    # Step 4b — Generate + upload Adjuster Guide PDF to Drive
    print(f"  {C}▶ Generating adjuster guide PDF...{X}", flush=True)
    try:
        import adjuster_guide as _guide_mod
        _guide_pdf = _guide_mod.generate_adjuster_guide_pdf(
            claim_id,
            copilot=copilot,
            intake=intake,
        )
        if _guide_pdf:
            _guide_filename = f"Adjuster_Guide_{claim_id}.pdf"
            _guide_ok = att_mod.upload_file_to_drive(claim_id, _guide_filename, _guide_pdf)
            if _guide_ok:
                # If no claim attachments were uploaded, build the Drive URL from the
                # folder that upload_file_to_drive just created.
                if not drive_url:
                    try:
                        _svc  = att_mod._get_drive_service()
                        _root = att_mod._get_or_create_folder(_svc, att_mod.DRIVE_ROOT_FOLDER_NAME)
                        _fid  = att_mod._get_or_create_folder(_svc, claim_id, parent_id=_root)
                        drive_url = f"https://drive.google.com/drive/folders/{_fid}"
                    except Exception:
                        pass
                print(f"  {G}✅ Adjuster guide uploaded: {_guide_filename}{X}")
            else:
                print(f"  {Y}Adjuster guide PDF generated but Drive upload failed{X}")
        else:
            print(f"  {Y}Adjuster guide PDF skipped (reportlab unavailable){X}")
    except Exception as _guide_exc:
        print(f"  {Y}Adjuster guide generation failed: {_guide_exc}{X}")

    # Step 5 — Write to BigQuery
    if write_bq:
        print(f"\n{B}[5/6] Writing to BigQuery...{X}")
        bq.write_claim(
            claim_id, sender, all_agents,
            drive_folder_url=drive_url,
            attachment_count=att_count,
            doc_risk_signals=doc_risks,
            agent_timings=pipeline_result.get("agent_timings") or {},
        )

    # Step 6 — Full assessment summary via email tool (+ PDF report if generated)
    print(f"\n{B}[6/6] Sending AI assessment summary...{X}")
    report_bytes = pipeline_result.get("report_pdf_bytes")
    att_list = None
    if report_bytes:
        att_list = [{
            "filename": f"ClaimIQ_Report_{claim_id}.pdf",
            "data":     report_bytes,
            "mime_type": "application/pdf",
        }]
        print(f"  {G}📎 PDF report attached ({len(report_bytes):,} bytes){X}")
    else:
        print(f"  {Y}No PDF report generated (thresholds not met or deps missing){X}")

    _send_update(
        stage="pipeline_complete",
        claim_id=claim_id,
        to_email=sender,
        context=all_agents,
        in_reply_to=message_id,
        # Keep subject identical to all other replies so Gmail threads everything together
        subject_override=f"Re: {subject}",
        attachments=att_list,
    )

    # ── Print result ──────────────────────────────────────────────────────────
    fraud_score = fraud.get("fraud_score", "?")
    risk        = _upper_label(fraud.get("risk_level"), "?")
    priority    = _upper_label(triage.get("priority"), "?")
    color       = triage.get("triage_color", "green")
    # Default to True (human review) when triage hasn't run — never show AUTO-ELIGIBLE
    # for a pipeline that didn't complete all agents.
    approval    = triage.get("required_human_approval")
    if approval is None:
        approval = (copilot.get("routing_decision") or {}).get("requires_human_approval")
    if approval is None:
        approval = True  # safe default: require human review when triage data is absent
    color_code  = R if color == "red" else Y if color in ("orange", "yellow") else G

    print(f"\n{B}{color_code}{'═'*60}{X}")
    print(f"{B}{color_code}  PIPELINE COMPLETE{X}")
    print(f"{color_code}{'═'*60}{X}")
    print(f"  {B}Claim ID   :{X} {claim_id}")
    print(f"  {B}Claimant   :{X} {intake.get('claimant_name', '?')}")
    print(f"  {B}Type       :{X} {_upper_label(intake.get('claim_type'), '?')}")
    print(f"  {B}Amount     :{X} ₹{float(intake.get('claim_amount') or 0):,.0f}")
    print(f"  {B}Attachments:{X} {att_count} file(s)")
    print(f"  {B}Doc Risks  :{X} {len(doc_risks)} signal(s)")
    print(f"  {B}Fraud      :{X} {fraud_score}/100  ({risk})")
    print(f"  {B}Priority   :{X} {priority}  [{_upper_label(color)}]")
    print(f"  {B}Routing    :{X} {triage.get('routing', '?')}")
    flag = f"{R}{B}⚠  HUMAN APPROVAL REQUIRED{X}" if approval else f"{G}✅ AUTO-ELIGIBLE{X}"
    print(f"  {B}Decision   :{X} {flag}")
    print(f"\n  {B}APPROVAL FORM:{X}")
    print(f"  {C}{FORM_URL_BASE}{claim_id}{X}")
    if drive_url:
        print(f"\n  {B}DOCUMENTS (Drive):{X}")
        print(f"  {C}{drive_url}{X}")
    print(f"{C}{'═'*60}{X}\n")

    _emit_explainability_payload(
        pipeline_result,
        attachment_count=att_count,
        document_summary=doc_summary,
        drive_url=drive_url,
        approval_url=f"{FORM_URL_BASE}{claim_id}",
    )

    # Register the fingerprint so an identical resend maps back to this claim
    _remember_claim(fingerprint, claim_id)

    return claim_id


def _emit_explainability_payload(
    pipeline_result: dict,
    *,
    attachment_count: int,
    document_summary: dict,
    drive_url: str,
    approval_url: str,
) -> None:
    """Print a machine-readable block for the Streamlit explainability tab."""
    payload = {
        key: value
        for key, value in (pipeline_result or {}).items()
        if key != "report_pdf_bytes"
    }
    payload["report_generated"] = bool((pipeline_result or {}).get("report_pdf_bytes"))
    payload["attachment_count"] = attachment_count
    payload["document_summary"] = document_summary or {}
    payload["drive_url"] = drive_url
    payload["approval_url"] = approval_url
    print("CLAIMIQ_EXPLAINABILITY_JSON_BEGIN")
    print(json.dumps(payload, ensure_ascii=False, default=str))
    print("CLAIMIQ_EXPLAINABILITY_JSON_END")


def _uploaded_documents_for_intake(attachments: list) -> list[dict]:
    return [
        {
            "filename": attachment.filename,
            "mime_type": attachment.mime_type,
            "data": attachment.data,
            "size": attachment.size,
        }
        for attachment in attachments
        if getattr(attachment, "data", None)
    ]


# ── Gmail polling ─────────────────────────────────────────────────────────────

def poll(write_bq: bool = True) -> None:
    emails = em.fetch_unread()
    if not emails:
        print(f"{Y}No unread emails in {em.GMAIL_ADDRESS}{X}")
        return
    for e in emails:
        print(f"\n{B}New claim from: {e['sender']}{X}")
        try:
            run_pipeline(
                e["body"], e["sender"], e["subject"], e["message_id"],
                write_bq=write_bq,
                raw_email_bytes=e.get("raw_bytes", b""),
            )
        except Exception:
            # Leave the email unread so it is retried on the next poll cycle.
            log.exception("Pipeline failed for email from %s — left unread for retry", e["sender"])
            continue
        # Only mark read once the pipeline has fully processed the claim,
        # so a crash mid-pipeline cannot silently lose an email.
        if e.get("uid"):
            em.mark_seen(e["uid"])


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="ClaimIQ Local Pipeline")
    parser.add_argument("--demo",   action="store_true", help="Run built-in demo claim")
    parser.add_argument("--watch",  action="store_true", help="Poll Gmail every 60s")
    parser.add_argument("--no-bq",  action="store_true", help="Skip BigQuery writes")
    args = parser.parse_args()

    write_bq = not args.no_bq

    if args.demo:
        print(f"{C}Running DEMO mode{X}")
        d = DEMO_CLAIM
        run_pipeline(d["body"], d["sender"], d["subject"], d["message_id"], write_bq)
        return

    if args.watch:
        print(f"{C}Watching {em.GMAIL_ADDRESS} every 60s  (Ctrl+C to stop)...{X}")
        while True:
            try:
                poll(write_bq)
            except KeyboardInterrupt:
                print(f"\n{Y}Stopped.{X}")
                break
            except Exception:
                log.exception("Poll cycle failed — retrying in 60s")
            try:
                time.sleep(60)
            except KeyboardInterrupt:
                print(f"\n{Y}Stopped.{X}")
                break
        return

    poll(write_bq)


if __name__ == "__main__":
    main()
