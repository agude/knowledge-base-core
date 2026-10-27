"""Parse Claude Code JSONL sessions into the neutral transcript model."""

import json
import re
from collections.abc import Mapping

from kb.transcripts import (
    App,
    Message,
    Role,
    Session,
    complete_lines,
    parse_timestamp,
    synthetic_id,
    unique_messages,
)

APP: App = "claude-code"
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def parse(text: str, session_id: str, parent_session: str | None = None) -> Session:
    """Parse one main or subagent transcript snapshot without reading the file."""
    lines, complete = complete_lines(text)
    messages: list[Message] = []
    project = ""
    latest_timestamp = None
    malformed = 0

    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                complete = False
            else:
                malformed += 1
            continue
        if not isinstance(record, dict):
            malformed += 1
            continue
        record_timestamp = parse_timestamp(record.get("timestamp"))
        if record_timestamp is not None and (
            latest_timestamp is None or record_timestamp > latest_timestamp
        ):
            latest_timestamp = record_timestamp
        project = _first_text(project, record.get("cwd"))
        message, invalid = _message(record)
        if invalid:
            malformed += 1
        if message is not None:
            messages.append(message)

    unique, duplicates = unique_messages(messages)
    return Session(
        app=APP,
        id=session_id,
        project=project,
        parent_session=parent_session,
        forked_from=None,
        messages=unique,
        latest_timestamp=latest_timestamp,
        snapshot_complete=complete,
        malformed_lines=malformed,
        duplicate_ids=duplicates,
    )


def _message(record: Mapping[str, object]) -> tuple[Message | None, bool]:
    """Return the retained user or assistant message and whether its record was malformed."""
    role_value = record.get("type")
    if role_value not in ("user", "assistant") or record.get("isMeta"):
        return None, False
    message = record.get("message")
    if not isinstance(message, Mapping):
        return None, True
    role: Role = role_value
    timestamp_value = record.get("timestamp")
    timestamp = parse_timestamp(timestamp_value)
    if timestamp is None:
        return None, True
    texts, commands = _content(message.get("content"), role)
    text = "\n".join(texts)
    if role == "user":
        text = SYSTEM_REMINDER.sub("", text)
    if not text.strip() and not commands:
        return None, False
    original_timestamp = timestamp_value if isinstance(timestamp_value, str) else ""
    message_id = record.get("uuid")
    if not isinstance(message_id, str) or not message_id:
        message_id = synthetic_id(APP, original_timestamp, role, text)
    return Message(message_id, timestamp, role, text, tuple(commands)), False


def _content(value: object, role: Role) -> tuple[list[str], list[str]]:
    """Extract user or assistant text blocks and Claude Bash command inputs."""
    if role == "user" and isinstance(value, str):
        return [value], []
    if not isinstance(value, list):
        return [], []
    texts: list[str] = []
    commands: list[str] = []
    for block in value:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        block_text = block.get("text")
        if block_type == "text" and isinstance(block_text, str):
            texts.append(block_text)
        elif role == "assistant" and block_type == "tool_use" and block.get("name") == "Bash":
            command = _bash_command(block.get("input"))
            if command is not None:
                commands.append(command)
    return texts, commands


def _bash_command(value: object) -> str | None:
    """A Claude Bash tool input's command, when it is a string."""
    if not isinstance(value, Mapping):
        return None
    command = value.get("command")
    return command if isinstance(command, str) else None


def _first_text(current: str, candidate: object) -> str:
    """Return the first non-empty string seen in a transcript metadata field."""
    if current or not isinstance(candidate, str) or not candidate:
        return current
    return candidate
