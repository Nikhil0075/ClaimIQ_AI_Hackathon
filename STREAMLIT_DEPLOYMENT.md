# ClaimIQ Streamlit Cloud Deployment

## App Settings

- Repository: `Nikhil0075/ClaimIQ_AI_Hackathon`
- Branch: `main`
- Main file path: `app/streamlit_app.py`
- Python version: `3.11` or `3.12`

## Required Secrets

Paste these in Streamlit Cloud app secrets. Do not commit these values to Git.

```toml
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-4o-mini"
CLAIMIQ_USE_OPENAI = "true"

GCP_PROJECT_ID = "your-gcp-project-id"
GOOGLE_CLOUD_PROJECT = "your-gcp-project-id"
GCP_REGION = "us-central1"
BQ_DATASET = "claims"
GOOGLE_APPLICATION_CREDENTIALS_JSON = """{...contents of a Google service account JSON with BigQuery access...}"""

GMAIL_ADDRESS = "your-claims-inbox@gmail.com"
GMAIL_APP_PASSWORD = "your-gmail-app-password"

LOOKER_URL = "https://lookerstudio.google.com/reporting/..."
FORM_URL_BASE = "https://docs.google.com/forms/d/.../viewform?usp=pp_url&entry.684140824="
DRIVE_ROOT_FOLDER_NAME = "ClaimIQ Claims"

GOOGLE_OAUTH_CREDENTIALS_JSON = """{...contents of credentials.json...}"""
GOOGLE_DRIVE_TOKEN_JSON = """{...contents of the generated Drive OAuth token JSON...}"""
```

## Google Drive OAuth Token

The app intentionally keeps the existing Google OAuth credentials flow.
Streamlit Cloud cannot reliably perform the first browser consent flow, so:

1. Run ClaimIQ locally with `GOOGLE_OAUTH_CREDENTIALS` pointing to `credentials.json`.
2. Complete the Google Drive browser consent flow locally.
3. Confirm a Drive upload works.
4. Copy the generated token JSON into `GOOGLE_DRIVE_TOKEN_JSON` in Streamlit Cloud secrets.

At runtime, `app/streamlit_deploy.py` writes both OAuth JSON secrets to private files
and sets `GOOGLE_OAUTH_CREDENTIALS` plus `GOOGLE_DRIVE_TOKEN_PATH` for the existing
Drive uploader.

If the generated token JSON is inconvenient to paste, you can instead set:

```toml
GOOGLE_OAUTH_CREDENTIALS_JSON = """{...contents of credentials.json...}"""
GOOGLE_DRIVE_REFRESH_TOKEN = "1//..."
```

The app will build the authorized-user token file from the OAuth client JSON and
refresh token.

Do not paste `credentials.json` into `GOOGLE_DRIVE_TOKEN_JSON`. That secret must
contain an authorized-user token with `client_id`, `client_secret`, and
`refresh_token`.

## BigQuery / Google Cloud Credentials

Streamlit Cloud is not Google Compute Engine, so Google libraries cannot use the
metadata server. If you see `metadata.google.internal` timeout errors, set:

```toml
GOOGLE_APPLICATION_CREDENTIALS_JSON = """{...service account JSON...}"""
```

The service account needs access to the project in `GCP_PROJECT_ID` and the
dataset in `BQ_DATASET`. At minimum, grant BigQuery Job User and BigQuery Data
Editor for the ClaimIQ dataset.

The app logs a startup deployment diagnostic. If this secret is missing, Google
Cloud lookups/writes fail fast with a clear configuration message instead of
waiting on the unavailable metadata server.

## Verification

After deployment:

1. Open the Streamlit app URL.
2. Run the demo claim.
3. Process one Gmail claim with an attachment.
4. Confirm OpenAI output, Gmail email, BigQuery rows, Drive folder upload, and Looker dashboard link.

For always-on Gmail polling, run `python app/run.py --watch` on a separate worker host.
