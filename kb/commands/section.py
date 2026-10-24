"""section - Extract a section from a markdown file.

Retrieves a section by H2 number (from `toc` output) or by heading text.
Returns everything from the matched heading up to the next heading at the
same or higher level.

Usage:
  section --file FILE (--number N | --heading TEXT | --top | --title) [--exact]
          [--json | --text-only]
  section --file FILE --references [--json]

Options:
  --file FILE      Markdown file to read (required)
  --number N       H2 section number, or N.M for H3 under H2 N (from toc output)
  --heading TEXT   Heading text to match (case-insensitive substring)
  --top            Retrieve the prose before the first H2
  --title          Retrieve the frontmatter title
  --exact          Require exact heading match instead of substring
  --json           Return one structured JSON object
  --text-only      Return the historical section body without metadata
  --references     Return the complete provenance reference list
  --section-references  Return complete sources resolved for a selected section
  --max-bytes N  Bound stdout bytes; section content remains complete by line

Examples:
  section --file knowledge/networking.md --number 1     # 1st H2 section
  section --file knowledge/networking.md --number 2     # 2nd H2 section
  section --file knowledge/networking.md --number 2.1   # 1st H3 under 2nd H2
  section --file knowledge/networking.md --heading 'DNS'  # any heading level
  section --file knowledge/networking.md --top            # preamble and H1
  section --file knowledge/networking.md --title          # frontmatter title

Notes:
  --number N targets H2s. --number N.M targets the Mth H3 under the Nth H2.
  --heading matches any heading level (H2, H3, etc.), returning content up
  to the next heading at the same or higher level.
"""

from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from kb import cli, frontmatter, paths, platform, retrieval
from kb.content import content_dir, nonnegative
from kb.markdown import Headings

MARKER = "[content truncated: retrieve without --max-bytes]\n"
NUMBER = re.compile(r"\d+(\.\d+)?")


def _bytes(text: str) -> int:
    return len(text.encode("utf-8", errors="surrogateescape"))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _ascii_lower(text: str) -> str:
    """GNU tr '[:upper:]' '[:lower:]' is bytewise: only ASCII changes."""
    return text.translate({code: code + 32 for code in range(ord("A"), ord("Z") + 1)})


@dataclass
class Match:
    found: bool = False
    heading: str = ""
    number: str = ""
    level: int | None = None
    body: list[str] = field(default_factory=list)
    h2_count: int = 0


def find_top(text: str) -> Match:
    match = Match(found=True, heading="top")
    parser = Headings()
    inside = False
    for index, line in enumerate(frontmatter.lines(text)):
        if index == 0 and line == "---":
            inside = True
            continue
        if inside:
            inside = line != "---"
            continue
        heading = parser.heading(line)
        if heading is not None and heading.level == 2:
            break
        match.body.append(line)
    return match


def find_section(text: str, target: str, query: str, exact: bool) -> Match:
    match = Match()
    target_h2, _, target_h3 = target.partition(".")
    wanted = _ascii_lower(query)
    parser = Headings()
    match_level = 0
    h3 = 0
    for line in frontmatter.lines(text):
        heading = parser.heading(line)
        if heading is None:
            if match.found:
                match.body.append(line)
            continue
        if match.found:
            if heading.level <= match_level:
                break
            match.body.append(line)
            continue
        if heading.level == 2:
            match.h2_count, h3 = match.h2_count + 1, 0
        elif heading.level == 3:
            h3 += 1
        if target:
            if target_h3:
                hit = (
                    heading.level == 3 and match.h2_count == int(target_h2) and h3 == int(target_h3)
                )
            else:
                hit = heading.level == 2 and match.h2_count == int(target_h2)
        else:
            title = _ascii_lower(heading.text)
            hit = title == wanted if exact else wanted in title
        if hit:
            match.found, match_level = True, heading.level
            match.heading, match.level = heading.text, heading.level
            if heading.level == 2:
                match.number = str(match.h2_count)
            elif heading.level == 3:
                match.number = f"{match.h2_count}.{h3}"
            match.body.append(line)
    return match


def _prefix(record: retrieval.Record, match: Match, command: str | None) -> dict[str, object]:
    locator: dict[str, object] = {"number": match.number or None, "heading": match.heading}
    if command:
        locator["command"] = command
    locator["level"] = match.level
    return {
        "path": record.relpath,
        "corpus": record.corpus,
        "locator": locator,
        "freshness": retrieval.freshness_json(record),
        "conflict": {"status": record.conflict},
        "provenance": retrieval.provenance_json(record),
        "section_metadata": retrieval.section_json(record),
    }


def _fence_closer(parser: Headings) -> str:
    return parser.fence_char * parser.fence_len + "\n" if parser.fence_char else ""


