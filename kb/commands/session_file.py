"""session-file - Resolve a session ID to its observation buffer path.

Usage: session-file --session-id ID [--create]

The resolver is the single path-formatting API for host adapters. Use
--create when an adapter needs to initialize a buffer after it was swept.
"""

from __future__ import annotations

from kb import cli, platform, session


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv, __doc__, values={"--session-id": "session-id"}, flags={"--create": "create"}
    )
    session_id = args.get("session-id")
    if not session_id:
        cli.fail("session-file: --session-id is required")
    directory = session.session_dir()
    path = session.buffer_path(directory, session_id)
    if path is None:
        cli.fail("session-file: invalid session ID")
    if "create" in args.flags:
        if not session.ensure_dir(directory):
            cli.fail(f"session-file: cannot create session directory {directory}")
        path.touch()
        platform.make_private(path)
    print(path)
    return 0
