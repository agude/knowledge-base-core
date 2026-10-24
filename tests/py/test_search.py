"""search: literal and question retrieval, ranking, scopes, output modes, budgets.

Each test pins every command it runs as one transcript golden: the command,
exit code, stdout, and stderr.
"""

from __future__ import annotations

import json
import re
import shutil

import pytest

from kbtest.golden import Golden
from kbtest.impl import REPO
from kbtest.runner import KB, Result


def _pin(kb: KB, golden: Golden, *results: Result) -> None:
    golden.check("transcript", kb.transcript(*results))


def _search(kb: KB, *args: str, env: dict[str, str | None] | None = None) -> Result:
    return kb.run("search", *args, env=env)


FRESH_FRONT = '---\ntitle: "{title}"\nupdated: 2026-08-08\nverified: 2026-08-08\n---\n\n'


# Matching


@pytest.mark.bats("search.bats", "search finds match in knowledge article")
def test_match_in_article(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "topic.md",
        "---\ntitle: Test\n---\n\n# Topic\n\n## Section One\n\nThe server uses PostgreSQL for storage.",
    )
    assert _hits(kb, "PostgreSQL") == [("knowledge/topic.md", "Section One")]
    _pin(kb, golden, _search(kb, "PostgreSQL"), _search(kb, "--json", "PostgreSQL"))


@pytest.mark.bats("search.bats", "search finds match in pending observations")
def test_match_in_pending(kb: KB, golden: Golden) -> None:
    kb.create_observation(
        "20260412T000000-0000aaaa.md", "Test obs", "Found a bug in the deploy script."
    )
    assert [path for path, _ in _hits(kb, "deploy script")] == [
        "observations/pending/20260412T000000-0000aaaa.md"
    ]
    _pin(kb, golden, _search(kb, "deploy script"), _search(kb, "--json", "deploy script"))


@pytest.mark.bats("search.bats", "search is case-insensitive")
def test_case_insensitive(kb: KB, golden: Golden) -> None:
    kb.create_article("topic.md", "# Topic\n\n## Info\n\nPostgreSQL is the database.")
    for term in ("postgresql", "POSTGRESQL"):
        assert [path for path, _ in _hits(kb, term)] == ["knowledge/topic.md"]
    _pin(kb, golden, _search(kb, "postgresql"), _search(kb, "POSTGRESQL"))


@pytest.mark.bats("search.bats", "search returns nothing for no match")
@pytest.mark.bats("search.bats", "search handles empty content directories")
def test_no_match(kb: KB, golden: Golden) -> None:
    empty = _search(kb, "anything")
    kb.create_article("topic.md", "# Topic\n\n## Info\n\nSome content.")
    assert _hits(kb, "zzzznonexistent") == []
    assert empty.returncode == 0 and _paths(empty) == []
    _pin(
        kb, golden, empty, _search(kb, "zzzznonexistent"), _search(kb, "--json", "zzzznonexistent")
    )


@pytest.mark.bats("search.bats", "search works when first file has no match")
def test_first_file_without_match(kb: KB, golden: Golden) -> None:
    kb.create_article("aaa-no-match.md", "# No Match\n\n## Section\n\nNothing relevant here.")
    kb.create_article(
        "zzz-has-match.md", "# Has Match\n\n## Found It\n\nThe PostgreSQL server is running."
    )
    assert [path for path, _ in _hits(kb, "PostgreSQL")] == ["knowledge/zzz-has-match.md"]
    _pin(kb, golden, _search(kb, "PostgreSQL"))


@pytest.mark.bats("search.bats", "search ANDs multiple terms within a file")
@pytest.mark.bats("search.bats", "search prints every line matching any term")
def test_multiple_terms(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "both.md", "# Both\n\n## Info\n\nThe Synology NAS is upstairs.\nIt runs Docker containers."
    )
    kb.create_article("one.md", "# One\n\n## Info\n\nThe Synology unit is upstairs.")
    assert [path for path, _ in _hits(kb, "synology", "docker")] == ["knowledge/both.md"]
    _pin(kb, golden, _search(kb, "synology", "docker"), _search(kb, "--json", "synology", "docker"))


@pytest.mark.bats("search.bats", "search treats a multi-word argument as one phrase")
def test_phrase_argument(kb: KB, golden: Golden) -> None:
    kb.create_article("phrase.md", "# Phrase\n\n## Info\n\nA Synology NAS lives here.")
    kb.create_article("split.md", "# Split\n\n## Info\n\nSynology makes it. A NAS is a NAS.")
    assert [path for path, _ in _hits(kb, "synology nas")] == ["knowledge/phrase.md"]
    _pin(kb, golden, _search(kb, "synology nas"))


# Arguments


@pytest.mark.bats("search.bats", "search rejects an unknown option instead of searching for it")
@pytest.mark.bats("search.bats", "search -- treats a leading-dash term literally")
@pytest.mark.bats("search.bats", "search with no terms exits nonzero")
@pytest.mark.bats("search.bats", "search rejects a non-numeric limit")
@pytest.mark.bats("search.bats", "search rejects an invalid byte budget")
def test_arguments(kb: KB, golden: Golden) -> None:
    kb.create_article("flags.md", "# Flags\n\n## Info\n\nNever pass --no-verify to git commit.")
    for args in (
        ["--all"],
        [],
        ["--limit", "lots", "x"],
        ["--per-file", "x", "x"],
        ["--max-bytes", "nope", "x"],
        ["--limit"],
    ):
        rejected = _search(kb, *args)
        assert rejected.returncode != 0 and rejected.err.strip(), args
    assert [path for path, _ in _hits(kb, "--", "--no-verify")] == ["knowledge/flags.md"]
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
    assert _json(_search(kb, "--json", "--max-bytes", "01000", "needle"))["max_bytes"] == 1000
    _pin(kb, golden, _search(kb, "--json", "--max-bytes", "01000", "needle"))


