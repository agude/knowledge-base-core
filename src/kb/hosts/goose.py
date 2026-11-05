"""Parse Goose's SQLite session database into the neutral transcript model.

Goose keeps every session in one database, sessions.db, in its sessions directory: a sessions
table with one row per session, and a messages table whose content_json holds each message's
content items. The database is opened read only, and both tables are read in one transaction,
so the sessions are one consistent snapshot while Goose writes.
"""

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby
from operator import itemgetter
from pathlib import Path

from kb.transcripts import App, Message, Role, Session, later, synthetic_id, unique_messages

APP: App = "goose"
DATABASE = "sessions.db"
# The developer extension's shell tool. Releases that prefixed each tool with its extension's
# name called it developer__shell.
SHELL_TOOLS = frozenset({"shell", "developer__shell"})
# These providers run Claude Code or the Codex CLI, which keep their own transcripts.
PROXIED_PROVIDERS = frozenset({"claude-code", "claude-acp", "codex", "codex-acp"})
# Goose stores message times in seconds, and reads a larger value as milliseconds.
MILLISECOND_THRESHOLD = 10_000_000_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SESSIONS = "SELECT id, working_dir, parent_session_id, updated_at, provider_name FROM sessions"
# Goose reads a conversation in this order.
MESSAGES = (
    "SELECT session_id, role, content_json, created_timestamp, metadata_json, message_id "
    "FROM messages ORDER BY session_id, created_timestamp, id"
)


class DatabaseError(Exception):
    """The session database exists, but it cannot be read."""


@dataclass(frozen=True)
class Header:
    """One sessions row: the session's ID, its working directory, its parent, and its update."""

    id: str
    project: str
    parent_session: str | None
    updated: datetime | None


@dataclass(frozen=True)
class Row:
    """One messages row, with the columns the parser reads, as stored."""

    role: object
    content: object
    created: object
    metadata: object
    message_id: object


@dataclass(frozen=True)
class Snapshot:
    """One parsed session, and when Goose last updated it, which stands in for a file's mtime."""

    session: Session
    updated: datetime


def parse(header: Header, rows: Iterable[Row]) -> Session:
    """Parse one session's message rows, in Goose's order, without reading the database.

    A row whose time or content cannot be read is counted as malformed. The snapshot is always
    complete, because a read transaction never sees a partly written row.
    """
    messages: list[Message] = []
    latest_timestamp: datetime | None = None
    malformed = 0
    for row in rows:
        timestamp = _timestamp(row.created)
        if timestamp is None:
            malformed += 1
            continue
        latest_timestamp = later(latest_timestamp, timestamp)
        message, invalid = _message(row, timestamp)
        if invalid:
            malformed += 1
        if message is not None:
            messages.append(message)

    unique, duplicates = unique_messages(messages)
    return Session(
        app=APP,
        id=header.id,
        project=header.project,
        parent_session=header.parent_session,
        forked_from=None,
        messages=unique,
        latest_timestamp=latest_timestamp,
        snapshot_complete=True,
        malformed_lines=malformed,
        duplicate_ids=duplicates,
    )


def read(root: Path) -> tuple[Snapshot, ...]:
    """Every session in the database under a sessions directory, in session ID order.

    A missing database has no sessions. Only the database is read; nothing is written. Raises
    DatabaseError when the database cannot be read.
    """
    return tuple(_snapshot(header, rows) for header, rows in _sessions(root))


def _sessions(root: Path) -> Iterator[tuple[Header, list[Row]]]:
    """Each session with messages in the database under root, and its rows, one at a time."""
    database = root / DATABASE
    if not database.is_file():
        return
    try:
        # Imported here, so a Python built without sqlite3 still runs kb for the other hosts.
        import sqlite3
    except ImportError as error:
        raise DatabaseError("this Python has no sqlite3 module") from error
    try:
        uri = f"{database.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, isolation_level=None)) as connection:
            connection.execute("BEGIN")
            headers = {
                header.id: header
                for header in map(_header, connection.execute(SESSIONS))
                if header is not None
            }
            for session_id, group in groupby(connection.execute(MESSAGES), key=itemgetter(0)):
                header = headers.get(session_id)
                if header is not None:
                    yield header, [Row(*row[1:]) for row in group]
    except sqlite3.Error as error:
        raise DatabaseError(str(error)) from error
    except OSError as error:
        raise DatabaseError(error.strerror or type(error).__name__) from error


