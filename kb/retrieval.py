"""Retrieval metadata: freshness, conflicts, provenance, and section metadata.

A port of the retrieval layer in scripts/_lib.sh, shared by section,
search, stale, and lint. Section metadata uses an HTML comment right after
an H2 or H3 heading:

    <!-- kb-section: verified=2026-09-01; ttl=domain; effective=2026-08-01;
         status=current; supersedes=2; sources=observations/archived/x.md -->

Values not in the comment inherit from the parent section (for an H3) or
the article front matter. `supersedes` belongs on the newer section and
points back to the older one's numeric locator. The comment is ignored
inside fenced code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from kb import dates, frontmatter, platform
from kb.markdown import Headings

DEFAULT_FRESHNESS_DAYS = 60
MAX_DISPLAYED_REFERENCES = 5
MAX_TTL_DAYS = 106751991167300  # The largest day count whose seconds fit in 64 bits.
SECTION_FIELDS = ("verified", "ttl", "effective", "status", "supersedes", "sources")
METADATA_START = re.compile(r"[ \t]*<!-- kb-section:")
NAMED_TTLS = {"people": 14, "status": 14, "process": 60, "domain": 180}
CORPORA = (
    ("knowledge/", "curated article"),
    ("sources/", "source document"),
    ("observations/pending/", "pending observation"),
    ("observations/archived/", "archive"),
    ("questions/", "question"),
)


def ttl_days(value: str) -> int | None:
    """A `ttl:` value as days: a name, or a decimal count that fits in seconds."""
    if value in NAMED_TTLS:
        return NAMED_TTLS[value]
    if not value or not (value.isascii() and value.isdigit()):
        return None
    days = int(value)
    return days if days <= MAX_TTL_DAYS else None


def trunc_days(seconds: int) -> int:
    """seconds // 86400, rounding toward zero as bash's arithmetic does."""
    days = abs(seconds) // 86400
    return days if seconds >= 0 else -days


def corpus(relpath: str) -> str:
    return next((name for prefix, name in CORPORA if relpath.startswith(prefix)), "unknown")


@dataclass
class Freshness:
    field: str = ""
    value: str = ""
    ttl: str = ""
    ttl_days: int | None = None
    status: str = "not-applicable"
    age_days: int | None = None
    ttl_raw: str = ""


def freshness(relpath: str, text: str, threshold_override: int | None = None) -> Freshness:
    result = Freshness()
    if relpath.startswith("knowledge/"):
        result.field = "verified"
    elif relpath.startswith("sources/"):
        result.field = "synced"
    else:
        return result
    raw_date = frontmatter.field(text, result.field) or ""
    result.value = raw_date
    ttl_raw = frontmatter.field(text, "ttl") or ""
    result.ttl_raw = result.ttl = ttl_raw
    threshold = ttl_days(ttl_raw)
    if threshold is None and ttl_raw.isascii() and ttl_raw.isdigit():
        result.status = "invalid"
        return result
    if threshold is None:
        threshold = DEFAULT_FRESHNESS_DAYS
        result.ttl = "default"
    result.ttl_days = threshold
    if not raw_date:
        result.status = "unknown"
        return result
    epoch = dates.date_epoch(raw_date.rsplit("T", 1)[0] if "T" in raw_date else raw_date)
    if epoch is None:
        result.status = "invalid"
        return result
    if threshold_override is not None:
        threshold = threshold_override
        result.ttl, result.ttl_days = "override", threshold
    age = dates.today_epoch() - epoch
    result.age_days = trunc_days(age)
    result.status = "stale" if age > threshold * 86400 else "fresh"
    return result


@dataclass
class Provenance:
    scope: str = "record"
    label: str = ""
    references: list[str] = field(default_factory=list)
    state: str = ""
    disposition: str = ""
    destination: str = ""

    @property
    def display(self) -> list[str]:
        return self.references[:MAX_DISPLAYED_REFERENCES]

    @property
    def truncated(self) -> bool:
        return len(self.references) > MAX_DISPLAYED_REFERENCES