# Locators


@pytest.mark.bats("search.bats", "search shows 'top' when match is before any H2")
def test_top_locator(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "topic.md",
        '---\ntitle: "Matched in frontmatter"\n---\n\n# Topic\n\nPreamble with target_word here.',
    )
    top = _json(_search(kb, "--json", "target_word"))["results"][0]["locator"]
    assert (top["section"], top["number"], top["command"]) == ("top", None, "--top")
    _pin(kb, golden, _search(kb, "--json", "target_word"), _search(kb, "target_word"))


@pytest.mark.bats("search.bats", "search exposes H2 numbers for duplicate headings")
def test_duplicate_heading_numbers(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "duplicate.md",
        "# Duplicate\n\n## Same heading\n\nfirst needle\n\n## Same heading\n\nsecond needle",
    )
    results = _json(_search(kb, "--json", "--limit", "0", "--per-file", "0", "needle"))["results"]
    assert [(r["locator"]["section"], r["locator"]["number"]) for r in results] == [
        ("Same heading", "1"),
        ("Same heading", "2"),
    ]
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
    # Files rank by their best section: the title match first.
    files = list(dict.fromkeys(path for path, _ in _hits(kb, "--limit", "0", "bind mounts")))
    assert files == ["knowledge/exact.md", "knowledge/passing.md"]
    _pin(kb, golden, _search(kb, "--files", "bind mounts"), _search(kb, "bind mounts"))


@pytest.mark.bats("search.bats", "search ranks an exact title above repeated body mentions")
def test_exact_title_above_repetition(kb: KB, golden: Golden) -> None:
    kb.create_article("exact.md", '---\ntitle: "Bind Mounts"\n---\n\n# Notes\n\nDocumentation.')
    kb.create_article("repeated.md", "# Repeated\n\n## Notes\n\n" + "bind mounts\n" * 5)
    top = _json(_search(kb, "--json", "--limit", "2", "--per-file", "0", "bind mounts"))["results"][
        0
    ]
    assert (top["path"], top["locator"]["section"], top["locator"]["command"]) == (
        "knowledge/exact.md",
        "title",
        "--title",
    )
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
    results = _json(_search(kb, "--json", "--per-file", "0", "same evidence"))["results"]
    assert len(results) == 1 and results[0]["match_count"] == 1
    _pin(kb, golden, _search(kb, "--json", "--per-file", "0", "same evidence"))


@pytest.mark.bats(
    "search.bats", "search ranks a section containing all terms above file-level fallback"
)
def test_complete_section_above_fallback(kb: KB, golden: Golden) -> None:
    kb.create_article("split.md", "# Split\n\n## First\n\nalpha\n\n## Second\n\nbeta")
    kb.create_article("complete.md", "# Complete\n\n## All terms\n\nalpha beta")
    assert _hits(kb, "--limit", "0", "--per-file", "0", "alpha", "beta")[0] == (
        "knowledge/complete.md",
        "All terms",
    )
    _pin(kb, golden, _search(kb, "--json", "--limit", "0", "--per-file", "0", "alpha", "beta"))


@pytest.mark.bats("search.bats", "search ranks complete coverage above title and heading fallback")
def test_complete_coverage_above_title_heading(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "title-heading-fallback.md",
        '---\ntitle: "alpha"\n---\n\n# Notes\n\n## beta\n\nThe terms are split between the title and heading.',
    )
    kb.create_article("complete.md", "# Complete\n\n## Unrelated\n\nalpha beta")
    assert _hits(kb, "--limit", "0", "--per-file", "0", "alpha", "beta")[0] == (
        "knowledge/complete.md",
        "Unrelated",
    )
    _pin(kb, golden, _search(kb, "--json", "--limit", "0", "--per-file", "0", "alpha", "beta"))


@pytest.mark.bats("search.bats", "search excerpt selects the strongest evidence line")
def test_strongest_excerpt(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "excerpt.md",
        "# Excerpt\n\n## Notes\n\nrelevant\ncontext\nrelevant context is the useful evidence\nother relevant line",
    )
    top = _json(_search(kb, "--json", "--per-file", "0", "relevant", "context"))["results"][0]
    assert "relevant context is the useful evidence" in top["text"]
    _pin(kb, golden, _search(kb, "--json", "--per-file", "0", "relevant", "context"))


@pytest.mark.bats("search.bats", "search ranks a heading match above a body match")
def test_heading_above_body(kb: KB, golden: Golden) -> None:
    kb.create_article("heading.md", "# A\n\n## Docker networking\n\nContent.")
    kb.create_article("body.md", "# B\n\n## Other\n\nWe mention docker here in prose.")
    assert _hits(kb, "docker")[0] == ("knowledge/heading.md", "Docker networking")
    _pin(kb, golden, _search(kb, "--files", "docker"), _search(kb, "docker"))


@pytest.mark.bats("search.bats", "search never prints frontmatter lines as results")
def test_no_front_matter_results(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "fm.md",
        FRESH_FRONT.format(title="Postgres Notes")
        + "# Postgres Notes\n\n## Setup\n\nThe server runs Postgres.",
    )
    texts = [
        r["text"] for r in _json(_search(kb, "--json", "--per-file", "0", "postgres"))["results"]
    ]
    assert all("title:" not in text for text in texts)
    assert any("The server runs Postgres" in text for text in texts)
    _pin(kb, golden, _search(kb, "postgres"))


# Limits


def _widgets(kb: KB, count: int, lines: int) -> None:
    body = "\n".join(f"Line {n} about widgets here." for n in range(1, lines + 1))
    for index in range(1, count + 1):
        kb.create_article(f"topic{index}.md", f"# Topic {index}\n\n## Section\n\n{body}")


