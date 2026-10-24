"""session-init - Create a session observation buffer.

Creates a JSONL buffer file for the given session ID and prints its
path to stdout. Idempotent: a second call with the same ID returns
the existing path. Then sweeps orphaned buffers older than 1 hour.

Usage: session-init --session-id ID [--persist-initialization]

Environment:
  SESSION_DIR  Override buffer directory (default: per-user runtime dir)
"""

from __future__ import annotations

from kb import cli, platform, session


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--session-id": "session-id"},
        flags={"--persist-initialization": "persist"},
    )
    session_id = args.get("session-id")
    if not session_id:
        cli.fail("session-init: --session-id is required")
    directory = session.session_dir()
    if not session.ensure_dir(directory):
        cli.fail(f"session-init: cannot create session directory {directory}")
    path = session.buffer_path(directory, session_id)
    if path is None:
        cli.fail("session-init: invalid session ID")
    path.touch()
    platform.make_private(path)
    if "persist" in args.flags and not session.mark_initialized(directory, session_id):
        cli.fail("session-init: cannot persist initialization state")
    # Hosts read stdout as the buffer path, so the sweep below prints nothing.
    print(path, flush=True)
    session.sweep(directory, path)
    return 0
