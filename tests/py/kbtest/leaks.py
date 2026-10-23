"""Detect writes that escaped into the host's real session directory.

Detection runs after the suite; it cannot prevent a leak. Isolation itself
comes from the confined environment (env.assert_confined).
"""

from __future__ import annotations

import os
from pathlib import Path


def real_session_dir(environ: dict[str, str] | None = None) -> Path:
    """The session directory the host's own sessions use (session_dir() in _lib.sh)."""
    environ = dict(os.environ) if environ is None else environ
    runtime = environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(runtime) / f"knowledge-sessions-{os.getuid()}"


def find_leaks(directory: Path, prefix: str, *, strict: bool) -> list[Path]:
    """Return files in directory that tests created.

    strict: report every file. Use where no live session can write to the
    directory, such as CI. Otherwise report only names containing prefix,
    the session-ID prefix every test uses; scripts that generate their own
    session IDs escape this check.
    """
    if not directory.is_dir():
        return []
    entries = sorted(directory.iterdir())
    if strict:
        return entries
    return [entry for entry in entries if prefix in entry.name]
