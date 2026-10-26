"""The one parser for Markdown files: front matter, headings, sections, and metadata.

Every command that reads a Markdown file goes through parse(), so they all
agree on these rules.

- Lines are split on "\\n", and a "\\r" that ends a line is dropped (CRLF). A
  final line without a newline is kept.
- Front matter exists only when line 1 is "---" and a later line is "---"
  (spaces and tabs may follow either). Without the closing line, the whole
  file is body text.
- A front matter line is "key: value". A value is a plain scalar (trailing
  spaces and tabs dropped), a double-quoted scalar (\\" and \\\\ escapes), or
  a single-quoted scalar (a doubled '' is one quote). A key with no value may
  be followed by "- item" lines, which form a list. The first occurrence of a
  key wins. Other lines are ignored.
- A fence opens with three or more backticks or tildes, indented by up to
  three spaces. A backtick fence's info string may not contain a backtick.
  The fence closes at a line of the same character, at least as long, with
  nothing after it. Lines inside a fence are never headings or metadata.
- A heading is one to three "#" at the start of a line, then a space or tab,
  then text. Closing hashes are dropped, and a heading with no text is not a
  heading. Lines starting with four or more "#" are body text.
- Sections: each H2 is numbered in order ("2") and runs to the next H2. Each
  H3 after an H2 is numbered under it ("2.1") and runs to the next H2 or H3.
  The top is the body before the first H2; an H3 there belongs to the top.
- Section metadata is an HTML comment that follows an H2 or H3, after blank
  lines only: "<!-- kb-section: key=value; key=value -->". It counts only when
  it is outside a fence and nothing but spaces follows "-->". It may span
  lines. Only SECTION_FIELDS are read, and "sources" is a comma-separated list.
- A field that a section does not set comes from its H2 (for an H3), and then
  from the article's front matter.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SECTION_FIELDS = ("verified", "synced", "ttl", "effective", "status", "supersedes", "sources")
METADATA_OPEN = "<!-- kb-section:"

FrontValue = str | tuple[str, ...]

_RULE = re.compile(r"---[ \t]*")
_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:(.*)")
_ITEM = re.compile(r"[ \t]*-[ \t]+(.*)")
_FENCE = re.compile(r"[ \t]{0,3}(`{3,}|~{3,})(.*)")
_HEADING = re.compile(r"(#{1,6})[ \t]+(.*)")
_CLOSING_HASHES = re.compile(r"(.*[^#\s])[ \t]+#+")
_ESCAPED = re.compile(r'\\(["\\])')


@dataclass(frozen=True)
class Section:
    """An H2 or H3 section: its key ("2" or "2.1"), heading, lines, and own metadata.

    start is the heading's line index, and end is the index after the
    section's last line. parent is the H2 key for an H3, and None for an H2.
    """

    key: str
    level: int
    heading: str
    start: int
    end: int
    parent: str | None
    meta: Mapping[str, str]


@dataclass(frozen=True)
class Document:
    """One parsed Markdown file. Lines exclude their line endings."""

    path: str
    lines: tuple[str, ...]
    front: Mapping[str, FrontValue]
    body_start: int
    top_end: int
    top_headings: tuple[str, ...]
    h1: str | None
    sections: tuple[Section, ...]
    heading_lines: frozenset[int]
    comment_lines: frozenset[int]

    @property
    def title(self) -> str | None:
        """The front matter title, or None when it is absent or empty."""
        value = self.front.get("title")
        return value if isinstance(value, str) and value else None

    def section(self, key: str) -> Section | None:
        """The section with this key, or None."""
        for section in self.sections:
            if section.key == key:
                return section
        return None

    def section_lines(self, section: Section) -> tuple[str, ...]:
        """The section's lines, without leading or trailing blank lines."""
        return _trim(self.lines[section.start : section.end])

    def top_lines(self) -> tuple[str, ...]:
        """The body before the first H2, without leading or trailing blank lines."""
        return _trim(self.lines[self.body_start : self.top_end])

    def prose(self, start: int, end: int) -> tuple[str, ...]:
        """The lines from start to end that are text: no headings and no metadata comments."""
        kept = [
            line
            for index, line in enumerate(self.lines[start:end], start)
            if index not in self.heading_lines and index not in self.comment_lines
        ]
        return _trim(kept)

    def scalar(self, name: str, section: Section | None = None) -> str | None:
        """A scalar field as the section sees it: its own, its H2's, or the article's."""
        inherited = self._inherited(name, section)
        if inherited is not None:
            return inherited
        value = self.front.get(name)
        return value if isinstance(value, str) else None

    def items(self, name: str, section: Section | None = None) -> tuple[str, ...]:
        """A list field as the section sees it. A section's comma-separated value wins."""
        inherited = self._inherited(name, section)
        if inherited is not None:
            return tuple(item.strip() for item in inherited.split(",") if item.strip())
        value = self.front.get(name)
        if isinstance(value, tuple):
            return value
        if isinstance(value, str) and value:
            return (value,)
        return ()

    def _inherited(self, name: str, section: Section | None) -> str | None:
        """The field from the section's metadata, or from its H2 when it is an H3."""
        if section is None:
            return None
        if name in section.meta:
            return section.meta[name]
        if section.parent is None:
            return None
        parent = self.section(section.parent)
        return None if parent is None else parent.meta.get(name)


