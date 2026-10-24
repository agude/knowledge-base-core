r"""session-append - Append a message to a session buffer.

Adds a single JSONL line with role, message, and timestamp to the
given buffer file. No-ops silently if the file does not exist (no
buffer means capture was not initialized for this session).

Usage: session-append (--file PATH | --session-id ID) \
         --role user|assistant --message TEXT|-
"""

from __future__ import annotations

import sys
from pathlib import Path

from kb import cli, platform, session

USAGE = (
    "Usage: session-append (--file PATH | --session-id ID) --role user|assistant --message TEXT|-\n"
    "Use --message - to read the exact message, including trailing newlines, from stdin."
)
OPTIONS = ("--file", "--session-id", "--role", "--message")


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        word = argv[index]
        if word in OPTIONS:
            if index + 1 >= len(argv):
                cli.fail(f"Option {word} requires an argument")
            if word == "--message" and "message" in values:
                cli.fail("session-append: --message may be specified only once")
            values[word[2:]] = argv[index + 1]
            index += 2
        elif word in ("-h", "--help"):
            print(USAGE)
            return 0
        else:
            cli.fail(f"Unknown option: {word}")
    message = values.get("message", "")
    data = b""
    if message == "-":
        data = sys.stdin.buffer.read()
    elif message:
        data = message.encode("utf-8", errors="surrogateescape")
    return record(
        values.get("file", ""),
        values.get("session-id", ""),
        values.get("role", ""),
        data,
        given=bool(message),
    )


def record(file: str, session_id: str, role: str, data: bytes, *, given: bool = True) -> int:
    """Append one message, with session-append's checks and exit status.

    Used in-process by the host adapters (plan 3.5): one attempt, so a
    failure reports once (audit A-021).
    """
    if file and session_id:
        cli.fail("session-append: use only one of --file or --session-id")
    if not file and not session_id:
        cli.fail("session-append: --file or --session-id is required")
    if session_id:
        try:
            buffer = session.buffer_for_append(session.session_dir(), session_id)
        except session.SessionBufferError as error:
            cli.fail(str(error))
        if buffer is None:
            return 0  # Capture was never initialized for this session.
    else:
        buffer = Path(file)
    if not role:
        cli.fail("session-append: --role is required")
    if role not in ("user", "assistant"):
        cli.fail(f"session-append: --role must be 'user' or 'assistant', got '{role}'")
    if not given or not buffer.is_file() or not data:
        return 0  # Nothing to record, or no buffer: capture is off.
    try:
        session.append(buffer, role, data)
    except OSError:
        cli.fail(f"session-append: could not write {buffer}")
    return 0
