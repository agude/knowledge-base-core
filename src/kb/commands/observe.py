"""kb observe: record one observation in observations/pending/, and commit only that file.

The write path follows section 3 of the observe plan: validate, render, scan, write to a
temporary file, take the lock, publish, commit, unlock, and report.
"""

import os
import socket
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from kb import args, lock, observation, write
from kb.args import Spec
from kb.context import load
from kb.errors import KbError

PENDING = "observations/pending"
SPEC = Spec(
    usage="observe --title TITLE --body TEXT",
    summary=(
        "Record one observation in observations/pending/ and commit it. The body is TEXT, or the\n"
        "standard input when TEXT is -. A body that holds a possible secret is refused."
    ),
    valued=frozenset({"--title", "--body"}),
)


def run(words: Sequence[str]) -> int:
    """Run kb observe. On success, print the Wrote line and return 0."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words:
        raise SPEC.usage_error()
    title, body = _arguments(parsed.values)
    wait = _wait()
    root = _content_root()
    try:
        name = _record(root, title, body, wait)
    except lock.LockBusy as busy:
        raise KbError(
            f"observe: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except (OSError, UnicodeError) as error:
        raise KbError(f"observe: {error}") from error
    sys.stdout.write(f"Wrote: {PENDING}/{name}\n")
    return 0


def _arguments(values: Mapping[str, str]) -> tuple[str, str]:
    """The title and the body, both validated. A body of - is read from standard input."""
    title = values.get("--title")
    text = values.get("--body")
    if title is None or text is None:
        raise SPEC.usage_error()
    body = _read_stdin() if text == "-" else text
    try:
        observation.check_title(title)
        observation.check_body(body)
    except observation.InvalidArgument:
        raise SPEC.usage_error() from None
    return title, body


def _read_stdin() -> str:
    """Standard input, read to the end of the file and decoded as UTF-8."""
    try:
        return sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as error:
        raise KbError(f"observe: standard input is not UTF-8: {error.reason}") from error


def _wait() -> int:
    """The lock wait from KB_LOCK_WAIT. An invalid value is a usage error."""
    try:
        return lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise SPEC.usage_error() from None


def _content_root() -> Path:
    """The content repository, resolved as the read commands resolve it."""
    try:
        return load(os.environ, sys.platform, Path.home()).root
    except KbError as error:
        raise KbError(f"observe: {error}") from error


def _record(root: Path, title: str, body: str, wait: int) -> str:
    """Write the observation, commit it, and return its file name."""
    when = datetime.now(UTC)
    host = observation.short_host(socket.gethostname())
    return write.publish_and_commit(
        root,
        PENDING,
        observation.render(title, body, write.project(), host, when),
        observation.scan_text(title, body),
        when,
        f"Observe: {title}",
        "observe",
        wait,
        sys.platform,
        observation.refusal_lines,
    )