def budget_json(prefix: dict[str, object], body: str, max_bytes: int) -> str:
    """The section JSON, with content cut at a line boundary to fit max_bytes."""
    full = _json({**prefix, "content": body}) + "\n"
    if _bytes(full) <= max_bytes:
        return full
    head = _json(prefix)[:-1] + ',"content":'
    head_bytes = _bytes(head)
    total = _bytes(body)
    marker_bytes = _bytes(_json(MARKER)) - 2

    def tail_bytes(omitted: int) -> int:
        return (
            _bytes(
                f',"content_truncated":true,"omitted_content_bytes":{omitted},"max_bytes":{max_bytes}}}'
            )
            + 1
        )

    parser = Headings()
    selected: list[str] = []
    selected_bytes = escaped_bytes = 0
    lines = body.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        line_bytes = _bytes(line) + 1
        escaped = _bytes(_json(line + "\n")) - 2
        state = (parser.fence_char, parser.fence_len)
        parser.track_fence(line)
        suffix = marker_bytes + (parser.fence_len + 2 if parser.fence_char else 0)
        candidate = (
            head_bytes
            + 2
            + escaped_bytes
            + escaped
            + suffix
            + tail_bytes(total - selected_bytes - line_bytes)
        )
        if candidate > max_bytes:
            parser.fence_char, parser.fence_len = state
            break
        selected.append(line)
        selected_bytes += line_bytes
        escaped_bytes += escaped
    omitted = total - selected_bytes
    content = "".join(f"{line}\n" for line in selected) + _fence_closer(parser) + MARKER
    output = (
        head
        + _json(content)
        + f',"content_truncated":true,"omitted_content_bytes":{omitted},"max_bytes":{max_bytes}}}'
        + "\n"
    )
    if _bytes(output) > max_bytes:
        cli.fail(
            f"Error: --max-bytes {max_bytes} is smaller than the minimum valid section envelope"
        )
    print(
        f"section: output budget used {_bytes(output)}/{max_bytes} bytes; omitted {omitted} content bytes",
        file=sys.stderr,
    )
    return output


def budget_text(output: str, max_bytes: int, text_only: bool) -> tuple[str, int]:
    """Text output cut at a line boundary to fit max_bytes; returns (text, status)."""
    if _bytes(output) <= max_bytes:
        return output, 0
    marker_bytes = _bytes(MARKER)
    parser = Headings()
    kept: list[str] = []
    used = 0
    body_started = overflow = False
    lines = output.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for line in lines:
        line_bytes = _bytes(line) + 1
        state = (parser.fence_char, parser.fence_len)
        parser.track_fence(line)
        candidate = (
            used + line_bytes + marker_bytes + (parser.fence_len + 1 if parser.fence_char else 0)
        )
        if candidate > max_bytes:
            parser.fence_char, parser.fence_len = state
            overflow = not text_only and not body_started
            break
        kept.append(line)
        used += line_bytes
        if not text_only and line == "---":
            body_started = True
    if overflow:
        cli.fail(
            f"Error: --max-bytes {max_bytes} is smaller than the complete section metadata envelope"
        )
    if not text_only and not body_started:
        cli.fail("Error: section output did not contain a complete metadata envelope")
    if used == 0 or used + marker_bytes > max_bytes:
        cli.fail(
            f"Error: --max-bytes {max_bytes} is too small for one complete section record and its truncation marker"
        )
    final = "".join(f"{line}\n" for line in kept) + _fence_closer(parser) + MARKER
    if _bytes(final) > max_bytes:
        cli.fail(
            f"Error: --max-bytes {max_bytes} is too small for one complete output record and its truncation marker"
        )
    print(
        f"section: output budget used {_bytes(final)}/{max_bytes} bytes; omitted {_bytes(output) - used} content/output bytes",
        file=sys.stderr,
    )
    return final, 0


def _references_output(
    record: retrieval.Record, as_json: bool, max_bytes: int | None, document: dict[str, object]
) -> int:
    if as_json:
        output = _json(document) + "\n"
        if max_bytes is not None and _bytes(output) > max_bytes:
            cli.fail(
                f"Error: --max-bytes {max_bytes} is smaller than the complete references response ({_bytes(output)} bytes)"
            )
        sys.stdout.write(output)
    else:
        for reference in record.provenance.references:
            print(reference)
    return 0


