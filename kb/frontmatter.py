"""Front matter: the YAML-like block between `---` lines at the top of a file."""

from __future__ import annotations

import re


def lines(text: str) -> list[str]:
    """Lines as bash's `while read` sees them: a final unterminated line is dropped."""
    parts = text.split("\n")
    parts.pop()  # The text after the last newline: empty, or an unterminated line.
    return parts


def field(text: str, name: str) -> str | None:
    """The value of name in the block after the first `---` line, as bash reads it.

    Matches frontmatter_field in scripts/_lib.sh: the block starts at the
    first line that is exactly `---`, wherever it is, and ends at the next;
    a double-quoted value is unquoted and yaml_escape is reversed.
    """
    pattern = re.compile(rf"{re.escape(name)}:\s*(.*)")
    inside = False
    for line in lines(text):
        if line == "---":
            if inside:
                return None
            inside = True
            continue
        if inside and (match := pattern.match(line)):
            value = match.group(1)
            if quoted := re.fullmatch(r'"(.*)"', value, re.DOTALL):
                value = quoted.group(1).replace('\\"', '"').replace("\\\\", "\\")
            return value
    return None
