"""Session buffers: where they live and how they become observations."""

from __future__ import annotations

import json
import os
import re
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kb import observe, platform
from kb.content import content_dir

SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
DEFAULT_MIN_MESSAGES = "3"


def session_dir() -> Path:
    """SESSION_DIR, else a per-user directory under XDG_RUNTIME_DIR or /tmp.

    Every prompt passes through these files, so the directory must not be
    a predictable shared path (see session_dir in scripts/_lib.sh).
    """
    configured = os.environ.get("SESSION_DIR")
    if configured:
        return Path(configured)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(runtime) / f"knowledge-sessions-{platform.user_id()}"


def buffer_path(directory: Path, session_id: str) -> Path | None:
    """The buffer for session_id, or None when the ID is not filename-safe."""
    if not SESSION_ID.fullmatch(session_id):
        return None
    return directory / f"session-{session_id}.jsonl"


def initialization_path(directory: Path, session_id: str) -> Path | None:
    if not SESSION_ID.fullmatch(session_id):
        return None
    return directory / f"session-{session_id}.initialized"


def clear_initialization_for(buffer: Path) -> None:
    """Remove the marker beside a buffer in the session directory, and nothing else."""
    directory = session_dir()
    name = buffer.name
    if buffer.parent != directory or not (name.startswith("session-") and name.endswith(".jsonl")):
        return
    marker = initialization_path(directory, name[len("session-") : -len(".jsonl")])
    if marker is not None:
        marker.unlink(missing_ok=True)


class Interrupted(Exception):
    pass


@contextmanager
def _interruptible() -> Iterator[None]:
    """Turn HUP, INT, and TERM into Interrupted for the duration of a flush."""

    def handler(signum: int, frame: object) -> None:
        raise Interrupted

    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        signals.append(signal.SIGHUP)
    previous = {signum: signal.signal(signum, handler) for signum in signals}
    try:
        yield
    finally:
        for signum, old in previous.items():
            signal.signal(signum, old)


def transcript(buffer: Path) -> tuple[str, int] | None:
    """The readable transcript and the record count, or None if a record is malformed.

    Bytes that are not UTF-8 become U+FFFD, as jq reads them.
    """
    parts = []
    count = 0
    for line in buffer.read_bytes().decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            return None
        if not (
            isinstance(record, dict)
            and isinstance(record.get("role"), str)
            and isinstance(record.get("message"), str)
        ):
            return None
        parts.append(f"### {record['role']}\n\n{record['message']}\n\n\n")
        count += 1
    return "".join(parts), count


def flush(buffer: Path, *, preserve_initialization: bool = False, announce: bool = True) -> int:
    """Turn a session buffer into one observation; return the exit status.

    The buffer is removed only once its observation is committed, so a
    failure or an interruption keeps it for the next sweep.
    """

    def done() -> int:
        if not preserve_initialization:
            clear_initialization_for(buffer)
        buffer.unlink(missing_ok=True)
        return 0

    if not buffer.is_file():
        if not preserve_initialization:
            clear_initialization_for(buffer)
        return 0
    try:
        with _interruptible():
            if buffer.stat().st_size == 0:
                return done()
            minimum = int(os.environ.get("KNOWLEDGE_MIN_MESSAGES") or DEFAULT_MIN_MESSAGES)
            parsed = transcript(buffer)
            if parsed is None:
                print(f"session-flush: could not parse {buffer}", file=sys.stderr)
                return 1
            text, count = parsed
            if count < minimum:
                platform.log(
                    "knowledge",
                    f"session-flush: dropping {count}-message transcript (min {minimum})",
                )
                return done()
            if not text:
                return done()
            try:
                observe.write(
                    content_dir(),
                    f"Session transcript ({count} messages)",
                    text,
                    "session-transcript",
                    announce=announce,
                )
            except observe.ObserveError:
                print(f"session-flush: observe failed, keeping {buffer}", file=sys.stderr)
                return 1
            return done()
    except Interrupted:
        print(f"session-flush: interrupted, keeping {buffer}", file=sys.stderr)
        return 130
