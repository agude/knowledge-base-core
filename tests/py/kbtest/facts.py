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
