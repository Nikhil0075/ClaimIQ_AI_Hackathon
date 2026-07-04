from types import SimpleNamespace

from claimiq.shared import openai_client
from claimiq.shared.openai_client import generate_json, parse_json


def test_parse_json_extracts_object_from_prose_wrapped_response():
    result = parse_json('Here is the JSON:\n{"intake_status":"complete","confidence_score":0.91}\nDone.')

    assert result["intake_status"] == "complete"
    assert result["confidence_score"] == 0.91


def test_parse_json_handles_json_code_fence():
    result = parse_json('```json\n{"claim_type":"health"}\n```')

    assert result["claim_type"] == "health"


def test_generate_json_retries_truncated_json(monkeypatch):
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(output_text='{"intake_status":"needs_review","classified_documents":{"doc')
            return SimpleNamespace(output_text='{"intake_status":"needs_review","classified_documents":{"doc.pdf":"medical_record"}}')

    monkeypatch.setattr(openai_client, "_openai_enabled", lambda: True)
    monkeypatch.setattr(openai_client, "_get_client", lambda: SimpleNamespace(responses=FakeResponses()))

    result = generate_json("return json", max_tokens=4096, model="gpt-4o-mini")

    assert result["intake_status"] == "needs_review"
    assert result["classified_documents"]["doc.pdf"] == "medical_record"
    assert len(calls) == 2
    assert calls[0]["max_output_tokens"] == 4096
    assert calls[1]["max_output_tokens"] == 8192
