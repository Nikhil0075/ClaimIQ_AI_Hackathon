"""OpenAI client helpers for ClaimIQ agents."""

from __future__ import annotations

import json
import logging
import os
import re
import base64
import time
from collections.abc import Callable
from typing import Any

from .config import settings

log = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key or api_key in {"sk-your-key", "your-openai-api-key"}:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from openai import OpenAI

        _client = OpenAI()
    return _client


def parse_json(raw: str) -> dict[str, Any]:
    clean = _strip_json_fence(raw)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        extracted = _extract_json_object(clean)
        if extracted:
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
        log.warning("OpenAI returned non-JSON content: %s", clean[:300])
        return {"error": "json_parse_failed", "details": str(exc), "_raw": clean[:1000]}


def _strip_json_fence(raw: str) -> str:
    clean = (raw or "").strip()
    fence = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", clean, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return clean


def _extract_json_object(text: str) -> str:
    """Return the first balanced JSON object from a prose-wrapped response."""
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ""


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def _openai_enabled() -> bool:
    use_openai = os.getenv("CLAIMIQ_USE_OPENAI", str(settings.use_openai)).strip().lower()
    if use_openai in {"0", "false", "no", "off"}:
        return False
    return True


def _json_mode_enabled() -> bool:
    """Native JSON output mode (structured response format). On by default;
    set CLAIMIQ_JSON_MODE=false if a configured model rejects the parameter."""
    return os.getenv("CLAIMIQ_JSON_MODE", "true").strip().lower() not in {"0", "false", "no", "off"}


def _is_format_error(exc: Exception) -> bool:
    """True when the API rejected the JSON response-format parameter itself."""
    text = str(exc).lower()
    return any(term in text for term in ("response_format", "text.format", "json_object", "unsupported parameter", "unknown parameter"))


