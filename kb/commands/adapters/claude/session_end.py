"""Claude SessionEnd: flush the session's buffer into one observation.

Claude reads nothing from this hook's stdout (audit A-040), so it prints
nothing there. A hook must not fail its host for input it cannot use, so
missing or malformed input exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from kb import platform, session


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    if os.environ.get("KNOWLEDGE_OBSERVE") == "0" or not os.environ.get("KNOWLEDGE_BASE"):
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or not session_id:
        return 0
    configured = os.environ.get("KNOWLEDGE_SESSION_FILE")
    buffer = (
        Path(configured) if configured else session.buffer_path(session.session_dir(), session_id)
    )
    if buffer is None or not buffer.is_file():
        return 0
    os.environ["KNOWLEDGE_OBSERVE"] = "1"
    return session.flush(buffer, announce=False)
