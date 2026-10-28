"""Article structure, metadata, and local reference checks."""

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal

from kb import corpus, locators
from kb.dates import parse_date
from kb.freshness import MAX_TTL_DAYS, NAMED_TTL_DAYS
from kb.model import Document, Section

MAX_H2_LINES = 50
_SECTION_LOCATOR = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]*)\)")
_EXTERNAL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_INLINE_CODE = re.compile(r"`+[^`]*`+")
_NON_SLUG = re.compile(r"[^A-Za-z0-9 _-]")
_WHITESPACE = re.compile(r"[ \t\f\v]+")
_HYPHENS = re.compile(r"-+")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_VALID_SECTION_STATUSES = {"current", "superseded", "unresolved"}


@dataclass(frozen=True)
class Finding:
    """One lint error or warning at a one-based source line."""

    path: str
    line: int
    severity: str
    message: str


@dataclass(frozen=True)
class Reference:
    """One local Markdown link or source reference at a one-based source line."""

    source_path: str
    line: int
    kind: Literal["link", "source"]
    destination: str


def references(document: Document) -> list[Reference]:
    """Return Markdown links and source entries read from one parsed document."""
    found = _front_matter_sources(document)
    metadata_lines = {
        line_index
        for comment in document.metadata_comments
        for line_index in range(comment.span.start, comment.span.end)
    }
    for section in document.sections:
        comment = section.metadata_comment
        if "sources" not in section.meta or comment is None:
            continue
        entry = next((entry for entry in comment.entries if entry.name == "sources"), None)
        if entry is not None:
            found.extend(_source_values(document.path, entry.value, entry.line_index + 1))

    for line_index, line in enumerate(document.lines):
        if (
            line_index < document.body_start
            or line_index in document.fenced_lines
            or line_index in metadata_lines
        ):
            continue
        text = _INLINE_CODE.sub("", line)
        for match in _MARKDOWN_LINK.finditer(text):
            destination = _link_destination(match.group(1))
            if destination:
                found.append(Reference(document.path, line_index + 1, "link", destination))
    return sorted(found, key=lambda reference: reference.line)


def fragment_resolves(document: Document, fragment: str) -> bool:
    """Whether a fragment selects text or names an H2/H3 heading in the document."""
    if fragment in {"title", "top"} and locators.select(document, fragment) is not None:
        return True
    if locators.NUMBERED.fullmatch(fragment):
        normalized = ".".join(part.lstrip("0") or "0" for part in fragment.split("."))
        if locators.select(document, normalized) is not None:
            return True
    slug = _heading_slug(fragment)
    return any(
        section.level in (2, 3)
        and (section.heading == fragment or (slug and _heading_slug(section.heading) == slug))
        for section in document.sections
    )


def reference_findings(
    root: Path,
    source: Document,
    documents: dict[str, Document],
) -> list[Finding]:
    """Check one document's local links and sources, caching each Markdown target."""
    findings: list[Finding] = []
    for reference in references(source):
        path, has_fragment, fragment = reference.destination.partition("#")
        if _external_or_absolute(reference.destination, path):
            continue

        source_file = root / source.path
        if reference.kind == "link":
            target = (source_file.parent / path).resolve() if path else source_file.resolve()
        else:
            target = (root / path).resolve()

        try:
            relpath = target.relative_to(root).as_posix()
        except ValueError:
            message = (
                f"local Markdown link escapes content root: {reference.destination}"
                if reference.kind == "link"
                else f"local source reference escapes content root: {reference.destination}"
            )
            findings.append(Finding(reference.source_path, reference.line, "error", message))
            continue

        if not target.is_file():
            message = (
                f"missing local Markdown link target: {reference.destination}"
                if reference.kind == "link"
                else f"missing local source reference: {reference.destination}"
            )
            findings.append(Finding(reference.source_path, reference.line, "error", message))
            continue
        if not has_fragment or not fragment or target.suffix != ".md":
            continue

        target_document = documents.get(relpath)
        if target_document is None:
            target_document = corpus.read_document(root, relpath)
            documents[relpath] = target_document
        if not fragment_resolves(target_document, fragment):
            message = (
                f"missing local Markdown link anchor '#{fragment}': {reference.destination}"
                if reference.kind == "link"
                else f"missing source reference anchor '#{fragment}': {reference.destination}"
            )
            findings.append(Finding(reference.source_path, reference.line, "error", message))
    return findings


def check_document(document: Document, require_ttl: bool = False) -> list[Finding]:
    """Return structural and metadata findings for one parsed article."""
    findings: list[Finding] = []
    _check_front_matter(document, require_ttl, findings)
    _check_headings(document, findings)
    _check_section_metadata(document, findings)
    return sorted(findings, key=_finding_order)


