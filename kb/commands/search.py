"""search - Search the knowledge base by ranked Markdown section.

Usage:
  search <term> [term ...]
  search -- <term>
  search --query QUESTION [--relax]

Options:
  --limit N      Maximum result sections (default 20; 0 for all)
  --per-file N   Maximum sections from one file (default 3; 0 for all)
  --path PATH    Restrict to a content-relative file or directory
  --topic NAME   Restrict to a knowledge topic directory
  --corpus TYPE  Restrict to knowledge, sources, pending, archive, or questions
  --archive      Also search archived observations and questions
  --files        List matching files and section counts only
  --query TEXT   Search a natural-language question instead of literal terms
  --relax        Retry a question with bounded any-term matching after no hits
  --explain      Print query and result diagnostics on stderr
  --max-bytes N  Bound stdout bytes; JSON keeps complete result records
  --json         Return one JSON object containing bounded results
  --text-only    Return metadata-free section text output
  -h, --help     Show this help message

Results are ranked sections. A section containing every query term outranks
file-level fallback sections whose terms are split across the file. Title
and heading matches outrank body evidence, and duplicate evidence lines
count once. H2/H3 results include their `section --number` value; `top` and
frontmatter-title results include direct `--top` and `--title` selectors.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from kb import cli, paths, platform, retrieval, search
from kb.content import content_dir, nonnegative

CORPUS_NAMES = {
    "knowledge": "knowledge",
    "curated": "knowledge",
    "article": "knowledge",
    "curated article": "knowledge",
    "sources": "sources",
    "source": "sources",
    "source document": "sources",
    "pending": "pending",
    "observation": "pending",
    "pending observation": "pending",
    "archive": "archive",
    "archived": "archive",
    "questions": "questions",
    "question": "questions",
}
CORPUS_ROOTS = {
    "knowledge": "knowledge",
    "sources": "sources",
    "pending": "observations/pending",
    "archive": "observations/archived",
    "questions": "questions",
}
TEXT_MARKER = "[output truncated: complete records omitted; increase --max-bytes]\n"
VALUES = {"--query", "--limit", "--per-file", "--path", "--topic", "--corpus", "--max-bytes"}
FLAGS = {"--relax", "--explain", "--archive", "--files", "--json", "--text-only"}


def _bytes(text: str) -> int:
    return len(text.encode("utf-8", errors="surrogateescape"))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _within(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent + "/")


@dataclass
class Options:
    terms: list[str] = field(default_factory=list)
    query: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    corpora: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)


def parse(argv: list[str]) -> Options:
    options = Options()
    index = 0
    while index < len(argv):
        word = argv[index]
        if word in VALUES:
            if index + 1 >= len(argv):
                cli.fail(f"Option {word} requires an argument")
            value = argv[index + 1]
            if word == "--query":
                if options.query is not None:
                    cli.fail("Error: --query may be used once")
                options.query = value
            elif word == "--corpus":
                options.corpora.append(value)
            else:
                options.values[word] = value
            index += 2
            continue
        if word in FLAGS:
            options.flags.add(word)
        elif word in ("-h", "--help"):
            cli.print_help(__doc__)
            raise SystemExit(0)
        elif word == "--":
            options.terms += argv[index + 1 :]
            break
        elif word.startswith("-"):
            cli.fail(f"Unknown option: {word} (use -- to search for it literally)")
        else:
            options.terms.append(word)
        index += 1
    return options


class Search:
    def __init__(self, options: Options, content: Path) -> None:
        self.o = options
        self.content = content
        self.question = options.query is not None
        self.json = "--json" in options.flags
        self.text_only = "--text-only" in options.flags
        self.files_only = "--files" in options.flags
        self.explain = "--explain" in options.flags
        self.match_mode = "strict"
        self.alias_matches: list[str] = []
        self.limit_omitted = 0
        self.lines_total = 0
        self.files_total = 0
        self.admitted = 0
        self.emitted = 0
        self.budget = (0, 0, 0)  # returned, omitted, bytes
        self.impossible = False
        self.records: dict[str, retrieval.Record] = {}

    # Query fields shared by every JSON record and the summary.

    def query_fields(self, result_alias: str | None = None) -> dict[str, object]:
        aliases = (
            ([result_alias] if result_alias else [])
            if result_alias is not None
            else self.alias_matches
        )
        return {
            "query_mode": "question" if self.question else "literal",
            "query": self.o.query if self.question else None,
            "query_terms": self.o.terms,
            "alias_matches": aliases,
            "match_mode": self.match_mode,
            "relaxed": self.match_mode == "relaxed",
        }

    def query_text(self) -> str:
        return f"query-mode=question; match-mode={self.match_mode}" if self.question else ""

    def record(self, relpath: str, number: str) -> retrieval.Record:
        if relpath not in self.records:
            self.records[relpath] = retrieval.load(relpath, Path(f"{self.content}/{relpath}"))
        return self.records[relpath].select(number)

    def metadata_json(self, record: retrieval.Record) -> dict[str, object]:
        return {
            "freshness": retrieval.freshness_json(record),
            "conflict": {"status": record.conflict},
            "provenance": retrieval.provenance_json(record),
            "section_metadata": retrieval.section_json(record),
        }

    def json_record(self, c: search.Candidate) -> str:
        if self.files_only:
            record = self.record(c.path, "")
            document: dict[str, object] = {
                "path": c.path,
                "corpus": record.corpus,
                "title": c.title,
                "match_count": c.match_count,
                "locator": None,
                **self.metadata_json(record),
            }
        else:
            record = self.record(c.path, c.number)
            locator: dict[str, object] = {"section": c.section or "top", "number": c.number or None}
            if c.command:
                locator["command"] = c.command
            locator["line"] = c.line
            document = {
                "path": c.path,
                "corpus": record.corpus,
                "title": c.title,
                "match_count": c.evidence_count,
                "locator": locator,
                **self.metadata_json(record),
                "text": c.excerpt,
            }
        document["routing"] = c.routing
        if c.alias:
            document["alias"] = c.alias
        document.update(self.query_fields(c.alias))
        return _json(document)

    def text_record(self, c: search.Candidate) -> str:
        query = self.query_text()
        if self.files_only:
            if self.text_only:
                return f"{c.path}  [{c.match_count}] {c.title}"
            if c.routing:
                return f"{c.path}  [routing] alias matched: {c.alias} [{query}]"
            metadata = retrieval.retrieval_text(self.record(c.path, ""))
            return f"{c.path}  [{c.match_count}] {c.title}" + _suffix("", metadata, query)
        if self.text_only:
            if c.routing:
                return f"{c.path} | alias | alias matched: {c.alias}"
            return f"{c.path} | {c.section or 'top'} | {c.excerpt}"
        if c.routing:
            return f"{c.path} | alias | alias matched: {c.alias} [routing-result] [{query}]"
        record = self.record(c.path, c.number)
        metadata = retrieval.retrieval_text(record)
        if detail := retrieval.section_text(record):
            metadata += f"; {detail}"
        locator = (
            f"section-number={c.number}"
            if c.number
            else f"section-command={c.command}"
            if c.command
            else ""
        )
        return f"{c.path} | {c.section or 'top'} | {c.excerpt}" + _suffix(locator, metadata, query)

    # Explanation on stderr.

    def explain_results(self, returned: int, byte_omitted: int = 0, budget_bytes: int = 0) -> None:
        if not self.explain:
            return
        out = [f"search explain: mode={'question' if self.question else 'literal'}"]
        if self.question:
            out.append(f"  original query: {self.o.query}")
            out.append(f"  retained terms: {' '.join(self.o.terms)}")
            out.append(f"  alias matches: {' '.join(self.alias_matches) or 'none'}")
        else:
            out.append(f"  literal terms: {' '.join(self.o.terms)}")
        out.append(f"  matching mode: {self.match_mode}")
        out.append(
            f"  scope: path={self.o.values.get('--path') or 'all'} "
            f"topic={self.o.values.get('--topic') or 'all'} corpora={' '.join(self.corpora)}"
        )
        out.append(
            f"  candidates: {self.lines_total}; returned: {returned}; output limits: "
            f"limit={self.o.values.get('--limit', '20')} per-file={self.o.values.get('--per-file', '3')}"
        )
        if self.max_bytes is not None:
            out.append(
                f"  omissions: result/per-file={self.limit_omitted}; byte-budget={byte_omitted}"
            )
            out.append(f"  byte budget: used={budget_bytes}/{self.max_bytes} bytes")
        if self.lines_total == 0:
            cause = (
                "path and topic filters have no intersection"
                if self.impossible
                else "no selected record matched the retained terms"
            )
            out.append(f"  no-hit cause: {cause}")
        elif self.limit_omitted or byte_omitted:
            if self.limit_omitted and byte_omitted:
                out.append(
                    "  omission cause: result/per-file limits and byte budget hid candidates"
                )
            elif self.limit_omitted:
                out.append("  omission cause: result/per-file limits hid candidates")
            else:
                out.append("  omission cause: byte budget hid complete records")
        print("\n".join(out), file=sys.stderr)

    # JSON output.

    def summary(
        self, returned: int, truncated: bool, extra: dict[str, object] | None = None
    ) -> dict[str, object]:
        return {
            **self.query_fields(),
            "total_files": self.files_total,
            "total_lines": self.lines_total,
            "returned": returned,
            "truncated": truncated,
            **(extra or {}),
        }

    def json_budget(self, records: list[str], total_candidates: int) -> int:
        def tail(returned: int, omitted: int) -> str:
            fields = self.summary(
                returned, omitted > 0, {"omitted_results": omitted, "max_bytes": self.max_bytes}
            )
            return "]," + _json(fields)[1:]

        body = _bytes('{"results":[')
        selected = 0
        while selected < len(records):
            candidate_body = body + _bytes(records[selected]) + (1 if selected else 0)
            omitted = total_candidates - selected - 1
            if candidate_body + _bytes(tail(selected + 1, omitted)) + 1 > self.max_bytes:
                break
            body, selected = candidate_body, selected + 1
        omitted = total_candidates - selected
        output = '{"results":[' + ",".join(records[:selected]) + tail(selected, omitted) + "\n"
        if _bytes(output) > self.max_bytes:
            cli.fail(
                f"Error: --max-bytes {self.max_bytes} is smaller than the minimum valid JSON response ({_bytes(output)} bytes)"
            )
        self.budget = (selected, len(records) - selected, _bytes(output))
        sys.stdout.write(output)
        if omitted > 0:
            print(
                f"search: output budget used {_bytes(output)}/{self.max_bytes} bytes; "
                f"omitted {omitted} complete result record(s)",
                file=sys.stderr,
            )
        return 0

    def empty_json(self) -> int:
        if self.max_bytes is not None:
            status = self.json_budget([], 0)
            self.explain_results(self.budget[0], self.budget[1], self.budget[2])
            return status
        sys.stdout.write('{"results":[],' + _json(self.summary(0, False))[1:] + "\n")
        self.explain_results(0)
        return 0

    # The search.

    def scope(self) -> list[Path]:
        o = self.o
        selected = [
            CORPUS_NAMES[c] if c in CORPUS_NAMES else _unknown_corpus(c) for c in o.corpora
        ] or ["knowledge", "sources", "pending"]
        if "--archive" in o.flags:
            selected += ["archive", "questions"]
        self.corpora = list(dict.fromkeys(selected))
        target = ""
        if "--path" in o.values:
            try:
                resolved = paths.resolve(self.content, o.values["--path"])
            except paths.PathError:
                raise SystemExit(1) from None
            if resolved is None:
                cli.fail(f"Search path not found: {o.values['--path']}")
            target = os.path.realpath(f"{self.content}/{resolved}")
        if "--topic" in o.values:
            raw = o.values["--topic"]
            topic = raw.removeprefix("knowledge/")
            if (
                not topic
                or topic.startswith("/")
                or topic == ".."
                or topic.startswith("../")
                or "/../" in topic
            ):
                cli.fail(f"Invalid topic: {raw}")
            topic_path = Path(f"{self.content}/knowledge/{topic}")
            if not topic_path.is_dir() or not paths.contained(self.content, topic_path):
                cli.fail(f"Knowledge topic not found: {raw}")
            candidate = os.path.realpath(topic_path)
            if not target or _within(candidate, target):
                target = candidate
            elif not _within(target, candidate):
                self.impossible = True
        directories: list[Path] = []
        if self.impossible:
            return directories
        for corpus in self.corpora:
            root = Path(f"{self.content}/{CORPUS_ROOTS[corpus]}")
            if not root.exists():
                continue
            chosen = root
            if target:
                canonical = os.path.realpath(root)
                if _within(target, canonical):
                    chosen = Path(target)
                elif not _within(canonical, target):
                    continue
            if (chosen.is_dir() or chosen.is_file()) and chosen not in directories:
                directories.append(chosen)
        return directories

    def files(self, directories: list[Path]) -> list[Path]:
        found: list[Path] = []
        for directory in directories:
            if directory.is_file():
                if directory.name.endswith(".md") and not directory.is_symlink():
                    found.append(directory)
                continue
            for root, _, names in os.walk(directory):
                for name in names:
                    path = Path(root) / name
                    if name.endswith(".md") and path.is_file() and not path.is_symlink():
                        found.append(path)
        return sorted(set(found), key=bytes)

    def candidates(self, files: list[Path]) -> list[search.Candidate]:
        out: list[search.Candidate] = []
        prefix = f"{self.content}/"
        for path in files:
            relpath = str(path).removeprefix(prefix)
            try:
                out += search.rank_file(
                    relpath,
                    path,
                    self.o.terms,
                    relaxed=self.match_mode == "relaxed",
                    aliases=self.question,
                    files_only=self.files_only,
                )
            except OSError:
                if relpath not in self.unreadable:
                    self.unreadable.add(relpath)
                    # Skip it with one warning; the rest still count (audit A-036).
                    print(f"search: cannot read {relpath}", file=sys.stderr)
        return search.ranked(out)

    def run(self) -> int:
        o = self.o
        self.unreadable: set[str] = set()
        directories = self.scope()
        if not directories:
            if self.json:
                return self.empty_json()
            if self.impossible:
                print("No files match the requested path and topic filters.", file=sys.stderr)
            self.explain_results(0)
            return 0
        files = self.files(directories)
        results = self.candidates(files)
        if not results and self.question and "--relax" in o.flags:
            self.match_mode = "relaxed"
            results = self.candidates(files)
        if not results:
            if self.json:
                return self.empty_json()
            self.explain_results(0)
            return 0
        limit, per_file = int(o.values.get("--limit", "20")), int(o.values.get("--per-file", "3"))
        seen_files: set[str] = set()
        shown_files: set[str] = set()
        per_file_shown: dict[str, int] = {}
        records: list[str] = []
        lines: list[str] = []
        for c in results:
            if c.alias and c.alias not in self.alias_matches:
                self.alias_matches.append(c.alias)
            if c.path not in seen_files:
                seen_files.add(c.path)
                self.files_total += 1
            self.lines_total += 1
            if limit and self.admitted >= limit:
                self.limit_omitted += 1
                continue
            if not self.files_only and per_file and per_file_shown.get(c.path, 0) >= per_file:
                self.limit_omitted += 1
                continue
            if self.json:
                records.append(self.json_record(c))
            else:
                lines.append(self.text_record(c))
            self.admitted += 1
            per_file_shown[c.path] = per_file_shown.get(c.path, 0) + 1
            shown_files.add(c.path)
        hidden_files = self.files_total - len(shown_files)
        if self.json:
            if self.max_bytes is not None:
                status = self.json_budget(records, self.lines_total)
                self.explain_results(*self.budget)
                return status
            self.emitted = len(records)
            hidden = self.lines_total - self.emitted
            sys.stdout.write(
                '{"results":['
                + ",".join(records)
                + "],"
                + _json(self.summary(self.emitted, hidden > 0))[1:]
                + "\n"
            )
            if hidden > 0:
                message = f"search: {hidden} result section(s) hidden"
                if hidden_files > 0:
                    message += f" in {hidden_files} unshown file(s)"
                print(message + "; raise --limit/--per-file or narrow the query.", file=sys.stderr)
            self.explain_results(self.emitted)
            return 0
        print("\n".join(lines))
        self.emitted = len(lines)
        if self.files_only:
            if hidden_files > 0:
                print(f"\n... {hidden_files} more file(s). Raise --limit, or narrow the query.")
        else:
            hidden = self.lines_total - self.admitted
            if hidden > 0:
                message = f"\n... {hidden} more result section(s)"
                if hidden_files > 0:
                    message += f" in {hidden_files} unshown file(s)"
                print(message + ". Raise --limit/--per-file, or narrow the query.")
        if self.max_bytes is None:
            self.explain_results(self.emitted)
        return 0


def _suffix(*values: str) -> str:
    return "".join(f" [{value}]" for value in values if value)


def _unknown_corpus(name: str) -> str:
    cli.fail(
        f"Error: unknown corpus '{name}' (use knowledge, sources, pending, archive, or questions)"
    )
    raise AssertionError


def budget_text(output: str, run: Search) -> str:
    """Text output cut to whole records under the byte budget (search_budget_finalize)."""
    max_bytes = run.max_bytes
    if _bytes(output) <= max_bytes:
        run.explain_results(run.admitted, 0, _bytes(output))
        return output
    lines = output.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    kept: list[str] = []
    used = 0
    marker = _bytes(TEXT_MARKER)
    for line in lines:
        size = _bytes(line) + 1
        if used + size + marker > max_bytes:
            break  # Ranked records form a prefix: never skip one to show a later one.
        kept.append(line)
        used += size
    if not kept or used + marker > max_bytes:
        cli.fail(
            f"Error: --max-bytes {max_bytes} is too small for one complete output record and its truncation marker"
        )
    selected = min(len(kept), run.admitted)
    run.explain_results(selected, run.admitted - selected, used + marker)
    print(
        f"search: output budget used {used + marker}/{max_bytes} bytes; omitted stdout records",
        file=sys.stderr,
    )
    return "".join(f"{line}\n" for line in kept) + TEXT_MARKER


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    options = parse(argv)
    flags = options.flags
    if "--json" in flags and "--text-only" in flags:
        cli.fail("Error: --json and --text-only cannot be combined")
    if options.query is not None and options.terms:
        cli.fail("Error: --query cannot be combined with positional literal terms")
    if options.query is not None and not options.query:
        cli.fail("Error: --query requires a non-empty question")
    if options.query is None and "--relax" in flags:
        cli.fail("Error: --relax requires --query")
    if options.query is not None:
        options.terms = search.question_terms(options.query)
        if not options.terms:
            cli.fail("Error: question contains no searchable terms after stopword removal")
    if not options.terms:
        cli.fail("Usage: search <term> [term ...] or search --query QUESTION")
    if any(not term for term in options.terms):
        cli.fail("Error: empty search term")
    for name in ("--limit", "--per-file"):
        value = options.values.get(name, "0")
        if not (value.isascii() and value.isdigit()):
            cli.fail("Error: --limit and --per-file take a number")
    max_bytes = (
        nonnegative("--max-bytes", options.values["--max-bytes"])
        if "--max-bytes" in options.values
        else None
    )
    content = content_dir()
    if not content.exists():
        cli.fail(f"Content directory could not be resolved: {content}")
    run = Search(options, Path(os.path.realpath(content)))
    run.max_bytes = max_bytes
    if max_bytes is None or run.json:
        return run.run()
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            status = run.run()
    except SystemExit:
        sys.stdout.write(captured.getvalue())
        raise
    if status:
        sys.stdout.write(captured.getvalue())
        return status
    sys.stdout.write(budget_text(captured.getvalue(), run))
    return 0