@pytest.mark.bats("search.bats", "search caps output at --limit and says what it dropped")
def test_limit(kb: KB, golden: Golden) -> None:
    _widgets(kb, 8, 4)
    data = _json(_search(kb, "--json", "--limit", "5", "widgets"))
    assert (data["returned"], data["total_lines"], data["truncated"]) == (5, 8, True)
    _pin(kb, golden, _search(kb, "--limit", "5", "widgets"), _search(kb, "widgets"))


@pytest.mark.bats("search.bats", "search --limit 0 prints everything")
def test_limit_zero(kb: KB, golden: Golden) -> None:
    _widgets(kb, 8, 1)
    assert (
        _json(_search(kb, "--json", "--limit", "0", "--per-file", "0", "widgets"))["returned"] == 8
    )
    _pin(kb, golden, _search(kb, "--limit", "0", "--per-file", "0", "widgets"))


@pytest.mark.bats("search.bats", "search caps sections from a single file with --per-file")
def test_per_file(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "many.md",
        "# Many\n\n## First\n\nwidgets one\n\n## Second\n\nwidgets two\n\n## Third\n\nwidgets three",
    )
    assert (
        _json(_search(kb, "--json", "--per-file", "2", "--limit", "0", "widgets"))["returned"] == 2
    )
    assert _json(_search(kb, "--json", "--limit", "0", "widgets"))["returned"] >= 2
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
    assert _hits(kb, "kubernetes") == [] and _hits(kb, "kafka") == []
    corpora = [r["corpus"] for r in _json(_search(kb, "--json", "--archive", "kafka"))["results"]]
    assert sorted(corpora) == ["archive", "question"]
    _pin(
        kb,
        golden,
        _search(kb, "kubernetes"),
        _search(kb, "--archive", "kubernetes"),
        _search(kb, "kafka"),
        _search(kb, "--archive", "kafka"),
    )


# Semantic helpers (behavior tier)


def _hits(kb: KB, *args: str) -> list[tuple[str, str]]:
    """(path, section) of each JSON result, in rank order."""
    data = _json(_search(kb, "--json", *args))
    return [(r["path"], r["locator"]["section"]) for r in data["results"]]


def _json(result: Result) -> dict:
    assert result.returncode == 0, result.err
    return json.loads(result.out)


def _paths(result: Result) -> list[str]:
    """Result paths from text output, in order (lines of the form 'path | section | ...')."""
    return [line.split(" | ", 1)[0] for line in result.out.splitlines() if " | " in line]


def _sections(result: Result) -> list[str]:
    return [line.split(" | ")[1] for line in result.out.splitlines() if " | " in line]


# Parsing


@pytest.mark.bats("search.bats", "search ignores headings inside code fences for section context")
@pytest.mark.bats("search.bats", "search honors fence length like the shared parser")
@pytest.mark.parametrize(
    "body",
    [
        "```bash\n## not a heading\ngrep widgets file\n```",
        "````markdown\n```\n## not a heading\nwidgets inside\n```\n````",
    ],
    ids=["fence", "longer-fence"],
)
def test_fenced_headings(kb: KB, golden: Golden, body: str) -> None:
    kb.create_article("fenced.md", f"# Fenced\n\n## Real Section\n\n{body}")
    data = _json(_search(kb, "--json", "widgets"))
    assert [r["locator"]["section"] for r in data["results"]] == ["Real Section"]
    _pin(kb, golden, _search(kb, "widgets"))


@pytest.mark.bats("search.bats", "search survives a filename containing a space")
@pytest.mark.bats("search.bats", "search survives a filename containing a quote")
def test_unusual_file_names(kb: KB, golden: Golden) -> None:
    kb.create_article("docker.md", "# D\n\n## S\n\ndocker notes")
    kb.create_article("has space.md", "# X\n\n## S\n\ndocker in a spaced name")
    kb.create_article("it's.md", "# X\n\n## S\n\ndocker in a quoted name")
    data = _json(_search(kb, "--json", "--limit", "0", "docker"))
    assert sorted(r["path"] for r in data["results"]) == [
        "knowledge/docker.md",
        "knowledge/has space.md",
        "knowledge/it's.md",
    ]
    _pin(kb, golden, _search(kb, "--limit", "0", "docker"))


@pytest.mark.bats("search.bats", "search matches a term containing a backslash literally")
@pytest.mark.bats("search.bats", "search does not expand an escape sequence in a term")
def test_terms_are_literal(kb: KB, golden: Golden) -> None:
    kb.create_article("win.md", "# W\n\n## S\n\npath C:\\new\\table here")
    kb.create_article("tab.md", "# T\n\n## S\n\nliteral a\tb")
    assert [r["path"] for r in _json(_search(kb, "--json", "C:\\new"))["results"]] == [
        "knowledge/win.md"
    ]
    assert _json(_search(kb, "--json", "a\\tb"))["results"] == []
    _pin(kb, golden, _search(kb, "C:\\new"), _search(kb, "a\\tb"))


@pytest.mark.bats("search.bats", "search keeps fields apart when a heading contains a pipe")
def test_heading_with_pipe(kb: KB, golden: Golden) -> None:
    kb.create_article("pipe.md", "# P\n\n## A | B\n\nzebra here")
    data = _json(_search(kb, "--json", "zebra"))
    assert data["results"][0]["locator"]["section"] == "A | B"
    _pin(kb, golden, _search(kb, "zebra"))


# Limits and omissions


@pytest.mark.bats("search.bats", "search reports the true number of hidden lines and files")
@pytest.mark.bats("search.bats", "search --files reports how many files it hid")
def test_hidden_counts(kb: KB, golden: Golden) -> None:
    for index in range(1, 11):
        kb.create_article(f"f{index}.md", f"# T{index}\n\n## S\n\nneedle here")
    limited = _search(kb, "--limit", "4", "needle")
    files = _search(kb, "--files", "--limit", "2", "needle")
    assert len(_paths(limited)) == 4
    assert "6 more result section(s)" in limited.out and "6 unshown file(s)" in limited.out
    assert "8 more file(s)" in files.out
    data = _json(_search(kb, "--json", "--limit", "4", "needle"))
    assert (data["returned"], data["total_lines"], data["truncated"]) == (4, 10, True)
    _pin(kb, golden, limited, files)