def _check_front_matter(document: Document, require_ttl: bool, findings: list[Finding]) -> None:
    for name in ("title", "updated", "verified"):
        value = document.front.get(name)
        line = _front_field_line(document, name) or 1
        if not isinstance(value, str) or not value:
            _add(findings, document, line, "error", f"front matter missing {name}")
        elif name != "title" and parse_date(value) is None:
            _add(findings, document, line, "error", f"{name} is not a YYYY-MM-DD date")

    ttl_value = document.front.get("ttl")
    if "ttl" not in document.front:
        if require_ttl:
            _add(findings, document, 1, "error", "front matter missing ttl")
    elif not valid_ttl(ttl_value):
        line = _front_field_line(document, "ttl") or 1
        _add(
            findings,
            document,
            line,
            "error",
            "ttl is not a named TTL or positive integer within the limit",
        )


def _check_headings(document: Document, findings: list[Finding]) -> None:
    if not document.h1_positions:
        _add(findings, document, 1, "error", "no H1")
    else:
        for line_index in document.h1_positions[1:]:
            _add(
                findings,
                document,
                line_index + 1,
                "error",
                "second H1 (one article, one H1)",
            )

    if document.unclosed_fence_start is not None:
        _add(
            findings,
            document,
            document.unclosed_fence_start + 1,
            "error",
            "unclosed code fence",
        )

    seen_headings: set[str] = set()
    for section in document.sections:
        if section.level != 2:
            continue
        line_count = section.end - section.start
        if line_count > MAX_H2_LINES:
            _add(
                findings,
                document,
                section.start + 1,
                "warning",
                f"H2 is {line_count} lines (max {MAX_H2_LINES}): {section.heading}",
            )
        if section.heading in seen_headings:
            _add(
                findings,
                document,
                section.start + 1,
                "warning",
                f"duplicate H2 text: {section.heading}",
            )
        seen_headings.add(section.heading)


def _check_section_metadata(document: Document, findings: list[Finding]) -> None:
    for diagnostic in document.metadata_diagnostics:
        _add(findings, document, diagnostic.line_index + 1, "error", diagnostic.message)

    supersedes_edges: dict[str, tuple[str, int]] = {}
    section_keys = {section.key for section in document.sections}
    for section in document.sections:
        _check_section_values(document, section, findings)
        _check_effective_date(document, section, findings)
        _check_supersedes(document, section, section_keys, supersedes_edges, findings)
    _check_supersedes_cycles(document, supersedes_edges, findings)


def _check_section_values(document: Document, section: Section, findings: list[Finding]) -> None:
    for name in ("verified", "synced", "effective"):
        value = section.meta.get(name)
        if value is not None and parse_date(value) is None:
            line = _section_field_line(section, name)
            label = "verified" if name == "synced" else name
            _add(findings, document, line, "error", f"invalid section {label} date")

    ttl_value = section.meta.get("ttl")
    if ttl_value is not None and not valid_ttl(ttl_value):
        _add(
            findings, document, _section_field_line(section, "ttl"), "error", "invalid section ttl"
        )

    status = section.meta.get("status")
    if status is not None and status not in _VALID_SECTION_STATUSES:
        _add(
            findings,
            document,
            _section_field_line(section, "status"),
            "error",
            "invalid section status",
        )


def _check_effective_date(document: Document, section: Section, findings: list[Finding]) -> None:
    effective, effective_line = _inherited_value(document, section, "effective")
    verified, _ = _inherited_verified(document, section)
    effective_date = parse_date(effective or "")
    verified_date = parse_date(verified or "")
    if effective_date is None or verified_date is None or effective_date <= verified_date:
        return
    _add(
        findings,
        document,
        effective_line,
        "error",
        f"effective date {effective} is after verified date {verified}",
    )


def _check_supersedes(
    document: Document,
    section: Section,
    section_keys: set[str],
    edges: dict[str, tuple[str, int]],
    findings: list[Finding],
) -> None:
    target = section.meta.get("supersedes")
    if target is None:
        return
    line = _section_field_line(section, "supersedes")
    status, _ = _inherited_value(document, section, "status")
    if status == "superseded":
        _add(
            findings,
            document,
            line,
            "error",
            "superseded section must not declare supersedes",
        )
    if _SECTION_LOCATOR.fullmatch(target) is None:
        _add(findings, document, line, "error", f"invalid supersedes locator: {target}")
        return
    if target not in section_keys:
        _add(findings, document, line, "error", f"supersedes section does not exist: {target}")
        return
    if target == section.key:
        _add(
            findings,
            document,
            line,
            "error",
            f"section cannot supersede itself: {section.key}",
        )
        return
    edges[section.key] = (target, line)


