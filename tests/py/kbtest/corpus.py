"""Generate a synthetic content tree shaped like the live knowledge base.

The counts and size quantiles below were measured on the live knowledge base
on 2026-10-24 (210 articles, 2,489 archived observations). generate() writes
`scale` times as many files of each kind, with file sizes and section counts
drawn from the same distributions. The text is pseudo-words, so no live
content leaves the knowledge base.

The same seed and scale produce a byte-identical tree. Only `random.Random`
with that seed is consulted; no clock, locale, or hash order.

Usage: python -m kbtest.corpus DEST [--scale N] [--seed S]
"""

from __future__ import annotations

import argparse
import bisect
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Percentile points that the quantile tables below are sampled at.
PERCENTILES = (
    0,
    5,
    10,
    15,
    20,
    25,
    30,
    35,
    40,
    45,
    50,
    55,
    60,
    65,
    70,
    75,
    80,
    85,
    90,
    95,
    98,
    99,
    100,
)

# Live counts at scale 1.
COUNTS = {
    "article": 210,
    "archived": 2489,
    "pending": 18,
    "open": 44,
    "resolved": 13,
}
DIRECTORIES = 16  # knowledge/ subdirectories at scale 1.

# File sizes in bytes, one value per entry in PERCENTILES.
SIZES = {
    "article": (
        497,
        1069,
        1354,
        1605,
        1817,
        2031,
        2261,
        2694,
        2961,
        3224,
        3471,
        3956,
        4332,
        4757,
        5282,
        6374,
        7749,
        9145,
        10339,
        12058,
        16456,
        19048,
        24517,
    ),
    "observation": (
        103,
        373,
        467,
        530,
        586,
        646,
        702,
        785,
        880,
        1024,
        1170,
        1435,
        1837,
        2384,
        3435,
        4807,
        6713,
        9308,
        14211,
        25411,
        44553,
        57560,
        294902,
    ),
    "question": (
        298,
        308,
        328,
        347,
        366,
        380,
        406,
        420,
        434,
        524,
        548,
        582,
        599,
        652,
        708,
        723,
        755,
        830,
        897,
        1025,
        1058,
        1058,
        1211,
    ),
}
SECTIONS = (1, 1, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 6, 6, 6, 7, 8, 9, 10, 12, 13, 17, 20)
SOURCES = (0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 5, 6, 7, 8, 10, 11, 13, 15, 26, 49, 55, 154)
SUBSECTION_SHARE = 0.04  # Share of headings that are `###`.
TTLS = (90, 180, 365)

# Dates are relative to this instant, the harness's fixed clock.
EPOCH = datetime(2026, 10, 23, tzinfo=UTC)
HISTORY_DAYS = 240

SYLLABLES = (
    "ka",
    "lo",
    "mi",
    "ne",
    "ru",
    "sa",
    "ti",
    "vo",
    "ze",
    "ba",
    "do",
    "fi",
    "gu",
    "ha",
    "je",
    "ko",
    "la",
    "mu",
    "no",
    "pe",
    "qui",
    "ra",
    "se",
    "to",
    "un",
    "ve",
    "wa",
    "xi",
    "yo",
    "zu",
)
VOCABULARY_SIZE = 4000

# Words that appear with a fixed share of articles, so benchmark queries have
# predictable hit counts: (word, share of articles).
MARKERS = (("benchmarkalpha", 0.5), ("benchmarkbeta", 0.05), ("benchmarkgamma", 0.005))


def _vocabulary(rng: random.Random) -> list[str]:
    words: set[str] = set()
    ordered = []
    while len(ordered) < VOCABULARY_SIZE:
        word = "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 4)))
        if word not in words:
            words.add(word)
            ordered.append(word)
    return ordered


