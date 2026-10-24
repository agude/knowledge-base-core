"""search: literal and question retrieval, ranking, scopes, output modes, budgets.

Each test pins every command it runs as one transcript golden: the command,
exit code, stdout, and stderr.
"""

from __future__ import annotations

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result


def _pin(kb: KB, golden: Golden, *results: Result) -> None:
    golden.check("transcript", kb.transcript(*results))


def _search(kb: KB, *args: str, env: dict[str, str | None] | None = None) -> Result:
    return kb.run("search", *args, env=env)


FRESH_FRONT = '---\ntitle: "{title}"\nupdated: 2026-08-08\nverified: 2026-08-08\n---\n\n'


# Matching


@pytest.mark.bats("search.bats", "search finds match in knowledge article")
@pytest.mark.audit("A-033")
def test_match_in_article(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "topic.md",
        "---\ntitle: Test\n---\n\n# Topic\n\n## Section One\n\nThe server uses PostgreSQL for storage.",
    )
    _pin(kb, golden, _search(kb, "PostgreSQL"), _search(kb, "--json", "PostgreSQL"))


@pytest.mark.bats("search.bats", "search finds match in pending observations")
def test_match_in_pending(kb: KB, golden: Golden) -> None:
    kb.create_observation(
        "20260412T000000-0000aaaa.md", "Test obs", "Found a bug in the deploy script."
    )
    _pin(kb, golden, _search(kb, "deploy script"), _search(kb, "--json", "deploy script"))


@pytest.mark.bats("search.bats", "search is case-insensitive")
def test_case_insensitive(kb: KB, golden: Golden) -> None:
    kb.create_article("topic.md", "# Topic\n\n## Info\n\nPostgreSQL is the database.")
    _pin(kb, golden, _search(kb, "postgresql"), _search(kb, "POSTGRESQL"))


@pytest.mark.bats("search.bats", "search returns nothing for no match")
@pytest.mark.bats("search.bats", "search handles empty content directories")
def test_no_match(kb: KB, golden: Golden) -> None:
    empty = _search(kb, "anything")
    kb.create_article("topic.md", "# Topic\n\n## Info\n\nSome content.")
    _pin(
        kb, golden, empty, _search(kb, "zzzznonexistent"), _search(kb, "--json", "zzzznonexistent")
    )


@pytest.mark.bats("search.bats", "search works when first file has no match")
def test_first_file_without_match(kb: KB, golden: Golden) -> None:
    kb.create_article("aaa-no-match.md", "# No Match\n\n## Section\n\nNothing relevant here.")
    kb.create_article(
        "zzz-has-match.md", "# Has Match\n\n## Found It\n\nThe PostgreSQL server is running."
    )
    _pin(kb, golden, _search(kb, "PostgreSQL"))


@pytest.mark.bats("search.bats", "search ANDs multiple terms within a file")
@pytest.mark.bats("search.bats", "search prints every line matching any term")
def test_multiple_terms(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "both.md", "# Both\n\n## Info\n\nThe Synology NAS is upstairs.\nIt runs Docker containers."
    )
    kb.create_article("one.md", "# One\n\n## Info\n\nThe Synology unit is upstairs.")
    _pin(kb, golden, _search(kb, "synology", "docker"), _search(kb, "--json", "synology", "docker"))


@pytest.mark.bats("search.bats", "search treats a multi-word argument as one phrase")
def test_phrase_argument(kb: KB, golden: Golden) -> None:
    kb.create_article("phrase.md", "# Phrase\n\n## Info\n\nA Synology NAS lives here.")
    kb.create_article("split.md", "# Split\n\n## Info\n\nSynology makes it. A NAS is a NAS.")
    _pin(kb, golden, _search(kb, "synology nas"))


# Arguments


