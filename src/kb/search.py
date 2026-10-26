"""Search: query terms, field-weighted BM25 ranking with a qualification threshold, and excerpts.

Every function here takes values and returns values. The caller reads the
files, builds the units, and formats the output.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from kb.model import Document

STOPWORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "s",
        "t",
        "d",
        "ll",
        "m",
        "o",
        "re",
        "ve",
        "y",
    ]
)
# Dates, paths, flags, and words. Flags come first, so "--no-verify" stays whole, and
# a path needs a slash, so "nas.md" is a word and "knowledge/nas.md" is one token.
TOKEN = re.compile(
    r"--[a-z0-9][a-z0-9_-]*"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"|[a-z0-9_.-]*(?:/[a-z0-9_.-]+)+"
    r"|[^\W_]+(?:'[^\W_]+)*"
)
TITLE_WEIGHT = 3.0
ALIAS_WEIGHT = 3.0
HEADING_WEIGHT = 2.0
BODY_WEIGHT = 1.0
K1 = 1.2
B = 0.75


@dataclass(frozen=True)
class Unit:
    """The searchable fields of one unit: a section, a top, or an evidence file."""

    title: tuple[str, ...]
    aliases: tuple[str, ...]
    headings: tuple[str, ...]
    body: tuple[str, ...]
    phrases: frozenset[str]


@dataclass(frozen=True)
class Candidate:
    """A curated unit: its fragment ("top" or an H2 key), its heading, and its unit."""

    fragment: str
    heading: str
    unit: Unit


@dataclass(frozen=True)
class Hit:
    """A unit that qualifies, by its position in the list ranked, and its score."""

    index: int
    score: float


@dataclass(frozen=True)
class _Profile:
    frequency: dict[str, float]
    length: float


def tokenize(text: str) -> list[str]:
    """The lowercase tokens of text, stopwords included."""
    return [match.group(0).rstrip(".") for match in TOKEN.finditer(text.lower())]


def index_tokens(text: str) -> tuple[str, ...]:
    """The tokens of text that are not stopwords."""
    return tuple(token for token in tokenize(text) if token not in STOPWORDS)


def query_terms(words: Sequence[str]) -> tuple[str, ...]:
    """The distinct, non-stopword terms of a query, in the order they first appear."""
    return tuple(dict.fromkeys(index_tokens(" ".join(words))))


def make_unit(
    title: str, aliases: Sequence[str], headings: Sequence[str], body: Sequence[str]
) -> Unit:
    """A unit from its title, aliases, headings, and body lines."""
    title_tokens = index_tokens(title)
    alias_tokens = [index_tokens(alias) for alias in aliases]
    heading_tokens = [index_tokens(heading) for heading in headings]
    phrases = {
        " ".join(tokens) for tokens in [title_tokens, *alias_tokens, *heading_tokens] if tokens
    }
    return Unit(
        title=title_tokens,
        aliases=tuple(token for tokens in alias_tokens for token in tokens),
        headings=tuple(token for tokens in heading_tokens for token in tokens),
        body=tuple(token for line in body for token in index_tokens(line)),
        phrases=frozenset(phrases),
    )


def article_candidates(document: Document) -> list[Candidate]:
    """The curated units of one article: its top when it has prose, and each H2 section."""
    title = document.title or ""
    aliases = document.items("aliases")
    candidates: list[Candidate] = []
    top = document.prose(document.body_start, document.top_end)
    if top:
        heading = document.h1 or title or PurePosixPath(document.path).stem
        unit = make_unit(title, aliases, document.top_headings, top)
        candidates.append(Candidate("top", heading, unit))
    for section in document.sections:
        if section.level != 2:
            continue
        subheadings = [child.heading for child in document.sections if child.parent == section.key]
        unit = make_unit(
            title,
            aliases,
            [section.heading, *subheadings],
            document.prose(section.start, section.end),
        )
        candidates.append(Candidate(section.key, section.heading, unit))
    return candidates


def rank(units: Sequence[Unit], terms: Sequence[str]) -> list[Hit]:
    """The units that qualify, best first. Ties keep their input order.

    A unit qualifies when it holds at least half of the distinct terms, rounded
    up, or when the whole query equals its title, an alias, or a heading.
    """
    if not terms or not units:
        return []
    profiles = [_profile(unit, terms) for unit in units]
    total = sum(profile.length for profile in profiles)
    average = total / len(units) or 1.0
    documents_with: dict[str, int] = {}
    for profile in profiles:
        for term in profile.frequency:
            documents_with[term] = documents_with.get(term, 0) + 1
    needed = math.ceil(len(terms) / 2)
    phrase = " ".join(terms)
    hits: list[Hit] = []
    for index, (unit, profile) in enumerate(zip(units, profiles, strict=True)):
        if len(profile.frequency) < needed and phrase not in unit.phrases:
            continue
        norm = K1 * (1 - B + B * profile.length / average)
        score = 0.0
        for term, frequency in profile.frequency.items():
            df = documents_with[term]
            idf = math.log(1 + (len(units) - df + 0.5) / (df + 0.5))
            score += idf * frequency * (K1 + 1) / (frequency + norm)
        hits.append(Hit(index, score))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits


def _profile(unit: Unit, terms: Sequence[str]) -> _Profile:
    fields = (
        (unit.title, TITLE_WEIGHT),
        (unit.aliases, ALIAS_WEIGHT),
        (unit.headings, HEADING_WEIGHT),
        (unit.body, BODY_WEIGHT),
    )
    length = sum(weight * len(tokens) for tokens, weight in fields)
    frequency: dict[str, float] = {}
    for term in terms:
        count = sum(weight * tokens.count(term) for tokens, weight in fields)
        if count:
            frequency[term] = count
    return _Profile(frequency, length)
