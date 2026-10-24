"""observe - Record a new observation in the knowledge base.

Creates a timestamped markdown file in observations/pending/ and
auto-commits it. The body can come from --body or stdin.

Usage:
  observe --title "..." --body "..."
  observe --title "..." --body - < file.txt

Options:
  --title TEXT   Observation title (required)
  --body TEXT    Observation body (required). Use - to read stdin.
  --source TEXT  Where this came from (default: "session")
  --no-commit    Skip the auto-commit

Examples:
  observe --title "DNS caching issue" --body "Discovered that..."
  observe --title "Meeting notes" --body - < /tmp/notes.txt
  observe --title "Quick note" --body "Remember to check X"
"""

from __future__ import annotations

import sys

from kb import cli, observe, platform
from kb.content import content_dir


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--title": "title", "--body": "body", "--source": "source"},
        flags={"--no-commit": "no-commit"},
    )
    title = args.get("title")
    if not title:
        cli.fail("Error: --title is required")
    body = args.get("body")
    if body == "-":
        # Bytes that are not UTF-8 pass through unchanged (surrogateescape).
        body = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape")
    elif not body:
        cli.fail("Error: --body is required (use --body - to read stdin)")
    try:
        observe.write(
            content_dir(),
            title,
            body,
            args.get("source", "session"),
            commit="no-commit" not in args.flags,
        )
    except observe.ObserveError as error:
        return observe.report(error)
    return 0
