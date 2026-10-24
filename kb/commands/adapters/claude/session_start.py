"""Claude SessionStart: start capture, then print the session context.

Claude injects this hook's stdout into the session as plain text, so the
context is printed however capture setup ends.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

from kb import output, platform, session
from kb.commands import session_context
from kb.commands.adapters import hook


def _start(data: dict[str, object]) -> None:
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if os.environ.get("KNOWLEDGE_OBSERVE") == "0":
        if env_file:
            platform.append_text(Path(env_file), "KNOWLEDGE_OBSERVE=0\n")
        return
    session_id = hook.text(data, "session_id") or f"{os.getpid()}-{int(time.time())}"
    directory = session.session_dir()
    buffer = session.buffer_path(directory, session_id)
    if buffer is None or not session.ensure_dir(directory):
        return
    buffer.touch()
    platform.make_private(buffer)
    with output.discarded():
        session.sweep(directory, buffer)
    if env_file:
        platform.append_text(
            Path(env_file), f"KNOWLEDGE_OBSERVE=1\nKNOWLEDGE_SESSION_FILE={buffer}\n"
        )


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    data = hook.payload()
    if not os.environ.get("KNOWLEDGE_BASE"):
        return 0
    # Capture failures never suppress the context.
    with contextlib.suppress(Exception):
        _start(data)
    sys.stdout.write(session_context.text())
    return 0
