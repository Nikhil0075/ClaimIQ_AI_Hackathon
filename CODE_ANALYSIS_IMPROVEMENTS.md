# ClaimIQ — Code Analysis & Improvement Plan
Generated 2026-07-03 from the tested run outputs in `email_output/` plus a full code review.

> **Live verification 2026-07-04** (claim CLM-20260703-50E696AA, property fire):
> A1 ✔ no Medical section in adjuster guide · A2 ✔ no self-referential guardrail sentence ·
> A3 ✔ "Claimed Amount: INR 1,580,000" (was N/A) · A4 ✔ audit trail shows real per-agent
> timestamps + Duration column (113.5s/54.3s/51.5s/37.7s/40.9s) · D4 ✔ router fast path used
> ("fixed policy routes all downstream agents", no LLM call) · Triage (F) ✔ N/A medical fields,
> Property Loss Surveyor, requires_manual_medical_review=false, fraud 85 correctly outranks
> to special_investigation/120h.
>
> **A5 fixed 2026-07-04**: new `claimiq/shared/pdf_text.py` sanitizer (cp1252 check → replacement map → NFKD → drop) deep-cleans all agent text entering `report_tool._build_pdf` and `generate_adjuster_guide_pdf`; unrenderable template glyphs (🔴🟡🟢 ✅ ⚠ ❌ ☑ ★ ☐) replaced with cp1252-safe markers. "fire‑spread" → "fire-spread", emoji dropped, ₹→"Rs ". All items in this plan are now closed except the E-section credential rotation (user action).

---

## A. Bugs visible in the generated PDFs (fix first)

### A1. "Medical" section appears on non-health claims — `claimiq/agents/copilot/functions.py:243`
The Adjuster Guide for the PROPERTY fire claim (CLM-…1CA8DACA) shows:
> *Medical — Diagnosis is not clearly captured; requested treatment: procedure is not clearly captured. Suggested reviewer: Fraud Reviewer.*

Cause: `"medical": _medical_explanation(intake, triage)` is built unconditionally for every claim type, and `_medical_explanation` (line 262) substitutes placeholder text when `diagnosis`/`procedure` are absent.

**Fix:** return `""` when claim type is not health/travel-medical or when neither diagnosis nor procedure is captured:
```python
def _medical_explanation(intake, triage):
    if str(intake.get("claim_type", "")).lower() not in ("health", "travel"):
        return ""
    if not (intake.get("diagnosis") or intake.get("procedure")):
        return ""
    ...
```
`app/adjuster_guide.py:342` already skips empty `med_text`, so this fixes the guide automatically. Same for the `medical_reviewer` view at line 322.

### A2. Redundant guardrail sentence — `claimiq/agents/coverage/functions.py:307`
Report page 3 prints: *"Regulatory guardrail changed preliminary status 'needs_review' to needs_review:"* — status "changed" to itself, with a trailing colon because `manual_review_reasons` was empty.

**Fix:** only append when the status actually changed and reasons exist:
```python
if result.get("manual_review_required") and original_status != "needs_review":
    reasons = "; ".join(result.get("manual_review_reasons") or []) or "regulatory guardrail"
    return f"{base} Regulatory guardrail changed preliminary status '{original_status}' to needs_review: {reasons}"
return base
```

### A3. "Claimed Amount: N/A" while ₹1,580,000 estimate exists
Report page 1 shows Claimed Amount N/A even though the fraud reasoning cites an "INR 1,580,000 estimate". The property fallback (`claimiq/agents/intake/functions.py:428-436`) only fires when `enriched["estimated_amount"]` or a document amount is populated — for this run neither was. Improve `_best_document_claim_amount` to also scan `repair_quote`-type documents and coverage/fraud outputs for the estimate, or have `report_tool` fall back to `coverage.applied_limits` / fraud-cited amounts before printing N/A.

### A4. Fake audit timestamps
Report page 7 shows identical `completed_at` for Intake→Triage. Two sources:
- `claimiq/tools/report_tool.py:738,747` — falls back to `generated_at` for every agent.
- `app/bq.py:143-145` — `started_at = completed_at = now`, `duration_ms = 0`, and `input_hash = uuid4()` (a random value, not a hash — defeats dedup/traceability).

