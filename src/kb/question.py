"""The question file: validation, serialization, and secret-refusal messages."""

import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal

from kb import model, observation

REMOVE = "gap: remove or redact it, then run kb gap again"
RESOLVE_REMOVE = "resolve: remove or redact it, then run kb resolve again"


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


def render_resolution(
    original: str,
    resolution: Literal["answered", "obsolete"],
    answer: str,
    destination: str | None,
    when: date,
) -> str:
    """Append resolution metadata and the answer while preserving the original text."""
    if resolution not in ("answered", "obsolete"):
        raise ValueError(f"unknown resolution: {resolution}")
    if (resolution == "answered") != (destination is not None):
        raise ValueError("answered resolutions need a destination; obsolete resolutions do not")

    bom = "\ufeff" if original.startswith("\ufeff") else ""
    text = original.removeprefix(bom)
    document = model.parse("question.md", text)
    if not document.front_matter_opened or not document.front_matter_closed:
        raise model.FrontMatterEditError("front matter is missing or unclosed")
    existing = {"resolved", "resolution", "destination"}
    present = sorted({field.name for field in document.front_fields} & existing)
    if present:
        raise model.FrontMatterEditError("resolution fields already exist: " + ", ".join(present))

    resolved_date = when.isoformat()
    rendered = model.edit_front_matter(text, "resolved", resolved_date)
    rendered = model.edit_front_matter(rendered, "resolution", resolution)
    if destination is not None:
        rendered = model.edit_front_matter(rendered, "destination", destination, quoted=True)

    ending = _line_ending(rendered)
    trailing = re.search(r"((?:\r\n|\n|\r)+)$", rendered)
    if trailing is None:
        separator = ending * 2
    elif len(re.findall(r"\r\n|\n|\r", trailing.group(1))) == 1:
        separator = ending
    else:
        separator = ""
    section = f"## Resolution ({resolved_date}){ending}{ending}{answer}{ending}"
    return bom + rendered + separator + section


def resolution_scan_text(answer: str, destination: str | None) -> str:
    """Put the stored destination and answer on stable lines for secret detection."""
    return f"destination: {destination or ''}\n\n{answer}\n"


def resolution_refusal_lines(findings: Sequence[tuple[str, int]]) -> list[str]:
    """Report secret detectors and the answer or destination line without its contents."""
    lines = []
    for kind, line in findings:
        if line == 1:
            location = "at destination"
        elif line >= 3:
            location = f"at answer line {line - 2}"
        else:
            raise ValueError(f"scan line {line} holds no agent text")
        lines.append(f"resolve: refused: possible secret ({kind}) {location}")
    return [*lines, RESOLVE_REMOVE]


def _line_ending(text: str) -> str:
    """The last line ending in the original, or LF for a file without one."""
    endings = re.findall(r"\r\n|\n|\r", text)
    return endings[-1] if endings else "\n"