def parse(path: str, text: str) -> Document:
    """Parse one Markdown file. path is its content-relative path, kept for later rules."""
    lines = _split_lines(text)
    front, body_start = _front_matter(lines)
    inside, headings = _scan(lines, body_start)
    h2_lines = [index for index, level, _ in headings if level == 2]
    top_end = h2_lines[0] if h2_lines else len(lines)
    sections, comment_lines = _sections(lines, inside, headings)
    return Document(
        path=path,
        lines=tuple(lines),
        front=front,
        body_start=body_start,
        top_end=top_end,
        top_headings=tuple(heading for index, _, heading in headings if index < top_end),
        h1=next((heading for _, level, heading in headings if level == 1), None),
        sections=tuple(sections),
        heading_lines=frozenset(index for index, _, _ in headings),
        comment_lines=frozenset(comment_lines),
    )


def _split_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _front_matter(lines: Sequence[str]) -> tuple[dict[str, FrontValue], int]:
    """The front matter fields and the index of the first body line."""
    if not lines or _RULE.fullmatch(lines[0]) is None:
        return {}, 0
    close = next(
        (index for index in range(1, len(lines)) if _RULE.fullmatch(lines[index])),
        None,
    )
    if close is None:
        return {}, 0
    raw: dict[str, str | list[str]] = {}
    open_list: list[str] | None = None
    for line in lines[1:close]:
        item = _ITEM.fullmatch(line)
        if item is not None:
            if open_list is not None:
                open_list.append(_scalar(item.group(1)))
            continue
        pair = _KEY.fullmatch(line)
        if pair is None:
            if line.strip(" \t"):
                open_list = None
            continue
        key, value = pair.group(1), pair.group(2).strip(" \t")
        open_list = None
        if key in raw:
            continue
        if value:
            raw[key] = _scalar(value)
        else:
            open_list = []
            raw[key] = open_list
    front: dict[str, FrontValue] = {}
    for key, found in raw.items():
        if isinstance(found, str):
            front[key] = found
        elif found:
            front[key] = tuple(found)
        else:
            front[key] = ""
    return front, close + 1