def run(args: cli.Parsed, max_bytes: int | None) -> int:
    flags = args.flags
    as_json, text_only = "json" in flags, "text-only" in flags
    number, query = args.get("number"), args.get("heading")
    top, title_only, exact = "top" in flags, "title" in flags, "exact" in flags
    references_only, section_references = "references" in flags, "section-references" in flags
    if as_json and text_only:
        cli.fail("Error: --json and --text-only cannot be combined")
    file = args.get("file")
    if not file:
        cli.fail("Error: --file is required")
    selectors = sum([bool(number), bool(query), top, title_only])
    if selectors > 1:
        cli.fail("Error: section selectors are mutually exclusive")
    if references_only and (number or query or top or title_only or exact or text_only):
        cli.fail("Error: --references cannot be combined with section selectors or --text-only")
    if references_only and section_references:
        cli.fail("Error: --references and --section-references cannot be combined")
    if section_references and text_only:
        cli.fail("Error: --section-references cannot be combined with --text-only")
    if section_references and selectors == 0:
        cli.fail("Error: --section-references requires a section selector")
    if not references_only and selectors == 0:
        cli.fail("Error: provide --number N, --heading TEXT, --top, or --title")
    if number and not NUMBER.fullmatch(number):
        cli.fail("Error: --number takes a section number such as 2 or 2.1")  # Audit A-018.
    content = content_dir()
    try:
        relpath = paths.resolve(content, file)
    except paths.PathError:
        return 1
    if relpath is None:
        cli.fail(f"File not found: {file}")
    path = Path(f"{content}/{relpath}")
    if not path.is_file():
        cli.fail(f"File not found: {path}")
    text = platform.read_text(path)

    if references_only:
        record = retrieval.load(relpath, path, sections=False)
        document = {
            "path": relpath,
            "corpus": record.corpus,
            "freshness": retrieval.freshness_json(record),
            "conflict": {"status": record.conflict},
            "provenance": retrieval.provenance_json(record, every=True),
        }
        if not as_json and max_bytes is not None:
            output = "".join(f"{r}\n" for r in record.provenance.references)
            if _bytes(output) > max_bytes:
                cli.fail(
                    f"Error: --max-bytes {max_bytes} is smaller than the complete references response ({_bytes(output)} bytes)"
                )
        return _references_output(record, as_json, max_bytes, document)

    if title_only:
        title = frontmatter.field(text, "title")
        if not title:
            cli.fail("Title not found")
        match = Match(found=True, heading=title, body=[title])
    elif top:
        match = find_top(text)
    else:
        match = find_section(text, number, query, exact)
    if not match.found:
        if number:
            cli.fail(f"Section #{number} not found (file has {match.h2_count} H2 sections)")
        cli.fail(f"Heading not found: '{query}'")

    record = retrieval.load(relpath, path).select(match.number)
    body = "".join(f"{line}\n" for line in match.body)
    command = "--top" if top else "--title" if title_only else None

    if section_references:
        document = {
            "path": relpath,
            "corpus": record.corpus,
            "locator": {"number": match.number or None, "heading": match.heading},
            "section_metadata": retrieval.section_json(record),
            "provenance": retrieval.provenance_json(record, every=True),
        }
        return _references_output(record, as_json, max_bytes, document)
    if text_only:
        sys.stdout.write(body)
        return 0
    if as_json:
        document = _prefix(record, match, command)
        if max_bytes is None:
            sys.stdout.write(_json({**document, "content": body}) + "\n")
        else:
            sys.stdout.write(budget_json(document, body, max_bytes))
        return 0
    locator = command or match.number or "heading"
    level = f" (H{match.level})" if match.level is not None else ""
    out = [
        f'Metadata: path={relpath}; corpus={record.corpus}; locator={locator} "{match.heading}"{level}'
    ]
    out.append(f"Freshness: {retrieval.freshness_text(record)}")
    if record.conflict != "none":
        out.append(f"Conflict: status={record.conflict}")
    if match.number:
        out.append(f"Section metadata: {retrieval.section_text(record)}")
    out.append(f"Provenance: scope={record.provenance.scope}; {retrieval.provenance_text(record)}")
    out.append("---")
    sys.stdout.write("\n".join(out) + "\n" + body)
    return 0


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={
            "--file": "file",
            "--number": "number",
            "--heading": "heading",
            "--max-bytes": "max-bytes",
        },
        flags={
            "--top": "top",
            "--title": "title",
            "--exact": "exact",
            "--json": "json",
            "--text-only": "text-only",
            "--references": "references",
            "--section-references": "section-references",
        },
    )
    max_bytes = (
        nonnegative("--max-bytes", args.get("max-bytes")) if "max-bytes" in args.values else None
    )
    if max_bytes is None or "json" in args.flags:
        return run(args, max_bytes)
    # Text output under a budget is produced in full, then cut to fit.
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            status = run(args, max_bytes)
    except SystemExit as exit_:
        sys.stdout.write(captured.getvalue())
        raise exit_ from None
    if status:
        sys.stdout.write(captured.getvalue())
        return status
    final, status = budget_text(captured.getvalue(), max_bytes, "text-only" in args.flags)
    sys.stdout.write(final)
    return status
