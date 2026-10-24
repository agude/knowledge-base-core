"""Codex UserPromptSubmit: append the prompt; always print one JSON object."""

from __future__ import annotations

import os

from kb import platform
from kb.commands import session_append
from kb.commands.adapters import hook


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    if not os.environ.get("KNOWLEDGE_BASE") or os.environ.get("KNOWLEDGE_OBSERVE") == "0":
        print("{}")
        return 0
    data = hook.payload()
    session_id = hook.text(data, "session_id")
    status = 0
    message = hook.text(data, "prompt").encode("utf-8", errors="surrogateescape")
    if session_id and message:
        try:
            status = session_append.record("", session_id, "user", message)
        except SystemExit as error:
            status = error.code if isinstance(error.code, int) else 1
    print("{}")
    return status
