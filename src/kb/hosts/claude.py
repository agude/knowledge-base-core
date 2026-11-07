"""Parse Claude Code JSONL sessions into the neutral transcript model."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kb.shellcalls import Invocation, invocations, sole_invocation
from kb.transcripts import (
    App,
    KbCall,
    Message,
    Role,
    Scan,
    Session,
    Store,
    complete_lines,
    earlier,
    later,
    parse_timestamp,
    synthetic_command_id,
    synthetic_id,
    text_of,
    tool_call_id,
    unique_messages,
)
from kb.transcripts import (
    read_store as read_transcript_store,
)

APP: App = "claude-code"
SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
# The tools whose input is a shell command. Claude Code on Windows has both.
SHELL_TOOLS = frozenset(("Bash", "PowerShell"))


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
    texts, commands, call_ids = _content(message.get("content"), role)
    text = "\n".join(texts)
    if role == "user":
        text = SYSTEM_REMINDER.sub("", text)
    if not text.strip() and not commands:
        return None, False
    original_timestamp = timestamp_value if isinstance(timestamp_value, str) else ""
    message_id = record.get("uuid")
    legacy_id = None
    generated = False
    if not isinstance(message_id, str) or not message_id:
        message_id = synthetic_id(APP, original_timestamp, role, text)
        if commands:
            legacy_id = message_id
            if len(call_ids) == len(commands):
                message_id = tool_call_id(call_ids)
            else:
                message_id = synthetic_command_id(
                    APP, original_timestamp, role, text, tuple(commands)
                )
                generated = True
    return Message(message_id, timestamp, role, text, tuple(commands), legacy_id, generated), False


def _content(value: object, role: Role) -> tuple[list[str], list[str], list[str]]:
    """Extract user or assistant text blocks and Claude Bash and PowerShell command inputs."""
    if role == "user" and isinstance(value, str):
        return [value], [], []
    if not isinstance(value, list):
        return [], [], []
    texts: list[str] = []
    commands: list[str] = []
    call_ids: list[str] = []
    for block in value:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        block_text = block.get("text")
        if block_type == "text" and isinstance(block_text, str):
            texts.append(block_text)
        elif role == "assistant" and block_type == "tool_use" and block.get("name") in SHELL_TOOLS:
            command = _shell_command(block.get("input"))
            if command is not None:
                commands.append(command)
                call_id = block.get("id")
                if isinstance(call_id, str) and call_id:
                    call_ids.append(call_id)
    return texts, commands, call_ids


def _shell_command(value: object) -> str | None:
    """A Claude shell tool input's command, when it is a string."""
    if not isinstance(value, Mapping):
        return None
    command = value.get("command")
    return command if isinstance(command, str) else None


def _first_text(current: str, candidate: object) -> str:
    """Return the first non-empty string seen in a transcript metadata field."""
    if current or not isinstance(candidate, str) or not candidate:
        return current
    return candidate


@dataclass
class _ToolCall:
    """One shell tool call that ran at least one recorded kb call, and its paired result.

    excluded is "missing" until a tool_result pairs with the call. After that it is None for a
    usable output, and otherwise the reason the output is not usable.
    """

    timestamp: datetime | None
    command: str
    found: tuple[Invocation, ...]
    output: str | None = None
    excluded: str | None = "missing"


def kb_calls(text: str, session_id: str | None) -> tuple[KbCall, ...]:
    """The recorded kb calls in one Claude Code transcript, each with its paired output."""
    return _scan(text, session_id).calls


def read_store(root: Path) -> Store:
    """Read every main and subagent Claude Code transcript under a projects directory.

    Only the files are read; nothing is written. An unreadable file is counted and skipped.
    """
    return read_transcript_store(_transcript_paths(root), lambda text, path: _scan(text, path.stem))


def _transcript_paths(root: Path) -> list[Path]:
    """Main transcripts, then subagent transcripts, in path order."""
    paths = sorted(root.glob("*/*.jsonl"))
    paths.extend(sorted(root.glob("*/*/subagents/agent-*.jsonl")))
    return paths


def _scan(text: str, session_id: str | None) -> Scan:
    """Pair each shell tool call that ran a kb call with its tool_result, by tool-use ID."""
    lines, _complete = complete_lines(text)
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
        project = _first_text(project, record.get("cwd"))
        message = record.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if record.get("type") == "assistant" and _is_shell_use(block):
                command = _shell_command(block.get("input"))
                found = invocations(command) if command is not None else ()
                if found and isinstance(block.get("id"), str):
                    call = _ToolCall(moment, command or "", found)
                    pending[block["id"]] = call
                    tool_calls.append(call)
            elif block.get("type") == "tool_result":
                use_id = block.get("tool_use_id")
                if isinstance(use_id, str) and use_id in pending:
                    _pair(pending.pop(use_id), block.get("content"))
    calls = tuple(
        _kb_call(call, found, session_id, project) for call in tool_calls for found in call.found
    )
    return Scan(calls, first, last)


def _pair(call: _ToolCall, content: object) -> None:
    """Set a tool call's output from its tool_result content, or the reason it is unusable."""
    text = text_of(content)
    if text is None:
        call.output, call.excluded = None, "unsupported"
    else:
        call.output, call.excluded = text, None


def _kb_call(call: _ToolCall, found: Invocation, session_id: str | None, project: str) -> KbCall:
    """One kb call. Its output is its own only when its tool call ran no other kb call."""
    excluded = "shared" if sole_invocation(call.command) is None else call.excluded
    return KbCall(
        app=APP,
        session_id=session_id,
        timestamp=call.timestamp,
        project=project,
        command=call.command,
        subcommand=found.subcommand,
        arguments=found.arguments,
        output=None if excluded is not None else call.output,
        excluded=excluded,
    )


def _is_shell_use(block: Mapping[str, object]) -> bool:
    return block.get("type") == "tool_use" and block.get("name") in SHELL_TOOLS
