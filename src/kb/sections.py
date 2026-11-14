"""Pure, byte-preserving edits to an article's sections and curation metadata.

The writer supplies whole sections as text; these functions decide where the text lands.
A section is an H2 with its H3s, or one H3, as model.parse numbers them. Every function
takes an article's text and returns the edited text and the line span of what it wrote.
Lines outside the edited span keep their bytes, including their line endings.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from kb import model
from kb.model import Document, LineSpan, Section

Placement = Literal["after", "before"]
_SOURCES_ENTRY = re.compile(r"(\bsources[ \t]*=)([^;]*?)([ \t]*(?:;|-->))")
_METADATA_START = re.compile(r"[ \t]*<!--[ \t]*kb-section(?=[: \t]|-->)")


class EditError(ValueError):
    """An edit cannot be applied without guessing."""


@dataclass(frozen=True)
class Edited:
    """The edited text and the zero-based span of the lines the edit wrote."""

    text: str
    written: LineSpan | None


@dataclass(frozen=True)
class Heading:
    """One H2 or H3 in writer text: its line index in the block, level, and text."""

    index: int
    level: int
    text: str


@dataclass(frozen=True)
class Block:
    """Writer-supplied text as trimmed lines without endings, and its H2 and H3 headings."""

    lines: tuple[str, ...]
    headings: tuple[Heading, ...]

    def has_metadata(self, heading: Heading) -> bool:
        """Whether the first nonblank line after the heading opens a metadata comment."""
        for line in self.lines[heading.index + 1 :]:
            if line.strip():
                return _METADATA_START.match(line) is not None
        return False


def parse_block(text: str) -> Block:
    """Parse writer text; refuse text that cannot be placed safely."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = model.split_lines(text)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise EditError("the text on stdin is empty")
    if model.is_rule(lines[0]):
        raise EditError("the text must not start with a front matter delimiter")
    # A leading blank line keeps the parser from reading a "---" pair as front matter.
    document = model.parse("block.md", "\n".join(["", *lines]) + "\n")
    if document.unclosed_fence_start is not None:
        raise EditError("the text has an unclosed code fence")
    headings: list[Heading] = []
    for index in sorted(document.heading_lines):
        parsed = model.heading(document.lines[index])
        assert parsed is not None
        level, heading_text = parsed
        if level == 1:
            raise EditError("the text must not contain an H1")
        if level in (2, 3):
            headings.append(Heading(index - 1, level, heading_text))
    return Block(tuple(lines), tuple(headings))


def _sections_block(text: str) -> Block:
    """A block that is one or more whole sections, starting with an H2 or H3 heading."""
    block = parse_block(text)
    if not block.headings or block.headings[0].index != 0:
        raise EditError("the text must start with an H2 or H3 heading")
    if block.headings[0].level == 3 and any(item.level == 2 for item in block.headings):
        raise EditError("text that starts with an H3 must not contain an H2")
    return block


def section(document: Document, key: str) -> Section:
    """The numbered section, or EditError."""
    found = document.section(key)
    if found is None:
        raise EditError(f"no section {key}")
    return found


def replace(text: str, key: str, replacement: str) -> Edited:
    """Replace a whole section with one or more sections of the same level.

    A replacement section that has no metadata comment keeps the comment of the replaced
    section with the same level and heading, so a rewrite does not drop verified dates.
    """
    document = model.parse("", text)
    target = section(document, key)
    block = _sections_block(replacement)
    if block.headings[0].level != target.level:
        raise EditError(f"section {key} is an H{target.level}; the text must start with one")
    replaced = [item for item in document.sections if target.start <= item.start < target.end]
    lines = _with_kept_metadata(document, replaced, block)
    return _splice(text, document, target.start, target.end, lines)


def append(text: str, key: str, addition: str) -> Edited:
    """Append paragraphs to the end of a section's own text, before any H3 it holds."""
    document = model.parse("", text)
    target = section(document, key)
    block = parse_block(addition)
    if block.headings:
        raise EditError("appended text must not contain H2 or H3 headings; use insert")
    own_end = next(
        (item.start for item in document.sections if item.parent == target.key),
        target.end,
    )
    position = own_end
    while position > target.start + 1 and not document.lines[position - 1].strip():
        position -= 1
    return _splice(text, document, position, position, block.lines)


def insert(text: str, anchor: str, placement: Placement, addition: str) -> Edited:
    """Insert one or more new sections after or before an anchor section, or after top."""
    document = model.parse("", text)
    block = _sections_block(addition)
    position = _position(document, anchor, placement, block.headings[0].level)
    return _splice(text, document, position, position, block.lines)


def move(text: str, key: str, anchor: str, placement: Placement) -> Edited:
    """Move a whole section after or before an anchor section, or after top."""
    document = model.parse("", text)
    target = section(document, key)
    if anchor == key:
        raise EditError("a section cannot be moved relative to itself")
    position = _position(document, anchor, placement, target.level)
    if target.start < position < target.end:
        raise EditError("a section cannot be moved inside itself")
    lines = _trim(document.lines[target.start : target.end])
    removed = _splice(text, document, target.start, target.end, ())
    if position >= target.end:
        position -= target.end - target.start
    return _splice(removed.text, model.parse("", removed.text), position, position, lines)


def remove(text: str, key: str) -> Edited:
    """Delete a whole section."""
    document = model.parse("", text)
    target = section(document, key)
    return _splice(text, document, target.start, target.end, ())


