"""lint - Check knowledge articles against the structural conventions.

Retrieval assumes every article has one H1, carries a parseable verified
date, and splits into H2 sections small enough to be worth loading.
Nothing enforced that, so drift surfaced only as bad answers: a second
H1 turns one article into two topics in `toc`, and an unclosed code
fence hides every heading after it from both `toc` and `section`.

Run during curation and after bulk edits.

Usage:
  lint [PATH ...] [--max-lines N] [--strict] [--batch BATCH_ID]

Options:
  --path PATH     Directory or file to check (repeatable; also positional)
  --max-lines N   Warn when an H2 exceeds N lines (default: 50)
  --strict        Treat warnings as errors
  --batch ID      During curation, allow a source reference to an archived
                  observation selected by this batch while it is pending

With no path, checks knowledge/.

Checks:
  error    no H1, or more than one H1
  error    frontmatter missing title, updated, or verified
  error    verified is not a YYYY-MM-DD date
  error    a code fence is left open at end of file
  error    a local Markdown link or source reference is missing
  error    a local Markdown link's heading anchor is missing
  warning  an H2 exceeds --max-lines
  warning  two H2s in one file share the same text (--heading picks the
           first silently)

Exit status:
  0  clean
  1  at least one error, or any warning under --strict

Examples:
  lint
  lint --path knowledge/home/
  lint knowledge/home/insulation.md --max-lines 40
  lint knowledge/a.md knowledge/b.md
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from kb import batches, cli, dates, frontmatter, paths, platform, retrieval
from kb.content import content_dir
from kb.markdown import Headings

LINK = re.compile(r"\[[^]]+\]\(([^)]*)\)")
SPACE = " \t\n\r\v\f"


def _ascii_lower(text: str) -> str:
    return text.translate({code: code + 32 for code in range(ord("A"), ord("Z") + 1)})


def heading_slug(text: str) -> str:
    """The ASCII GitHub-style slug, bytewise as LC_ALL=C tr and sed compute it."""
    data = _ascii_lower(text).encode("utf-8", errors="surrogateescape")
    data = re.sub(rb"[^a-z0-9 _-]", b"", data)
    data = re.sub(rb"\s+", b"-", data)
    data = re.sub(rb"-+", b"-", data).strip(b"-")
    return data.decode("ascii")


def _lines(text: str) -> list[str]:
    """Lines as `while read || [[ -n $line ]]`: a final unterminated line counts."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _external(target: str) -> bool:
    return target.startswith("//") or bool(re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target))


