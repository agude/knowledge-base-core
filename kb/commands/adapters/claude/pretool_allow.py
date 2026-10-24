"""PreToolUse hook: auto-allow scripts bundled with this project's skills.

A permission decision covers the whole command string, not just its first
word, so the command is approved only when it is a single simple command
(no operators, redirections, or substitutions outside single quotes) whose
first word is an executable in this tree's executables directory.

Staying silent falls through to normal permissioning, so a false
rejection costs a prompt while a false approval costs everything. Reject
when unsure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from kb import platform

DECISION = (
    '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow",'
    '"permissionDecisionReason":"Auto-approved skill script"}}'
)
OPERATORS = frozenset(";&|<>()\n")


def is_simple_command(command: str) -> bool:
    """True when the command line runs exactly one command.

    Single quotes suppress everything; double quotes still allow $( ) and
    backticks, so those stay fatal inside them. A backslash escapes the next
    character outside single quotes. An unterminated quote is rejected.
    """
    in_single = in_double = False
    index = 0
    while index < len(command):
        char = command[index]
        following = command[index + 1 : index + 2]
        index += 1
        if in_single:
            in_single = char != "'"
            continue
        if char == "\\":
            index += 1
            continue
        if char == "`" or (char == "$" and following == "("):
            return False
        if in_double:
            in_double = char != '"'
            continue
        if char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char in OPERATORS:
            return False
    return not (in_single or in_double)


def _dirname(path: str) -> str:
    """POSIX dirname(1)."""
    stripped = path.rstrip("/")
    if not stripped:
        return "/" if path else "."
    if "/" not in stripped:
        return "."
    return stripped.rsplit("/", 1)[0].rstrip("/") or "/"


def _basename(path: str) -> str:
    """POSIX basename(1)."""
    stripped = path.rstrip("/")
    return stripped.rsplit("/", 1)[-1] if stripped else ("/" if path else "")


def approved(command: str, scripts_dir: Path) -> bool:
    if not command or not is_simple_command(command):
        return False
    script_path = command.split(" ", 1)[0]
    directory = Path(_dirname(script_path))
    if not directory.is_dir() or directory.resolve() != scripts_dir:
        return False
    target = scripts_dir / _basename(script_path)
    return target.is_file() and os.access(target, os.X_OK)


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    # This adapter lives below <executables>/adapters/claude; the approved
    # command surface is the executables directory itself.
    scripts_dir = (Path(sys.argv[0]).resolve().parent / ".." / "..").resolve()
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return 0
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return 0
    # The bash adapter reads the command through $(...), which drops trailing newlines.
    if approved(command.rstrip("\n"), scripts_dir):
        print(DECISION)
    return 0