def generate_json(
    prompt: str,
    *,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    if not _openai_enabled():
        raise RuntimeError("OpenAI calls are disabled by CLAIMIQ_USE_OPENAI=false")

    selected_model = model or os.getenv("OPENAI_MODEL", settings.openai_model)
    request = {
        "model": selected_model,
        "input": prompt,
        "max_output_tokens": max_tokens,
    }
    if _is_reasoning_model(selected_model):
        effort = reasoning_effort or os.getenv("REASONING_EFFORT", settings.reasoning_effort)
        request["reasoning"] = {"effort": effort}
    else:
        request["temperature"] = temperature
    if _json_mode_enabled():
        # Native JSON mode: the model is constrained to emit a single valid JSON
        # object, making the fence-stripping/extraction path a rare fallback.
        request["text"] = {"format": {"type": "json_object"}}

    try:
        response = _call_with_rate_limit_retry(lambda: _get_client().responses.create(**request))
    except Exception as exc:
        if "text" in request and _is_format_error(exc):
            log.warning("Model %s rejected JSON response format (%s) — retrying without", selected_model, exc)
            request.pop("text", None)
            response = _call_with_rate_limit_retry(lambda: _get_client().responses.create(**request))
        else:
            raise
    parsed = parse_json(_response_text(response))
    if _should_retry_json_parse(parsed, max_tokens):
        retry_tokens = _retry_token_budget(max_tokens)
        log.info("Retrying OpenAI JSON generation with max_output_tokens=%s", retry_tokens)
        request["max_output_tokens"] = retry_tokens
        response = _call_with_rate_limit_retry(lambda: _get_client().responses.create(**request))
        parsed = parse_json(_response_text(response))
    return parsed


def generate_json_messages(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Generate strict JSON from chat-style messages.

    This path mirrors the working local test.py SDK pattern and also supports
    vision inputs through OpenAI chat message content parts.
    """
    if not _openai_enabled():
        raise RuntimeError("OpenAI calls are disabled by CLAIMIQ_USE_OPENAI=false")

    selected_model = model or os.getenv("OPENAI_MODEL", settings.openai_model)
    request = {
        "model": selected_model,
        "messages": messages,
    }
    if _is_reasoning_model(selected_model):
        effort = reasoning_effort or os.getenv("REASONING_EFFORT", settings.reasoning_effort)
        request["reasoning_effort"] = effort
        request["max_completion_tokens"] = max_tokens
    else:
        request["temperature"] = temperature
        request["max_tokens"] = max_tokens
    if _json_mode_enabled():
        request["response_format"] = {"type": "json_object"}

    try:
        response = _call_with_rate_limit_retry(lambda: _get_client().chat.completions.create(**request))
    except Exception as exc:
        if "response_format" in request and _is_format_error(exc):
            log.warning("Model %s rejected response_format (%s) — retrying without", selected_model, exc)
            request.pop("response_format", None)
            response = _call_with_rate_limit_retry(lambda: _get_client().chat.completions.create(**request))
        else:
            raise
    content = response.choices[0].message.content or ""
    parsed = parse_json(content)
    if _should_retry_json_parse(parsed, max_tokens):
        retry_tokens = _retry_token_budget(max_tokens)
        log.info("Retrying OpenAI chat JSON generation with max_tokens=%s", retry_tokens)
        if _is_reasoning_model(selected_model):
            request["max_completion_tokens"] = retry_tokens
        else:
            request["max_tokens"] = retry_tokens
        response = _call_with_rate_limit_retry(lambda: _get_client().chat.completions.create(**request))
        content = response.choices[0].message.content or ""
        parsed = parse_json(content)
    return parsed


def image_content_part(data: bytes, mime_type: str) -> dict[str, Any]:
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def is_rate_limit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    code = str(getattr(exc, "code", "") or "").lower()
    if code in {"rate_limit", "rate_limit_exceeded"}:
        return True
    text = str(exc).lower()
    return "rate limit" in text or "rate_limit_exceeded" in text or "too many requests" in text


def _call_with_rate_limit_retry(call: Callable[[], Any]) -> Any:
    max_attempts = max(1, int(os.getenv("CLAIMIQ_OPENAI_RATE_LIMIT_ATTEMPTS", "4")))
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not is_rate_limit_error(exc) or attempt >= max_attempts:
                raise
            delay = _rate_limit_delay_seconds(exc, attempt)
            log.warning(
                "OpenAI rate limit hit; retrying attempt %s/%s after %.2fs",
                attempt + 1,
                max_attempts,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError("OpenAI rate-limit retry loop ended unexpectedly")


def _rate_limit_delay_seconds(exc: Exception, attempt: int) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    raw_retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if raw_retry_after:
        try:
            return min(max(float(raw_retry_after), 0.1), 8.0)
        except ValueError:
            pass

    text = str(exc)
    ms_match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*ms", text, flags=re.IGNORECASE)
    if ms_match:
        return min(max(float(ms_match.group(1)) / 1000.0, 0.1), 8.0)
    sec_match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*s", text, flags=re.IGNORECASE)
    if sec_match:
        return min(max(float(sec_match.group(1)), 0.1), 8.0)
    return min(0.5 * (2 ** (attempt - 1)), 8.0)


_DEFAULT_REASONING_PREFIXES = "o1,o3,o4,gpt-5"


def _is_reasoning_model(model: str) -> bool:
    """Whether the model takes reasoning-effort params instead of temperature.

    Prefix allowlist is env-overridable (CLAIMIQ_REASONING_MODEL_PREFIXES,
    comma-separated) so new model families don't silently take the wrong
    request-parameter branch until a code change ships.
    """
    normalized = (model or "").lower()
    raw = os.getenv("CLAIMIQ_REASONING_MODEL_PREFIXES", _DEFAULT_REASONING_PREFIXES)
    prefixes = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return any(normalized.startswith(prefix) for prefix in prefixes)


def _should_retry_json_parse(parsed: dict[str, Any], max_tokens: int) -> bool:
    if parsed.get("error") != "json_parse_failed":
        return False
    if max_tokens >= _json_retry_max_tokens():
        return False
    raw = str(parsed.get("_raw") or "").lstrip()
    return raw.startswith("{") or raw.startswith("[") or "Unterminated string" in str(parsed.get("details") or "")


def _retry_token_budget(max_tokens: int) -> int:
    return min(max(max_tokens * 2, max_tokens + 1024), _json_retry_max_tokens())


def _json_retry_max_tokens() -> int:
    return int(os.getenv("CLAIMIQ_JSON_RETRY_MAX_TOKENS", "12000"))
