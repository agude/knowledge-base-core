"""Claude Stop: append the reply to the session buffer.

KNOWLEDGE_SESSION_FILE, set by SessionStart, takes precedence over the
session ID; an empty message records nothing.
"""

from __future__ import annotations

import os

from kb import platform
from kb.commands import session_append
from kb.commands.adapters import hook


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    if os.environ.get("KNOWLEDGE_OBSERVE") == "0" or not os.environ.get("KNOWLEDGE_BASE"):
        return 0
    data = hook.payload()
    session_id = hook.text(data, "session_id")
    if not session_id:
        return 0
    message = hook.text(data, "last_assistant_message").encode("utf-8", errors="surrogateescape")
    if not message:
        return 0
    file = os.environ.get("KNOWLEDGE_SESSION_FILE", "")
    return session_append.record(file, "" if file else session_id, "assistant", message)
