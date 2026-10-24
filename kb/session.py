"""Session buffers: where they live and how they become observations."""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kb import observe, output, platform
from kb.content import UsageError, content_dir, nonnegative

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


def _minimum(value: str) -> int:
    """KNOWLEDGE_MIN_MESSAGES; a non-number is an error that keeps the buffer."""
    return nonnegative("KNOWLEDGE_MIN_MESSAGES", value)


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
            try:
                minimum = _minimum(os.environ.get("KNOWLEDGE_MIN_MESSAGES") or DEFAULT_MIN_MESSAGES)
            except UsageError as error:
                print(error, file=sys.stderr)
                return 1
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
                # As bash runs observe with 2>/dev/null: only the line below reports a failure.
                with output.discarded(stdout=False):
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


# Directories, buffers, and markers


def ensure_dir(directory: Path) -> bool:
    """Create the session directory privately; False if it is missing or not ours."""
    try:
        platform.make_private_dirs(directory)
    except OSError:
        return False
    if not directory.is_dir() or not platform.owned_by_user(directory):
        return False
    platform.make_private(directory)  # A pre-existing directory keeps its old mode.
    return True


def _touch_private(path: Path) -> None:
    path.touch()
    platform.make_private(path)


def mark_initialized(directory: Path, session_id: str) -> bool:
    marker = initialization_path(directory, session_id)
    if marker is None or not ensure_dir(directory):
        return False
    try:
        _touch_private(marker)
    except OSError:
        return False
    return True


def is_initialized(directory: Path, session_id: str) -> bool:
    marker = initialization_path(directory, session_id)
    return (
        marker is not None
        and marker.is_file()
        and not marker.is_symlink()
        and platform.owned_by_user(marker)
    )


class SessionBufferError(Exception):
    """The buffer could not be found or created; the message says why."""


def buffer_for_append(directory: Path, session_id: str) -> Path | None:
    """A session's buffer, recreated if it was swept; None when capture was never initialized.

    session-start sweeps buffers idle for an hour, so a long-idle session
    would otherwise capture nothing for the rest of its life. The buffer is
    recreated only when capture was initialized: KNOWLEDGE_OBSERVE=1,
    KNOWLEDGE_SESSION_FILE, or the durable marker.
    """
    path = buffer_path(directory, session_id)
    if path is None:
        raise SessionBufferError("session buffer: invalid session ID")
    if path.is_file():
        return path
    if (
        os.environ.get("KNOWLEDGE_OBSERVE") != "1"
        and not os.environ.get("KNOWLEDGE_SESSION_FILE")
        and not is_initialized(directory, session_id)
    ):
        return None
    if not ensure_dir(directory):
        raise SessionBufferError(f"session buffer: cannot create session directory {directory}")
    try:
        _touch_private(path)
    except OSError as error:
        raise SessionBufferError(f"session buffer: cannot create {path}") from error
    return path


def encode(role: str, message: bytes) -> bytes:
    """One buffer record in jq's format (audit A-002): compact, DEL escaped,
    invalid UTF-8 replaced with U+FFFD, a float timestamp."""
    text = message.decode("utf-8", errors="replace")
    record = json.dumps(
        {"role": role, "message": text, "timestamp": time.time()},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (record.replace("\x7f", "\\u007f") + "\n").encode("utf-8")


def append(buffer: Path, role: str, message: bytes) -> None:
    """Append one record in a single write."""
    with buffer.open("ab") as handle:
        handle.write(encode(role, message))


ORPHAN_SECONDS = 60 * 60


def sweep(directory: Path, current: Path) -> None:
    """Flush buffers idle for over an hour, ours only, silently.

    Each orphan is one commit and can wait on a held lock, so the caller
    sweeps after reporting its own buffer; a host that kills the hook then
    loses only sweep progress.
    """
    now = time.time()
    for orphan in sorted(directory.glob("session-*.jsonl"), key=bytes):
        if orphan == current or orphan.is_symlink() or not orphan.is_file():
            continue
        if not platform.owned_by_user(orphan):
            continue
        try:
            idle = now - orphan.stat().st_mtime
        except OSError:
            continue
        if idle > ORPHAN_SECONDS:
            with output.discarded():
                flush(orphan, preserve_initialization=True, announce=False)