@pytest.mark.bats("search.bats", "search rejects an unknown option instead of searching for it")
@pytest.mark.bats("search.bats", "search -- treats a leading-dash term literally")
@pytest.mark.bats("search.bats", "search with no terms exits nonzero")
@pytest.mark.bats("search.bats", "search rejects a non-numeric limit")
@pytest.mark.bats("search.bats", "search rejects an invalid byte budget")
def test_arguments(kb: KB, golden: Golden) -> None:
    kb.create_article("flags.md", "# Flags\n\n## Info\n\nNever pass --no-verify to git commit.")
    _pin(
        kb,
        golden,
        _search(kb, "--all"),
        _search(kb, "--", "--no-verify"),
        _search(kb),
        _search(kb, "--limit", "lots", "widgets"),
        _search(kb, "--per-file", "x", "widgets"),
        _search(kb, "--max-bytes", "nope", "widgets"),
        _search(kb, "--limit"),
    )


@pytest.mark.bats("search.bats", "search treats leading-zero byte budgets as decimal")
def test_leading_zero_budget(kb: KB, golden: Golden) -> None:
    kb.create_article("budget.md", "# Budget\n\nneedle")
    _pin(kb, golden, _search(kb, "--json", "--max-bytes", "01000", "needle"))


# Locators


@pytest.mark.bats("search.bats", "search shows 'top' when match is before any H2")
def test_top_locator(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "topic.md",
        '---\ntitle: "Matched in frontmatter"\n---\n\n# Topic\n\nPreamble with target_word here.',
    )
    _pin(kb, golden, _search(kb, "--json", "target_word"), _search(kb, "target_word"))


@pytest.mark.bats("search.bats", "search exposes H2 numbers for duplicate headings")
def test_duplicate_heading_numbers(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "duplicate.md",
        "# Duplicate\n\n## Same heading\n\nfirst needle\n\n## Same heading\n\nsecond needle",
    )
    _pin(
        kb,
        golden,
        _search(kb, "--json", "--limit", "0", "--per-file", "0", "needle"),
        _search(kb, "--limit", "0", "--per-file", "0", "needle"),
    )


# Ranking


@pytest.mark.bats("search.bats", "search ranks a title match above a body match")
def test_title_above_body(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "exact.md",
        FRESH_FRONT.format(title="Bind Mounts on Synology")
        + "# Bind Mounts on Synology\n\n## Setup\n\nDetails.",
    )
    kb.create_article(
        "passing.md",
        FRESH_FRONT.format(title="Home Lab Overview")
        + "# Home Lab Overview\n\n## Machines\n\nOne line mentions bind mounts in passing.",
    )
    _pin(kb, golden, _search(kb, "--files", "bind mounts"), _search(kb, "bind mounts"))


@pytest.mark.bats("search.bats", "search ranks an exact title above repeated body mentions")
def test_exact_title_above_repetition(kb: KB, golden: Golden) -> None:
    kb.create_article("exact.md", '---\ntitle: "Bind Mounts"\n---\n\n# Notes\n\nDocumentation.')
    kb.create_article("repeated.md", "# Repeated\n\n## Notes\n\n" + "bind mounts\n" * 5)
    _pin(
        kb,
        golden,
        _search(kb, "--json", "--limit", "2", "--per-file", "0", "bind mounts"),
        _search(kb, "--limit", "1", "bind mounts"),
    )


@pytest.mark.bats("search.bats", "search counts repeated identical evidence once")
def test_repeated_evidence_once(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "repeated.md", "# Repeated\n\n## Notes\n\nsame evidence\nsame evidence\nsame evidence"
    )
    _pin(kb, golden, _search(kb, "--json", "--per-file", "0", "same evidence"))


@pytest.mark.bats(
    "search.bats", "search ranks a section containing all terms above file-level fallback"
)
def test_complete_section_above_fallback(kb: KB, golden: Golden) -> None:
    kb.create_article("split.md", "# Split\n\n## First\n\nalpha\n\n## Second\n\nbeta")
    kb.create_article("complete.md", "# Complete\n\n## All terms\n\nalpha beta")
    _pin(kb, golden, _search(kb, "--json", "--limit", "0", "--per-file", "0", "alpha", "beta"))


