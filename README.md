# ClaimIQ Hackathon

ClaimIQ is a Track 1 agentic insurance claims workflow for the HCLTech-OpenAI Agentic AI Hackathon.
It uses OpenAI APIs for specialist claim agents and Google Cloud services for insurance data, audit, and operations.
The code is organized so each agent owns its prompt, tools, and deterministic business logic.

## Structure

```text
claimiq/
  agents/
    intake/
      agent.py
      tool.py
      functions.py
    coverage/
      agent.py
      tool.py
      functions.py
    fraud/
      agent.py
      tool.py
      functions.py
    triage/
      agent.py
      tool.py
      functions.py
    copilot/
      agent.py
      tool.py
      functions.py
  pipeline/
    orchestrator.py
  shared/
    config.py
    openai_client.py
    google_clients.py
    audit.py
```

## Local Smoke Test

```powershell
python -m claimiq.pipeline.orchestrator --sample tests/sample_claim.json
```

Without API credentials, the pipeline still runs with safe deterministic fallbacks.
With `OPENAI_API_KEY` and project configuration, the agents use OpenAI models and BigQuery.

## Working App Surface

The proven operations layer from the working ClaimIQ folder lives in `app/`:

```powershell
streamlit run app/streamlit_app.py
python app/run.py --demo
python app/run.py --watch
```

It includes the Streamlit console, Gmail polling/sending, attachment extraction,
Google Drive upload, BigQuery writes, and Looker Studio dashboard link.
Real credentials are intentionally not copied into this repo; configure them through `.env`.

The working source you identified was used as the baseline for this `app/` layer,
excluding `credentials.json`, local logs, and Python cache files.

## Documentation

Detailed setup and code documentation is available at [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md).

## Hackathon Fit

- Track: Track 1 - Agents/Agentic Workflows for Industry/Business Transformation.
- Industry: Insurance and financial services.
- Workflow: Intake -> Coverage -> Fraud -> Triage -> Adjuster Copilot.
- OpenAI stack: OpenAI API for structured agent reasoning, Codex-assisted development, and optional ChatGPT Enterprise demo narration.
- Business impact: faster claim intake, fraud prioritization, auditable decisions, and mandatory human review gates for high-risk claims.