**Fix:** stamp each agent output with its own `completed_at`/`duration_ms` in `orchestrator._run_selected_stage` (you already time the pipeline; time each stage), pass that through to the report and BQ, and compute `input_hash = hashlib.sha256(json.dumps(input, sort_keys=True)).hexdigest()[:16]`.

### A5. Missing glyphs (■) in PDFs
Extracted text shows `■` where emoji/arrow characters were used (report + guide). Helvetica lacks those glyphs. Either strip non-Latin-1 symbols in `_clean()` or register a DejaVuSans TTF in `report_tool.py`/`adjuster_guide.py` and use it for symbol runs.

---

## B. Reliability / correctness risks (not yet seen in output, will bite)

### B1. `--watch` loop dies on any error — `app/run.py:487-496`
Only `KeyboardInterrupt` is caught. Any exception in `poll()` (IMAP hiccup, `ValueError` from `InputValidator`, OpenAI outage) kills the watcher. Wrap the body:
```python
while True:
    try:
        poll(write_bq)
    except KeyboardInterrupt:
        break
    except Exception:
        log.exception("poll failed; retrying in 60s")
    time.sleep(60)
```

### B2. Emails marked read before processing — `app/email_io.py:103`
`fetch_unread` sets `\Seen` immediately after fetch. If the pipeline then crashes, the claim email is silently lost. Mark seen only after `run_pipeline` returns (return UIDs from `fetch_unread`, ack after success), or move failed messages to a retry label.

