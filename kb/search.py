"""Ranking Markdown sections for search: a port of the awk program in scripts/search.

Each file yields one candidate per section that mentions a term, plus a
title candidate when the title holds every term. A section containing every
term outranks file-level fallbacks whose terms are split across the file;
title and heading matches outrank body evidence; repeated identical lines
count once; the two best evidence lines form the excerpt.

The heading rules here are search's own, as in bash: any run of hashes
followed by whitespace is a heading line, an H1 returns to the top section,
and an H3 opens a section only under an H2.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from kb import platform

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "please",
        "should",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "they",
        "this",
        "to",
        "use",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)
EXCERPT_LENGTH = 120
SPACE = " \t\n\r\v\f"  # awk's [[:space:]], without Python's extra separators.
FRONT_MATTER_FENCE = re.compile(r"---\s*")
METADATA_START = re.compile(r"[ \t]*<!-- kb-section:")
HEADING = re.compile(r"#+\s")
ALIAS_ITEM = re.compile(r"\s*-\s+")


def question_terms(question: str) -> list[str]:
    """Deterministic literal terms from a natural-language question (question_terms)."""
    terms: list[str] = []
    seen: set[str] = set()
    quote_open = False
    for raw in question.split("\n"):
        text = re.sub(r"[^\w/.:@+\-']", " ", raw.lower())
        for word in re.split(r"\s+", text):
            if not word:
                continue
            if not word.startswith(("/", "-")):
                word = re.sub(r"^[+:]+", "", word)
                word = re.sub(r"[+:]+$", "", word)
            if not word.endswith("/"):
                word = re.sub(r"\.+$", "", word)
            if word.startswith("'"):
                word = word.lstrip("'")
                quote_open = True
            if quote_open and word.endswith("'"):
                word = word.rstrip("'")
                quote_open = False
            if word and word not in STOPWORDS and word not in seen:
                terms.append(word)
                seen.add(word)
    return terms


@dataclass
class Candidate:
    tier: int
    score: int
    path: str
    order: int  # Section index; 0 for the title, -1 for an alias routing result.
    section: str
    number: str
    command: str
    title: str
    match_count: int
    evidence_count: int
    routing: bool
    alias: str
    line: int
    excerpt: str


@dataclass
class _Section:
    name: str
    number: str
    hits: set[int] = field(default_factory=set)
    heading_hits: set[int] = field(default_factory=set)
    body_hits: set[int] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    excerpts: list[tuple[int, int, str]] = field(default_factory=list)  # (score, line, text)

    def add_excerpt(self, number: int, line: str, score: int) -> None:
        text = line.strip(SPACE)[:EXCERPT_LENGTH]
        if text in self.seen:
            return
        self.seen.add(text)
        if len(self.excerpts) < 2:
            self.excerpts.append((score, number, text))
            return
        lowest = 1 if self.excerpts[1][0] < self.excerpts[0][0] else 0
        if score > self.excerpts[lowest][0]:
            self.excerpts[lowest] = (score, number, text)

    def _ordered(self) -> list[tuple[int, int, str]]:
        if len(self.excerpts) == 2:
            first, second = self.excerpts
            if second[0] > first[0] or (second[0] == first[0] and second[1] < first[1]):
                return [second, first]
        return self.excerpts

    @property
    def excerpt(self) -> str:
        return " ... ".join(text for _, _, text in self._ordered())

    @property
    def excerpt_line(self) -> int:
        return self._ordered()[0][1]


class _Fence:
    def __init__(self) -> None:
        self.char = ""
        self.length = 0

    def check(self, line: str) -> bool:
        """True for a fence delimiter line, opening or closing (search's fence_check)."""
        lead = len(line) - len(line.lstrip(" "))
        if lead > 3:
            return False
        char = line[lead : lead + 1]
        if char not in ("`", "~"):
            return False
        count = len(line[lead:]) - len(line[lead:].lstrip(char))
        if count < 3:
            return False
        info = line[lead + count :]
        if not self.char:
            if char == "`" and "`" in info:
                return False
            self.char, self.length = char, count
            return True
        if char == self.char and count >= self.length and not re.sub(r"[ \t]", "", info):
            self.char, self.length = "", 0
        return True


def rank_file(
    relpath: str, path: Path, terms: list[str], *, relaxed: bool, aliases: bool, files_only: bool
) -> list[Candidate]:
    """The candidates one file contributes (the awk program's per-file pass and emit)."""
    lines = platform.read_text(path).split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    terms = [t.lower() for t in terms]
    n = len(terms)
    file_hits: set[int] = set()
    title_hits: set[int] = set()
    sections = [_Section("top", "")]
    current = 0
    in_fm = in_metadata = in_aliases = False
    alias = ""
    title = ""
    fence = _Fence()
    h2 = h3 = 0
    for number, line in enumerate(lines, start=1):
        lower = line.lower()
        if number == 1 and FRONT_MATTER_FENCE.fullmatch(line):
            in_fm = True
            continue
        if in_fm:
            if FRONT_MATTER_FENCE.fullmatch(line):
                in_fm = in_aliases = False
                continue
            if aliases and re.fullmatch(r"aliases:\s*", line):
                in_aliases = True
                continue
            if in_aliases and ALIAS_ITEM.match(line):
                value = re.sub(
                    r'"\s*$', "", re.sub(r'^"', "", ALIAS_ITEM.sub("", line, count=1)), count=1
                )
                found = sum(1 for t in terms if t in value.lower())
                if (relaxed and found > 0) or (not relaxed and found == n):
                    alias = value
                    file_hits.update(range(n))
                continue
            if in_aliases:
                in_aliases = False
            if line.startswith("title:"):
                title = re.sub(r'^"|"$', "", line[6:].strip(SPACE))
                for index, term in enumerate(terms):
                    if term in title.lower():
                        title_hits.add(index)
                        file_hits.add(index)
            continue
        if in_metadata:
            closing = line.find("-->")
            if closing < 0:
                continue
            in_metadata = False
            line = line[closing + 3 :]
            lower = line.lower()
        elif not fence.char and METADATA_START.match(line):
            closing = line.find("-->")
            if closing < 0:
                in_metadata = True
                continue
            line = line[closing + 3 :]
            lower = line.lower()
        if fence.check(line):
            continue
        heading = False
        if not fence.char and HEADING.match(line):
            heading = True
            hashes = len(line) - len(line.lstrip("#"))
            text = re.sub(r"\s*#+$", "", line[hashes:].strip(SPACE))
            if hashes == 2:
                h2, h3 = h2 + 1, 0
                sections.append(_Section(text, str(h2)))
                current = len(sections) - 1
            elif hashes == 3 and h2 > 0:
                h3 += 1
                sections.append(_Section(text, f"{h2}.{h3}"))
                current = len(sections) - 1
            elif hashes == 1:
                current = 0
        matched = [index for index, term in enumerate(terms) if term in lower]
        if not matched:
            continue
        section = sections[current]
        for index in matched:
            file_hits.add(index)
            section.hits.add(index)
            (section.heading_hits if heading else section.body_hits).add(index)
        section.add_excerpt(number, line, (40 if heading else 20) + len(matched) * 10)

    if relaxed:
        admitted = bool(file_hits) or (aliases and bool(alias))
    else:
        admitted = (aliases and bool(alias)) or len(file_hits) == n
    if not admitted:
        return []

    def score(section: _Section) -> int:
        total = 0
        for index in section.hits:
            total += 90 if index in title_hits else 0
            total += 30 if index in section.heading_hits else 0
            total += 8 if index in section.body_hits else 0
        total += 80 if len(section.hits) == n else -20
        return total + min(len(section.seen), 4) * 2

    found: list[tuple[int, int, int]] = []  # (tier, score, section index or 0 for the title)
    for index, section in enumerate(sections, start=1):
        if section.hits:
            found.append((1 if len(section.hits) == n else 0, score(section), index))
    if len(title_hits) == n:
        found.append((2, len(title_hits) * 100 + 80, 0))
    complete = sum(1 for tier, _, _ in found if tier >= 1)
    if alias and not relaxed and complete == 0:
        found = []
    routing = False
    if not found and alias:
        found, routing = [(1, 70, -1)], True
    if not found:
        return []
    count = len(found)
    if files_only:
        tier, best = max((tier, score_) for tier, score_, _ in found)
        return [
            Candidate(
                tier, best, relpath, 0, "-", "-", "-", title, count, count, routing, alias, 0, ""
            )
        ]
    out = []
    for tier, score_, index in found:
        if index == -1:
            out.append(
                Candidate(
                    tier,
                    score_,
                    relpath,
                    -1,
                    "alias",
                    "",
                    "--alias",
                    title,
                    count,
                    0,
                    True,
                    alias,
                    0,
                    alias,
                )
            )
        elif index == 0:
            out.append(
                Candidate(
                    tier,
                    score_,
                    relpath,
                    0,
                    "title",
                    "",
                    "--title",
                    title,
                    count,
                    1,
                    False,
                    alias,
                    1,
                    title,
                )
            )
        else:
            section = sections[index - 1]
            out.append(
                Candidate(
                    tier,
                    score_,
                    relpath,
                    index,
                    section.name,
                    section.number,
                    "--top" if index == 1 else "",
                    title,
                    count,
                    len(section.seen),
                    False,
                    alias,
                    section.excerpt_line,
                    section.excerpt,
                )
            )
    return out


def ranked(candidates: list[Candidate]) -> list[Candidate]:
    """Tier and score descending, then path (bytes) and section order ascending."""
    return sorted(
        candidates,
        key=lambda c: (
            -c.tier,
            -c.score,
            c.path.encode("utf-8", errors="surrogateescape"),
            c.order,
        ),
    )