# Labels and provenance


@pytest.mark.bats("search.bats", "search default output labels freshness and uncurated evidence")
@pytest.mark.bats("search.bats", "search text-only omits retrieval metadata")
def test_labels(kb: KB, golden: Golden) -> None:
    kb.create_article("old.md", '---\ntitle: "Old"\nverified: 2020-01-01\n---\n\n# Old\n\nneedle')
    kb.create_observation("20260412T000000-0000eeee.md", "Pending", "needle")
    data = _json(_search(kb, "--json", "--limit", "2", "needle"))
    by_corpus = {r["corpus"]: r for r in data["results"]}
    assert by_corpus["curated article"]["freshness"]["status"] == "stale"
    assert "pending observation" in by_corpus
    text = _search(kb, "--limit", "2", "needle")
    text_only = _search(kb, "--text-only", "needle")
    assert "freshness=stale" in text.out and "uncurated evidence" in text.out
    assert "freshness=" not in text_only.out and "| top | needle" in text_only.out
    _pin(kb, golden, text, text_only)


@pytest.mark.bats("search.bats", "search exposes unresolved conflicts separately from freshness")
def test_conflicts(kb: KB, golden: Golden) -> None:
    fixture = REPO / "tests" / "fixtures" / "lint" / "corrections"
    shutil.copytree(fixture / "knowledge", kb.layout.content / "knowledge", dirs_exist_ok=True)
    shutil.copytree(
        fixture / "observations", kb.layout.content / "observations", dirs_exist_ok=True
    )
    top = _json(_search(kb, "--json", "--limit", "1", "team message"))["results"][0]
    assert (top["freshness"]["status"], top["conflict"]["status"]) == ("fresh", "unresolved")
    text = _search(kb, "--limit", "1", "team message")
    assert "freshness=fresh" in text.out and "conflict=unresolved" in text.out
    _pin(kb, golden, text)


@pytest.mark.bats("search.bats", "search JSON handles spaces, quotes, Unicode, and empty results")
def test_json_values(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "résumé notes.md",
        '---\ntitle: "Résumé Notes"\nverified: not-a-date\n---\n\n# Résumé Notes\n\n## Cité\n\nNeedle "quoted".',
    )
    hit = _search(kb, "--json", "needle")
    top = _json(hit)["results"][0]
    assert top["path"] == "knowledge/résumé notes.md"
    assert top["text"] == 'Needle "quoted".'
    assert top["freshness"]["status"] == "invalid"
    assert (top["locator"]["section"], top["locator"]["number"]) == ("Cité", "1")
    empty = _search(kb, "--json", "absent")
    data = _json(empty)
    assert (data["results"], data["returned"], data["truncated"]) == ([], 0, False)
    _pin(kb, golden, hit, empty)


@pytest.mark.bats("search.bats", "search JSON reports source and archive provenance")
def test_source_and_archive_provenance(kb: KB, golden: Golden) -> None:
    (kb.layout.content / "sources" / "manual.md").write_text(
        '---\ntitle: "Manual"\ncanonical: "https://example.test/manual"\nsynced: 2026-09-05\n---\n\n# Manual\n\nneedle\n',
        encoding="utf-8",
    )
    (kb.layout.content / "observations" / "archived" / "old.md").write_text(
        '---\ntitle: "Old"\ndisposition: duplicate\ndestination: knowledge/manual.md#Setup\n---\n\n# Old\n\nneedle\n',
        encoding="utf-8",
    )
    result = _search(kb, "--json", "--archive", "needle")
    by_corpus = {r["corpus"]: r for r in _json(result)["results"]}
    assert "https://example.test/manual" in by_corpus["source document"]["provenance"]["references"]
    assert by_corpus["archive"]["provenance"]["disposition"] == "duplicate"
    _pin(kb, golden, result)


@pytest.mark.bats("search.bats", "search JSON keeps truncation diagnostics off stdout")
def test_json_diagnostics_on_stderr(kb: KB, golden: Golden) -> None:
    for index in range(1, 4):
        kb.create_article(f"topic{index}.md", f"# Topic {index}\n\nneedle")
    result = _search(kb, "--json", "--limit", "1", "needle")
    data = _json(result)
    assert (data["truncated"], data["returned"]) == (True, 1)
    assert "hidden" in result.err
    _pin(kb, golden, result)


@pytest.mark.bats("search.bats", "search caps provenance references and reports the complete count")
def test_reference_cap(kb: KB, golden: Golden) -> None:
    sources = "".join(f"  - observations/evidence-{i}.md\n" for i in range(1, 8))
    kb.create_article(
        "many-sources.md",
        f'---\ntitle: "Many Sources"\nverified: 2026-01-01\nsources:\n{sources}---\n\n# Many Sources\n\nneedle',
    )
    provenance = _json(_search(kb, "--json", "needle"))["results"][0]["provenance"]
    assert len(provenance["references"]) == 5
    assert (provenance["reference_count"], provenance["references_truncated"]) == (7, True)
    text = _search(kb, "needle")
    assert "+2 more" in text.out
    _pin(kb, golden, text)


@pytest.mark.bats("search.bats", "search reports open questions as question records")
def test_question_records(kb: KB, golden: Golden) -> None:
    kb.create_question("20260412T000000-0000eeee.md", "Who owns the kafka cluster?")
    result = _search(kb, "--json", "--archive", "kafka")
    top = _json(result)["results"][0]
    assert top["corpus"] == "question"
    assert (top["provenance"]["state"], top["provenance"]["label"]) == (
        "open",
        "unresolved knowledge gap",
    )
    _pin(kb, golden, result)


