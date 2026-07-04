# ClaimIQ Technical Documentation

## 1. Overview

ClaimIQ is a Track 1 agentic workflow for insurance claims processing. It automates the path from claim intake to adjuster-ready decision support using five specialist agents and an operations layer for Gmail, attachments, Google Drive, BigQuery, Looker Studio, and a Streamlit console.

The hackathon version is structured around OpenAI-backed agents with deterministic fallbacks. Google Cloud remains the operational data plane for policy lookup, audit persistence, claim queue tables, Drive evidence storage, and Looker Studio reporting.

## 2. Business Workflow

The production flow is:

1. A customer sends a claim email to the configured Gmail inbox.
2. `app/email_io.py` polls unread email through Gmail IMAP.
3. `app/attachments.py` extracts attachments and prepares document evidence.
4. Five agents run in sequence:
   - Intake Agent
   - Coverage Agent
   - Fraud Agent
   - Triage Agent
   - Adjuster Copilot
5. Attachments are uploaded into Google Drive under `ClaimIQ Claims/{claim_id}`.
6. Claim and agent records are written to BigQuery.
7. A customer summary email is sent through Gmail SMTP.
8. The Streamlit console and Looker Studio dashboard display operational status.

## 3. Repository Layout

```text
D:\claimiq_hackathon
  app/
    run.py                  # End-to-end local runner for Gmail/demo/watch modes
    streamlit_app.py        # Streamlit operations console
    email_io.py             # Gmail IMAP/SMTP integration
    attachments.py          # Attachment extraction, document summary, Drive upload
    bq.py                   # BigQuery write layer for dashboard tables
    FullLogo_Transparent_NoBuffer.png

  claimiq/
    agents/
      intake/
        agent.py            # Agent entry point and fallback handling
        tool.py             # OpenAI prompt/tool call
        functions.py        # Deterministic extraction helpers
      coverage/
        agent.py
        tool.py             # Policy lookup + OpenAI coverage reasoning
        functions.py        # Deterministic coverage logic
      fraud/
        agent.py
        tool.py             # Duplicate lookup + OpenAI fraud synthesis
        functions.py        # Deterministic fraud scoring rules
      triage/
        agent.py
        tool.py             # OpenAI routing synthesis
        functions.py        # Hard human-review rules
      copilot/
        agent.py
        tool.py             # OpenAI adjuster brief synthesis
        functions.py        # Fallback brief and evidence log helpers

    pipeline/
      orchestrator.py       # Pure Python sequential pipeline

    shared/
      config.py             # Environment-driven settings
      openai_client.py      # Shared OpenAI Responses API helper
      google_clients.py     # Lazy BigQuery/GCS client factories
      audit.py              # Safe audit/agent-output persistence
      gemini.py             # Compatibility shim; new code uses openai_client.py

  tests/
    sample_claim.json
    test_intake_functions.py
    test_pipeline_smoke.py

  .env.example
  requirements.txt
  pyproject.toml
  README.md
```

## 4. Core Components

### 4.1 Streamlit Operations Console

File: `app/streamlit_app.py`

The Streamlit console is the demo and operator UI. It can trigger the pipeline runner, display recent execution logs, show agent progress, and link out to Looker Studio. The app calls `app/run.py` through a subprocess, so it exercises the same path as the command-line runner.

Main environment variables:

- `LOOKER_URL`
- `CLAIMIQ_USE_OPENAI`
- `CLAIMIQ_WRITE_BQ`

### 4.2 Local Runner

File: `app/run.py`

The runner supports:

```powershell
python app\run.py --demo
python app\run.py --watch
python app\run.py --no-bq
```

Modes:

- `--demo`: Runs the built-in claim without Gmail.
- `--watch`: Polls Gmail every 60 seconds.
- `--no-bq`: Skips BigQuery writes for local testing.

The runner sends a received confirmation, extracts attachments, runs all agents, uploads documents to Drive, writes BigQuery rows, sends the final summary email, and prints a console summary.

### 4.3 Agent Package

Each agent follows the same structure:

- `agent.py`: The public `run(...)` entry point, audit events, exception handling, and fallback selection.
- `tool.py`: OpenAI prompt construction and external lookup calls where needed.
- `functions.py`: Deterministic business logic used for fallback and guardrails.

This makes each agent independently testable and keeps agent-specific code inside that agent folder.

## 5. Agent Details

### 5.1 Intake Agent

Path: `claimiq/agents/intake/`

Responsibilities:

- Read the email body and document summary.
- Extract claimant, policy number, claim type, incident date, amount, vehicle, location, risk indicators, missing information, and narrative summary.
- Use deterministic regex extraction when OpenAI is disabled or unavailable.

Important files:

- `tool.py`: Builds the OpenAI prompt for structured claim extraction.
- `functions.py`: Extracts policy number, amount, date, and claim type fallback.