def _header(row: Sequence[object]) -> Header | None:
    """A sessions row's header, or None for a row without an ID or from a proxied provider."""
    session_id, project, parent, updated, provider = row
    if not isinstance(session_id, str) or not session_id or provider in PROXIED_PROVIDERS:
        return None
    return Header(
        id=session_id,
        project=project if isinstance(project, str) else "",
        parent_session=parent if isinstance(parent, str) and parent else None,
        updated=_updated(updated),
    )


def _snapshot(header: Header, rows: Sequence[Row]) -> Snapshot:
    """A parsed session, updated at its sessions row's time or else at its newest message."""
    session = parse(header, rows)
    return Snapshot(session, header.updated or session.latest_timestamp or EPOCH)


def _message(row: Row, timestamp: datetime) -> tuple[Message | None, bool]:
    """Return the retained user or assistant message and whether its row was malformed.

    A message or text block that Goose does not show the user, such as per-turn context or a
    compaction summary, is injected for the agent and is not retained.
    """
    role_value = row.role
    if role_value not in ("user", "assistant") or not _user_visible(row.metadata):
        return None, False
    content = _content(row.content)
    if content is None:
        return None, True
    role: Role = role_value
    texts: list[str] = []
    commands: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        item_text = item.get("text")
        if item.get("type") == "text" and isinstance(item_text, str) and _shown_to(item, "user"):
            texts.append(item_text)
        elif role == "assistant":
            command = _shell_command(item)
            if command is not None:
                commands.append(command)
    text = "\n".join(texts)
    if not text.strip() and not commands:
        return None, False
    message_id = row.message_id
    if not isinstance(message_id, str) or not message_id:
        message_id = synthetic_id(APP, str(row.created), role, text)
    return Message(message_id, timestamp, role, text, tuple(commands)), False


def _user_visible(value: object) -> bool:
    """Whether Goose shows a message to the user. Like Goose, unreadable metadata is visible."""
    if not isinstance(value, str):
        return True
    try:
        metadata = json.loads(value)
    except json.JSONDecodeError:
        return True
    return not (isinstance(metadata, Mapping) and metadata.get("userVisible") is False)


def _shown_to(block: object, role: Role) -> bool:
    """Whether a content block is shown to a role: it names no audience, or names the role."""
    annotations = block.get("annotations") if isinstance(block, Mapping) else None
    audience = annotations.get("audience") if isinstance(annotations, Mapping) else None
    return not isinstance(audience, list) or role in audience


def _content(value: object) -> list[object] | None:
    """A row's content items, or None when its content_json is not a JSON array."""
    if not isinstance(value, str):
        return None
    try:
        content = json.loads(value)
    except json.JSONDecodeError:
        return None
    return content if isinstance(content, list) else None


def _shell_command(item: Mapping[str, object]) -> str | None:
    """The command of a successful developer shell tool request, when it is a string."""
    if item.get("type") != "toolRequest":
        return None
    call = item.get("toolCall")
    if not isinstance(call, Mapping) or call.get("status") != "success":
        return None
    value = call.get("value")
    if not isinstance(value, Mapping) or value.get("name") not in SHELL_TOOLS:
        return None
    arguments = value.get("arguments")
    command = arguments.get("command") if isinstance(arguments, Mapping) else None
    return command if isinstance(command, str) else None


def _timestamp(value: object) -> datetime | None:
    """A message's created_timestamp in UTC, in seconds or, above the threshold, milliseconds."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    seconds = value / 1000 if value > MILLISECOND_THRESHOLD else value
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _updated(value: object) -> datetime | None:
    """A sessions row's updated_at. SQLite writes UTC without an offset, so a naive time is UTC."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