class _Text:
    """Zipf-distributed pseudo-words."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.words = _vocabulary(rng)
        weights = [1 / (rank + 1) for rank in range(len(self.words))]
        self.cumulative = []
        total = 0.0
        for weight in weights:
            total += weight
            self.cumulative.append(total)

    def word(self) -> str:
        point = self.rng.random() * self.cumulative[-1]
        return self.words[min(bisect.bisect_left(self.cumulative, point), len(self.words) - 1)]

    def phrase(self, low: int, high: int) -> str:
        return " ".join(self.word() for _ in range(self.rng.randint(low, high)))

    def paragraphs(self, size: int, extra: tuple[str, ...] = ()) -> str:
        """Paragraphs of about `size` bytes, with each word in `extra` placed once."""
        out: list[str] = []
        length = 0
        pending = list(extra)
        while length < size or pending:
            sentence = self.phrase(6, 18).capitalize()
            if pending:
                sentence += " " + pending.pop()
            sentence += "."
            out.append(sentence)
            length += len(sentence) + 1
            if self.rng.random() < 0.2:
                out.append("\n\n")
        return " ".join(out).replace(" \n\n ", "\n\n").strip()


def _quantile(rng: random.Random, table: tuple[int, ...]) -> float:
    """Sample a value whose distribution interpolates the quantile table."""
    point = rng.random() * 100
    index = min(bisect.bisect_right(PERCENTILES, point), len(PERCENTILES) - 1)
    lo_p, hi_p = PERCENTILES[index - 1], PERCENTILES[index]
    lo_v, hi_v = table[index - 1], table[index]
    fraction = (point - lo_p) / (hi_p - lo_p)
    if lo_v > 0 and hi_v > 0:
        return math.exp(math.log(lo_v) + fraction * (math.log(hi_v) - math.log(lo_v)))
    return lo_v + fraction * (hi_v - lo_v)


def _stamp(rng: random.Random) -> datetime:
    return EPOCH - timedelta(seconds=rng.randrange(HISTORY_DAYS * 86400))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def _observation_name(rng: random.Random, used: set[str]) -> tuple[str, datetime]:
    while True:
        created = _stamp(rng)
        name = f"{created:%Y%m%dT%H%M%S}-{rng.getrandbits(32):08x}.md"
        if name not in used:
            used.add(name)
            return name, created


def _header(fields: list[str]) -> str:
    return "---\n" + "".join(f"{field}\n" for field in fields) + "---\n\n"


def _observations(root: Path, rng: random.Random, text: _Text, scale: int) -> list[str]:
    used: set[str] = set()
    archived = []
    for kind in ("archived", "pending"):
        for _ in range(COUNTS[kind] * scale):
            name, created = _observation_name(rng, used)
            title = text.phrase(3, 9).capitalize()
            head = _header(
                [f'title: "{title}"', "source: session", f"created: {created:%Y-%m-%dT%H:%M:%SZ}"]
            )
            size = max(int(_quantile(rng, SIZES["observation"])) - len(head), 20)
            _write(root / "observations" / kind / name, head + text.paragraphs(size) + "\n")
            if kind == "archived":
                archived.append(name)
    return archived


def _directories(rng: random.Random, text: _Text, count: int) -> list[str]:
    """Top-level areas, with about one in five holding a subdirectory."""
    names: list[str] = []
    while len(names) < count:
        area = text.words[len(names) * 7 % VOCABULARY_SIZE] + f"-{len(names)}"
        names.append(area)
        if len(names) < count and rng.random() < 0.2:
            names.append(f"{area}/{text.word()}")
    return names


def _articles(
    root: Path, rng: random.Random, text: _Text, scale: int, archived: list[str]
) -> list[str]:
    directories = _directories(rng, text, DIRECTORIES * scale)
    paths = []
    for index in range(COUNTS["article"] * scale):
        directory = directories[index % len(directories)]
        rel = f"knowledge/{directory}/{text.word()}-{index}.md"
        title = text.phrase(2, 6).title()
        updated = _stamp(rng)
        verified = updated - timedelta(days=rng.randrange(120))
        sources = rng.sample(archived, min(int(_quantile(rng, SOURCES)), len(archived)))
        fields = [
            f'title: "{title}"',
            f"updated: {updated:%Y-%m-%d}",
            f"verified: {verified:%Y-%m-%d}",
            f"ttl: {rng.choice(TTLS)}",
        ]
        if sources:
            fields.append("sources:")
            fields += [f"  - observations/archived/{name}" for name in sources]
        head = _header(fields) + f"# {title}\n\n"
        markers = tuple(word for word, share in MARKERS if rng.random() < share)
        sections = max(int(_quantile(rng, SECTIONS)), 1)
        budget = max(int(_quantile(rng, SIZES["article"])) - len(head), 40 * sections)
        parts = []
        for number in range(sections):
            level = "###" if number and rng.random() < SUBSECTION_SHARE else "##"
            body = text.paragraphs(budget // sections, markers if number == 0 else ())
            parts.append(f"{level} {text.phrase(1, 4).title()}\n\n{body}\n")
        _write(root / rel, head + "\n".join(parts))
        paths.append(rel)
    return paths


def _questions(
    root: Path, rng: random.Random, text: _Text, scale: int, articles: list[str]
) -> None:
    used: set[str] = set()
    for kind in ("open", "resolved"):
        for _ in range(COUNTS[kind] * scale):
            name, created = _observation_name(rng, used)
            fields = [
                f'title: "{text.phrase(5, 12).capitalize()}?"',
                "source: session",
                f"context: {rng.choice(articles)}",
                f"created: {created:%Y-%m-%dT%H:%M:%SZ}",
            ]
            head = _header(fields)
            size = max(int(_quantile(rng, SIZES["question"])) - len(head), 20)
            body = text.paragraphs(size)
            if kind == "resolved":
                body += f"\n\n## Answer\n\n{text.paragraphs(80)}"
            _write(root / "questions" / kind / name, head + body + "\n")


def generate(dest: Path, *, scale: int = 10, seed: int = 0) -> None:
    """Write a content tree (without .git) into dest, which must not exist."""
    if dest.exists():
        raise FileExistsError(dest)
    rng = random.Random(seed)
    text = _Text(rng)
    for sub in (
        "knowledge",
        "observations/pending",
        "observations/archived",
        "questions/open",
        "questions/resolved",
        "sources",
    ):
        (dest / sub).mkdir(parents=True)
    (dest / "sources" / ".gitkeep").touch()
    archived = _observations(dest, rng, text, scale)
    articles = _articles(dest, rng, text, scale, archived)
    _questions(dest, rng, text, scale, articles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dest", type=Path)
    parser.add_argument("--scale", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    generate(args.dest, scale=args.scale, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