PROVENANCE_KINDS = (
    ("knowledge/", "article", "article-level references", ""),
    ("sources/", "document", "document-level reference", ""),
    ("observations/pending/", "observation", "uncurated evidence", ""),
    ("observations/archived/", "archive", "archived evidence", ""),
    ("questions/open/", "question", "unresolved knowledge gap", "open"),
    ("questions/resolved/", "question", "resolved question record", "resolved"),
    ("questions/", "question", "question record", "unknown"),
)


def _unquote(value: str) -> str:
    if quoted := re.fullmatch(r'"(.*)"', value, re.DOTALL):
        return quoted.group(1).replace('\\"', '"').replace("\\\\", "\\")
    return value


def provenance(relpath: str, text: str) -> Provenance:
    result = Provenance()
    for prefix, scope, label, state in PROVENANCE_KINDS:
        if relpath.startswith(prefix):
            result.scope, result.label, result.state = scope, label, state
            break
    if relpath.startswith("sources/") and (canonical := frontmatter.field(text, "canonical")):
        result.references.append(canonical)
    inside = in_sources = False
    for line in frontmatter.lines(text):
        if line == "---":
            if inside:
                break
            inside = True
            continue
        if not inside:
            continue
        if re.fullmatch(r"sources:\s*", line):
            in_sources = True
            continue
        if in_sources:
            if item := re.fullmatch(r"\s*-\s+(.*)", line, re.DOTALL):
                result.references.append(_unquote(item.group(1)))
                continue
            in_sources = False
    if relpath.startswith("observations/archived/"):
        result.disposition = frontmatter.field(text, "disposition") or ""
        result.destination = frontmatter.field(text, "destination") or ""
    return result


@dataclass
class Section:
    """Metadata for one H2 or H3, after inheritance and validation."""

    heading: str = ""
    verified: str = ""
    ttl: str = ""
    effective: str = ""
    status: str = ""
    supersedes: str = ""
    sources: str = ""
    source_scope: str = "article"
    scope: str = "article"
    field_scopes: dict[str, str] = field(default_factory=dict)
    valid: bool = True
    invalid: str = ""

    def add_invalid(self, detail: str) -> None:
        self.valid = False
        self.invalid = f"{self.invalid}; {detail}" if self.invalid else detail

    @property
    def source_list(self) -> list[str]:
        return [s.strip() for s in self.sources.split(",") if s.strip()]


@dataclass
class Record:
    """Everything retrieval reports about one file, optionally for one section."""

    relpath: str
    corpus: str
    freshness: Freshness
    conflict: str
    provenance: Provenance
    article: Section
    sections: dict[str, Section] = field(default_factory=dict)
    selected: Section | None = None
    locator: str = ""

    def select(self, locator: str) -> Record:
        """This record as seen from one section (section_metadata_select)."""
        chosen = self.sections.get(locator) if locator else None
        result = replace(self, selected=chosen, locator=locator)
        if chosen is None:
            return result
        fresh = replace(self.freshness)
        provenance_ = replace(self.provenance, references=list(self.provenance.references))
        if chosen.source_scope == "section":
            provenance_.scope, provenance_.label = "section", "section-level references"
            provenance_.references = chosen.source_list
        if chosen.ttl:
            fresh.ttl_days, fresh.ttl = ttl_days(chosen.ttl), chosen.ttl
        if not chosen.valid:
            fresh.status = "invalid"
        elif chosen.verified:
            fresh.value = chosen.verified
            fresh.field = "synced" if self.relpath.startswith("sources/") else "verified"
            epoch = dates.date_epoch(chosen.verified.split("T", 1)[0]) or 0
            age = dates.today_epoch() - epoch
            fresh.age_days = trunc_days(age)
            fresh.status = "stale" if age > (fresh.ttl_days or 0) * 86400 else "fresh"
        conflict = "unresolved" if chosen.status == "unresolved" else self.conflict
        return replace(result, freshness=fresh, provenance=provenance_, conflict=conflict)


def _trim(value: str) -> str:
    return value.strip(" \t\n\r\v\f")


def _date_problem(value: str) -> bool:
    return bool(value) and dates.date_epoch(value) is None


