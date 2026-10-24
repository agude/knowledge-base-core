"""Host adapter helpers: reading the hook payload as jq would."""

from __future__ import annotations

import json
import sys


def payload() -> dict[str, object]:
    """The hook's JSON input; anything unreadable is an empty object."""
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def text(data: dict[str, object], key: str) -> str:
    """`jq -r '.key // empty'`: null and false are empty; other non-strings print as JSON."""
    value = data.get(key)
    if value is None or value is False:
        return ""
    if isinstance(value, str):
        return value
    return (
        json.dumps(value, indent=2, ensure_ascii=False)
        if isinstance(value, dict | list)
        else json.dumps(value)
    )
