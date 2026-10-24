"""session-flush - Convert a session buffer into a raw observation.

Reads the session JSONL (user prompts + assistant responses), formats
it as a readable transcript, and saves it as a single observation.
The curator handles extraction and judgment later.

Transcripts shorter than KNOWLEDGE_MIN_MESSAGES (default 3) are
dropped. A third of every transcript ever captured here was a single
question and its answer, and that noise is paid for twice: once in the
content repo's history and once in the curator's attention. The filter
is mechanical on purpose — nothing here judges content, because
whatever a weak filter discards is invisible to the curator forever.

The cost is real: a one-exchange session that happened to contain a
durable fact is now lost unless the agent called `observe` explicitly,
which is what it is supposed to do anyway. Set
KNOWLEDGE_MIN_MESSAGES=0 to keep everything.

Called by host adapters and by session-init when it sweeps orphaned files.

Usage:
  session-flush [--preserve-initialization] <session-file>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kb import cli, platform, session

USAGE = "Usage: session-flush [--preserve-initialization] <session-file>"


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    preserve = False
    args = list(argv)
    if args[:1] in (["-h"], ["--help"]):
        cli.print_help(__doc__)
        return 0
    if args[:1] == ["--preserve-initialization"]:
        preserve = True
        args = args[1:]
    if args[:1] and args[0].startswith("-") and args[0] != "-":
        print(f"Unknown option: {args[0]}", file=sys.stderr)
        return 1
    if len(args) != 1:
        # A missing argument is a caller bug (audit A-032); a missing
        # buffer is not, because the orphan sweep may have flushed it.
        print(USAGE, file=sys.stderr)
        return 1
    os.environ["KNOWLEDGE_OBSERVE"] = "1"
    return session.flush(Path(args[0]), preserve_initialization=preserve)