def _scalar(text: str) -> str:
    """A front matter value without its surrounding spaces or quotes."""
    value = text.strip(" \t")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _ESCAPED.sub(r"\1", value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _scan(lines: Sequence[str], start: int) -> tuple[list[bool], list[tuple[int, int, str]]]:
    """Which lines are inside a fence, and the headings of levels 1 to 3 outside fences."""
    inside = [False] * len(lines)
    headings: list[tuple[int, int, str]] = []
    marker = ""
    length = 0
    for index in range(start, len(lines)):
        line = lines[index]
        if marker:
            inside[index] = True
            if _closes(line, marker, length):
                marker = ""
            continue
        opened = _opens(line)
        if opened is not None:
            marker, length = opened
            inside[index] = True
            continue
        heading = _heading(line)
        if heading is not None and heading[0] <= 3:
            headings.append((index, heading[0], heading[1]))
    return inside, headings


def _opens(line: str) -> tuple[str, int] | None:
    """The fence character and length when line opens a fence."""
    match = _FENCE.fullmatch(line)
    if match is None:
        return None
    marker, info = match.group(1), match.group(2)
    if marker[0] == "`" and "`" in info:
        return None
    return marker[0], len(marker)


def _closes(line: str, marker: str, length: int) -> bool:
    """True when line closes an open fence of this character and length."""
    match = _FENCE.fullmatch(line)
    if match is None:
        return False
    closing, info = match.group(1), match.group(2)
    return closing[0] == marker and len(closing) >= length and not info.strip(" \t")


def _heading(line: str) -> tuple[int, str] | None:
    """The level and text of a heading line, or None."""
    if not line.startswith("#"):
        return None
    match = _HEADING.fullmatch(line)
    if match is None:
        return None
    level = len(match.group(1))
    text = match.group(2).rstrip(" \t")
    closing = _CLOSING_HASHES.fullmatch(text)
    if closing is not None:
        text = closing.group(1)
    elif not text.strip("#"):
        text = ""
    return (level, text) if text else None


def _sections(
    lines: Sequence[str],
    inside: Sequence[bool],
    headings: Sequence[tuple[int, int, str]],
) -> tuple[list[Section], set[int]]:
    """The H2 and H3 sections, numbered, with their ends and metadata, and the metadata lines."""
    marks = [(index, level) for index, level, _ in headings if level in (2, 3)]
    sections: list[Section] = []
    comment_lines: set[int] = set()
    h2_key: str | None = None
    h2_count = 0
    h3_count = 0
    for index, level, heading in headings:
        if level == 2:
            h2_count += 1
            h3_count = 0
            h2_key = str(h2_count)
            key, parent = h2_key, None
        elif level == 3 and h2_key is not None:
            h3_count += 1
            key, parent = f"{h2_key}.{h3_count}", h2_key
        else:
            continue
        end = next(
            (later for later, later_level in marks if later > index and later_level <= level),
            len(lines),
        )
        fields, span = _metadata(lines, inside, index)
        if span is not None:
            comment_lines.update(range(span[0], span[1] + 1))
        sections.append(
            Section(
                key=key,
                level=level,
                heading=heading,
                start=index,
                end=end,
                parent=parent,
                meta=fields,
            )
        )
    return sections, comment_lines


def _metadata(
    lines: Sequence[str], inside: Sequence[bool], heading: int
) -> tuple[dict[str, str], tuple[int, int] | None]:
    """The metadata that follows the heading at index heading, and the lines it spans."""
    index = heading + 1
    while index < len(lines) and not inside[index] and not lines[index].strip(" \t"):
        index += 1
    if index >= len(lines) or inside[index]:
        return {}, None
    first = lines[index].lstrip(" \t")
    if not first.startswith(METADATA_OPEN):
        return {}, None
    found = _comment_body(lines, index, first[len(METADATA_OPEN) :])
    if found is None:
        return {}, None
    body, last = found
    return _fields(body), (index, last)


def _comment_body(lines: Sequence[str], start: int, first: str) -> tuple[str, int] | None:
    """The text between the opener and "-->", and the line that closes it.

    None when the comment is unclosed, or when text other than spaces follows "-->".
    """
    parts: list[str] = []
    current = first
    index = start
    while True:
        if "-->" in current:
            body, _, after = current.partition("-->")
            if after.strip(" \t"):
                return None
            parts.append(body)
            return " ".join(parts), index
        parts.append(current)
        index += 1
        if index >= len(lines):
            return None
        current = lines[index]


def _fields(body: str) -> dict[str, str]:
    """The known key=value entries of a metadata comment. The first occurrence wins."""
    fields: dict[str, str] = {}
    for entry in body.split(";"):
        key, equals, value = entry.partition("=")
        name = key.strip(" \t")
        if equals and name in SECTION_FIELDS and name not in fields:
            fields[name] = value.strip(" \t")
    return fields


def _trim(lines: Sequence[str]) -> tuple[str, ...]:
    """The lines without leading or trailing blank lines."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip(" \t"):
        start += 1
    while end > start and not lines[end - 1].strip(" \t"):
        end -= 1
    return tuple(lines[start:end])