def _apply(record: Record, locator: str, raw: str, base: str) -> None:
    """Inherit, then apply one comment's fields to locator (section_metadata_apply)."""
    parent = record.sections.get(base) if base else None
    if parent is not None:
        section = replace(parent, field_scopes=dict(parent.field_scopes))
        explicit = parent.scope == "section"
    else:
        article = record.article
        section = replace(article, field_scopes=dict.fromkeys(SECTION_FIELDS, "article"))
        section.valid, section.invalid = True, ""
        explicit = False
    section.heading = record.sections[locator].heading if locator in record.sections else ""
    seen: dict[str, str] = {}
    for pair in raw.replace(";", "\n").split("\n"):
        if not pair:
            continue
        pair = _trim(pair)
        if "=" in pair:
            key, value = pair.split("=", 1)
        elif ":" in pair:
            key, value = pair.split(":", 1)
        else:
            section.add_invalid(f"malformed field '{pair}'")
            continue
        key, value = _trim(key), _trim(value)
        canonical = "verified" if key in ("verified", "synced") else key
        if canonical not in SECTION_FIELDS:
            section.add_invalid(f"unknown field '{key}'")
            continue
        if canonical in seen:
            if seen[canonical] != value:
                section.add_invalid(
                    f"conflicting values for field '{canonical}': '{seen[canonical]}' and '{value}'"
                )
        else:
            seen[canonical] = value
        setattr(section, canonical, value)
        if canonical == "sources":
            section.source_scope = "section"
        explicit = True
        section.field_scopes[canonical] = "section"
    if section.verified and (
        not dates.DATE.fullmatch(section.verified) or _date_problem(section.verified)
    ):
        section.add_invalid(f"invalid verification date '{section.verified}'")
    if section.effective and (
        not dates.DATE.fullmatch(section.effective) or _date_problem(section.effective)
    ):
        section.add_invalid(f"invalid effective date '{section.effective}'")
    if section.ttl and ttl_days(section.ttl) is None:
        section.add_invalid(f"invalid ttl '{section.ttl}'")
    if section.status not in ("current", "superseded", "unresolved"):
        section.add_invalid(f"invalid status '{section.status}'")
    section.scope = "section" if explicit else "article"
    record.sections[locator] = section


def load(relpath: str, path: Path, *, sections: bool = True) -> Record:
    """Read path and build its retrieval record, parsing section metadata if asked."""
    text = platform.read_text(path)
    fresh = freshness(relpath, text)
    provenance_ = provenance(relpath, text)
    conflict = (
        (frontmatter.field(text, "conflict") or "none")
        if relpath.startswith("knowledge/")
        else "none"
    )
    verified, ttl = fresh.value, fresh.ttl_raw
    if not fresh.field:
        verified = frontmatter.field(text, "verified") or ""
        ttl = frontmatter.field(text, "ttl") or ""
    article = Section(
        verified=verified,
        ttl=ttl,
        effective=frontmatter.field(text, "effective") or "",
        status=frontmatter.field(text, "status") or "current",
        supersedes=frontmatter.field(text, "supersedes") or "",
        sources=", ".join(provenance_.references),
    )
    record = Record(relpath, corpus(relpath), fresh, conflict or "none", provenance_, article)
    if sections:
        _parse_sections(record, text)
    return record


def _parse_sections(record: Record, text: str) -> None:
    """Walk headings and kb-section comments (section_metadata_for_file)."""
    headings = Headings()
    locator = ""
    in_metadata = allowed = placement = misplaced = False
    buffer = ""
    h2 = h3 = 0
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        if not in_metadata:
            heading = headings.heading(line)
            if heading is not None:
                if heading.level == 2:
                    h2, h3 = h2 + 1, 0
                    locator, parent = str(h2), ""
                elif heading.level == 3:
                    h3 += 1
                    locator, parent = f"{h2}.{h3}", str(h2)
                else:
                    allowed = False
                    continue
                record.sections[locator] = Section(heading=heading.text)
                _apply(record, locator, "", parent)
                record.sections[locator].heading = heading.text
                if misplaced:
                    record.sections[locator].add_invalid(
                        "invalid section metadata placement before first section"
                    )
                    misplaced = False
                allowed = True
                continue
            if headings.fence_char:
                allowed = False
                continue
            if not line.strip(" \t\n\r\v\f"):
                continue
            if not METADATA_START.match(line):
                allowed = False
                continue
            placement, allowed, in_metadata = allowed, False, True
            line = line.split("<!-- kb-section:", 1)[1]
        if "-->" in line:
            before, after = line.split("-->", 1)
            buffer += before
            if not after.strip(" \t\n\r\v\f"):
                if not locator:
                    misplaced = True
                elif not placement:
                    record.sections[locator].add_invalid(
                        "invalid section metadata placement after body content"
                    )
                else:
                    _apply(record, locator, buffer, locator)
            in_metadata, buffer = False, ""
        else:
            buffer += line + "\n"
    if in_metadata and locator:
        if placement:
            _apply(record, locator, buffer, locator)
        record.sections[locator].add_invalid("unclosed section metadata comment")


