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
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_ITEM = re.compile(r"[ \t]*-[ \t]+(.*)")
_FENCE = re.compile(r"[ \t]{0,3}(`{3,}|~{3,})(.*)")
_HEADING = re.compile(r"(#{1,6})[ \t]+(.*)")
_CLOSING_HASHES = re.compile(r"(.*[^#\s])[ \t]+#+")
_ESCAPED = re.compile(r'\\(["\\])')
_METADATA_START = re.compile(r"[ \t]*<!--[ \t]*kb-section(?=[: \t]|-->)")


@dataclass(frozen=True)
class LineSpan:
    """A zero-based, half-open range of lines."""

    start: int
    end: int


class FrontMatterEditError(ValueError):
    """A front-matter edit cannot be applied without guessing."""


@dataclass(frozen=True)
class FrontMatterField:
    """One front matter field occurrence, including duplicate and block-list spans."""

    name: str
    span: LineSpan
    value: FrontValue
    block: bool
    item_line_indices: tuple[int, ...]


@dataclass(frozen=True)
class MetadataEntry:
    """A key=value pair from a section metadata comment."""

    name: str
    value: str
    line_index: int


@dataclass(frozen=True)
class MetadataDiagnostic:
    """A syntax or placement problem in section metadata."""

    line_index: int
    message: str


@dataclass(frozen=True)
class MetadataComment:
    """A raw section metadata comment and the information parsed from it."""

    span: LineSpan
    raw: str
    section_key: str | None
    fields: Mapping[str, str]
    entries: tuple[MetadataEntry, ...]
    diagnostics: tuple[MetadataDiagnostic, ...]
    valid_opener: bool
    closed: bool
    trailing_text: bool


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
    metadata_comment: MetadataComment | None


@dataclass(frozen=True)
class Document:
    """One parsed Markdown file. Lines exclude their line endings."""

    path: str
    lines: tuple[str, ...]
    front: Mapping[str, FrontValue]
    front_fields: tuple[FrontMatterField, ...]
    front_matter_span: LineSpan | None
    front_matter_opened: bool
    front_matter_closed: bool
    body_start: int
    top_end: int
    top_headings: tuple[str, ...]
    h1: str | None
    h1_positions: tuple[int, ...]
    fenced_lines: frozenset[int]
    unclosed_fence_start: int | None
    sections: tuple[Section, ...]
    metadata_comments: tuple[MetadataComment, ...]
    metadata_diagnostics: tuple[MetadataDiagnostic, ...]
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
    front, body_start, front_fields, front_matter_span, opened, closed = _front_matter(lines)
    inside, headings, h1_positions, unclosed_fence_start = _scan(lines, body_start)
    metadata_comments, metadata_diagnostics = _metadata_comments(
        lines, inside, headings, body_start
    )
    h2_lines = [index for index, level, _ in headings if level == 2]
    top_end = h2_lines[0] if h2_lines else len(lines)
    sections, comment_lines = _sections(lines, headings, metadata_comments)
    return Document(
        path=path,
        lines=tuple(lines),
        front=front,
        front_fields=front_fields,
        front_matter_span=front_matter_span,
        front_matter_opened=opened,
        front_matter_closed=closed,
        body_start=body_start,
        top_end=top_end,
        top_headings=tuple(heading for index, _, heading in headings if index < top_end),
        h1=next((heading for _, level, heading in headings if level == 1), None),
        h1_positions=h1_positions,
        fenced_lines=frozenset(index for index, is_fenced in enumerate(inside) if is_fenced),
        unclosed_fence_start=unclosed_fence_start,
        sections=tuple(sections),
        metadata_comments=metadata_comments,
        metadata_diagnostics=metadata_diagnostics,
        heading_lines=frozenset(index for index, _, _ in headings),
        comment_lines=frozenset(comment_lines),
    )


