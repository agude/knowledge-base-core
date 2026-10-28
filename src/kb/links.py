"""Read inline and reference-style Markdown link destinations for content linting."""

import re
from collections.abc import Sequence

_DEFINITION = re.compile(r" {0,3}\[((?:\\.|[^\]\\])+)\]:[ \t]*(.*)")
_ESCAPED_PUNCTUATION = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])")


def destinations(lines: Sequence[str]) -> list[tuple[int, str]]:
    """Return one-based use locations and targets; definitions may follow their uses.

    The caller blanks front matter, fences, metadata, and inline code. Reference
    labels ignore case and collapse whitespace; their first definition wins.
    """
    definitions: dict[str, str] = {}
    definition_lines: set[int] = set()
    for line_index, line in enumerate(lines):
        match = _DEFINITION.fullmatch(line)
        if match is None:
            continue
        target = _destination(match.group(2), 0)
        if target is not None:
            definitions.setdefault(_label(match.group(1)), target[0])
            definition_lines.add(line_index)

    found: list[tuple[int, str]] = []
    for line_index, line in enumerate(lines):
        if line_index not in definition_lines:
            found.extend((line_index + 1, target) for target in _line_targets(line, definitions))
    return found


def _line_targets(line: str, definitions: dict[str, str]) -> list[str]:
    """Read balanced link text and its inline target or reference label."""
    found: list[str] = []
    index = 0
    while index < len(line):
        if line[index] == "\\":
            index += 2
            continue
        if line[index] != "[":
            index += 1
            continue
        closing = _closing_bracket(line, index)
        if closing is None:
            index += 1
            continue
        label = line[index + 1 : closing]
        after = closing + 1
        if after < len(line) and line[after] == "(":
            inline = _inline_target(line, after + 1)
            if inline is not None:
                target, index = inline
                found.append(target)
                continue
        if after < len(line) and line[after] == "[":
            reference_end = _closing_bracket(line, after)
            if reference_end is not None:
                label = line[after + 1 : reference_end] or label
                after = reference_end + 1
        reference_target = definitions.get(_label(label))
        if reference_target is not None:
            found.append(reference_target)
            index = after
        else:
            index += 1
    return found


def _closing_bracket(text: str, start: int) -> int | None:
    """Find the matching bracket, skipping escaped punctuation and nested labels."""
    depth = 1
    index = start + 1
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _inline_target(text: str, start: int) -> tuple[str, int] | None:
    """Read a destination followed by an optional title and the closing parenthesis."""
    start = _skip_space(text, start)
    target = _destination(text, start)
    if target is None:
        return None
    destination, end = target
    index = _skip_space(text, end)
    if index > end and index < len(text) and text[index] in "\"'(":
        closing = ")" if text[index] == "(" else text[index]
        index += 1
        while index < len(text) and text[index] != closing:
            index += 2 if text[index] == "\\" else 1
        if index == len(text):
            return None
        index = _skip_space(text, index + 1)
    if index < len(text) and text[index] == ")":
        return destination, index + 1
    return None


def _destination(text: str, start: int) -> tuple[str, int] | None:
    """Read an angle-delimited target or a bare target with balanced parentheses."""
    index = start
    angled = index < len(text) and text[index] == "<"
    if angled:
        index += 1
        start = index
    depth = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            index += 2
            continue
        if angled:
            if character == ">":
                return _unescape(text[start:index]), index + 1
            if character == "<":
                return None
        elif character.isspace() or (character == ")" and depth == 0):
            break
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        index += 1
    if angled or depth:
        return None
    return _unescape(text[start:index]), index


def _skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _label(text: str) -> str:
    return " ".join(text.split()).casefold()


def _unescape(text: str) -> str:
    return _ESCAPED_PUNCTUATION.sub(r"\1", text)
