"""Pure titles, secret-redaction transforms, rendering, and validation for transcripts."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from kb.model import parse as parse_markdown
from kb.observation import escape
from kb.transcripts import Message, Session, timestamp_text

SOURCE = "session-transcript"
REDACTED = "[redacted: {detector}]"
TILDE_RUN = re.compile(r"~+")


@dataclass(frozen=True)
class ContentLine:
    """The message content line represented by one line in a secrets scan."""

    message_index: int
    command_index: int | None
    line_index: int


def title_candidates(messages: Sequence[Message]) -> tuple[str, str, str | None]:
    """Return the safe fallback title, excerpted title, and user excerpt."""
    fallback = f"Session transcript ({len(messages)} messages)"
    excerpt: str | None = None
    for message in messages:
        if message.role != "user":
            continue
        excerpt = next((line.strip() for line in message.text.splitlines() if line.strip()), None)
        if excerpt:
            break
    if excerpt is None:
        return fallback, fallback, None
    excerpt = excerpt[:60]
    return fallback, f"{fallback}: {excerpt}", excerpt


def title_after_scan(
    messages: Sequence[Message], findings: Sequence[tuple[str, int]]
) -> tuple[str, int]:
    """Drop the title excerpt when the separate title scan reports a finding."""
    fallback, candidate, excerpt = title_candidates(messages)
    if excerpt is not None and findings:
        return fallback, 1
    return candidate, 0


def scan_text(messages: Sequence[Message]) -> tuple[str, tuple[ContentLine, ...]]:
    """Flatten only text and command lines, with locations for findings from secrets.py."""
    lines: list[str] = []
    locations: list[ContentLine] = []
    for message_index, message in enumerate(messages):
        _append_lines(lines, locations, message.text, message_index, None)
        for command_index, command in enumerate(message.commands):
            _append_lines(lines, locations, command, message_index, command_index)
    if not lines:
        return "", ()
    return "\n".join(lines) + "\n", tuple(locations)


def redact_messages(
    messages: Sequence[Message],
    findings: Sequence[tuple[str, int]],
    locations: Sequence[ContentLine],
) -> tuple[tuple[Message, ...], int]:
    """Replace finding lines inside text or commands while leaving structure untouched."""
    replacements: dict[ContentLine, str] = {}
    for detector, line_number in findings:
        location_index = line_number - 1
        if 0 <= location_index < len(locations):
            location = locations[location_index]
            replacements.setdefault(location, REDACTED.format(detector=detector))
    if not replacements:
        return tuple(messages), 0

    redacted: list[Message] = []
    for message_index, message in enumerate(messages):
        text = _replace_lines(message.text, message_index, None, replacements)
        commands = tuple(
            _replace_lines(command, message_index, command_index, replacements)
            for command_index, command in enumerate(message.commands)
        )
        redacted.append(replace(message, text=text, commands=commands))
    return tuple(redacted), len(replacements)


def render(
    session: Session,
    messages: Sequence[Message],
    part: int,
    host: str,
    created: datetime,
    forked_from: str | None = None,
    title: str | None = None,
) -> str:
    """Render one transcript observation with stable front matter and fenced messages."""
    if session.id is None:
        raise ValueError("a transcript observation needs a session ID")
    if not messages:
        raise ValueError("a transcript observation needs at least one message")
    if part < 1:
        raise ValueError("a transcript part must be positive")
    if title is None:
        _, title, _ = title_candidates(messages)
    started = timestamp_text(messages[0].timestamp)
    ended = timestamp_text(messages[-1].timestamp)
    lines = [
        "---",
        f'title: "{escape(title)}"',
        f"source: {SOURCE}",
        f'project: "{escape(session.project)}"',
        f'host: "{escape(host)}"',
        f"app: {session.app}",
        f'session: "{escape(session.id)}"',
    ]
    if session.parent_session is not None:
        lines.append(f'parent_session: "{escape(session.parent_session)}"')
    if forked_from is not None:
        lines.append(f'forked_from: "{escape(forked_from)}"')
    lines.extend(
        (
            f"part: {part}",
            f'first_message: "{escape(messages[0].id)}"',
            f'last_message: "{escape(messages[-1].id)}"',
            f"started: {started}",
            f"ended: {ended}",
            f"created: {timestamp_text(created)}",
            "---",
            "",
            _render_messages(messages),
        )
    )
    return "\n".join(lines) + "\n"


def validate(
    text: str,
    session: Session,
    messages: Sequence[Message],
    part: int,
    host: str,
    created: datetime,
    forked_from: str | None = None,
    title: str | None = None,
) -> tuple[str, ...]:
    """Check rendered front matter against its expected values and count its H2 messages."""
    if session.id is None or not messages:
        return ("missing session ID or messages",)
    if title is None:
        _, title, _ = title_candidates(messages)
    expected = {
        "title": title,
        "source": SOURCE,
        "project": session.project,
        "host": host,
        "app": session.app,
        "session": session.id,
        "part": str(part),
        "first_message": messages[0].id,
        "last_message": messages[-1].id,
        "started": timestamp_text(messages[0].timestamp),
        "ended": timestamp_text(messages[-1].timestamp),
        "created": timestamp_text(created),
    }
    if session.parent_session is not None:
        expected["parent_session"] = session.parent_session
    if forked_from is not None:
        expected["forked_from"] = forked_from
    document = parse_markdown("observation.md", text)
    failures = [
        field
        for field, expected_value in expected.items()
        if document.front.get(field) != expected_value
    ]
    for optional in ("parent_session", "forked_from"):
        if optional not in expected and optional in document.front:
            failures.append(optional)
    if sum(section.level == 2 for section in document.sections) != len(messages):
        failures.append("message headings")
    return tuple(failures)


def _append_lines(
    lines: list[str],
    locations: list[ContentLine],
    value: str,
    message_index: int,
    command_index: int | None,
) -> None:
    """Add a content value's lines and source locations to the secrets scan."""
    if not value:
        return
    for line_index, line in enumerate(value.split("\n")):
        lines.append(line)
        locations.append(ContentLine(message_index, command_index, line_index))


def _replace_lines(
    value: str,
    message_index: int,
    command_index: int | None,
    replacements: Mapping[ContentLine, str],
) -> str:
    """Apply redactions to one text or command value by its line indices."""
    if not value:
        return value
    lines = value.split("\n")
    for line_index, _line in enumerate(lines):
        location = ContentLine(message_index, command_index, line_index)
        if location in replacements:
            lines[line_index] = replacements[location]
    return "\n".join(lines)


def _render_messages(messages: Sequence[Message]) -> str:
    """Render numbered H2 messages, text fences, and separate shell fences."""
    sections: list[str] = []
    for number, message in enumerate(messages, start=1):
        lines = [f"## {number}. {message.role}, {timestamp_text(message.timestamp)}"]
        if message.text:
            lines.extend(("", _fence(message.text, "text")))
        for command in message.commands:
            lines.extend(("", _fence(command, "sh")))
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _fence(value: str, info: str) -> str:
    """Wrap a message value in a tilde fence longer than any tildes inside it."""
    longest = max((len(match.group()) for match in TILDE_RUN.finditer(value)), default=0)
    marker = "~" * max(4, longest + 1)
    ending = "" if value.endswith("\n") else "\n"
    return f"{marker}{info}\n{value}{ending}{marker}"