### 5.2 Coverage Agent

Path: `claimiq/agents/coverage/`

Responsibilities:

- Look up the policy in BigQuery.
- Determine active status, coverage status, waiting-period breach, exclusions, limits, and reasoning.
- Fall back to deterministic coverage based on the policy record if OpenAI is unavailable.

Important files:

- `tool.py`: `lookup_policy(...)` and `reason_about_coverage(...)`.
- `functions.py`: Date parsing and deterministic coverage calculation.

BigQuery table expected:

- `{GCP_PROJECT_ID}.{BQ_DATASET}.policies`

### 5.3 Fraud Agent

Path: `claimiq/agents/fraud/`

Responsibilities:

- Run deterministic fraud checks before LLM synthesis.
- Detect new-policy timing, duplicate claim patterns, amount/limit anomalies, and risk signals.
- Keep the deterministic fraud score fixed when asking OpenAI to synthesize reasoning.

Important files:

- `functions.py`: Fraud weights and risk-band logic.
- `tool.py`: BigQuery duplicate lookup and fraud explanation prompt.

BigQuery table expected:

- `{GCP_PROJECT_ID}.{BQ_DATASET}.claims_master`

### 5.4 Triage Agent

Path: `claimiq/agents/triage/`

Responsibilities:

- Route the claim to auto approve, standard review, senior review, special investigation, or legal.
- Enforce hard human-review gates.
- Assign priority, color, SLA, and next steps.

Hard approval triggers:

- Fraud score above `FRAUD_HIGH_THRESHOLD`.
- Coverage is `needs_review` or `not_covered`.
- Claim amount above `HIGH_VALUE_THRESHOLD`.
- Claim type is health, medical, legal, or life.
- Duplicate claim detected.

### 5.5 Adjuster Copilot

Path: `claimiq/agents/copilot/`

Responsibilities:

- Combine intake, coverage, fraud, and triage outputs.
- Produce an adjuster-ready brief.
- Include evidence log, coverage position, fraud assessment, routing decision, open questions, checklist, and Markdown summary.

## 6. Shared Runtime

### 6.1 Configuration

File: `claimiq/shared/config.py`

All runtime settings are environment-driven. The app loads `.env` when `python-dotenv` is installed.

### 6.2 OpenAI Client

File: `claimiq/shared/openai_client.py`

This wraps OpenAI calls for the agents. It reads:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `CLAIMIQ_USE_OPENAI`

If `CLAIMIQ_USE_OPENAI=false`, agent code raises a controlled runtime error and falls back to deterministic behavior.

### 6.3 Audit Persistence

File: `claimiq/shared/audit.py`

The audit layer writes agent outputs and audit events when `CLAIMIQ_WRITE_BQ=true`. If BigQuery is not configured, it logs locally and does not crash the pipeline.

## 7. Environment Variables

Create `.env` from `.env.example`:

```powershell
copy .env.example .env
```

Required for OpenAI agent calls:

```text
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4.1
CLAIMIQ_USE_OPENAI=true
```

Required for BigQuery and Google Cloud:

```text
GCP_PROJECT_ID=your-project-id
GCP_REGION=us-central1
BQ_DATASET=claims
CLAIMIQ_WRITE_BQ=true
```

Required for Gmail:

```text
GMAIL_ADDRESS=claim.iq.ai.001@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password
```

Required for Google Forms approval links:

```text
FORM_URL_BASE=https://docs.google.com/forms/d/your-form-id/viewform?usp=pp_url&entry.your_entry_id=
```

Required for Looker Studio:

```text
LOOKER_URL=https://lookerstudio.google.com/reporting/your-report-id/page/your-page
```

Required for Google Drive upload:

```text
DRIVE_ROOT_FOLDER_NAME=ClaimIQ Claims
GOOGLE_OAUTH_CREDENTIALS=credentials.json
```

The actual credential files and `.env` should not be committed.

## 8. Installation

Recommended setup:

```powershell
cd D:\claimiq_hackathon
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Alternative editable install:

```powershell
pip install -e .
```

## 9. Running Locally

### 9.1 Deterministic Smoke Test Without External Services

```powershell
$env:CLAIMIQ_USE_OPENAI='false'
python -m claimiq.pipeline.orchestrator --sample tests\sample_claim.json --pretty
```

This verifies the pure Python agent chain without Gmail, BigQuery, Drive, or OpenAI.

### 9.2 Full App Demo Without BigQuery

```powershell
$env:CLAIMIQ_USE_OPENAI='false'
python app\run.py --demo --no-bq
```

This verifies the app runner shell, email skip behavior, agent sequence, Drive skip behavior, and final console summary.

### 9.3 Streamlit Console

```powershell
streamlit run app\streamlit_app.py
```

The Streamlit app launches the same `app/run.py` runner and displays operational progress.

### 9.4 Gmail Watch Mode

```powershell
python app\run.py --watch
```

This mode polls unread Gmail messages every 60 seconds. It requires `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`.

## 10. Google Service Setup

### 10.1 Gmail

1. Enable two-step verification on the Gmail account.
2. Create an app password.
3. Set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env`.
4. The app uses IMAP for reads and SMTP over SSL for sends.

