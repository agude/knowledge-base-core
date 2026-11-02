"""The neutral model shared by the host transcript parsers and sync logic."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

App = Literal["claude-code", "codex"]
Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    """One retained user or assistant turn, with text and shell commands kept separately."""

    id: str
    timestamp: datetime
    role: Role
    text: str
    commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class Session:
    """One transcript file after its host-specific records have been interpreted."""

    app: App
    id: str | None
    project: str
    parent_session: str | None
    forked_from: str | None
    messages: tuple[Message, ...]
    latest_timestamp: datetime | None
    snapshot_complete: bool
    malformed_lines: int = 0
    duplicate_ids: int = 0


def complete_lines(text: str) -> tuple[tuple[str, ...], bool]:
    """Return newline-terminated JSONL lines and whether the snapshot has a complete tail."""
    if not text:
        return (), True
    pieces = text.split("\n")
    complete = pieces[-1] == ""
    pieces.pop()
    return tuple(line.removesuffix("\r") for line in pieces), complete


def parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO timestamp with a time zone and normalize it to UTC."""
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp.astimezone(UTC)


def timestamp_text(value: datetime) -> str:
    """Render an aware timestamp in UTC ISO form, preserving available precision."""
    if value.tzinfo is None:
        raise ValueError("the timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def synthetic_id(app: App, timestamp: str, role: Role, text: str) -> str:
    """Build the stable 16-hex ID used when a retained message has no host ID."""
    material = "\0".join((app, timestamp, role, text)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def unique_messages(messages: Sequence[Message]) -> tuple[tuple[Message, ...], int]:
    """Keep the first occurrence of each message ID and return the duplicate count."""
    seen: set[str] = set()
    kept: list[Message] = []
    duplicates = 0
    for message in messages:
        if message.id in seen:
            duplicates += 1
            continue
        seen.add(message.id)
        kept.append(message)
    return tuple(kept), duplicates


def earlier(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def later(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


@dataclass(frozen=True)
class KbCall:
    """One kb call that an agent ran through its shell tool, with that tool call's output.

    subcommand is one of the recorded kb subcommands, and arguments are the words after it.
    shared is True when the tool call ran more than one recorded kb call. Its output then
    belongs to all of them, and no split is guessed. output is None when the tool call has
    no paired result.
    """

    app: App
    session_id: str | None
    timestamp: datetime | None
    project: str
    command: str
    subcommand: str
    arguments: tuple[str, ...]
    output: str | None
    shared: bool


@dataclass(frozen=True)
class Store:
    """The kb calls found in one host's raw session store, and the span of its records."""

    calls: tuple[KbCall, ...]
    files: int
    unreadable: int
    first: datetime | None
    last: datetime | None
