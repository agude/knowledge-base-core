"""The neutral model shared by the host transcript parsers and sync logic."""

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

App = Literal["claude-code", "codex", "goose"]
Role = Literal["user", "assistant"]
# Why a kb call's output is not usable: no paired result, a command that shares its output
# with another call, a batch of results, output that is still incomplete, or an output shape
# that is not recognized.
EXCLUSIONS = ("missing", "shared", "batch", "incomplete", "unsupported")


@dataclass(frozen=True)
class Message:
    """One retained user or assistant turn, with text and shell commands kept separately."""

    id: str
    timestamp: datetime
    role: Role
    text: str
    commands: tuple[str, ...] = ()
    legacy_id: str | None = None
    synthetic_command: bool = False
    legacy_duplicate: bool = False


@dataclass(frozen=True)
class Session:
    """One transcript after its host-specific records have been interpreted."""

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
    try:
        return timestamp.astimezone(UTC)
    except OverflowError:
        return None


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
    """Deduplicate host IDs; count anonymous calls and retain their old identity membership."""
    seen: set[str] = set()
    legacy_seen: set[str] = set()
    occurrences: dict[str, int] = {}
    kept: list[Message] = []
    duplicates = 0
    for message in messages:
        if message.synthetic_command:
            occurrence = occurrences.get(message.id, 0) + 1
            occurrences[message.id] = occurrence
            message = replace(message, id=f"{message.id}-{occurrence}")
        if message.id in seen:
            duplicates += 1
            continue
        seen.add(message.id)
        legacy = message.legacy_id or message.id
        message = replace(message, legacy_duplicate=legacy in legacy_seen)
        legacy_seen.add(legacy)
        kept.append(message)
    return tuple(kept), duplicates


def synthetic_command_id(
    app: App, timestamp: str, role: Role, text: str, commands: tuple[str, ...]
) -> str:
    """Hash structured retained content; unique_messages adds a stable occurrence suffix."""
    material = json.dumps((app, timestamp, role, text, commands), ensure_ascii=True).encode("utf-8")
    return "cmd-" + hashlib.sha256(material).hexdigest()[:16]


def tool_call_id(ids: Sequence[str]) -> str:
    """Use one host call ID verbatim, or an unambiguous identity for an ordered group."""
    if len(ids) == 1:
        return ids[0]
    material = json.dumps(tuple(ids), ensure_ascii=True).encode("utf-8")
    return "tools-" + hashlib.sha256(material).hexdigest()[:16]


def text_of(value: object) -> str | None:
    """The text of a tool output that is a string, or a list of text blocks. None otherwise.

    The blocks are joined with newlines. A list that holds any block without text, or an empty
    list, has no text.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, list) or not value:
        return None
    texts: list[str] = []
    for block in value:
        if not isinstance(block, Mapping) or not isinstance(block.get("text"), str):
            return None
        texts.append(block["text"])
    return "\n".join(texts)


def earlier(current: datetime | None, candidate: datetime | None) -> datetime | None:
    """The earlier of two optional timestamps. None counts as no timestamp."""
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def later(current: datetime | None, candidate: datetime | None) -> datetime | None:
    """The later of two optional timestamps. None counts as no timestamp."""
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


@dataclass(frozen=True)
class KbCall:
    """One kb call that an agent ran through its shell tool, with the output that belongs to it.

    subcommand is one of the recorded kb subcommands, and arguments are the words after it.
    output is the decoded command output, and it is None unless the output is usable. excluded
    then names why it is not: one of EXCLUSIONS. A call is usable only when its tool call ran
    exactly this one kb call, so that its output is its own.
    """

    app: App
    session_id: str | None
    timestamp: datetime | None
    project: str
    command: str
    subcommand: str
    arguments: tuple[str, ...]
    output: str | None
    excluded: str | None

    def __post_init__(self) -> None:
        if (self.output is None) == (self.excluded is None):
            raise ValueError("a kb call has output or an exclusion, and not both or neither")
        if self.excluded is not None and self.excluded not in EXCLUSIONS:
            raise ValueError(f"unknown exclusion: {self.excluded}")


@dataclass(frozen=True)
class Scan:
    """The kb calls in one transcript file, and the span of its records."""

    calls: tuple[KbCall, ...]
    first: datetime | None
    last: datetime | None


@dataclass(frozen=True)
class Store:
    """The kb calls found in one host's raw session store, and the span of its records."""

    calls: tuple[KbCall, ...]
    files: int
    unreadable: int
    first: datetime | None
    last: datetime | None


def read_store(paths: Iterable[Path], scan: Callable[[str, Path], Scan]) -> Store:
    """Scan each transcript file that the paths name. Only the files are read; nothing is written.

    An unreadable file is counted and skipped. scan is given the file's text and its path.
    """
    calls: list[KbCall] = []
    files = unreadable = 0
    first: datetime | None = None
    last: datetime | None = None
    for path in paths:
        files += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        found = scan(text, path)
        calls.extend(found.calls)
        first = earlier(first, found.first)
        last = later(last, found.last)
    return Store(tuple(calls), files, unreadable, first, last)