# Scopes


@pytest.mark.bats("search.bats", "search path and topic filters scope knowledge results")
def test_path_and_topic(kb: KB, golden: Golden) -> None:
    kb.create_article("projects/tool.md", "# Tool\n\n## Build\n\nproject-only needle")
    kb.create_article("home.md", "# Home\n\n## Notes\n\nother needle")
    by_path = _search(kb, "--path", "knowledge/projects", "needle")
    by_topic = _search(kb, "--topic", "projects", "needle")
    assert _paths(by_path) == ["knowledge/projects/tool.md"]
    assert _paths(by_topic) == ["knowledge/projects/tool.md"]
    _pin(kb, golden, by_path, by_topic)


@pytest.mark.bats("search.bats", "search corpus filter selects only the requested corpus")
def test_corpus_filter(kb: KB, golden: Golden) -> None:
    kb.create_article("article.md", "# Article\n\nneedle")
    (kb.layout.content / "sources" / "manual.md").write_text(
        '---\ntitle: "Manual"\nsynced: 2026-09-05\n---\n\n# Manual\n\nneedle\n', encoding="utf-8"
    )
    result = _search(kb, "--corpus", "sources", "needle")
    assert _paths(result) == ["sources/manual.md"]
    _pin(kb, golden, result, _search(kb, "--corpus", "bogus", "needle"))


@pytest.mark.bats("search.bats", "search normalizes a relative content root")
def test_relative_content_root(kb: KB, golden: Golden) -> None:
    kb.create_article("relative.md", "# Relative\n\nneedle")
    result = kb.run(
        "search",
        "needle",
        env={"KB_CONTENT_DIR": kb.layout.content.name},
        cwd=kb.layout.content.parent,
    )
    assert _paths(result) == ["knowledge/relative.md"]
    _pin(kb, golden, result)


@pytest.mark.bats(
    "search.bats", "search returns a valid empty JSON response for an empty scope intersection"
)
def test_empty_scope_intersection(kb: KB, golden: Golden) -> None:
    kb.create_article("one/needle.md", "# One\n\nneedle")
    kb.create_article("two/needle.md", "# Two\n\nneedle")
    result = _search(
        kb, "--json", "--max-bytes", "400", "--path", "knowledge/one", "--topic", "two", "needle"
    )
    data = _json(result)
    assert (data["results"], data["returned"], data["truncated"]) == ([], 0, False)
    _pin(kb, golden, result)


# Question mode


@pytest.mark.bats(
    "search.bats", "question search normalizes prose while preserving commands dates and paths"
)
def test_question_preserves_identifiers(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "question.md",
        "# Question\n\n## Evidence\n\nrestart --no-verify on 2026-10-03 from /srv/backups/kb; keep not current.",
    )
    query = "How do I restart --no-verify on 2026-10-03 from /srv/backups/kb?"
    data = _json(_search(kb, "--json", "--query", query))
    assert data["query_terms"] == ["restart", "--no-verify", "2026-10-03", "/srv/backups/kb"]
    assert [r["path"] for r in data["results"]] == ["knowledge/question.md"]
    text = _search(kb, "--query", query)
    assert "query-mode=question" in text.out
    _pin(kb, golden, text)


@pytest.mark.bats("search.bats", "question normalization preserves short flags and negation")
@pytest.mark.bats(
    "search.bats", "question search strips wrapping quotes but preserves internal apostrophes"
)
@pytest.mark.bats("search.bats", "question search strips quotes spanning a phrase")
@pytest.mark.bats("search.bats", "question search preserves quoted command boundaries across lines")
@pytest.mark.parametrize(
    ("question", "terms"),
    [
        ("How do I run tool -s? Why doesn't this work?", ["run", "tool", "-s", "doesn't", "work"]),
        ("Where is 'needle'? Why doesn't this work?", ["needle", "doesn't", "work"]),
        ("What is 'systemctl restart kb-api'?", ["systemctl", "restart", "kb-api"]),
        ("What is 'systemctl\nrestart kb-api'?", ["systemctl", "restart", "kb-api"]),
    ],
    ids=["short-flags", "apostrophes", "quoted-phrase", "multiline-quote"],
)
def test_question_terms(kb: KB, golden: Golden, question: str, terms: list[str]) -> None:
    kb.create_article(
        "evidence.md", "# Evidence\n\n## Restart\n\nRun systemctl restart kb-api. needle"
    )
    result = _search(kb, "--json", "--query", question)
    assert _json(result)["query_terms"] == terms
    _pin(kb, golden, result)


@pytest.mark.bats(
    "search.bats", "question search strips sentence punctuation without losing dotted identifiers"
)
@pytest.mark.bats("search.bats", "question search preserves non-ASCII searchable terms")
@pytest.mark.parametrize(
    "question",
    ["Where are the backups.", "What is the API hostname.", "What is the résumé status?"],
    ids=["sentence-period", "dotted-identifier", "non-ascii"],
)
def test_question_punctuation_and_unicode(kb: KB, golden: Golden, question: str) -> None:
    kb.create_article(
        "punctuation.md",
        "# Punctuation\n\n## Evidence\n\nBackups live at /srv/backups/kb. The API hostname is api.internal.example.",
    )
    kb.create_article("unicode.md", "# Résumé\n\n## État\n\nThe résumé status is current.")
    result = _search(kb, "--json", "--query", question)
    assert _json(result)["results"], "the question must find its evidence"
    _pin(kb, golden, result)


