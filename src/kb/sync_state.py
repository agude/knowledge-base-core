"""The outcome of the last regular `kb sync`, kept in the common Git directory.

`kb sync` replaces <git dir>/kb/sync-state.json while it holds the writer lock. Git never
commits the file. The message is the first line of the failure that sync printed, so it can
contain a path that Git or the operating system reported.
"""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from kb.errors import KbError

SCHEMA_VERSION = 1
OUTCOMES = ("ok", "dirty", "error")
DIRECTORY = "kb"
FILE = "sync-state.json"
TMP = "kb-tmp"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class SyncState:
    """One regular sync run. last_exchange is the time of the last ok run, or None."""

    kb_version: str
    last_run: datetime
    last_outcome: str
    last_exchange: datetime | None
    message: str | None


def path(git_directory: Path) -> Path:
    """The record's location under a repository's common Git directory."""
    return git_directory / DIRECTORY / FILE


def read(git_directory: Path) -> SyncState | None:
    """The recorded state, None when no record exists, or KbError when it cannot be used."""
    target = path(git_directory)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise KbError(f"cannot read {target}: {error}") from error
    return parse(text)


def parse(text: str) -> SyncState:
    """Validate a record's text. Raises KbError that names the first invalid field."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise KbError(f"sync state: invalid JSON: {error.msg}") from None
    if not isinstance(data, dict):
        raise KbError("sync state: the record is not a JSON object")
    schema = data.get("schema_version")
    if type(schema) is not int or schema != SCHEMA_VERSION:
        raise KbError(f"sync state: unsupported schema_version {schema!r}")
    version = data.get("kb_version")
    outcome = data.get("last_outcome")
    message = data.get("message")
    if not isinstance(version, str) or not version:
        raise KbError("sync state: kb_version must be a non-empty string")
    if outcome not in OUTCOMES:
        raise KbError(f"sync state: last_outcome must be one of {', '.join(OUTCOMES)}")
    if message is not None and not isinstance(message, str):
        raise KbError("sync state: message must be a string or null")
    exchange = data.get("last_exchange")
    return SyncState(
        kb_version=version,
        last_run=_time(data.get("last_run"), "last_run"),
        last_outcome=outcome,
        last_exchange=None if exchange is None else _time(exchange, "last_exchange"),
        message=message,
    )


def render(state: SyncState) -> str:
    """The record's text: one line of JSON in the documented key order, then a newline."""
    data = {
        "schema_version": SCHEMA_VERSION,
        "kb_version": state.kb_version,
        "last_run": _format(state.last_run),
        "last_outcome": state.last_outcome,
        "last_exchange": None if state.last_exchange is None else _format(state.last_exchange),
        "message": state.message,
    }
    return json.dumps(data) + "\n"


def write(git_directory: Path, state: SyncState) -> None:
    """Replace the record atomically, staging the new text in the Git directory's kb-tmp.

    The caller holds the writer lock. A failure leaves the previous record in place.
    """
    destination = path(git_directory)
    scratch = git_directory / TMP
    scratch.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = scratch / f"sync-state-{os.urandom(4).hex()}.json"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(render(state))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _time(value: object, name: str) -> datetime:
    """Parse a UTC timestamp in the record's format, or raise KbError that names the field."""
    text = value if isinstance(value, str) else ""
    try:
        return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        raise KbError(f"sync state: {name} must be a UTC timestamp") from None


def _format(value: datetime) -> str:
    """The timestamp in UTC, in the record's format."""
    return value.astimezone(UTC).strftime(TIME_FORMAT)