@pytest.mark.bats("search.bats", "search ranks complete coverage above title and heading fallback")
def test_complete_coverage_above_title_heading(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "title-heading-fallback.md",
        '---\ntitle: "alpha"\n---\n\n# Notes\n\n## beta\n\nThe terms are split between the title and heading.',
    )
    kb.create_article("complete.md", "# Complete\n\n## Unrelated\n\nalpha beta")
    _pin(kb, golden, _search(kb, "--json", "--limit", "0", "--per-file", "0", "alpha", "beta"))


@pytest.mark.bats("search.bats", "search excerpt selects the strongest evidence line")
def test_strongest_excerpt(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "excerpt.md",
        "# Excerpt\n\n## Notes\n\nrelevant\ncontext\nrelevant context is the useful evidence\nother relevant line",
    )
    _pin(kb, golden, _search(kb, "--json", "--per-file", "0", "relevant", "context"))


@pytest.mark.bats("search.bats", "search ranks a heading match above a body match")
def test_heading_above_body(kb: KB, golden: Golden) -> None:
    kb.create_article("heading.md", "# A\n\n## Docker networking\n\nContent.")
    kb.create_article("body.md", "# B\n\n## Other\n\nWe mention docker here in prose.")
    _pin(kb, golden, _search(kb, "--files", "docker"), _search(kb, "docker"))


@pytest.mark.bats("search.bats", "search never prints frontmatter lines as results")
def test_no_front_matter_results(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "fm.md",
        FRESH_FRONT.format(title="Postgres Notes")
        + "# Postgres Notes\n\n## Setup\n\nThe server runs Postgres.",
    )
    _pin(kb, golden, _search(kb, "postgres"))


# Limits


def _widgets(kb: KB, count: int, lines: int) -> None:
    body = "\n".join(f"Line {n} about widgets here." for n in range(1, lines + 1))
    for index in range(1, count + 1):
        kb.create_article(f"topic{index}.md", f"# Topic {index}\n\n## Section\n\n{body}")


@pytest.mark.bats("search.bats", "search caps output at --limit and says what it dropped")
def test_limit(kb: KB, golden: Golden) -> None:
    _widgets(kb, 8, 4)
    _pin(kb, golden, _search(kb, "--limit", "5", "widgets"), _search(kb, "widgets"))


@pytest.mark.bats("search.bats", "search --limit 0 prints everything")
def test_limit_zero(kb: KB, golden: Golden) -> None:
    _widgets(kb, 8, 1)
    _pin(kb, golden, _search(kb, "--limit", "0", "--per-file", "0", "widgets"))


@pytest.mark.bats("search.bats", "search caps sections from a single file with --per-file")
def test_per_file(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "many.md",
        "# Many\n\n## First\n\nwidgets one\n\n## Second\n\nwidgets two\n\n## Third\n\nwidgets three",
    )
    _pin(
        kb,
        golden,
        _search(kb, "--per-file", "2", "--limit", "0", "widgets"),
        _search(kb, "--limit", "0", "widgets"),
    )


# Corpora


@pytest.mark.bats("search.bats", "search skips the archive unless asked")
@pytest.mark.bats("search.bats", "search --archive includes open questions")
def test_archive_and_questions(kb: KB, golden: Golden) -> None:
    (kb.layout.content / "observations" / "archived" / "20260412T000000-0000cccc.md").write_text(
        '---\ntitle: "Old note"\n---\n\nSomething about kubernetes and kafka.\n', encoding="utf-8"
    )
    kb.create_question("20260412T000000-0000dddd.md", "Who owns the kafka cluster?")
    _pin(
        kb,
        golden,
        _search(kb, "kubernetes"),
        _search(kb, "--archive", "kubernetes"),
        _search(kb, "kafka"),
        _search(kb, "--archive", "kafka"),
    )
