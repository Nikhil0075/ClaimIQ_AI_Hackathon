from app import attachments


def test_browser_oauth_disabled_for_deployment_token_path(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_TOKEN_PATH", "/tmp/claimiq/drive_token.json")
    monkeypatch.delenv("CLAIMIQ_ALLOW_BROWSER_OAUTH", raising=False)
    monkeypatch.delenv("CLAIMIQ_DRIVE_TOKEN_SOURCE", raising=False)

    assert attachments._browser_oauth_allowed() is False
    assert "GOOGLE_DRIVE_TOKEN_JSON" in attachments._browser_oauth_unavailable_message()


def test_browser_oauth_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_TOKEN_PATH", "/tmp/claimiq/drive_token.json")
    monkeypatch.setenv("CLAIMIQ_ALLOW_BROWSER_OAUTH", "true")

    assert attachments._browser_oauth_allowed() is True
