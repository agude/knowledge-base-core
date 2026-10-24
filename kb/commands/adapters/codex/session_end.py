"""Codex SessionEnd: flush the buffer synchronously; always print one JSON object.

Codex allows SessionEnd at most three seconds, and the commit lock waits
30 seconds by default, so the flush waits at most one second: a held lock
fails inside the budget and the buffer stays for a later sweep. The exit
status is the flush's, so a failed flush stays visible.
"""

from __future__ import annotations

import os

from kb import output, platform, session
from kb.commands.adapters import hook


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    if not os.environ.get("KNOWLEDGE_BASE") or os.environ.get("KNOWLEDGE_OBSERVE") == "0":
        print("{}")
        return 0
    data = hook.payload()
    session_id = hook.text(data, "session_id")
    buffer = session.buffer_path(session.session_dir(), session_id) if session_id else None
    status = 0
    if buffer is not None:
        os.environ["KNOWLEDGE_LOCK_WAIT"] = "1"
        os.environ["KNOWLEDGE_OBSERVE"] = "1"
        with output.discarded():
            status = session.flush(buffer, announce=False)
    print("{}")
    return status