@pytest.mark.bats("search.bats", "question search rejects an all-stopword question")
@pytest.mark.bats("search.bats", "question and literal search modes cannot be combined")
def test_question_errors(kb: KB, golden: Golden) -> None:
    stopwords = _search(kb, "--query", "how do I")
    combined = _search(kb, "--query", "find this", "literal")
    assert stopwords.returncode != 0 and "no searchable terms" in stopwords.err
    assert combined.returncode != 0 and "cannot be combined" in combined.err
    _pin(kb, golden, stopwords, combined)


@pytest.mark.bats("search.bats", "question relaxation is opt in and ranks complete coverage first")
def test_question_relaxation(kb: KB, golden: Golden) -> None:
    kb.create_article("partial.md", "# Partial\n\n## Evidence\n\nrestart service")
    kb.create_article("complete.md", "# Complete\n\n## Evidence\n\nrestart api database")
    question = "how restart api database tunnel"
    strict = _search(kb, "--query", question, "--json")
    relaxed = _search(kb, "--query", question, "--relax", "--json", "--limit", "0")
    assert _json(strict)["results"] == []
    data = _json(relaxed)
    assert data["match_mode"] == "relaxed"
    assert data["results"][0]["path"] == "knowledge/complete.md"
    _pin(kb, golden, strict, relaxed)


@pytest.mark.bats("search.bats", "question aliases produce an explicit routing result")
@pytest.mark.bats(
    "search.bats", "question aliases do not promote partial body evidence to strict evidence"
)
@pytest.mark.parametrize(
    "section",
    [
        "## Peers\n\nThe peer is wg-kb-prod.",
        "## Billing\n\nProduction billing uses a separate account.",
    ],
    ids=["routing", "no-promotion"],
)
def test_question_aliases(kb: KB, golden: Golden, section: str) -> None:
    kb.create_article(
        "network.md",
        f'---\ntitle: "WireGuard"\naliases:\n  - "production tunnel"\n---\n# Network\n\n{section}',
    )
    result = _search(kb, "--query", "where is the production tunnel", "--json")
    results = _json(result)["results"]
    assert len(results) == 1
    top = results[0]
    assert (top["routing"], top["locator"]["command"], top["alias"]) == (
        True,
        "--alias",
        "production tunnel",
    )
    assert (top["text"], top["match_mode"]) == ("production tunnel", "strict")
    _pin(kb, golden, result)


@pytest.mark.bats("search.bats", "question explanation stays on stderr and preserves JSON stdout")
def test_question_explanation(kb: KB, golden: Golden) -> None:
    kb.create_article("explain.md", "# Explain\n\n## Evidence\n\nrestart api")
    result = _search(kb, "--query", "how restart api", "--explain", "--json")
    data = _json(result)
    assert (data["query"], data["query_terms"]) == ("how restart api", ["restart", "api"])
    assert "original query: how restart api" in result.err
    _pin(kb, golden, result)


# Metadata


@pytest.mark.bats("search.bats", "search JSON includes section metadata for section results")
def test_section_metadata_in_results(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "section-metadata.md",
        '---\ntitle: "Section Metadata"\nverified: 2026-10-03\n---\n\n# Section Metadata\n\n## Current\n\n'
        "<!-- kb-section: verified=2026-10-03; status=current; supersedes=2 -->\nCurrent guidance.\n\n"
        "## Historical\n\n<!-- kb-section: verified=2026-01-01; status=superseded; "
        "sources=observations/archived/old.md -->\nHistorical guidance.",
    )
    result = _search(
        kb, "--json", "historical", "guidance", env={"FRESHNESS_TODAY_EPOCH": "1790985600"}
    )
    top = _json(result)["results"][0]
    assert top["section_metadata"]["status"] == "superseded"
    assert top["section_metadata"]["source_scope"] == "section"
    assert (top["provenance"]["scope"], top["freshness"]["status"]) == ("section", "stale")
    _pin(kb, golden, result)


@pytest.mark.bats(
    "search.bats", "search uses matched H3 metadata instead of its H2 parent metadata"
)
def test_h3_metadata(kb: KB, golden: Golden) -> None:
    fixture = REPO / "tests" / "fixtures" / "section-metadata"
    shutil.copy(fixture / "knowledge" / "metadata.md", kb.layout.content / "knowledge")
    shutil.copytree(
        fixture / "observations", kb.layout.content / "observations", dirs_exist_ok=True
    )
    result = _search(
        kb,
        "--json",
        "--limit",
        "0",
        "--per-file",
        "0",
        "Inherited section metadata",
        env={"FRESHNESS_TODAY_EPOCH": "1790985600"},
    )
    results = _json(result)["results"]
    assert len(results) == 1
    top = results[0]
    assert top["locator"]["number"] == "2.1"
    assert (
        top["section_metadata"]["status"],
        top["freshness"]["status"],
        top["conflict"]["status"],
    ) == (
        "superseded",
        "stale",
        "none",
    )
    _pin(kb, golden, result)


@pytest.mark.bats(
    "search.bats", "search keeps section metadata isolated when result files interleave"
)
def test_metadata_isolation(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "a.md",
        '---\ntitle: "Article A"\nverified: 2026-10-03\nttl: domain\nstatus: current\nsources:\n'
        "  - observations/archived/a.md\n---\n\n# Article A\n\n## Needle\n\nneedle\n\n## History\n\nneedle",
    )
    kb.create_article(
        "b.md",
        '---\ntitle: "Article B"\nverified: 2025-01-01\nttl: domain\nstatus: superseded\nsources:\n'
        "  - observations/archived/b.md\n---\n\n# Article B\n\n## Notes\n\nneedle\nanother needle",
    )
    result = _search(kb, "--json", "--limit", "0", "--per-file", "0", "needle")
    rows = [
        (
            r["path"],
            r["locator"]["number"],
            r["freshness"]["value"],
            r["section_metadata"]["status"],
        )
        for r in _json(result)["results"]
    ]
    assert rows == [
        ("knowledge/a.md", "1", "2026-10-03", "current"),
        ("knowledge/b.md", "1", "2025-01-01", "superseded"),
        ("knowledge/a.md", "2", "2026-10-03", "current"),
    ]
    assert (
        _json(result)["results"][2]["provenance"]["references"][0] == "observations/archived/a.md"
    )
    _pin(kb, golden, result)


