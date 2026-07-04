"""Backward-compatible import shim.

ClaimIQ has been migrated to OpenAI APIs for the hackathon track. New code
should import from claimiq.shared.openai_client directly.
"""

from .openai_client import generate_json, parse_json

__all__ = ["generate_json", "parse_json"]
