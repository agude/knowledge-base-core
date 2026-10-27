"""The observation file: its validation, its bytes, its names, and its refusal messages.

Every function here is pure. The command layer supplies the time, the random
suffix, the attribution, and the content path, and it does the file I/O. This
module writes front matter. It never parses it.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime

SUFFIX = re.compile(r"[0-9a-f]{8}")
REMOVE = "observe: remove or redact it, then run kb observe again"


class InvalidArgument(ValueError):
    """A title or body that the contract refuses. The command reports it as a usage error."""


def check_title(title: str) -> None:
    """Raise InvalidArgument unless the title is one line and has some text in it."""
    if "\n" in title or "\r" in title:
        raise InvalidArgument("the title must be one line")
    if not title.strip():
        raise InvalidArgument("the title must not be blank")


def check_body(body: str) -> None:
    """Raise InvalidArgument unless the body has some text in it."""
    if not body.strip():
        raise InvalidArgument("the body must not be blank")


def escape(text: str) -> str:
    """Escape text for a double-quoted YAML scalar: backslashes first, then double quotes."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def short_host(name: str) -> str:
    """The host name up to its first dot."""
    return name.split(".", 1)[0]


def created_text(when: datetime) -> str:
    """The created field for a timestamp: UTC, in the form YYYY-mm-ddTHH:MM:SSZ."""
    return _utc(when).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_name(when: datetime, suffix: str) -> str:
    """The observation's file name: its UTC time, a dash, the suffix, and .md."""
    return f"{_utc(when):%Y%m%dT%H%M%S}-{_checked(suffix)}.md"


def temporary_name(suffix: str) -> str:
    """The name of the temporary file that holds the observation until it is published."""
    return f"observation-{_checked(suffix)}.md"


def render(title: str, body: str, project: str, host: str, when: datetime) -> str:
    """The observation file's bytes: front matter, a blank line, the body, and one newline."""
    return (
        "---\n"
        f'title: "{escape(title)}"\n'
        "source: session\n"
        f'project: "{escape(project)}"\n'
        f'host: "{escape(host)}"\n'
        f"created: {created_text(when)}\n"
        "---\n"
        "\n"
        f"{body}\n"
    )


def scan_text(title: str, body: str) -> str:
    """The text that the secrets check scans: the title on line 1, a blank line 2, the body from line 3."""
    return f'title: "{escape(title)}"\n\n{body}\n'


def location(scan_line: int) -> str:
    """Where a finding on a line of the scan text is, in words the agent can act on."""
    if scan_line == 1:
        return "at title"
    if scan_line >= 3:
        return f"at body line {scan_line - 2}"
    raise ValueError(f"scan line {scan_line} holds no agent text")


def refusal_lines(findings: Sequence[tuple[str, int]]) -> list[str]:
    """The stderr lines for a refused observation: one line per finding, then the instruction.

    A finding is its detector's name and its line in the scan text. The secret itself is
    never part of a message.
    """
    lines = [
        f"observe: refused: possible secret ({kind}) {location(line)}" for kind, line in findings
    ]
    return [*lines, REMOVE]


def _utc(when: datetime) -> datetime:
    """The timestamp in UTC. A naive timestamp is refused, because its zone is unknown."""
    if when.tzinfo is None:
        raise ValueError("the timestamp must be timezone-aware")
    return when.astimezone(UTC)


def _checked(suffix: str) -> str:
    """The suffix, unchanged, when it is eight lowercase hex digits."""
    if not SUFFIX.fullmatch(suffix):
        raise ValueError(f"the suffix must be 8 lowercase hex digits, not {suffix!r}")
    return suffix
