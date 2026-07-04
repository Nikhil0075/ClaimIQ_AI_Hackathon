import pytest
from dataclasses import FrozenInstanceError

from claimiq.pipeline.orchestrator import run_pipeline
from claimiq.pipeline.session import ClaimSession
from claimiq.shared.validation import InputValidator


def test_claim_session_transitions_are_versioned_and_immutable():
    session = ClaimSession(claim_id="CLM-STATE-1", email_body="Policy POL-123456 accident details.")

    with pytest.raises(FrozenInstanceError):
        session.workflow_state = "complete"

    next_session = session.transition_state("guard_passed")

    assert session.workflow_state == "initialized"
    assert next_session.workflow_state == "guard_passed"
    assert next_session.workflow_version == session.workflow_version + 1

    with pytest.raises(ValueError):
        next_session.transition_state("agents_running")


def test_claim_session_records_outputs_and_errors_functionally():
    session = ClaimSession(claim_id="CLM-STATE-2", email_body="Policy POL-123456 accident details.")
    updated = session.add_agent_output("intake", {"policy_number": "POL-123456"})
    failed = updated.add_agent_error("coverage", "Policy lookup failed")

    assert session.outputs == {}
    assert updated.outputs["intake"]["policy_number"] == "POL-123456"
    assert failed.errors["coverage"] == "Policy lookup failed"
    assert failed.agent_errors["coverage"] == ["Policy lookup failed"]


def test_pipeline_rejects_forbidden_email_body_before_session_start():
    with pytest.raises(ValueError, match="forbidden pattern"):
        run_pipeline(
            claim_id="CLM-BAD-1",
            email_body="<script>alert('x')</script>",
            sender_email="customer@example.com",
        )


def test_input_validator_allows_existing_demo_policy_format():
    assert InputValidator.validate_policy_number("POL-123456")[0] is True
    assert InputValidator.validate_policy_number("HLT-78901")[0] is True
