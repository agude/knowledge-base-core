"""kb gap: record and commit one attributed question in questions/open/."""

import os
import socket
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from kb import areas, args, lock, observation, question, write
from kb.args import Spec
from kb.context import load
from kb.errors import KbError

WHO = "gap"
OPEN_QUESTIONS = "questions/open"
SPEC = Spec(
    usage="gap --title TITLE --body TEXT --context PATH",
    summary=(
        "Record one attributed question in questions/open/ and commit it. PATH names its best-"
        "known area and need not exist. The body is TEXT, or standard input when TEXT is -."
    ),
    valued=frozenset({"--title", "--body", "--context"}),
)


def run(words: Sequence[str]) -> int:
    """Run kb gap, then print the committed question's path."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words:
        raise SPEC.usage_error()
    title, body, supplied_context = _arguments(parsed.values)
    wait = _wait()
    root = _content_root()
    context = areas.for_storage(root, supplied_context, WHO)
    try:
        name = _record(root, title, context, body, wait)
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except (OSError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    sys.stdout.write(f"Wrote: {OPEN_QUESTIONS}/{name}\n")
    return 0


def _arguments(values: Mapping[str, str]) -> tuple[str, str, str]:
    """The required title, body, and context, with stdin support for the body."""
    title = values.get("--title")
    text = values.get("--body")
    context = values.get("--context")
    if title is None or text is None or context is None:
        raise SPEC.usage_error()
    body = _read_stdin() if text == "-" else text
    try:
        observation.check_title(title)
        observation.check_body(body)
    except observation.InvalidArgument:
        raise SPEC.usage_error() from None
    return title, body, context


def _read_stdin() -> str:
    """Read the body from standard input and decode it as UTF-8."""
    try:
        return sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as error:
        raise KbError(f"{WHO}: standard input is not UTF-8: {error.reason}") from error


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
        raise KbError(f"{WHO}: {error}") from error


def _record(root: Path, title: str, context: str, body: str, wait: int) -> str:
    """Render, scan, publish, and commit the attributed question."""
    when = datetime.now(UTC)
    text = question.render(
        title, context, body, write.project(), observation.short_host(socket.gethostname()), when
    )
    return write.publish_and_commit(
        root,
        OPEN_QUESTIONS,
        text,
        question.scan_text(title, context, body),
        when,
        f"Ask: {title}",
        WHO,
        wait,
        sys.platform,
        question.refusal_lines,
    )
