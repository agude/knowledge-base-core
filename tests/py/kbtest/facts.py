"""Extract the facts a command reports, independent of its layout.

Contract tests compare these facts; the layout around them is pinned only by
reference goldens. Each function documents what it keeps.
"""

from __future__ import annotations

import re

_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)*)\.\s?(.*)$")
_DEEPER = re.compile(r"^\s*- (.*)$")
_AREA = re.compile(r"^\s*(\S+/|knowledge/ \(loose files\))\s+(\d+)$")
_TOTAL = re.compile(r"^\s*(\d+) articles\.")
# tree(1) draws with box characters, spaces, and no-break spaces.
_TREE_CHARS = "\u2502\u251c\u2514\u2500 \u00a0"


def toc(text: str) -> str:
    """toc output as facts.

    Keeps: file headers, title lines, numbered headings (number and name),
    deeper headings, --map areas with counts and the total, and --dirs entry
    names in order. Drops: indentation, tree-drawing characters, and blank
    lines.
    """
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            rows.append(f"file {stripped[1:-1]}")
        elif match := _AREA.match(line):
            rows.append(f"area {match.group(1)} {match.group(2)}")
        elif match := _TOTAL.match(line):
            rows.append(f"total {match.group(1)}")
        elif match := _NUMBERED.match(line):
            rows.append(f"heading {match.group(1)} {match.group(2)}")
        elif match := _DEEPER.match(line):
            rows.append(f"deeper {match.group(1)}")
        else:
            rows.append(f"line {stripped.lstrip(_TREE_CHARS).rstrip('/')}")
    return "\n".join(rows) + "\n"


def section_body(text: str) -> str:
    """section output without its metadata header.

    Default output starts with metadata lines and a '---' separator; the
    content after it is what the reader asked for. --text-only output is
    content already.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line == "---\n" and index > 0 and lines[0].startswith("Metadata: "):
            return "".join(lines[index + 1 :])
    return text


def session_context(text: str, instructions: str) -> str:
    """Session context as facts.

    Keeps: whether the tooling instructions open the context verbatim, the
    topic map (areas and total), the state line, and any further lines (the
    content repository's own instructions). Drops: headings and blank lines
    around them.
    """
    verbatim = bool(instructions) and text.startswith(instructions)
    rows = [f"instructions {'verbatim' if verbatim else 'missing'}"]
    rest = text[len(instructions) :] if verbatim else text
    for line in rest.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "## Topic areas (auto-generated)":
            continue
        if stripped.startswith("State: "):
            rows.append(f"state {stripped[len('State: ') :]}")
        elif match := _AREA.match(line):
            rows.append(f"area {match.group(1)} {match.group(2)}")
        elif match := _TOTAL.match(line):
            rows.append(f"total {match.group(1)}")
        else:
            rows.append(f"line {stripped}")
    return "\n".join(rows) + "\n"


_STALE_ROW = re.compile(r"^ +(?:(\d+) days|\[([a-z ]+)\]) +(\S+)", re.MULTILINE)
_STALE_TOTALS = re.compile(
    r"(\d+) stale, (\d+) missing date|(\d+) section\(s\) needing attention|No stale articles"
)


def stale(text: str) -> str:
    """What stale flagged: each path with its age or label, and the totals.

    Layout and wording are reference; which items are flagged, how old they
    are, and the totals are contract.
    """
    if re.fullmatch(r"\d+\n", text):
        return f"count {text}"
    rows = [f"{path} {age or label}" for age, label, path in _STALE_ROW.findall(text)]
    totals = _STALE_TOTALS.search(text)
    rows.append(f"totals {totals.group(0) if totals else 'none'}")
    return "\n".join(rows) + "\n"


def status(text: str) -> str:
    """Counts, dates, topics, and the brief line: the values status and context report."""
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(
            r"\d+ articles \| \d+ pending \| \d+ stale \| \d+ open question\(s\)", stripped
        ):
            rows.append(f"brief {stripped}")
        elif match := re.fullmatch(
            r"([A-Z][A-Za-z ]+):\s+(\d+|never|\d{4}-\d{2}-\d{2} .+)", stripped
        ):
            rows.append(f"{match.group(1)}={match.group(2)}")
        elif match := re.fullmatch(r"Topics \((\d+) files\):", stripped):
            rows.append(f"topic files={match.group(1)}")
        elif stripped == "Topics: (none yet)":
            rows.append("topic files=0")
        elif (
            line.startswith("  ")
            and ":" not in stripped
            and rows
            and rows[-1].startswith(("topic", "  "))
        ):
            rows.append(f"  {stripped}")
    return "\n".join(rows) + "\n"


def questions(text: str) -> list[tuple[str, str]]:
    """Listed questions as (title, context) from '- title (context)' lines."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        item = line[2:]
        context = ""
        if item.endswith(")") and " (" in item:
            item, context = item[:-1].rsplit(" (", 1)
        rows.append((item, context))
    return rows


def pending(text: str) -> list[str]:
    """Observation files named in the listing, in order."""
    return re.findall(r"\[([^\]]+)\]$", text, re.MULTILINE)
