"""session-context - Output the knowledge base context for session injection.

Prints the KB topic map, live state, and any project-specific instruction
file to stdout. Host adapters inject it using their own protocol.

Usage: session-context
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

from kb import platform
from kb.commands import status, toc
from kb.content import ROOT, content_dir


def instruction_file(directory: Path) -> Path | None:
    """AGENTS.md, the portable name, else CLAUDE.md, the compatibility name."""
    for name in ("AGENTS.md", "CLAUDE.md"):
        if (directory / name).is_file():
            return directory / name
    return None


def text() -> str:
    """The context hosts inject at session start; failures never stop it."""
    content = content_dir()
    out = io.StringIO()
    if root := instruction_file(ROOT):
        out.write(platform.read_text(root))
    out.write("\n## Topic areas (auto-generated)\n\n")
    with contextlib.suppress(Exception), contextlib.redirect_stderr(io.StringIO()):
        out.write("\n".join(toc.area_map(content, content / "knowledge")) + "\n")
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            state = status.brief(content)
    except Exception:  # Any failure reads as unavailable, as in bash.
        state = "unavailable"
    out.write(f"\nState: {state}\n")
    if instructions := instruction_file(content):
        out.write("\n" + platform.read_text(instructions))
    return out.getvalue()


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    sys.stdout.write(text())  # A host entry point: arguments are ignored (audit A-034).
    return 0
