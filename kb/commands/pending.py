"""pending - List uncurated observations.

Shows pending observations with their titles and dates.
Use --full to include the body text.
Use --preview for bounded queue metrics without body text.

Usage:
  pending [--full] [--count] [--preview] [--max-bytes N]

Options:
  --full    Show full observation content, not just titles
  --count   Just print the count
  --preview Show batch-selectable queue metrics and lexical topic hints
  --max-bytes N  With --preview, select input files within a byte budget
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from kb import cli, dates, frontmatter, pending, platform
from kb.content import content_dir, nonnegative
from kb.markdown import Headings

MAX_TOPIC_HINTS = 8
MAX_METADATA_WARNINGS = 8
MAX_TOPIC_HINT_LENGTH = 120
MAX_METADATA_BYTES = 65536
MAX_TOPIC_ARTICLES = 256
TOPIC_SAMPLE_BYTES = 8192
MAX_PREVIEW_REPORT_ITEMS = 8
IGNORED_WORDS = frozenset(
    [
        "an",
        "and",
        "for",
        "from",
        "into",
        "of",
        "on",
        "the",
        "this",
        "with",
        "knowledge",
        "article",
        "setup",
        "session",
        "transcript",
        "skill",
        "system",
        "guide",
    ]
)
METADATA_FIELD = re.compile(r"(title|source|created|topic):\s*(.*)", re.DOTALL)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")


def _unquote(value: str) -> str:
    if quoted := re.fullmatch(r'"(.*)"', value, re.DOTALL):
        return quoted.group(1).replace('\\"', '"').replace("\\\\", "\\")
    return value


def _normalise(text: str) -> str:
    """ASCII lowercase; every run of other bytes becomes one space (GNU tr is bytewise)."""
    data = text.encode("utf-8", errors="surrogateescape").lower()
    return re.sub(rb"[^a-z0-9]+", b" ", data).decode("ascii")


def _bounded(label: str) -> str:
    return label[:117] + "..." if len(label) > MAX_TOPIC_HINT_LENGTH else label


def _head(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def _human(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    for unit, scale in (("KiB", 1024), ("MiB", 1024**2), ("GiB", 1024**3)):
        if size < scale * 1024 or unit == "GiB":
            return f"{size / scale:.1f} {unit}"
    raise AssertionError


def article_label(path: Path) -> str:
    """The first H1, else the front matter title, else the file name."""
    headings = Headings()
    inside = False
    fallback = ""
    for line in frontmatter.lines(_decode(_head(path, MAX_METADATA_BYTES))):
        if line == "---":
            inside = not inside
            continue
        heading = headings.heading(line)
        if heading is not None and heading.level == 1:
            return heading.text
        if inside and (match := re.fullmatch(r"title:\s*(.*)", line, re.DOTALL)):
            fallback = _unquote(match.group(1))
    return fallback or path.name.removesuffix(".md")


@dataclass
class Metadata:
    values: dict[str, str] = field(default_factory=dict)
    first_line: str = ""
    complete: bool = False


def read_metadata(path: Path) -> Metadata:
    # The bash reader takes the head through $(...), which drops trailing newlines.
    text = _decode(_head(path, MAX_METADATA_BYTES)).rstrip("\n")
    metadata = Metadata(first_line=text.split("\n", 1)[0])
    inside = False
    for line in text.split("\n"):
        if line == "---":
            if inside:
                metadata.complete = True
                break
            inside = True
            continue
        if inside and (match := METADATA_FIELD.fullmatch(line)):
            metadata.values[match.group(1)] = _unquote(match.group(2))
    return metadata


def _issues(metadata: Metadata) -> tuple[list[str], int | None, str]:
    issues = []
    if not (metadata.first_line == "---" and metadata.complete):
        issues.append("malformed frontmatter")
    if not metadata.values.get("title"):
        issues.append("missing title")
    if not metadata.values.get("source"):
        issues.append("missing source")
    created = metadata.values.get("created", "")
    epoch = None
    created_date = created.split("T", 1)[0].split(" ", 1)[0]
    if not created:
        issues.append("missing created")
    else:
        epoch = dates.date_epoch(created_date)
        if epoch is None:
            issues.append("invalid created")
    return issues, epoch, created_date


def _sample(path: Path, title: str) -> str:
    lines = _decode(_head(path, TOPIC_SAMPLE_BYTES)).split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    body, inside = [], False
    for number, line in enumerate(lines):
        if number == 0 and line == "---":
            inside = True
        elif inside and line == "---":
            inside = False
        elif not inside:
            body.append(line)
    return f"{title} " + "\n".join(body).rstrip("\n")


class TopicHints:
    """Count which article topics the pending items mention (pending's awk program)."""

    def __init__(self) -> None:
        self.display_by_label: dict[str, str] = {}
        self.word_count: dict[str, int] = {}
        self.labels_by_word: dict[str, list[str]] = {}
        self.files: dict[str, int] = {}
        self.score: dict[str, int] = {}
        self.display: dict[str, str] = {}
        self.matched: set[tuple[str, str]] = set()

    def topic(self, label: str, display: str) -> None:
        seen = label in self.display_by_label
        self.display_by_label[label] = display
        if seen:
            return
        self.word_count.setdefault(label, 0)
        words: set[str] = set()
        for word in label.split(" "):
            if (
                len(word) >= 3
                and not word.isdigit()
                and word not in IGNORED_WORDS
                and word not in words
            ):
                words.add(word)
                self.word_count[label] += 1
                self.labels_by_word.setdefault(word, []).append(label)

    def add(self, label: str, display: str, item: str) -> None:
        if not label:
            return
        if (label, item) not in self.matched:
            self.matched.add((label, item))
            self.files[label] = self.files.get(label, 0) + 1
        self.score[label] = self.score.get(label, 0) + 1
        self.display.setdefault(label, display)

    def pending(self, item: str, text: str) -> None:
        seen: set[str] = set()
        matches: dict[str, int] = {}
        for word in text.split(" "):
            if len(word) >= 3 and word not in seen and word in self.labels_by_word:
                seen.add(word)
                for label in self.labels_by_word[word]:
                    matches[label] = matches.get(label, 0) + 1
        for label, count in matches.items():
            if count >= (2 if self.word_count.get(label, 0) > 1 else 1):
                self.add(label, self.display_by_label.get(label, ""), item)

    def top(self) -> list[tuple[int, str]]:
        ranked = sorted(
            self.files, key=lambda label: (-self.files[label], -self.score[label], label)
        )
        return [(self.files[label], self.display[label]) for label in ranked[:MAX_TOPIC_HINTS]]


def preview(content: Path, max_bytes: int | None) -> None:
    pending_dir = content / "observations" / "pending"
    selection = None
    if max_bytes is not None:
        selection = pending.select(pending_dir, max_bytes)
        files = selection.files
    else:
        files = sorted(pending.top_level(pending_dir), key=bytes)
    hints = TopicHints()
    capped = False
    knowledge = content / "knowledge"
    if knowledge.is_dir():
        articles = sorted((p for p in knowledge.rglob("*.md") if p.is_file()), key=bytes)
        capped = len(articles) > MAX_TOPIC_ARTICLES
        for article in articles[:MAX_TOPIC_ARTICLES]:
            label = article_label(article)
            if not label:
                continue
            label = _bounded(label)
            normalized = _normalise(label)
            if normalized:
                hints.topic(normalized, label)

    totals = {"observation": [0, 0], "transcript": [0, 0]}
    oldest: tuple[int, str, str] | None = None
    warnings: list[tuple[str, str]] = []
    warning_count = 0
    for index, path in enumerate(files, start=1):
        size = path.stat().st_size
        metadata = read_metadata(path)
        kind = (
            "transcript" if metadata.values.get("source") == "session-transcript" else "observation"
        )
        totals[kind][0] += 1
        totals[kind][1] += size
        issues, epoch, created_date = _issues(metadata)
        if issues:
            warning_count += 1
            if len(warnings) < MAX_METADATA_WARNINGS:
                warnings.append((path.name, ", ".join(issues)))
        if epoch is not None and (oldest is None or epoch < oldest[0]):
            oldest = (epoch, created_date, path.name)
        topic = metadata.values.get("topic", "")
        if topic:
            topic = _bounded(topic)
            normalized = _normalise(topic)
            if normalized:
                hints.add(normalized, topic, str(index))
        else:
            hints.pending(str(index), _normalise(_sample(path, metadata.values.get("title", ""))))

    out = ["Batch-selectable queue preview", f"Batch-selectable items: {len(files)}"]
    if selection is not None:
        out += [f"Input budget: {max_bytes} bytes", f"Selected input bytes: {selection.total}"]
        out += [f"Selected size: {s} bytes" for s in selection.sizes[:MAX_PREVIEW_REPORT_ITEMS]]
        shown = selection.skipped[:MAX_PREVIEW_REPORT_ITEMS]
        out += [f"Skipped oversized: {s}" for s in shown]
        if len(selection.skipped) > len(shown):
            out.append(f"... {len(selection.skipped) - len(shown)} more oversized item(s)")
    if oldest is not None:
        age = dates.today_epoch() - oldest[0]
        if age < 0:
            out.append(
                f"Oldest pending age: created in {(-age + 86399) // 86400} day(s) ({oldest[1]}; {oldest[2]})"
            )
        else:
            out.append(f"Oldest pending age: {age // 86400} day(s) ({oldest[1]}; {oldest[2]})")
    else:
        out.append("Oldest pending age: unknown (no valid created date)")
    for kind, label in (("observation", "Observation"), ("transcript", "Transcript")):
        count, size = totals[kind]
        out.append(f"{label} items: {count} ({_human(size)}; {size} bytes)")
    total = totals["observation"][1] + totals["transcript"][1]
    out.append(f"Input volume: {_human(total)} ({total} bytes)")
    out.append("Topic hints (hints only; no LLM):")
    if capped:
        out.append(f"  topic article metadata capped at {MAX_TOPIC_ARTICLES} file(s)")
    top = [(count, display) for count, display in hints.top() if display]
    out += [f"  {display} ({count} pending item(s))" for count, display in top] or [
        "  none available"
    ]
    if not warnings:
        out.append("Metadata warnings: none")
    else:
        out.append(f"Metadata warnings: {warning_count} malformed file(s)")
        out += [f"  {name}: {detail}" for name, detail in warnings]
        if warning_count > len(warnings):
            out.append(f"  ... {warning_count - len(warnings)} more malformed file(s)")
    print("\n".join(out))


def _pad(text: str, width: int) -> str:
    """Left-justify to width bytes, as C printf's %-Ns does."""
    size = len(text.encode("utf-8", errors="surrogateescape"))
    return text + " " * max(0, width - size)


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--max-bytes": "max-bytes"},
        flags={"--full": "full", "--count": "count", "--preview": "preview"},
    )
    max_bytes = None
    if "max-bytes" in args.values:
        max_bytes = nonnegative("--max-bytes", args.get("max-bytes"))
    flags = args.flags
    if "preview" in flags and ("full" in flags or "count" in flags):
        cli.fail("--preview cannot be combined with --full or --count")
    if max_bytes is not None and "preview" not in flags:
        cli.fail("--max-bytes requires --preview")
    content = content_dir()
    if "preview" in flags:
        preview(content, max_bytes)
        return 0
    directory = content / "observations" / "pending"
    files = (
        sorted((p for p in directory.rglob("*.md") if p.is_file()), key=bytes)
        if directory.is_dir()
        else []
    )
    if "count" in flags:
        print(len(files))
        return 0
    if not files:
        print("No pending observations.")
        return 0
    print(f"{len(files)} pending observation(s):\n")
    for path in files:
        if "full" in flags:
            print(f"--- {path.name} ---")
            print(platform.read_text(path), end="")
            print()
        else:
            text = platform.read_text(path)
            title = frontmatter.field(text, "title") or ""
            created = frontmatter.field(text, "created") or ""
            print(f"  {_pad(title, 30)}  {created}  [{path.name}]")
    return 0