def edit_front_matter(
    text: str,
    name: str,
    value: str,
    after: str | None = None,
) -> str:
    """Replace one scalar field or insert it after a field or before the closing delimiter.

    The field and insertion anchor must each be unique scalar fields. The new value is a
    single-line string; only its field line is replaced, and insertions use the surrounding
    line ending.
    """
    if _FIELD_NAME.fullmatch(name) is None:
        raise FrontMatterEditError(f"invalid field name: {name}")
    if "\n" in value or "\r" in value:
        raise FrontMatterEditError("front matter value must be a single line")

    document = parse("", text)
    if not document.front_matter_opened:
        raise FrontMatterEditError("front matter is missing")
    if not document.front_matter_closed:
        raise FrontMatterEditError("front matter is unclosed")

    matches = [field for field in document.front_fields if field.name == name]
    if len(matches) > 1:
        raise FrontMatterEditError(f"front matter field is duplicated: {name}")
    raw_lines = _split_raw_lines(text)
    if matches:
        field = matches[0]
        if field.block:
            raise FrontMatterEditError(f"front matter field is a block list: {name}")
        line_ending = _line_ending(raw_lines[field.span.start])
        raw_lines[field.span.start] = f"{name}: {_scalar_source(value)}{line_ending}"
        result = "".join(raw_lines)
        if parse("", result).scalar(name) != value:
            raise FrontMatterEditError(f"edited value did not round-trip: {name}")
        return result

    span = document.front_matter_span
    if span is None:
        raise FrontMatterEditError("front matter is missing")
    if after is None:
        insert_at = span.end - 1
    else:
        if _FIELD_NAME.fullmatch(after) is None:
            raise FrontMatterEditError(f"invalid insertion anchor: {after}")
        anchors = [field for field in document.front_fields if field.name == after]
        if not anchors:
            raise FrontMatterEditError(f"insertion anchor is missing: {after}")
        if len(anchors) > 1:
            raise FrontMatterEditError(f"insertion anchor is duplicated: {after}")
        anchor = anchors[0]
        if anchor.block:
            raise FrontMatterEditError(f"insertion anchor is a block list: {after}")
        insert_at = anchor.span.end

    line_ending = _line_ending(raw_lines[insert_at - 1]) if insert_at else ""
    if not line_ending and insert_at < len(raw_lines):
        line_ending = _line_ending(raw_lines[insert_at])
    if not line_ending:
        line_ending = "\n"
    raw_lines.insert(insert_at, f"{name}: {_scalar_source(value)}{line_ending}")
    result = "".join(raw_lines)
    if parse("", result).scalar(name) != value:
        raise FrontMatterEditError(f"edited value did not round-trip: {name}")
    return result