### B3. Crash on `None` claim amount — `app/run.py:382`
`f"₹{intake.get('claim_amount', 0):,.0f}"` raises `TypeError` when the key exists with value `None` (`.get` default doesn't apply). Use `float(intake.get('claim_amount') or 0)`.

### B4. `InputValidator` failures crash the pipeline — `claimiq/shared/validation.py:116-118` + `orchestrator.py:52`
`validate_pipeline_inputs` raises `ValueError` (e.g. claim > ₹1 crore, 26 attachments, subject > 500 chars). Nothing in `app/run.py` catches it, so one oversized legitimate claim kills the run (and the watcher, see B1). These should route to `needs_review`/rewrite_request, not raise. Also `MAX_CLAIM_AMOUNT_INR = 10_000_000` is low for property claims.

### B5. Empty body for HTML-only emails — `app/email_io.py:76-86`
If a sender's mail client sends only `text/html`, `body` stays `""` → mail guard always requests a rewrite. Also `get_payload(decode=True)` can return `None` → `.decode` crash. Add an HTML fallback (`html2text` or strip tags) and guard against `None`.

### B6. Duplicate-claim false positives across test runs
A new `claim_id` is generated per email with no idempotency (`run.py:135`). Re-sending the same email creates a new claim, and the fraud agent then flags the earlier copies as duplicates (this inflated the 85/100 score in your fire-claim run). Consider a content hash (sender + policy + incident_date) to detect resubmissions and treat them as updates rather than fresh claims.

### B7. Two divergent SMTP implementations
`app/email_io.py:send` (no timeout, plain From) vs `claimiq/tools/email_tool.py:_smtp_send` (timeout=15, friendly From, attachments). `run.py` uses both — rewrite-request replies go through `email_io`, everything else through `email_tool`, so rewrite emails look different and can hang without a timeout. Delete `email_io.send` and route everything through `email_tool`.

### B8. Errored agents count as completed
`session.outputs` includes `{"error": ...}` dicts, so `_workflow_state.completed_agents` lists failed agents, and `orchestrator.py:97-99` reports `status="partial"` but `workflow_state="failed"` (contradictory). Exclude error outputs from `outputs`, or add an explicit per-agent status.

---

## C. Dead code & prompt hygiene

| Where | Issue |
|---|---|
| `claimiq/pipeline/mail_guard.py:34-58` | First `prompt = f"""…"""` is immediately overwritten by the second (line 59). Dead ~25-line f-string that still gets built each call. Delete. |
| `app/streamlit_app copy.py` | 1,520-line dead duplicate. Delete. |
| `app/frontend/*.tmp.*` | 5 editor temp files (`layout.py.tmp.*`, `styles.py.tmp.*`, `explainability.py.tmp.*`). Delete. |
| `app/run.py:445-451` | `_run()` helper is no longer called. Delete. |
| `app/run.py:45` + `:72` | `load_dotenv` called twice with the same file. |
| `app/run.py:190` + `:338` | `send_claim_update` imported twice inside the function; `import re as _re` mid-function. Hoist to module level. |
| `orchestrator.py:5-9` vs `:313-321` | `argparse`, `json`, `Path` imported at module top *and* re-imported inside `_load_sample`/`main`. |
| `router.py:6`, `mail_guard.py` | `settings` imported but the OpenAI path never uses parts of it; `orchestrator.py:303` has a mis-indented dict key (`"previous_stage"`). Cosmetic but confusing. |
| `tests/Health Claim - ACL Reconstruction/mail.txt.txt` | Double extension. |

---

## D. Design improvements

**D1. Ack-email intake duplication — `app/run.py:193-219`.** The claim-received email re-implements policy/claimant/claim-type extraction with regexes that will drift from the intake agent (e.g. `PRO` prefix isn't in `_policy_re`, so your fire claim's ack said "insurance" not "property"). Either send the ack with just the claim ID (no guessed fields) or reuse a shared lightweight extractor.

**D2. JSON mode for OpenAI calls — `claimiq/shared/openai_client.py`.** `generate_json` relies on prompt discipline + fence-stripping + a retry. The Responses API supports structured output (`text={"format": {"type": "json_object"}}` or JSON schema). Using it removes the whole `parse_json`/retry path for supported models.

**D3. Model-name gating is fragile — `openai_client.py:194-200`.** `_is_reasoning_model` matches `o3/o4/gpt-5` prefixes. New model names will silently take the wrong branch (temperature vs reasoning). Make it an env-driven allowlist (`CLAIMIQ_REASONING_MODELS`).

**D4. Router prompt cost.** `router.py:78` ships up to 9 KB of session snapshot to the LLM to make a decision that the prompt itself makes deterministic ("if intake_status complete → select all four"). The deterministic route already covers this; consider LLM routing only for ambiguous cases — saves one model call per claim.

**D5. `report_pdf_bytes` inside the result dict — `orchestrator.py:259`.** Raw PDF bytes in the summary dict get `json.dumps(..., default=str)`-serialized in `main()` and in any logger that dumps the result. Return it as a separate value or attach lazily.

**D6. `should_generate_report` default — `report_tool.py:92`.** Missing coverage output defaults to `"needs_review"` → every intake-only run generates a report. Default to `""` and test explicitly.

**D7. BQ `validation_status` hardcoded `"complete"` — `bq.py:121`.** Use the real intake status.

**D8. Config duplication.** `FORM_URL_BASE` defined in both `run.py` and `email_io.py`; Gmail address fallback hardcoded (`email_io.py:31`); env fallback chains (`CLAIMIQ_ORCHESTRATOR_MODEL` → `CLAIMIQ_ROUTER_MODEL`) repeated in `router.py` and `run.py`. Centralize in `claimiq/shared/config.py`.

**D9. 58 broad `except Exception` blocks.** Fine at pipeline boundaries, but several swallow root causes (e.g. `run.py:316-317` bare `pass` around Drive-folder lookup). At minimum `log.exception` in each.

---

## E. Repo hygiene & security

- Local credential files such as `credentials.json` and `.env` can contain OAuth client secrets, API keys, and app passwords. Keep them gitignored, rotate any credentials that were shared outside the local machine, and delete duplicate local copies before demo hand-off.
- `ig_00a6…png` (1.7 MB) at repo root, generated PDFs in `email_output/` and the nested `claimiq_hackathon/` output folder: add `email_output/`, `*.png` outputs to `.gitignore` or move to an untracked `artifacts/` dir.
- `adjuster_guide_sample.pdf`, `claimiq_streamlit_logs.json` — same treatment.

---

## F. Triage agent — claim-type & priority coverage (added 2026-07-03, DONE)

Review finding: the triage agent was health-claim-only. Every emergency/urgent term was clinical, so motor/property/travel claims with severe impact fell through to "Routine / standard_review", and non-medical claims carried nonsense medical fields (`medical_necessity: Supported`, specialist `Medical Reviewer`, `requires_manual_medical_review: True`).

Implemented in `claimiq/agents/triage/functions.py` + `tool.py`:

- **Non-medical urgency tiers.** `NONMEDICAL_EMERGENCY_TERMS` (uninhabitable, family displaced, total loss, structure collapse, evacuation, repatriation…) → critical/red; `NONMEDICAL_URGENT_TERMS` (undrivable, stranded, passport stolen, hospitalized abroad, water damage spreading…) → high/amber. Both gated so they cannot fire on medical claims.
- **New routing queue** `urgent_claim_review` (SLA 8h) for severe non-medical impact; added to the LLM prompt's routing list and protected by the hard-override so AI synthesis cannot downgrade it.
- **Medical-dimension detection.** `_is_medical_claim()` treats travel claims with hospitalization/treatment as clinical (full medical triage + mandatory human review reason); pure travel disruption goes the non-medical path.
- **Domain specialists.** motor → Motor Assessor, property → Property Loss Surveyor, travel → Travel Claims Reviewer, life/legal reviewers — Medical Reviewer no longer suggested for claims without a medical dimension.
- **Honest fields.** `medical_necessity`/`expected_hospital_stay`/`expected_rehabilitation` = "N/A (non-medical claim)"; `requires_manual_medical_review` false for non-medical claims; triage summary says "Claim triage … no medical dimension" instead of "Clinical triage".
- **Approval reasons** extended: severe non-medical impact and travel-with-medical-treatment now require human approval.
- **`estimated_settlement_days` fixed**: derived from the routing SLA (ceil(sla/24), +7 for investigation/legal) — previously a red fraud investigation claimed a 1-day settlement.

Verified: all 7 existing health-claim edge-case tests still pass unchanged + 9 new scenarios (property fire displacement → critical/8h/Property Loss Surveyor; motor undrivable → urgent; travel cardiac arrest abroad → medical_emergency_review/Cardiology; stranded traveler → urgent/Travel Claims Reviewer; fraud ≥70 still outranks everything; AI cannot downgrade non-medical urgency).

---

## Suggested order of work

1. ~~A1, A2, B3~~ — **DONE 2026-07-03**: medical section gated by claim type, guardrail sentence fixed, None-safe amount print.
2. ~~B1, B2, B4~~ — **DONE 2026-07-03**: watch loop survives errors; IMAP UID + BODY.PEEK with mark_seen after success; validation errors now route to rewrite_request (limits env-overridable, INR cap raised to 5 crore).
3. ~~A4~~ — **DONE 2026-07-03**: real per-agent started_at/completed_at/duration_ms recorded in the session, shown in the report audit trail (new Duration column), written to BQ with a deterministic sha256 input_hash. (D7 still open.)
4. ~~C~~ — **DONE 2026-07-03**: deleted `streamlit_app copy.py`, 5 frontend `.tmp` files, dead mail_guard prompt, unused `_run()`, unused agent imports, duplicate `load_dotenv`/`send_claim_update` imports (hoisted to module level), orchestrator re-imports + indent fix, unused `settings` import in router, renamed `mail.txt.txt`, fixed run.py docstring paths.
5. ~~A3, B6~~ — **DONE 2026-07-03** (code-verified; send one live test claim to confirm end-to-end):
   - A3: `_as_positive_amount` now parses currency-marked strings ("INR 1,580,000", "Rs. 2,85,000/-", "₹5000"); `_best_document_claim_amount` scans all amount-hinting extracted fields (blocklisting sum_insured/deductible/premium) plus currency figures in document summaries; the estimated-amount fallback applies to every claim type, not only property; the PDF report falls back to the estimate with an "(est.)" suffix instead of N/A.
   - B6: content-fingerprint registry (`app/.claimiq_seen.json`, gitignored, `CLAIMIQ_DEDUP_WINDOW_DAYS`=30) — identical resends get a polite "already processed as CLM-…" reply instead of a new claim_id, ending fraud-agent false duplicates from test reruns.
6. ~~D2/D3/D4~~ — **DONE 2026-07-03**:
   - D2: native JSON mode on both OpenAI paths (`text.format`/`response_format` json_object) with automatic retry-without on models that reject it; kill-switch `CLAIMIQ_JSON_MODE=false`.
   - D3: reasoning-model detection via env allowlist `CLAIMIQ_REASONING_MODEL_PREFIXES` (default `o1,o3,o4,gpt-5`).
   - D4: router skips the LLM entirely when intake_status is complete/needs_review (fixed policy = all four agents) — saves one reasoning-model call + ~9KB prompt per claim; `CLAIMIQ_ROUTER_ALWAYS_LLM=true` restores old behaviour.
