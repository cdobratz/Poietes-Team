"""
tools/llm_json.py — Parse a JSON object out of an LLM reply.

Supervisor, monitor, coder, security, and content all strip the same fences.
"""
from __future__ import annotations

import json


def parse_llm_json(raw: str) -> dict | None:
    """Return a JSON object from ``raw``, or None when it is not one.

    Strips a single leading ```json / ``` fence and a single trailing ``` fence.
    Non-strings, non-objects, and invalid JSON return None so callers can apply
    their own fallback.
    """
    if not isinstance(raw, str):
        return None
    try:
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(clean)
    except (json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
