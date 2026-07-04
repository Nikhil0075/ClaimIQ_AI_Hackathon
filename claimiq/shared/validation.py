"""Input validation helpers for ClaimIQ pipeline boundaries."""

from __future__ import annotations

import os
import re
from typing import Any


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class InputValidator:
    """Centralized validation for externally supplied claim payload fields.

    Limits are env-overridable so ops can raise them without a code change.
    Validation failures should be routed to a customer rewrite request by the
    orchestrator — they are not meant to crash the pipeline.
    """

    MAX_EMAIL_LENGTH = _env_int("CLAIMIQ_MAX_EMAIL_LENGTH", 50_000)
    MAX_SUBJECT_LENGTH = _env_int("CLAIMIQ_MAX_SUBJECT_LENGTH", 500)
    MAX_POLICY_NUMBER_LENGTH = _env_int("CLAIMIQ_MAX_POLICY_NUMBER_LENGTH", 50)
    # 5 crore default — high-value property/fire claims routinely exceed 1 crore.
    MAX_CLAIM_AMOUNT_INR = _env_int("CLAIMIQ_MAX_CLAIM_AMOUNT_INR", 50_000_000)
    MAX_UPLOADED_DOCUMENTS = _env_int("CLAIMIQ_MAX_UPLOADED_DOCUMENTS", 25)

    POLICY_REGEX = {
        "india": r"^[A-Z]{2,3}[- ]?\d{4,12}(?:[- ]?[A-Z0-9]+)?$",
        "uk": r"^[A-Z]{2,3}\d{8,10}$",
        "us": r"^[A-Z0-9]{8,20}$",
    }

    FORBIDDEN_PATTERNS = (
        r"<script.*?</script>",
        r"\beval\s*\(",
        r"\bos\.(system|exec|popen)\s*\(",
        r"\bsubprocess\.(run|call|popen)\s*\(",
    )

    @classmethod
    def validate_email_body(cls, body: str, market: str = "india") -> tuple[bool, str]:
        if not isinstance(body, str):
            return False, "email_body must be string"
        if not body.strip():
            return False, "email_body cannot be empty"
        if len(body) > cls.MAX_EMAIL_LENGTH:
            return False, f"email_body exceeds {cls.MAX_EMAIL_LENGTH} chars"
        return cls._check_forbidden_patterns(body, "email_body")

    @classmethod
    def validate_subject(cls, subject: str | None) -> tuple[bool, str]:
        if subject is None:
            return True, "OK"
        if not isinstance(subject, str):
            return False, "subject must be string"
        if len(subject) > cls.MAX_SUBJECT_LENGTH:
            return False, f"subject exceeds {cls.MAX_SUBJECT_LENGTH} chars"
        return cls._check_forbidden_patterns(subject, "subject")

    @classmethod
    def validate_policy_number(cls, policy_num: str | None, market: str = "india") -> tuple[bool, str]:
        if not policy_num:
            return True, "OK"
        if not isinstance(policy_num, str):
            return False, "policy_number must be string"
        normalized = policy_num.strip().upper()
        if len(normalized) > cls.MAX_POLICY_NUMBER_LENGTH:
            return False, f"policy_number exceeds {cls.MAX_POLICY_NUMBER_LENGTH} chars"
        regex = cls.POLICY_REGEX.get(market)
        if regex and not re.match(regex, normalized):
            return False, f"policy_number does not match {market} format"
        return True, "OK"

    @classmethod
    def validate_claim_amount(cls, amount: Any, currency: str = "INR") -> tuple[bool, str]:
        if amount in (None, ""):
            return True, "OK"
        if not isinstance(amount, (int, float)):
            return False, "claim_amount must be numeric"
        if amount <= 0:
            return False, "claim_amount must be > 0"
        if currency == "INR" and amount > cls.MAX_CLAIM_AMOUNT_INR:
            return False, f"claim_amount exceeds {cls.MAX_CLAIM_AMOUNT_INR} INR"
        return True, "OK"

    @classmethod
    def validate_uploaded_documents(cls, uploaded_documents: list[dict[str, Any]] | None) -> tuple[bool, str]:
        if uploaded_documents is None:
            return True, "OK"
        if not isinstance(uploaded_documents, list):
            return False, "uploaded_documents must be a list"
        if len(uploaded_documents) > cls.MAX_UPLOADED_DOCUMENTS:
            return False, f"uploaded_documents exceeds {cls.MAX_UPLOADED_DOCUMENTS} files"
        for index, document in enumerate(uploaded_documents):
            if not isinstance(document, dict):
                return False, f"uploaded_documents[{index}] must be a dict"
            filename = document.get("filename")
            if filename is not None and not isinstance(filename, str):
                return False, f"uploaded_documents[{index}].filename must be string"
            data = document.get("data")
            if data is not None and not isinstance(data, bytes):
                return False, f"uploaded_documents[{index}].data must be bytes"
        return True, "OK"

    @classmethod
    def validate_pipeline_inputs(
        cls,
        *,
        email_body: str,
        subject: str = "",
        documents_summary: dict[str, Any] | None = None,
        uploaded_documents: list[dict[str, Any]] | None = None,
        market: str = "india",
    ) -> None:
        checks = [
            cls.validate_email_body(email_body, market),
            cls.validate_subject(subject),
            cls.validate_uploaded_documents(uploaded_documents),
        ]
        if isinstance(documents_summary, dict):
            checks.extend([
                cls.validate_policy_number(documents_summary.get("policy_number"), market),
                cls.validate_claim_amount(documents_summary.get("claim_amount"), str(documents_summary.get("currency") or "INR")),
            ])
        for is_valid, message in checks:
            if not is_valid:
                raise ValueError(message)

    @classmethod
    def _check_forbidden_patterns(cls, value: str, field_name: str) -> tuple[bool, str]:
        for pattern in cls.FORBIDDEN_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE | re.DOTALL):
                return False, f"{field_name} contains forbidden pattern"
        return True, "OK"