class Linter:
    def __init__(self, content: Path, max_lines: int, manifest: Path | None) -> None:
        self.content = content
        self.max_lines = max_lines
        self.manifest = manifest
        self.errors = 0
        self.warnings = 0
        self.out: list[str] = []

    def err(self, rel: str, where: object, message: str) -> None:
        self.errors += 1
        self.out.append(f"  error    {rel}:{where}  {message}")

    def warn(self, rel: str, where: object, message: str) -> None:
        self.warnings += 1
        self.out.append(f"  warning  {rel}:{where}  {message}")

    def has_anchor(self, target: Path, expected: str) -> bool:
        parser = Headings()
        for line in _lines(platform.read_text(target)):
            heading = parser.heading(line)
            if heading is not None and heading_slug(heading.text) == expected:
                return True
        return False

    def _pending_in_batch(self, source_path: str) -> bool:
        if self.manifest is None or not source_path.startswith("observations/archived/"):
            return False
        name = source_path.removeprefix("observations/archived/")
        if not name.endswith(".md") or "/" in name:
            return False
        member = batches.member(self.manifest, name)
        pending = self.content / "observations" / "pending" / name
        return (
            member is not None
            and member.status == "pending"
            and pending.is_file()
            and hashlib.sha256(pending.read_bytes()).hexdigest() == member.sha
        )

    def source_reference(self, rel: str, where: object, reference: str) -> None:
        if _external(reference) or not (reference.endswith(".md") or ".md#" in reference):
            return
        source_path, _, fragment = reference.partition("#")
        if source_path.startswith("/"):
            self.err(rel, where, f"absolute local source reference is unsupported: {reference}")
            return
        target = Path(f"{self.content}/{source_path}")
        if not paths.contained(self.content, target):
            self.err(rel, where, f"local source reference escapes content root: {reference}")
            return
        if not target.is_file():
            if not self._pending_in_batch(source_path):
                self.err(rel, where, f"missing local source reference: {reference}")
            return
        if fragment and str(target).endswith(".md"):
            fragment = _ascii_lower(fragment)
            if not self.has_anchor(target, fragment):
                self.err(rel, where, f"missing source reference anchor '#{fragment}': {reference}")

    def frontmatter_fields(self, rel: str, text: str) -> None:
        for name in ("title", "updated", "verified"):
            value = frontmatter.field(text, name) or ""
            if not value:
                self.err(rel, 1, f"frontmatter missing {name}")
            elif name != "title" and not dates.DATE.fullmatch(value):
                self.err(rel, 1, f"{name} is not a YYYY-MM-DD date: {value}")

    def headings(self, rel: str, text: str) -> None:
        parser = Headings()
        h1 = 0
        h2_text, h2_start = "", 0
        seen: list[str] = []
        number = 0

        def close(end: int) -> None:
            nonlocal h2_text
            if not h2_text:
                return
            length = end - h2_start + 1
            if length > self.max_lines:
                self.warn(rel, h2_start, f"H2 is {length} lines (max {self.max_lines}): {h2_text}")
            if h2_text in seen:
                self.warn(rel, h2_start, f"duplicate H2 text: {h2_text}")
            seen.append(h2_text)
            h2_text = ""

        for number, line in enumerate(_lines(text), start=1):
            heading = parser.heading(line)
            if heading is None:
                continue
            if heading.level <= 2:
                close(number - 1)
            if heading.level == 1:
                h1 += 1
                if h1 == 2:
                    self.err(rel, number, f"second H1 (one article, one H1): {heading.text}")
            elif heading.level == 2:
                h2_text, h2_start = heading.text, number
        close(number)
        if h1 == 0:
            self.err(rel, 1, "no H1 (toc has no title for this file)")
        if parser.fence_char:
            self.err(rel, number, "unclosed code fence (hides later headings from toc and section)")

    def section_metadata(self, rel: str, path: Path, text: str) -> None:
        record = retrieval.load(rel, path)
        article_verified = frontmatter.field(text, "verified") or ""
        reported = bool(article_verified) and not dates.DATE.fullmatch(article_verified)
        targets: dict[str, str] = {}
        locators = sorted(record.sections, key=lambda loc: [int(part) for part in loc.split(".")])
        for locator in locators:
            section = record.sections[locator]
            details = [d for d in section.invalid.split("; ") if d] if not section.valid else []
            if reported and section.field_scopes.get("verified") == "article":
                # Reported once already, as a front matter error (audit A-028).
                details = [
                    d for d in details if d != f"invalid verification date '{article_verified}'"
                ]
            if details:
                self.err(rel, locator, f"section metadata invalid: {'; '.join(details)}")
            supersedes = section.supersedes
            if section.status == "superseded" and supersedes:
                self.err(
                    rel,
                    locator,
                    "superseded section must not declare supersedes; put the link on the newer section",
                )
            elif supersedes:
                if not re.fullmatch(r"\d+(\.\d+)?", supersedes):
                    self.err(rel, locator, f"invalid supersedes locator: {supersedes}")
                elif supersedes not in record.sections:
                    self.err(rel, locator, f"supersedes section does not exist: {supersedes}")
                elif supersedes == locator:
                    self.err(rel, locator, f"section cannot supersede itself: {locator}")
                else:
                    targets[locator] = supersedes
            if section.effective and section.verified:
                effective, verified = (
                    dates.date_epoch(section.effective),
                    dates.date_epoch(section.verified),
                )
                if effective is not None and verified is not None and effective > verified:
                    self.err(
                        rel,
                        locator,
                        f"effective date {section.effective} is after verified date {section.verified}",
                    )
            if section.source_scope == "section":
                for source in section.source_list:
                    self.source_reference(rel, locator, source)
        cycle_reported = False
        for locator in locators:
            chain: set[str] = set()
            current = locator
            while current in targets:
                if current in chain:
                    if not cycle_reported:
                        self.err(rel, current, "supersedes relationship contains a cycle")
                        cycle_reported = True
                    break
                chain.add(current)
                current = targets[current]

    def source_references(self, rel: str, text: str) -> None:
        inside = in_sources = False
        for number, line in enumerate(_lines(text), start=1):
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
                    self.source_reference(rel, number, frontmatter.unquote(item.group(1)))
                    continue
                in_sources = False

    def local_links(self, rel: str, path: Path, text: str) -> None:
        parser = Headings()
        inside = done = False
        for number, line in enumerate(_lines(text), start=1):
            if line == "---" and not done:
                if inside:
                    inside, done = False, True
                else:
                    inside = True
                continue
            if not done:
                continue
            if parser.track_fence(line) or parser.fence_char:
                continue
            remaining = re.sub(r"`+[^`]*`+", "", line)
            while match := LINK.search(remaining):
                self.local_link(rel, path, number, match.group(1))
                remaining = remaining.split(match.group(0), 1)[1]

    def local_link(self, rel: str, path: Path, number: int, raw: str) -> None:
        value = raw.strip(SPACE)
        if value.startswith("<"):
            destination = value[1:].split(">", 1)[0]
        else:
            destination = re.split(r"\s", value, maxsplit=1)[0] if value else ""
        if not destination or _external(destination):
            return
        link_path, _, fragment = destination.partition("#")
        if link_path.startswith("/"):
            self.err(rel, number, f"absolute local Markdown link is unsupported: {destination}")
            return
        target = Path(f"{path.parent}/{link_path}") if link_path else path
        if not paths.contained(self.content, target):
            self.err(rel, number, f"local Markdown link escapes content root: {destination}")
            return
        if not target.is_file():
            self.err(rel, number, f"missing local Markdown link target: {destination}")
            return
        if fragment and str(target).endswith(".md"):
            fragment = _ascii_lower(fragment)
            if not self.has_anchor(target, fragment):
                self.err(
                    rel, number, f"missing local Markdown link anchor '#{fragment}': {destination}"
                )

    def check(self, path: Path) -> None:
        rel = str(path).removeprefix(f"{self.content}/")
        try:
            text = platform.read_text(path)
        except OSError:
            # An unreadable article is an error, named once (audit A-036).
            self.errors += 1
            print(f"lint: cannot read {rel}", file=sys.stderr)
            return
        self.frontmatter_fields(rel, text)
        self.headings(rel, text)
        self.section_metadata(rel, path, text)
        self.source_references(rel, text)
        self.local_links(rel, path, text)