@pytest.mark.bats("search.bats", "search excludes standalone section metadata from evidence")
def test_metadata_is_not_evidence(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "metadata-evidence.md",
        "---\ntitle: Metadata evidence\nverified: 2026-10-04\n---\n# Metadata evidence\n\n## Service\n\n"
        "<!-- kb-section:\nstatus=current;\nsources=observations/archived/metadata-only-needle.md\n-->\n"
        "The service listens on port 8080.",
    )
    hidden = _search(kb, "--json", "metadata-only-needle")
    port = _search(kb, "--json", "8080")
    assert _json(hidden)["returned"] == 0
    metadata = _json(port)["results"][0]["section_metadata"]
    assert metadata["valid"] and metadata["status"] == "current"
    _pin(kb, golden, hidden, port)


@pytest.mark.bats("search.bats", "search retains prose after an inline metadata comment closes")
@pytest.mark.parametrize(
    "comment",
    [
        "<!-- kb-section: status=unresolved --> inline-evidence-needle",
        "<!-- kb-section:\nstatus=unresolved\n--> inline-evidence-needle",
    ],
    ids=["one-line", "multi-line"],
)
def test_prose_after_inline_metadata(kb: KB, golden: Golden, comment: str) -> None:
    kb.create_article(
        "inline-closing.md",
        f"---\ntitle: Inline closing\nverified: 2026-10-04\n---\n## Service\n{comment}\nBody evidence.",
    )
    result = _search(kb, "--json", "inline-evidence-needle")
    data = _json(result)
    assert data["returned"] == 1
    top = data["results"][0]
    assert (
        top["locator"]["number"],
        top["section_metadata"]["status"],
        top["conflict"]["status"],
    ) == (
        "1",
        "current",
        "none",
    )
    assert "inline-evidence-needle" in top["text"]
    _pin(kb, golden, result)


@pytest.mark.bats("search.bats", "search serializes leading-zero TTLs as canonical JSON numbers")
def test_leading_zero_ttl_is_canonical(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "decimal-ttl.md",
        "---\ntitle: Decimal TTL\nverified: 2026-10-04\n---\n## Service\n<!-- kb-section: ttl=08 -->\nBody evidence.",
    )
    result = _search(kb, "--json", "evidence", env={"FRESHNESS_TODAY_EPOCH": "1792022400"})
    assert re.search(r'"ttl_days":\s*8\s*[,}]', result.out), "ttl_days must be the JSON number 8"
    data = _json(result)
    assert data["returned"] == 1
    assert (
        data["results"][0]["freshness"]["ttl_days"],
        data["results"][0]["freshness"]["status"],
    ) == (8, "stale")
    assert result.err == ""
    _pin(kb, golden, result)


# Byte budgets: invariants, not exact bytes


def _matrix(kb: KB, stem: str, count: int, sections: int = 1) -> None:
    for index in range(1, count + 1):
        body = "\n\n".join(
            f"## Part {part}\n\n{stem}-needle result {index} part {part} with enough text for a record."
            for part in range(1, sections + 1)
        )
        kb.create_article(f"{stem}-{index}.md", f"# {stem.title()} {index}\n\n{body}")


MODES = {"json": ["--json"], "text": [], "text-only": ["--text-only"]}


@pytest.mark.bats("search.bats", "search JSON byte budgets retain complete records")
def test_json_budget_complete_records(kb: KB, golden: Golden) -> None:
    for name in ("budget", "budget-two"):
        kb.create_article(
            f"{name}.md",
            f"# {name}\n\n## Evidence\n\nbudget needle with enough metadata to make the response larger than its envelope.",
        )
    full = _search(kb, "--json", "--limit", "0", "needle")
    cap = len(full.stdout) - 1
    bounded = _search(kb, "--json", "--limit", "0", "--max-bytes", str(cap), "needle")
    assert len(bounded.stdout) <= cap
    data = _json(bounded)
    assert (data["truncated"], data["omitted_results"]) == (True, 1)
    assert data["results"] == _json(full)["results"][: len(data["results"])]
    _pin(kb, golden, bounded)


@pytest.mark.bats("search.bats", "search JSON budgets report records hidden by result limits")
def test_json_budget_reports_limit_omissions(kb: KB, golden: Golden) -> None:
    for name in ("budget-one", "budget-two"):
        kb.create_article(f"{name}.md", f"# {name}\n\n## Evidence\n\nbudget-limit-needle")
    result = _search(kb, "--json", "--limit", "1", "--max-bytes", "20000", "budget-limit-needle")
    data = _json(result)
    assert (data["returned"], data["total_lines"], data["truncated"], data["omitted_results"]) == (
        1,
        2,
        True,
        1,
    )
    _pin(kb, golden, result)


@pytest.mark.bats(
    "search.bats", "search text byte budgets preserve unbounded output and omission counts"
)
@pytest.mark.parametrize("mode", ["text", "text-only"])
@pytest.mark.parametrize(
    "admission",
    [
        ["--limit", "0", "--per-file", "0"],
        ["--limit", "1", "--per-file", "0"],
        ["--limit", "0", "--per-file", "1"],
    ],
    ids=["unlimited", "result-limit", "per-file-limit"],
)
def test_text_budget_large_enough_changes_nothing(kb: KB, mode: str, admission: list[str]) -> None:
    kb.create_article(
        "budget-summary.md",
        "# Budget Summary\n\n## First\n\nbudget-summary-needle first\n\n## Second\n\nbudget-summary-needle second",
    )
    full = _search(kb, *MODES[mode], *admission, "budget-summary-needle")
    bounded = _search(kb, *MODES[mode], *admission, "--max-bytes", "10000", "budget-summary-needle")
    assert bounded.stdout == full.stdout
    limited = admission != ["--limit", "0", "--per-file", "0"]
    assert len(_paths(full)) == (1 if limited else 2)
    assert ("1 more result section(s)" in full.out) == limited


