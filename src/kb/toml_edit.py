"""Line-preserving edits to TOML text that kb writes one top-level key into."""

import tomllib

BOM = "﻿"


def first_table_line(lines: list[str]) -> int:
    """The index of the first table header, or len(lines) when there is none.

    A line counts only when it starts with "[" and every line before it parses as
    complete TOML, so lines inside a multi-line array or string never count.
    """
    for index, line in enumerate(lines):
        if not line.removeprefix(BOM).lstrip().startswith("["):
            continue
        try:
            tomllib.loads("".join(lines[:index]).removeprefix(BOM))
        except tomllib.TOMLDecodeError:
            continue
        return index
    return len(lines)


def insert_line(text: str, lines: list[str], index: int, assignment: str) -> str:
    """Insert `assignment` (no line ending) at index, matching the file's newline style.

    Adds a missing final newline when inserting at the end, and keeps a leading BOM
    first when inserting at line 0.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    edited = list(lines)
    if index == len(edited) and edited and not edited[-1].endswith(("\n", "\r")):
        edited[-1] += newline
    line = assignment + newline
    if index == 0 and edited and edited[0].startswith(BOM):
        edited[0] = edited[0].removeprefix(BOM)
        line = BOM + line
    edited.insert(index, line)
    return "".join(edited)