def _files(content: Path, targets: list[str]) -> list[Path]:
    files: list[Path] = []
    for value in targets or [str(content / "knowledge")]:
        target = Path(value)
        if not target.exists():
            try:
                resolved = paths.resolve(content, value)
            except paths.PathError:
                raise SystemExit(1) from None
            if resolved is not None:
                target = Path(f"{content}/{resolved}")
            elif not targets:
                continue  # A missing knowledge directory is an empty one (audit A-035).
            else:
                cli.fail(f"Not found: {value}")  # Audit A-027.
        if not paths.contained(content, target):
            cli.fail(f"Path outside content root: {target}")
        if target.is_dir():
            files += paths.markdown_files(target)
        elif target.is_file():
            files.append(target)
        else:
            cli.fail(f"Not found: {target}")
    return files


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--path": "path", "--file": "path", "--max-lines": "max-lines", "--batch": "batch"},
        flags={"--strict": "strict"},
        positional=True,
    )
    targets = _targets(argv)
    max_lines = args.get("max-lines", "50")
    if not (max_lines.isascii() and max_lines.isdigit()):
        cli.fail("Error: --max-lines takes a number")
    content = content_dir()
    manifest = None
    if batch := args.get("batch"):
        if not batches.valid_id(batch):
            cli.fail(f"Invalid batch id: {batch}")
        manifest = batches.directory(content) / batch
        if not manifest.is_file():
            cli.fail(f"Batch not found: {batch}")
    files = _files(content, targets)
    linter = Linter(content, int(max_lines), manifest)
    for path in files:
        linter.check(path)
    print(
        "\n".join(
            [
                *linter.out,
                "",
                f"{len(files)} file(s): {linter.errors} error(s), {linter.warnings} warning(s)",
            ]
        )
    )
    if linter.errors or ("strict" in args.flags and linter.warnings):
        return 1
    return 0


def _targets(argv: list[str]) -> list[str]:
    """Paths from --path, --file, and positional words, in the order given."""
    found, index = [], 0
    while index < len(argv):
        word = argv[index]
        if word in ("--path", "--file", "--max-lines", "--batch"):
            if word in ("--path", "--file"):
                found.append(argv[index + 1])
            index += 2
            continue
        if not word.startswith("-"):
            found.append(word)
        index += 1
    return found
