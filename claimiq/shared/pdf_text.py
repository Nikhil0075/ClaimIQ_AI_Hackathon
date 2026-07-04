"""Sanitize text for PDF rendering with reportlab base-14 fonts.

Helvetica & friends are encoded as WinAnsi (cp1252). Any character outside
that set (emoji, non-breaking hyphens, arrows, rupee sign, ...) renders as a
black square. LLM-generated text frequently contains such characters, so both
PDF builders deep-sanitize their inputs through this module.

Strategy per character: keep if cp1252-encodable -> explicit replacement map
-> NFKD normalization (drops accents, splits ligatures) -> drop silently.
"""

from __future__ import annotations

import unicodedata
from typing import Any

# Explicit textual equivalents for characters NFKD cannot resolve.
_REPLACEMENTS = {
    "‐": "-",      # hyphen
    "‑": "-",      # non-breaking hyphen (the "fire‑spread" culprit)
    "‒": "-",      # figure dash
    "―": "-",      # horizontal bar
    "⁃": "-",      # hyphen bullet
    "→": "->",     # rightwards arrow
    "←": "<-",     # leftwards arrow
    "⇒": "=>",     # rightwards double arrow
    "₹": "Rs ",    # Indian rupee sign
    "≈": "~",      # almost equal
    "≠": "!=",     # not equal
    "≤": "<=",     # less-than or equal
    "≥": ">=",     # greater-than or equal
    "•": "*",      # bullet is in cp1252, listed for safety
    "●": "*",      # black circle
    "■": "*",      # black square
    "✓": "[x]",    # check mark
    "✔": "[x]",    # heavy check mark
    "☑": "[x]",    # ballot box with check
    "☐": "[ ]",    # ballot box
    "✗": "[!]",    # ballot x
    "⚠": "!",      # warning sign
    "✅": "[OK]",   # white heavy check mark
    "❌": "[X]",    # cross mark
    "★": "*",      # black star
    "☆": "*",      # white star
    "​": "",       # zero-width space
    "‌": "",       # zero-width non-joiner
    "‍": "",       # zero-width joiner
    "﻿": "",       # BOM
    " ": " ",      # narrow no-break space
    " ": " ",      # figure space
    " ": " ",      # thin space
    " ": " ",      # hair space
}


def sanitize_pdf_text(text: str) -> str:
    """Return `text` with every non-cp1252 character replaced or dropped."""
    if not isinstance(text, str):
        return text
    try:
        text.encode("cp1252")
        return text  # fast path: already fully renderable
    except UnicodeEncodeError:
        pass

    out: list[str] = []
    for ch in text:
        try:
            ch.encode("cp1252")
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass
        mapped = _REPLACEMENTS.get(ch)
        if mapped is not None:
            out.append(mapped)
            continue
        # Try to decompose (é -> e, ﬁ -> fi, ² -> 2, …)
        norm = unicodedata.normalize("NFKD", ch)
        norm = "".join(c for c in norm if not unicodedata.combining(c))
        try:
            norm.encode("cp1252")
            out.append(norm)
        except UnicodeEncodeError:
            # Emoji / symbols with no textual equivalent: drop rather than ■
            continue
    return "".join(out)


def sanitize_deep(value: Any) -> Any:
    """Recursively sanitize every string inside dicts/lists/tuples."""
    if isinstance(value, str):
        return sanitize_pdf_text(value)
    if isinstance(value, dict):
        return {key: sanitize_deep(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_deep(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_deep(item) for item in value)
    return value