def add_front_source(text: str, value: str) -> str:
    """Add value to the front matter sources block list, newest first.

    An existing citation of the same file, whole or by fragment, leaves the text unchanged.
    """
    document = model.parse("", text)
    if not document.front_matter_opened or not document.front_matter_closed:
        raise EditError("front matter is missing or unclosed")
    fields = [field for field in document.front_fields if field.name == "sources"]
    if len(fields) > 1:
        raise EditError("front matter field is duplicated: sources")
    raw = model.split_raw_lines(text)
    ending = _ending(raw)
    if not fields:
        span = document.front_matter_span
        assert span is not None
        raw[span.end - 1 : span.end - 1] = [f"sources:{ending}", f"  - {value}{ending}"]
    else:
        field = fields[0]
        if not field.block:
            raise EditError("front matter sources is not a block list")
        if _cites(document.items("sources"), value):
            return text
        prefix = "  - "
        if field.item_line_indices:
            item = document.lines[field.item_line_indices[0]]
            prefix = item[: len(item) - len(item.lstrip(" \t-"))]
        raw.insert(field.span.start + 1, f"{prefix}{value}{ending}")
    result = "".join(raw)
    if value not in model.parse("", result).items("sources"):
        raise EditError("the added source did not round-trip")
    return result


def section_source_owner(document: Document, key: str) -> Section | None:
    """The section whose metadata comment supplies sources for key, or None for the article."""
    target = document.section(key)
    if target is None:
        return None
    if "sources" in target.meta:
        return target
    parent = None if target.parent is None else document.section(target.parent)
    if parent is not None and "sources" in parent.meta:
        return parent
    return None


def add_section_source(text: str, key: str, value: str) -> str:
    """Add value to the sources of the metadata comment that supplies them for key."""
    document = model.parse("", text)
    owner = section_source_owner(document, key)
    if owner is None or owner.metadata_comment is None:
        raise EditError(f"section {key} has no section-level sources")
    if _cites(document.items("sources", owner), value):
        return text
    comment = owner.metadata_comment
    if comment.span.end - comment.span.start != 1:
        raise EditError(f"section {owner.key} has a multi-line metadata comment")
    raw = model.split_raw_lines(text)
    line = raw[comment.span.start]
    match = _SOURCES_ENTRY.search(line)
    if match is None:
        raise EditError(f"section {owner.key} has a sources entry that cannot be edited")
    current = match.group(2).rstrip(" \t")
    joined = f"{current}, {value}" if current.strip() else value
    raw[comment.span.start] = line[: match.start(2)] + joined + line[match.end(2) :]
    result = "".join(raw)
    edited = model.parse("", result)
    if value not in edited.items("sources", edited.section(owner.key)):
        raise EditError("the added source did not round-trip")
    return result


def set_ttl(text: str, value: str) -> str:
    """Set the front matter ttl, inserting it after verified, without changing verified."""
    document = model.parse("", text)
    after = "verified" if any(field.name == "verified" for field in document.front_fields) else None
    try:
        return model.edit_front_matter(text, "ttl", value, after=after)
    except model.FrontMatterEditError as error:
        raise EditError(str(error)) from error


def _cites(items: Sequence[str], value: str) -> bool:
    """Whether items already cite the file value names, wholly or by a fragment."""
    return any(item == value or item.startswith(f"{value}#") for item in items)


def _position(document: Document, anchor: str, placement: Placement, level: int) -> int:
    """The line index where a section of this level goes relative to the anchor."""
    if anchor == "top":
        if placement != "after" or level != 2:
            raise EditError("only an H2 can go --after top")
        return document.top_end
    target = section(document, anchor)
    if level == 2 and target.level != 2:
        raise EditError("an H2 must be placed relative to an H2")
    if level == 3 and target.level == 2 and placement == "before":
        raise EditError("an H3 goes --after an H2, as its last H3, or relative to an H3")
    return target.end if placement == "after" else target.start


def _with_kept_metadata(document: Document, replaced: Sequence[Section], block: Block) -> list[str]:
    """Block lines, with replaced sections' metadata comments restored where omitted."""
    kept: dict[tuple[int, str], tuple[str, ...]] = {}
    for item in replaced:
        comment = item.metadata_comment
        if comment is not None and comment.section_key == item.key:
            kept.setdefault(
                (item.level, item.heading),
                document.lines[comment.span.start : comment.span.end],
            )
    lines = list(block.lines)
    # Insert from the bottom so the indices of earlier headings stay valid.
    for heading in reversed(block.headings):
        comment_lines = kept.get((heading.level, heading.text))
        if comment_lines is None or block.has_metadata(heading):
            continue
        lines[heading.index + 1 : heading.index + 1] = ["", *comment_lines]
    return lines


def _splice(text: str, document: Document, start: int, end: int, lines: Sequence[str]) -> Edited:
    """Replace lines start:end with lines, keeping one blank line around the new text."""
    raw = model.split_raw_lines(text)
    ending = _ending(raw)
    if raw and not raw[-1].endswith(("\n", "\r")):
        raw[-1] += ending
    new = list(_trim(lines))
    before = raw[:start]
    after = raw[end:]
    if not new and not after:
        while len(before) > document.body_start and not before[-1].strip():
            before.pop()
    lead = bool(new and before and before[-1].strip() and start > document.body_start)
    trail = bool(new and after and after[0].strip())
    middle = [f"{line}{ending}" for line in ([""] if lead else []) + new + ([""] if trail else [])]
    written_start = len(before) + (1 if lead else 0)
    span = LineSpan(written_start, written_start + len(new)) if new else None
    return Edited("".join(before + middle + after), span)


def _trim(lines: Sequence[str]) -> tuple[str, ...]:
    """Lines without leading or trailing blank lines."""
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return tuple(lines[start:end])


def _ending(raw: Sequence[str]) -> str:
    """The article's line ending, read from its first line that has one."""
    for line in raw:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"
