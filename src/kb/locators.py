"""Locators: the names kb prints and accepts.

A locator is PATH, or PATH#FRAGMENT. The fragment is "title" (the front
matter title), "top" (the body before the first H2), "N" (the Nth H2 with
its H3s), or "N.M" (the Mth H3 under the Nth H2). Resolving PATH to a file
needs the file system, so the corpus module does it. This module parses a
locator, selects the text it names, and formats the header line.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from kb.model import Document, Section

NUMBERED = re.compile(r"[0-9]+(?:\.[0-9]+)?")


@dataclass(frozen=True)
class Locator:
    """PATH as typed, and the fragment (None for the whole file)."""

    path: str
    fragment: str | None


@dataclass(frozen=True)
class Selection:
    """The text a fragment names: its heading, its lines, and its section if it has one."""

    heading: str
    lines: tuple[str, ...]
    section: Section | None


def parse_locator(text: str) -> Locator:
    """Split a locator at its first "#". Numbered fragments lose leading zeros."""
    path, separator, fragment = text.partition("#")
    if not separator:
        return Locator(path, None)
    if NUMBERED.fullmatch(fragment):
        fragment = ".".join(str(int(part)) for part in fragment.split("."))
    return Locator(path, fragment)


def display_title(document: Document) -> str:
    """The title a header or listing shows: the front matter title, else the H1, else the file name."""
    return document.title or document.h1 or PurePosixPath(document.path).stem


def outline(document: Document) -> list[str]:
    """One locator line for the title, then one for each H2 and each H3 indented under it."""
    lines: list[str] = []
    if document.title:
        lines.append(f"{document.path}#title | {document.title}")
    for section in document.sections:
        indent = "  " if section.level == 3 else ""
        lines.append(f"{indent}{document.path}#{section.key} | {section.heading}")
    return lines


def select(document: Document, fragment: str) -> Selection | None:
    """The text the fragment names, or None when the document has no such part."""
    if fragment == "title":
        title = document.title
        return None if title is None else Selection(title, (title,), None)
    if fragment == "top":
        return Selection(document.h1 or document.title or "", document.top_lines(), None)
    section = document.section(fragment)
    if section is None:
        return None
    return Selection(section.heading, document.section_lines(section), section)


def header(locator: str, heading: str, status: str | None, sources: int | None) -> str:
    """The line before a block: locator, heading, and, for curated files, status and sources."""
    parts = [locator, heading]
    if status is not None:
        parts.append(status)
    if sources is not None:
        parts.append(f"{sources} source" + ("" if sources == 1 else "s"))
    return " | ".join(parts)


def block(head: str, lines: Sequence[str]) -> str:
    """A header and its lines, ending with a newline."""
    return "\n".join([head, *lines]) + "\n"
