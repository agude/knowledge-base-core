"""Parse Codex rollout JSONL sessions into the neutral transcript model."""

import json
import re
from collections.abc import Mapping
from pathlib import Path

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

APP: App = "codex"
SHELL_FUNCTIONS = frozenset({"exec", "exec_command", "run_shell_command", "shell"})
INJECTED_BLOCKS = (
    re.compile(
        r"<environment_context\b[^>]*>.*?</environment_context\s*>", re.IGNORECASE | re.DOTALL
    ),
    re.compile(
        r"<codex_internal_context\b[^>]*>.*?</codex_internal_context\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"<AGENTS\.md instructions\b[^>]*>.*?</AGENTS\.md instructions\s*>",
        re.IGNORECASE | re.DOTALL,
    ),
)


def parse(text: str, filename: str) -> Session:
    """Parse one Codex rollout snapshot, using the filename-matching session metadata ID."""
    lines, complete = complete_lines(text)
    filename_id = _filename_id(filename)
    session_id: str | None = None
    project = ""
    parent_session: str | None = None
    forked_from: str | None = None
    messages: list[Message] = []
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
        if record.get("type") == "session_meta":
            session_id, project, parent_session, forked_from = _metadata(
                record.get("payload"),
                filename_id,
                session_id,
                project,
                parent_session,
                forked_from,
            )
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
        forked_from=forked_from,
        messages=unique,
        snapshot_complete=complete,
        malformed_lines=malformed,
        duplicate_ids=duplicates,
    )


def _filename_id(filename: str) -> str | None:
    """Return the ID encoded in a rollout-<id>.jsonl filename."""
    name = Path(filename).name
    stem = Path(name).stem
    if not stem.startswith("rollout-") or len(stem) == len("rollout-"):
        return None
    return stem.removeprefix("rollout-")


def _metadata(
    value: object,
    filename_id: str | None,
    session_id: str | None,
    project: str,
    parent_session: str | None,
    forked_from: str | None,
) -> tuple[str | None, str, str | None, str | None]:
    """Use only metadata whose ID matches the rollout filename."""
    if not isinstance(value, Mapping) or filename_id is None:
        return session_id, project, parent_session, forked_from
    candidate_id = value.get("id")
    if candidate_id != filename_id or session_id is not None:
        return session_id, project, parent_session, forked_from
    cwd = value.get("cwd")
    project = cwd if isinstance(cwd, str) else ""
    parent = value.get("parent_thread_id")
    fork = value.get("forked_from_id")
    parent_session = parent if isinstance(parent, str) else None
    forked_from = fork if isinstance(fork, str) else None
    return filename_id, project, parent_session, forked_from


def _message(record: Mapping[str, object]) -> tuple[Message | None, bool]:
    """Return retained message text or shell command content from a Codex item."""
    if record.get("type") != "response_item":
        return None, False
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None, True
    item_type = payload.get("type")
    if item_type == "message":
        return _text_message(record, payload)
    command = _tool_command(payload, item_type)
    if command is None:
        return None, False
    return _make_message(record, payload, "assistant", "", (command,))


def _text_message(
    record: Mapping[str, object], payload: Mapping[str, object]
) -> tuple[Message | None, bool]:
    """Extract text from a Codex user or assistant message item."""
    role_value = payload.get("role")
    if role_value not in ("user", "assistant"):
        return None, False
    role: Role = role_value
    texts = _message_text(payload.get("content"), role)
    text = "\n".join(texts)
    if role == "user":
        for block in INJECTED_BLOCKS:
            text = block.sub("", text)
        text = text.strip("\r\n")
    if not text.strip():
        return None, False
    return _make_message(record, payload, role, text, ())


def _message_text(value: object, role: Role) -> list[str]:
    """Extract Codex input_text or output_text blocks for a message role."""
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    block_type = "input_text" if role == "user" else "output_text"
    texts: list[str] = []
    for block in value:
        if not isinstance(block, Mapping):
            continue
        text = block.get("text")
        if block.get("type") in (block_type, "text") and isinstance(text, str):
            texts.append(text)
    return texts


def _tool_command(payload: Mapping[str, object], item_type: object) -> str | None:
    """Extract command input from Codex exec and shell-style function calls."""
    name = payload.get("name")
    if not isinstance(name, str):
        return None
    normalized = name.rsplit(".", 1)[-1]
    if item_type == "custom_tool_call" and normalized == "exec":
        return _command_value(payload.get("input"))
    if item_type == "function_call" and normalized in SHELL_FUNCTIONS:
        arguments = payload.get("arguments", payload.get("input"))
        return _command_value(arguments)
    return None


def _command_value(value: object) -> str | None:
    """Return a command from a string, direct field, or JSON-encoded arguments."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(decoded, Mapping):
            return _command_field(decoded)
        return value
    if isinstance(value, Mapping):
        return _command_field(value)
    return None


def _command_field(value: Mapping[str, object]) -> str | None:
    """The command or cmd field of shell-tool arguments."""
    command = value.get("command", value.get("cmd"))
    return command if isinstance(command, str) else None


def _make_message(
    record: Mapping[str, object],
    payload: Mapping[str, object],
    role: Role,
    text: str,
    commands: tuple[str, ...],
) -> tuple[Message | None, bool]:
    """Build a retained message after validating its timestamp and assigning an ID."""
    timestamp_value = record.get("timestamp")
    timestamp = parse_timestamp(timestamp_value)
    if timestamp is None:
        return None, True
    message_id = payload.get("id")
    if not isinstance(message_id, str) or not message_id:
        original_timestamp = timestamp_value if isinstance(timestamp_value, str) else ""
        message_id = synthetic_id(APP, original_timestamp, role, text)
    return Message(message_id, timestamp, role, text, commands), False
