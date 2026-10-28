"""The question file: validation, serialization, and secret-refusal messages."""

from collections.abc import Sequence
from datetime import datetime

from kb import observation

REMOVE = "gap: remove or redact it, then run kb gap again"


def render(title: str, context: str, body: str, project: str, host: str, when: datetime) -> str:
    """The question bytes, with the supplied context and observe-style attribution."""
    return (
        "---\n"
        f'title: "{observation.escape(title)}"\n'
        f'context: "{observation.escape(context)}"\n'
        "source: session\n"
        f'project: "{observation.escape(project)}"\n'
        f'host: "{observation.escape(host)}"\n'
        f"created: {observation.created_text(when)}\n"
        "---\n"
        "\n"
        f"{body}\n"
    )


def scan_text(title: str, context: str, body: str) -> str:
    """The title, context, and body in the line layout used by the secrets scanner."""
    return f"title: {title}\ncontext: {context}\n\n{body}\n"


def refusal_lines(findings: Sequence[tuple[str, int]]) -> list[str]:
    """Secret refusal messages that identify a field without printing its contents."""
    return [
        *[f"gap: refused: possible secret ({kind}) {location(line)}" for kind, line in findings],
        REMOVE,
    ]


def location(scan_line: int) -> str:
    """The supplied field containing a finding in scan_text's line layout."""
    if scan_line == 1:
        return "at title"
    if scan_line == 2:
        return "at context"
    if scan_line >= 4:
        return f"at body line {scan_line - 3}"
    raise ValueError(f"scan line {scan_line} holds no agent text")