def _split_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _split_raw_lines(text: str) -> list[str]:
    """Split on the parser's newline boundary while preserving every character."""
    lines = text.split("\n")
    return [f"{line}\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])


def _line_ending(line: str) -> str:
    """The line ending on one original line, if any."""
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _scalar_source(value: str) -> str:
    """Write a single-line scalar without changing its parsed value."""
    if (
        not value
        or value != value.strip(" \t")
        or (len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'")
    ):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _front_matter(
    lines: Sequence[str],
) -> tuple[dict[str, FrontValue], int, tuple[FrontMatterField, ...], LineSpan | None, bool, bool]:
    """The front matter values, field spans, and body start."""
    if not lines or _RULE.fullmatch(lines[0]) is None:
        return {}, 0, (), None, False, False
    close = next(
        (index for index in range(1, len(lines)) if _RULE.fullmatch(lines[index])),
        None,
    )
    if close is None:
        return {}, 0, (), LineSpan(0, len(lines)), True, False
    raw: dict[str, str | list[str]] = {}
    names: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    values: list[str | list[str]] = []
    blocks: list[bool] = []
    item_line_indices: list[list[int]] = []
    open_field_index: int | None = None
    for line_index in range(1, close):
        line = lines[line_index]
        item = _ITEM.fullmatch(line)
        if item is not None:
            if open_field_index is not None:
                ends[open_field_index] = line_index + 1
                current_items = values[open_field_index]
                if isinstance(current_items, list):
                    current_items.append(_scalar(item.group(1)))
                    item_line_indices[open_field_index].append(line_index)
            continue
        pair = _KEY.fullmatch(line)
        if pair is None:
            if line.strip(" \t"):
                open_field_index = None
            continue
        key, value = pair.group(1), pair.group(2).strip(" \t")
        open_field_index = None
        names.append(key)
        starts.append(line_index)
        ends.append(line_index + 1)
        blocks.append(not value)
        item_line_indices.append([])
        if value:
            scalar = _scalar(value)
            values.append(scalar)
            if key not in raw:
                raw[key] = scalar
        else:
            new_items: list[str] = []
            values.append(new_items)
            open_field_index = len(names) - 1
            if key not in raw:
                raw[key] = new_items
    front: dict[str, FrontValue] = {}
    for key, found in raw.items():
        if isinstance(found, str):
            front[key] = found
        elif found:
            front[key] = tuple(found)
        else:
            front[key] = ""
    fields = tuple(
        FrontMatterField(
            name=name,
            span=LineSpan(start, end),
            value=tuple(value)
            if isinstance(value, list) and value
            else ("" if isinstance(value, list) else value),
            block=block,
            item_line_indices=tuple(item_line_indices[index]),
        )
        for index, (name, start, end, value, block) in enumerate(
            zip(names, starts, ends, values, blocks, strict=True)
        )
    )
    return front, close + 1, fields, LineSpan(0, close + 1), True, True


def _scalar(text: str) -> str:
    """A front matter value without its surrounding spaces or quotes."""
    value = text.strip(" \t")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _ESCAPED.sub(r"\1", value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _scan(
    lines: Sequence[str], start: int
) -> tuple[list[bool], list[tuple[int, int, str]], tuple[int, ...], int | None]:
    """Find fenced lines, headings, H1 positions, and any unclosed fence start."""
    inside = [False] * len(lines)
    headings: list[tuple[int, int, str]] = []
    h1_positions: list[int] = []
    marker = ""
    length = 0
    unclosed_fence_start: int | None = None
    for index in range(start, len(lines)):
        line = lines[index]
        if marker:
            inside[index] = True
            if _closes(line, marker, length):
                marker = ""
                unclosed_fence_start = None
            continue
        opened = _opens(line)
        if opened is not None:
            marker, length = opened
            inside[index] = True
            unclosed_fence_start = index
            continue
        heading = _heading(line)
        if heading is not None and heading[0] <= 3:
            headings.append((index, heading[0], heading[1]))
            if heading[0] == 1:
                h1_positions.append(index)
    return inside, headings, tuple(h1_positions), unclosed_fence_start


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
    headings: Sequence[tuple[int, int, str]],
    metadata_comments: Sequence[MetadataComment],
) -> tuple[list[Section], set[int]]:
    """Build numbered H2/H3 sections and retain metadata the reader understands."""
    locations = _section_locations(headings)
    marks = [(index, level) for index, (_, level, _) in locations.items()]
    comments_by_section = {
        comment.section_key: comment
        for comment in metadata_comments
        if comment.section_key is not None
    }
    sections: list[Section] = []
    comment_lines: set[int] = set()
    for line_index, level, heading in headings:
        location = locations.get(line_index)
        if location is None:
            continue
        key, _, parent = location
        end = next(
            (later for later, later_level in marks if later > line_index and later_level <= level),
            len(lines),
        )
        comment = comments_by_section.get(key)
        can_read_metadata = (
            comment is not None
            and comment.valid_opener
            and comment.closed
            and not comment.trailing_text
        )
        if can_read_metadata and comment is not None:
            comment_lines.update(range(comment.span.start, comment.span.end))
        sections.append(
            Section(
                key=key,
                level=level,
                heading=heading,
                start=line_index,
                end=end,
                parent=parent,
                meta=comment.fields if can_read_metadata and comment is not None else {},
                metadata_comment=comment,
            )
        )
    return sections, comment_lines


def _fields(body: str) -> dict[str, str]:
    """The known key=value entries of a metadata comment. The first occurrence wins."""
    fields: dict[str, str] = {}
    for entry in body.split(";"):
        key, equals, value = entry.partition("=")
        name = key.strip(" \t")
        if equals and name in SECTION_FIELDS and name not in fields:
            fields[name] = value.strip(" \t")
    return fields


def _section_locations(
    headings: Sequence[tuple[int, int, str]],
) -> dict[int, tuple[str, int, str | None]]:
    """The section key, level, and parent at each H2 or H3 heading line."""
    locations: dict[int, tuple[str, int, str | None]] = {}
    parent_key: str | None = None
    h2_count = 0
    h3_count = 0
    for line_index, level, _ in headings:
        if level == 2:
            h2_count += 1
            h3_count = 0
            parent_key = str(h2_count)
            locations[line_index] = (parent_key, level, None)
        elif level == 3 and parent_key is not None:
            h3_count += 1
            key = f"{parent_key}.{h3_count}"
            locations[line_index] = (key, level, parent_key)
    return locations


def _metadata_comments(
    lines: Sequence[str],
    inside: Sequence[bool],
    headings: Sequence[tuple[int, int, str]],
    body_start: int,
) -> tuple[tuple[MetadataComment, ...], tuple[MetadataDiagnostic, ...]]:
    """Find section metadata comments, including malformed and misplaced comments."""
    section_locations = _section_locations(headings)
    section_lines = set(section_locations)
    comments: list[MetadataComment] = []
    diagnostics: list[MetadataDiagnostic] = []
    line_index = body_start
    while line_index < len(lines):
        if inside[line_index] or _METADATA_START.match(lines[line_index]) is None:
            line_index += 1
            continue

        comment, last_line = _read_metadata_comment(
            lines, line_index, section_locations, section_lines
        )
        comments.append(comment)
        diagnostics.extend(comment.diagnostics)
        line_index = last_line + 1
    return tuple(comments), tuple(diagnostics)


def _read_metadata_comment(
    lines: Sequence[str],
    start: int,
    section_locations: Mapping[int, tuple[str, int, str | None]],
    section_lines: set[int],
) -> tuple[MetadataComment, int]:
    """Read one comment candidate, determine placement, and parse its fields."""
    first = lines[start].lstrip(" \t")
    valid_opener = first.startswith(METADATA_OPEN)
    if valid_opener:
        current = first[len(METADATA_OPEN) :]
    else:
        current = first.split("kb-section", 1)[1].lstrip(" \t:")

    parts: list[tuple[str, int]] = []
    closed = False
    trailing_text = False
    current_line = start
    last_line = start
    while True:
        if "-->" in current:
            body_part, _, after = current.partition("-->")
            parts.append((body_part, current_line))
            trailing_text = bool(after.strip(" \t"))
            closed = True
            last_line = current_line
            break
        parts.append((current, current_line))
        current_line += 1
        if current_line >= len(lines):
            last_line = len(lines) - 1
            break
        current = lines[current_line]
        last_line = current_line

    previous_line = start - 1
    while previous_line >= 0 and not lines[previous_line].strip(" \t"):
        previous_line -= 1
    location = section_locations.get(previous_line)
    section_key = location[0] if location is not None else None
    fields, entries, field_diagnostics, _ = _metadata_fields(parts)
    comment_diagnostics: list[MetadataDiagnostic] = []
    if not valid_opener:
        comment_diagnostics.append(
            MetadataDiagnostic(start, "malformed section metadata comment opener")
        )
    if not closed:
        comment_diagnostics.append(
            MetadataDiagnostic(start, "section metadata comment is unclosed")
        )
    elif trailing_text:
        comment_diagnostics.append(MetadataDiagnostic(start, "section metadata has trailing text"))
    if section_key is None:
        earlier_sections = any(section_line < start for section_line in section_lines)
        message = (
            "section metadata appears after section content"
            if earlier_sections
            else "section metadata appears before the first section"
        )
        comment_diagnostics.append(MetadataDiagnostic(start, message))
    comment_diagnostics.extend(field_diagnostics)

    comment = MetadataComment(
        span=LineSpan(start, last_line + 1),
        raw="\n".join(lines[start : last_line + 1]),
        section_key=section_key,
        fields=fields,
        entries=entries,
        diagnostics=tuple(comment_diagnostics),
        valid_opener=valid_opener,
        closed=closed,
        trailing_text=trailing_text,
    )
    return comment, last_line


def _metadata_fields(
    parts: Sequence[tuple[str, int]],
) -> tuple[dict[str, str], tuple[MetadataEntry, ...], tuple[MetadataDiagnostic, ...], str]:
    """Parse known fields and retain syntax findings for every comment entry."""
    body_parts: list[str] = []
    line_by_character: list[int] = []
    for part, line_index in parts:
        body_parts.append(part)
        line_by_character.extend([line_index] * len(part))
        body_parts.append(" ")
        line_by_character.append(line_index)
    body = "".join(body_parts)
    fields = _fields(body)
    entries: list[MetadataEntry] = []
    diagnostics: list[MetadataDiagnostic] = []
    seen_fields: dict[str, str] = {}
    offset = 0
    for raw_entry in body.split(";"):
        entry_start = offset
        offset += len(raw_entry) + 1
        value_text = raw_entry.strip(" \t")
        if not value_text:
            continue
        leading_space = len(raw_entry) - len(raw_entry.lstrip(" \t"))
        character_index = entry_start + leading_space
        line_index = (
            line_by_character[character_index]
            if character_index < len(line_by_character)
            else (parts[0][1] if parts else 0)
        )
        name, equals, value = value_text.partition("=")
        name = name.strip(" \t")
        value = value.strip(" \t")
        if not equals or not name:
            diagnostics.append(MetadataDiagnostic(line_index, f"malformed field '{value_text}'"))
            continue
        entries.append(MetadataEntry(name, value, line_index))
        if name not in SECTION_FIELDS:
            diagnostics.append(MetadataDiagnostic(line_index, f"unknown field '{name}'"))
            continue
        canonical_name = "verified" if name in {"verified", "synced"} else name
        if canonical_name in seen_fields and seen_fields[canonical_name] != value:
            diagnostics.append(
                MetadataDiagnostic(
                    line_index,
                    f"conflicting values for field '{canonical_name}'",
                )
            )
        else:
            seen_fields[canonical_name] = value
    if not body.strip(" \t"):
        line_index = parts[0][1] if parts else 0
        diagnostics.append(MetadataDiagnostic(line_index, "section metadata comment is empty"))
    return fields, tuple(entries), tuple(diagnostics), body


def _trim(lines: Sequence[str]) -> tuple[str, ...]:
    """The lines without leading or trailing blank lines."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip(" \t"):
        start += 1
    while end > start and not lines[end - 1].strip(" \t"):
        end -= 1
    return tuple(lines[start:end])