@pytest.mark.bats("search.bats", "search text byte budgets accept an exact unbounded-response cap")
@pytest.mark.bats("search.bats", "search output modes honor exact and one-byte-short budgets")
@pytest.mark.parametrize("mode", sorted(MODES))
def test_exact_and_short_budgets(kb: KB, golden: Golden, mode: str) -> None:
    _matrix(kb, "matrix", 3)
    args = [*MODES[mode], "--limit", "0", "--per-file", "0"]
    if mode == "json":
        # The budget is part of the JSON response, so find the fixed point.
        cap = 10000
        for _ in range(10):
            measured = len(_search(kb, *args, "--max-bytes", str(cap), "matrix-needle").stdout)
            if measured == cap:
                break
            cap = measured
    else:
        cap = len(_search(kb, *args, "matrix-needle").stdout)
    exact = _search(kb, *args, "--max-bytes", str(cap), "matrix-needle")
    assert exact.returncode == 0 and len(exact.stdout) == cap
    short = _search(kb, *args, "--max-bytes", str(cap - 1), "matrix-needle")
    assert short.returncode == 0 and len(short.stdout) <= cap - 1
    if mode == "json":
        full, cut = _json(exact), _json(short)
        assert (full["truncated"], full["returned"]) == (False, 3)
        assert cut["truncated"] and cut["returned"] < 3
        assert cut["omitted_results"] == cut["total_lines"] - cut["returned"]
        assert cut["results"] == full["results"][: cut["returned"]]
    else:
        assert exact.stdout == _search(kb, *args, "matrix-needle").stdout
        assert "output truncated" in short.out
    _pin(kb, golden, short)


@pytest.mark.bats("search.bats", "search combines result, per-file, and byte limits")
@pytest.mark.bats(
    "search.bats", "search explanation reports emitted records after the JSON byte budget"
)
@pytest.mark.bats(
    "search.bats", "search text explanations count result records across output modes"
)
@pytest.mark.parametrize("mode", sorted(MODES))
def test_combined_limits(kb: KB, golden: Golden, mode: str) -> None:
    _matrix(kb, "combined", 3, sections=3)
    admitted = _json(_search(kb, "--json", "--limit", "5", "--per-file", "2", "combined-needle"))
    assert (admitted["returned"], admitted["total_lines"]) == (5, 9)
    one = _search(
        kb,
        *MODES[mode],
        "--limit",
        "1",
        "--per-file",
        "2",
        "--max-bytes",
        "10000",
        "combined-needle",
    )
    cap = len(one.stdout)
    bounded = _search(
        kb,
        *MODES[mode],
        "--limit",
        "5",
        "--per-file",
        "2",
        "--max-bytes",
        str(cap),
        "--explain",
        "combined-needle",
    )
    assert bounded.returncode == 0 and len(bounded.stdout) <= cap
    explain = re.search(r"candidates: (\d+); returned: (\d+)", bounded.err)
    omissions = re.search(r"omissions: result/per-file=(\d+); byte-budget=(\d+)", bounded.err)
    assert explain and omissions, bounded.err
    candidates, returned = map(int, explain.groups())
    by_limit, by_budget = map(int, omissions.groups())
    assert candidates == 9 and 0 < returned < 5
    assert by_limit > 0 and by_budget > 0 and by_limit + by_budget == candidates - returned
    if mode == "json":
        data = _json(bounded)
        assert data["returned"] == returned and data["truncated"]
        assert data["results"] == admitted["results"][:returned]
    _pin(kb, golden, bounded)


@pytest.mark.bats("search.bats", "search rejects a byte budget smaller than the JSON envelope")
def test_budget_below_envelope(kb: KB, golden: Golden) -> None:
    kb.create_article("budget.md", "# Budget\n\nneedle")
    result = _search(kb, "--json", "--max-bytes", "0", "needle")
    assert result.returncode != 0 and "minimum valid JSON response" in result.err
    _pin(kb, golden, result)


@pytest.mark.bats("search.bats", "search text byte budgets signal omitted output")
def test_text_budget_signals_truncation(kb: KB, golden: Golden) -> None:
    for name in ("budget", "budget-two"):
        kb.create_article(
            f"{name}.md",
            f"# {name}\n\n## Evidence\n\nbudget needle with a long enough result line to require truncation.",
        )
    result = _search(kb, "--text-only", "--max-bytes", "200", "needle")
    assert result.returncode == 0 and len(result.stdout) <= 200
    assert "output truncated" in result.out
    _pin(kb, golden, result)


@pytest.mark.bats(
    "search.bats", "search text byte budgets never skip a larger higher-ranked record"
)
def test_text_budget_keeps_rank_order(kb: KB, golden: Golden) -> None:
    long_dir = "long" * 35
    kb.create_article(f"{long_dir}/high.md", "# High\n\n## Needle\n\nneedle")
    kb.create_article("low.md", "# Low\n\n## Notes\n\nneedle")
    full = _search(kb, "--limit", "0", "--per-file", "0", "needle")
    first = len(full.out.splitlines(keepends=True)[0].encode())
    marker = len(b"[output truncated: complete records omitted; increase --max-bytes]\n")
    result = _search(
        kb, "--max-bytes", str(first + marker - 1), "--limit", "0", "--per-file", "0", "needle"
    )
    assert result.returncode != 0
    assert "low.md" not in result.out
    _pin(kb, golden, result)
