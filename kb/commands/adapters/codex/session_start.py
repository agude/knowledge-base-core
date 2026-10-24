"""Codex SessionStart: start capture, then return the context as hook JSON."""

from __future__ import annotations

import json
import os

from kb import output, platform, session
from kb.commands import session_context
from kb.commands.adapters import hook


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    if not os.environ.get("KNOWLEDGE_BASE"):
        print("{}")
        return 0
    data = hook.payload()
    session_id = hook.text(data, "session_id")
    if os.environ.get("KNOWLEDGE_OBSERVE") != "0" and session_id:
        # Codex runs each hook in a fresh process, so initialization persists.
        try:
            with output.discarded():
                directory = session.session_dir()
                buffer = session.buffer_path(directory, session_id)
                if buffer is not None and session.ensure_dir(directory):
                    buffer.touch()
                    platform.make_private(buffer)
                    session.mark_initialized(directory, session_id)
                    session.sweep(directory, buffer)
        except Exception:  # As `session-init ... || true`: capture never blocks the context.
            pass
    try:
        context = session_context.text().rstrip("\n")
    except Exception:  # No context is an empty object, never a failed hook.
        context = ""
    if context:
        document = {
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}
        }
        print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    else:
        print("{}")
    return 0