def _check_supersedes_cycles(
    document: Document,
    edges: dict[str, tuple[str, int]],
    findings: list[Finding],
) -> None:
    reported_cycles: set[frozenset[str]] = set()
    for start in sorted(edges):
        path: list[str] = []
        seen: dict[str, int] = {}
        current = start
        while current in edges:
            if current in seen:
                cycle = frozenset(path[seen[current] :])
                if cycle not in reported_cycles:
                    reported_cycles.add(cycle)
                    line = edges[current][1]
                    _add(
                        findings,
                        document,
                        line,
                        "error",
                        "supersedes relationship contains a cycle",
                    )
                break
            seen[current] = len(path)
            path.append(current)
            current = edges[current][0]


def _inherited_verified(document: Document, section: Section) -> tuple[str | None, int]:
    """The section's verified date, including the legacy `synced` alias."""
    current: Section | None = section
    while current is not None:
        if "verified" in current.meta:
            return current.meta["verified"], _section_field_line(current, "verified")
        if "synced" in current.meta:
            return current.meta["synced"], _section_field_line(current, "synced")
        current = document.section(current.parent) if current.parent is not None else None
    front_value = document.front.get("verified")
    value = front_value if isinstance(front_value, str) else None
    return value, _front_field_line(document, "verified") or 1


def _inherited_value(document: Document, section: Section, name: str) -> tuple[str | None, int]:
    """The first section or article value and its source line."""
    current: Section | None = section
    while current is not None:
        if name in current.meta:
            return current.meta[name], _section_field_line(current, name)
        current = document.section(current.parent) if current.parent is not None else None
    front_value = document.front.get(name)
    value = front_value if isinstance(front_value, str) else None
    return value, _front_field_line(document, name) or 1


def _front_field_line(document: Document, name: str) -> int | None:
    """The one-based line of the first front matter occurrence named name."""
    field = next((field for field in document.front_fields if field.name == name), None)
    return None if field is None else field.span.start + 1


def _front_matter_sources(document: Document) -> list[Reference]:
    """Return sources from the first front-matter field occurrence."""
    field = next((field for field in document.front_fields if field.name == "sources"), None)
    if field is None:
        return []
    if isinstance(field.value, tuple):
        return [
            Reference(document.path, line_index + 1, "source", value)
            for value, line_index in zip(field.value, field.item_line_indices, strict=True)
            if value
        ]
    if field.value:
        return [Reference(document.path, field.span.start + 1, "source", field.value)]
    return []


def _source_values(path: str, value: str, line: int) -> list[Reference]:
    """Split a comma-separated section source field into reference entries."""
    return [
        Reference(path, line, "source", item.strip()) for item in value.split(",") if item.strip()
    ]


def _link_destination(raw: str) -> str:
    """Remove Markdown angle brackets or an optional link title."""
    destination = raw.strip()
    if destination.startswith("<"):
        closing = destination.find(">")
        if closing >= 0:
            return destination[1:closing]
    return destination.split(maxsplit=1)[0] if destination else ""


def _external_or_absolute(destination: str, path: str) -> bool:
    """Whether a target is a URL or an absolute path, both outside local linting."""
    return (
        destination.startswith("//")
        or _EXTERNAL_SCHEME.match(destination) is not None
        or path.startswith("/")
        or PureWindowsPath(path).is_absolute()
    )


def _heading_slug(heading: str) -> str:
    """The ASCII GitHub-style slug accepted by the old lint script."""
    slug = _NON_SLUG.sub("", heading.translate(_ASCII_LOWER))
    slug = _WHITESPACE.sub("-", slug)
    return _HYPHENS.sub("-", slug).strip("-")


def _section_field_line(section: Section, name: str) -> int:
    """The one-based line for a section metadata field, or its comment start."""
    comment = section.metadata_comment
    if comment is not None:
        entry = next((entry for entry in comment.entries if entry.name == name), None)
        if entry is not None:
            return entry.line_index + 1
        return comment.span.start + 1
    return section.start + 1


def valid_ttl(value: object) -> bool:
    """Whether a TTL is named or a positive integer within the supported limit."""
    if not isinstance(value, str):
        return False
    if value in NAMED_TTL_DAYS:
        return True
    if not value.isascii() or not value.isdigit():
        return False
    significant = value.lstrip("0")
    maximum = str(MAX_TTL_DAYS)
    return bool(significant) and (
        len(significant) < len(maximum)
        or (len(significant) == len(maximum) and significant <= maximum)
    )


def _add(
    findings: list[Finding], document: Document, line: int, severity: str, message: str
) -> None:
    findings.append(Finding(document.path, line, severity, message))


def _finding_order(finding: Finding) -> tuple[str, int, int, str]:
    """Stable path and line order, with errors before warnings on the same line."""
    return (
        finding.path,
        finding.line,
        0 if finding.severity == "error" else 1,
        finding.message,
    )
