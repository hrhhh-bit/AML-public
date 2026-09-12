"""Robust JSON extraction utilities shared by distillation & parsing.

Format-agnostic helpers that tolerate the noise typical of fast LLM output:
markdown fences, chain-of-thought preambles/postambles, trailing commas and
single-element array wrappers.  Kept in ``aml_rag`` so both the extractor and
the distiller can reuse them without an upward dependency on the agent layer.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = [
    "strip_code_fences",
    "extract_outermost_json",
    "load_json_robust",
    "extract_json_list",
]

#: Strips any ```lang ... ``` fence (json, python, plain, ...).
_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*(.*?)\s*```", re.DOTALL)
#: Removes trailing commas before a closing brace/bracket.
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_all_fences(text: str) -> str:
    prev: str | None = None
    while prev != text:
        prev = text
        text = _FENCE_RE.sub(r"\1", text)
    return text.strip()


def extract_outermost_json(text: str) -> str:
    """Return the outermost balanced JSON object/array via bracket matching."""
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escaped = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            return text[start : end + 1]
    return text


def strip_code_fences(raw: str) -> str:
    """Remove fences / prose and keep the outermost JSON chunk."""
    return extract_outermost_json(_strip_all_fences(raw))


def load_json_robust(text: str) -> tuple[Any | None, str | None]:
    """Load JSON with a trailing-comma repair fallback.

    Returns ``(payload, error)`` — ``error`` is a standardised syntax message.
    """
    try:
        return json.loads(text), None
    except json.JSONDecodeError as first_exc:
        repaired = _TRAILING_COMMA_RE.sub(r"\1", text)
        try:
            return json.loads(repaired), None
        except json.JSONDecodeError as second_exc:
            return None, (
                f"invalid JSON after cleanup: {second_exc.msg} at "
                f"line {second_exc.lineno} col {second_exc.colno}"
            )


def extract_json_list(raw: str) -> tuple[list[Any] | None, str | None]:
    """Extract a JSON array from an LLM reply (single object -> one-element list)."""
    cleaned = strip_code_fences(raw)
    payload, error = load_json_robust(cleaned)
    if error is not None:
        return None, error
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        return [payload], None
    return None, f"expected a JSON object/array, got {type(payload).__name__}"