### 10.2 Google Drive

1. Create an OAuth 2.0 Client ID in Google Cloud Console.
2. Download the OAuth client JSON.
3. Set `GOOGLE_OAUTH_CREDENTIALS=credentials.json`.
4. Run the app once. A browser consent flow opens.
5. The token is cached under `~/.claimiq/drive_token.json`.

### 10.3 BigQuery

The runtime expects tables similar to:

- `claims_master`
- `agent_outputs`
- `audit_trail`
- `policies`

`app/bq.py` writes operational dashboard rows to `claims_master` and `agent_outputs`.

`claimiq/shared/audit.py` can also write `audit_trail` and `agent_outputs` for agent-level events.

The writer strips unknown fields if it can read the table schema, so schema drift does not immediately break the app.

### 10.4 Looker Studio

Looker Studio should point to the BigQuery claim queue or claims master view. Configure the dashboard URL with:

```text
LOOKER_URL=...
```

The Streamlit console renders this as an external dashboard link.

## 11. Data Contracts

### 11.1 Pipeline Result

The orchestrator returns:

```json
{
  "claim_id": "CLM-...",
  "status": "complete",
  "triage_color": "amber",
  "fraud_score": 0,
  "required_human_approval": true,
  "outputs": {
    "intake": {},
    "coverage": {},
    "fraud": {},
    "triage": {},
    "copilot": {}
  },
  "errors": {},
  "duration_ms": 1234
}
```

### 11.2 BigQuery Claim Master Row

`app/bq.py` writes key fields:

- `claim_id`
- `sender_email`
- `claimant_name`
- `policy_number`
- `claim_type`
- `incident_date`
- `incident_description`
- `claim_amount_mentioned`
- `contact_phone`
- `location_of_incident`
- `vehicle_registration`
- `supporting_docs_mentioned`
- `attachment_count`
- `drive_folder_url`
- `doc_risk_signals`
- `validation_status`
- `missing_fields`
- `pipeline_status`
- `created_at`
- `updated_at`

### 11.3 Agent Outputs Row

One row per agent:

- `claim_id`
- `agent_name`
- `agent_version`
- `input_hash`
- `output_json`
- `status`
- `error_message`
- `started_at`
- `completed_at`
- `duration_ms`

## 12. Safety and Responsible AI Controls

ClaimIQ is designed as decision support, not autonomous settlement authority.

Controls:

- High-risk and high-value claims trigger mandatory human approval.
- Coverage uncertainty routes to human review.
- Fraud signals are evidence-linked and explainable.
- Agent failures fall back to safe deterministic outputs.
- Audit events and agent outputs are persisted when BigQuery is enabled.
- Customer-facing emails describe assessment status and next steps, not final legal liability.

## 13. Testing and Validation

Run syntax validation:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -c "import ast, pathlib; files=list(pathlib.Path('claimiq').rglob('*.py'))+list(pathlib.Path('app').rglob('*.py'))+list(pathlib.Path('tests').rglob('*.py')); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in files]; print(f'AST OK: {len(files)} files')"
```

Run tests after installing requirements:

```powershell
pytest -q
```

Current tests:

- `tests/test_intake_functions.py`: verifies fallback extraction does not confuse policy number with amount.
- `tests/test_pipeline_smoke.py`: verifies the pipeline produces intake and copilot outputs with OpenAI disabled.

## 14. Hackathon Submission Mapping

Track:

- Track 1 - Agents/Agentic Workflows for Industry/Business Transformation.

Industry:

- Insurance and financial services.

OpenAI usage:

- OpenAI API for specialist agent reasoning.
- Structured JSON prompts for agent-to-agent contracts.
- Codex for development, refactoring, test scaffolding, and documentation.
- ChatGPT Enterprise can be used in the video narrative to show adjuster Q&A over the generated brief.

Business impact:

- Faster first response.
- Automated claim data extraction.
- Automated coverage and fraud prioritization.
- Human-in-the-loop approval gates.
- Dashboard-ready BigQuery records.
- Auditable agent trace.

## 15. Known Local Development Notes

- If `OPENAI_API_KEY` is missing, set `CLAIMIQ_USE_OPENAI=false` for deterministic local testing.
- If `GMAIL_APP_PASSWORD` is missing, email send/read functions skip or return no messages safely.
- If Google Drive credentials are missing, upload is skipped and the pipeline still completes.
- If BigQuery credentials are missing, use `--no-bq` or `CLAIMIQ_WRITE_BQ=false`.
- `app/streamlit_app.py` requires Streamlit to be installed.
