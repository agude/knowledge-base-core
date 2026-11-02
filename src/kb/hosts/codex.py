"""Parse Codex rollout JSONL sessions into the neutral transcript model."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kb.shellcalls import Invocation, invocations
from kb.transcripts import (
    App,
    KbCall,
    Message,
    Role,
    Session,
    Store,
    complete_lines,
    earlier,
    later,
    parse_timestamp,
    synthetic_id,
    unique_messages,
)

APP: App = "codex"
SHELL_FUNCTIONS = frozenset({"exec", "exec_command", "run_shell_command", "shell"})
EXEC_COMMAND = re.compile(r'\b(?:cmd|command)\s*:\s*("(?:\\.|[^"\\])*")')
TIMESTAMPED_ROLLOUT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)$")
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
        latest_timestamp=latest_timestamp,
        snapshot_complete=complete,
        malformed_lines=malformed,
        duplicate_ids=duplicates,
    )


def _filename_id(filename: str) -> str | None:
    """Return the session ID encoded in a rollout filename."""
    name = Path(filename).name
    stem = Path(name).stem
    if not stem.startswith("rollout-") or len(stem) == len("rollout-"):
        return None
    filename_id = stem.removeprefix("rollout-")
    timestamped_match = TIMESTAMPED_ROLLOUT.fullmatch(filename_id)
    if timestamped_match is not None:
        return timestamped_match.group(1)
    return filename_id


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


@dataclass
class _ToolCall:
    """One Codex exec or shell call that ran at least one recorded kb call, and its output.

    commands holds each shell command the call ran, with the recorded kb calls in it.
    """

    timestamp: datetime | None
    commands: list[tuple[str, tuple[Invocation, ...]]]
    output: str | None = None


@dataclass(frozen=True)
class _Scan:
    calls: tuple[KbCall, ...]
    first: datetime | None
    last: datetime | None


def kb_calls(text: str, filename: str) -> tuple[KbCall, ...]:
    """The recorded kb calls in one Codex rollout, each with its paired output."""
    return _scan(text, filename).calls


def read_store(root: Path) -> Store:
    """Read every Codex rollout under a sessions directory. Only the files are read.

    An unreadable file is counted and skipped.
    """
    calls: list[KbCall] = []
    files = unreadable = 0
    first: datetime | None = None
    last: datetime | None = None
    for path in sorted(root.rglob("rollout-*.jsonl")):
        files += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        scan = _scan(text, path.name)
        calls.extend(scan.calls)
        first = earlier(first, scan.first)
        last = later(last, scan.last)
    return Store(tuple(calls), files, unreadable, first, last)


def _scan(text: str, filename: str) -> _Scan:
    """Pair each exec or shell call that ran a kb call with its output, by call ID."""
    lines, _complete = complete_lines(text)
    session_id = _filename_id(filename)
    project = ""
    first: datetime | None = None
    last: datetime | None = None
    pending: dict[str, _ToolCall] = {}
    tool_calls: list[_ToolCall] = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        moment = parse_timestamp(record.get("timestamp"))
        first = earlier(first, moment)
        last = later(last, moment)
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if record.get("type") == "session_meta":
            cwd = payload.get("cwd")
            if not project and isinstance(cwd, str):
                project = cwd
            continue
        if record.get("type") != "response_item":
            continue
        item_type = payload.get("type")
        call_id = payload.get("call_id")
        if item_type in ("custom_tool_call", "function_call"):
            commands = _recorded_commands(payload, item_type)
            if not commands:
                continue
            call = _ToolCall(moment, commands)
            tool_calls.append(call)
            if isinstance(call_id, str):
                pending[call_id] = call
        elif item_type in ("custom_tool_call_output", "function_call_output"):
            if isinstance(call_id, str) and call_id in pending:
                pending.pop(call_id).output = _output_text(payload.get("output"))
    calls = tuple(
        KbCall(
            app=APP,
            session_id=session_id,
            timestamp=call.timestamp,
            project=project,
            command=command,
            subcommand=found.subcommand,
            arguments=found.arguments,
            output=call.output,
            shared=sum(len(items) for _command, items in call.commands) > 1,
        )
        for call in tool_calls
        for command, items in call.commands
        for found in items
    )
    return _Scan(calls, first, last)


def _recorded_commands(
    payload: Mapping[str, object], item_type: object
) -> list[tuple[str, tuple[Invocation, ...]]]:
    """Each shell command of a tool call that holds a recorded kb call, with those calls."""
    found: list[tuple[str, tuple[Invocation, ...]]] = []
    for command in _shell_commands(payload, item_type):
        items = invocations(command)
        if items:
            found.append((command, items))
    return found


def _shell_commands(payload: Mapping[str, object], item_type: object) -> list[str]:
    """The shell commands of an exec call, or of a shell-style function call."""
    name = payload.get("name")
    if not isinstance(name, str):
        return []
    normalized = name.rsplit(".", 1)[-1]
    if item_type == "custom_tool_call" and normalized == "exec":
        source = payload.get("input")
        return _exec_commands(source) if isinstance(source, str) else []
    if item_type == "function_call" and normalized in SHELL_FUNCTIONS:
        command = _command_value(payload.get("arguments", payload.get("input")))
        return [] if command is None else [command]
    return []


def _exec_commands(source: str) -> list[str]:
    """The string literals given as cmd or command in an exec script.

    Literals that are not JSON strings, such as template literals, are not read.
    """
    commands: list[str] = []
    for literal in EXEC_COMMAND.findall(source):
        try:
            value = json.loads(literal)
        except json.JSONDecodeError:
            continue
        if isinstance(value, str):
            commands.append(value)
    return commands


def _output_text(value: object) -> str:
    """A tool output's text: a string, or the text blocks of a list."""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    texts: list[str] = []
    for block in value:
        if isinstance(block, Mapping) and isinstance(block.get("text"), str):
            texts.append(str(block["text"]))
    return "\n".join(texts)
