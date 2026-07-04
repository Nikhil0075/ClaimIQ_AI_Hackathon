from claimiq.agents.coverage import tool as coverage_tool
from claimiq.agents.intake import tool as intake_tool
from claimiq.pipeline import mail_guard, router
from claimiq.pipeline.session import ClaimSession
from claimiq.shared.config import settings


def test_mail_guard_uses_lightweight_model(monkeypatch):
    captured = {}

    def fake_generate_json(prompt, **kwargs):
        captured.update(kwargs)
        return {"action": "rewrite_request", "missing_fields": [], "confidence": 0.5}

    monkeypatch.setattr(mail_guard, "generate_json", fake_generate_json)

    mail_guard._evaluate_with_openai("How do I file a claim?")

    assert captured["model"] == settings.lightweight_model


def test_router_uses_orchestrator_model_with_medium_reasoning(monkeypatch):
    captured = {}

    def fake_generate_json(prompt, **kwargs):
        captured.update(kwargs)
        return {"selected_agents": ["coverage", "fraud", "triage", "copilot"]}

    monkeypatch.setattr(router, "generate_json", fake_generate_json)
    session = ClaimSession(claim_id="CLM-MODEL-1", email_body="Policy POL-123456")
    session = session.add_agent_output("intake", {"intake_status": "complete", "policy_number": "POL-123456"})

    router._choose_with_openai(session)

    assert captured["model"] == "gpt-5.5"
    assert captured["reasoning_effort"] == "medium"


def test_coverage_uses_reasoning_model(monkeypatch):
    captured = {}

    def fake_generate_json(prompt, **kwargs):
        captured.update(kwargs)
        return {"coverage_status": "needs_review"}

    monkeypatch.setattr(coverage_tool, "generate_json", fake_generate_json)

    coverage_tool.reason_about_coverage({"claim_type": "health"}, {}, {})

    assert captured["model"] == settings.reasoning_model


def test_intake_splits_reasoning_text_and_vision_models(monkeypatch):
    captured = {"json": [], "messages": []}

    def fake_generate_json(prompt, **kwargs):
        captured["json"].append(kwargs)
        return {"intake_status": "complete"}

    def fake_generate_json_messages(messages, **kwargs):
        captured["messages"].append(kwargs)
        return {"document_type": "damage_photo"}

    monkeypatch.setattr(intake_tool, "generate_json", fake_generate_json)
    monkeypatch.setattr(intake_tool, "generate_json_messages", fake_generate_json_messages)

    intake_tool.extract_claim("Policy POL-123456. Incident on 2026-06-10.", uploaded_documents=[])
    intake_tool._analyze_text_document("note.txt", "text/plain", "Invoice INR 50000")
    intake_tool._analyze_image_document("photo.png", "image/png", b"fake-bytes")

    assert captured["json"][0]["model"] == settings.reasoning_model
    assert captured["json"][1]["model"] == settings.lightweight_model
    assert captured["messages"][0]["model"] == settings.vision_model