# Emitters


def freshness_json(record: Record) -> dict[str, object]:
    fresh = record.freshness
    return {
        "field": fresh.field or None,
        "value": fresh.value or None,
        "ttl": fresh.ttl or None,
        "ttl_days": fresh.ttl_days,
        "status": fresh.status,
        "age_days": fresh.age_days,
    }


def provenance_json(record: Record, *, every: bool = False) -> dict[str, object]:
    provenance_ = record.provenance
    result: dict[str, object] = {
        "scope": provenance_.scope,
        "label": provenance_.label or None,
        "references": list(provenance_.references if every else provenance_.display),
        "reference_count": len(provenance_.references),
        "references_truncated": False if every else provenance_.truncated,
    }
    for name in ("state", "disposition", "destination"):
        if value := getattr(provenance_, name):
            result[name] = value
    return result


def section_json(record: Record) -> dict[str, object] | None:
    section = record.selected
    if section is None:
        return None
    result: dict[str, object] = {
        "available": True,
        "locator": record.locator,
        "scope": section.scope,
    }
    if section.source_scope == "section":
        result["source_scope"] = "section"
    result["field_scopes"] = {
        name: section.field_scopes.get(name, "")
        for name in SECTION_FIELDS
        if getattr(section, name) or name == "status"
    }
    result["verified"] = section.verified or None
    result["ttl"] = section.ttl or None
    if section.effective:
        result["effective"] = section.effective
    result["status"] = section.status
    if section.supersedes:
        result["supersedes"] = section.supersedes
    result["sources"] = section.source_list
    result["valid"] = section.valid
    if section.invalid:
        result["invalid"] = section.invalid
    return result


def freshness_text(record: Record) -> str:
    fresh = record.freshness
    if fresh.field:
        ttl = f"{fresh.ttl_days}d" if fresh.ttl_days is not None else "d"
        return (
            f"{record.corpus}; {fresh.field}={fresh.value or 'unknown'}; ttl={ttl}; "
            f"freshness={fresh.status}"
        )
    return (
        f"{record.corpus}; {record.provenance.label}" if record.provenance.label else record.corpus
    )


def _references_text(provenance_: Provenance) -> str:
    if provenance_.display:
        shown = ", ".join(provenance_.display)
        if provenance_.truncated:
            hidden = len(provenance_.references) - MAX_DISPLAYED_REFERENCES
            return f"refs={shown} (+{hidden} more; {provenance_.scope})"
        return f"refs={shown} ({provenance_.scope})"
    return f"refs=none ({provenance_.scope})"


def _provenance_tail(provenance_: Provenance) -> str:
    tail = ""
    for name in ("state", "disposition", "destination"):
        if value := getattr(provenance_, name):
            tail += f"; {name}={value}"
    return tail


def provenance_text(record: Record) -> str:
    return _references_text(record.provenance) + _provenance_tail(record.provenance)


def retrieval_text(record: Record) -> str:
    """The one-line summary search prints after each hit."""
    text = freshness_text(record)
    provenance_ = record.provenance
    if provenance_.display or provenance_.label:
        text += "; " + _references_text(provenance_)
    text += _provenance_tail(provenance_)
    if record.conflict != "none":
        text += f"; conflict={record.conflict}"
    return text


def section_text(record: Record) -> str:
    section = record.selected
    if section is None:
        return ""
    text = f"section-status={section.status}; section-scope={section.scope}"
    if section.effective:
        text += f"; effective={section.effective}"
    if section.supersedes:
        text += f"; supersedes={section.supersedes}"
    if section.invalid:
        text += f"; metadata-invalid={section.invalid}"
    return text
