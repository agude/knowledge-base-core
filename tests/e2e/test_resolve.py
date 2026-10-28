"""End-to-end tests for resolving open questions."""

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from .harness import Kb

QUESTION = "questions/open/20261001T090000-bbbb2222.md"


def _question(kb: Kb, relative: str = QUESTION) -> Path:
    return kb.content / relative


def _failure(result: CompletedProcess[str], cause: str) -> None:
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("resolve:")
    assert cause in result.stderr


def test_answers_a_question_with_exact_bytes_and_canonical_destination(git_kb: Kb) -> None:
    original = _question(git_kb).read_bytes()
    head = git_kb.git("rev-parse", "HEAD")
    expected = (
        original.replace(
            b"created: 2026-10-01T09:00:00Z\n---",
            b"created: 2026-10-01T09:00:00Z\n"
            b"resolved: 2026-10-26\nresolution: answered\n"
            b'destination: "knowledge/infra/nas.md#1"\n---',
        )
        + b"\n## Resolution (2026-10-26)\n\nSee the restart order in NAS.\n"
    )

    result = git_kb(
        "resolve",
        QUESTION,
        "--answer",
        "See the restart order in NAS.",
        "--destination",
        "infra/nas.md#01",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "Resolved: questions/open/20261001T090000-bbbb2222.md -> "
        "questions/resolved/20261001T090000-bbbb2222.md\n"
    )
    assert result.stderr == ""
    assert not _question(git_kb).exists()
    assert _question(git_kb, "questions/resolved/20261001T090000-bbbb2222.md").read_bytes() == (
        expected
    )
    assert git_kb.git("rev-parse", "HEAD") == head


def test_obsoletes_a_question_and_keeps_legacy_questions_without_attribution(git_kb: Kb) -> None:
    relative = "questions/open/old-question.md"
    question = _question(git_kb, relative)
    original = (
        b'---\ntitle: "Old question"\ncreated: 2026-10-01T00:00:00Z\n---\n\nNo longer relevant.\n'
    )
    question.write_bytes(original)
    expected = (
        original.replace(
            b"created: 2026-10-01T00:00:00Z\n---",
            b"created: 2026-10-01T00:00:00Z\nresolved: 2026-10-26\nresolution: obsolete\n---",
        )
        + b"\n## Resolution (2026-10-26)\n\nThe system was retired.\n"
    )

    result = git_kb("resolve", relative, "--answer", "The system was retired.", "--obsolete")

    assert result.returncode == 0, result.stderr
    assert _question(git_kb, "questions/resolved/old-question.md").read_bytes() == expected
    assert not question.exists()


def test_reads_unicode_answer_from_stdin_and_preserves_quoted_title(git_kb: Kb) -> None:
    title = 'Where is "München" \\ backup?'
    gap = git_kb(
        "gap",
        "--title",
        title,
        "--body",
        "The backup destination is not recorded.",
        "--context",
        "infra",
    )
    assert gap.returncode == 0, gap.stderr
    relative = gap.stdout.removeprefix("Wrote: ").removesuffix("\n")
    answer = "Café backup files live with the NAS.\nCheck the index."

    result = git_kb(
        "resolve",
        relative,
        "--answer",
        "-",
        "--destination",
        "knowledge/infra/nas.md#1",
        stdin=answer,
    )

    assert result.returncode == 0, result.stderr
    resolved = _question(git_kb, relative.replace("questions/open/", "questions/resolved/"))
    text = resolved.read_text(encoding="utf-8")
    assert 'title: "Where is \\"München\\"' in text
    assert 'destination: "knowledge/infra/nas.md#1"' in text
    assert text.endswith(f"## Resolution (2026-10-26)\n\n{answer}\n")


def test_refuses_invalid_destination_locators(git_kb: Kb) -> None:
    cases = [
        ("knowledge/missing.md", "no file matches"),
        ("knowledge/infra/nas.md#99", "no section 99"),
        ("sources/vendor-guide.md", "knowledge/"),
    ]
    for destination, cause in cases:
        result = git_kb(
            "resolve", QUESTION, "--answer", "A safe answer.", "--destination", destination
        )
        _failure(result, cause)
        assert _question(git_kb).is_file()

    for directory in ("a", "b"):
        article = _question(git_kb, f"knowledge/{directory}/shared.md")
        article.parent.mkdir(parents=True, exist_ok=True)
        article.write_text(
            "---\ntitle: Shared\nupdated: 2026-10-20\nverified: 2026-10-20\n"
            "ttl: domain\n---\n# Shared\n",
            encoding="utf-8",
        )
    ambiguous = git_kb(
        "resolve", QUESTION, "--answer", "A safe answer.", "--destination", "shared.md"
    )
    _failure(ambiguous, "matches 2 files")


@pytest.mark.parametrize(
    ("question", "options", "cause"),
    [
        (QUESTION, ("--answer", "A safe answer."), "exactly one"),
        (
            QUESTION,
            (
                "--answer",
                "A safe answer.",
                "--destination",
                "knowledge/infra/nas.md#1",
                "--obsolete",
            ),
            "exactly one",
        ),
        (
            "questions/resolved/20260915T120000-cccc3333.md",
            ("--answer", "A safe answer.", "--obsolete"),
            "questions/open/",
        ),
    ],
)
def test_refuses_wrong_outcome_or_non_open_questions(
    git_kb: Kb, question: str, options: tuple[str, ...], cause: str
) -> None:
    result = git_kb("resolve", question, *options)

    _failure(result, cause)


def test_requires_an_answer_and_a_real_open_question(git_kb: Kb) -> None:
    missing_answer = git_kb("resolve", QUESTION, "--destination", "knowledge/infra/nas.md#1")
    assert missing_answer.returncode == 1
    assert missing_answer.stdout == ""
    assert missing_answer.stderr.startswith("Usage: kb resolve ")

    missing_question = git_kb(
        "resolve",
        "questions/open/missing.md",
        "--answer",
        "A safe answer.",
        "--obsolete",
    )
    _failure(missing_question, "no question matches")


def test_refuses_existing_resolved_copy_without_changing_either_file(git_kb: Kb) -> None:
    source = _question(git_kb)
    resolved = _question(git_kb, "questions/resolved/20261001T090000-bbbb2222.md")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text("Existing resolved copy.\n", encoding="utf-8")
    before_source = source.read_bytes()
    before_resolved = resolved.read_bytes()

    result = git_kb("resolve", QUESTION, "--answer", "A safe answer.", "--obsolete")

    _failure(result, "already exists")
    assert source.read_bytes() == before_source
    assert resolved.read_bytes() == before_resolved


def test_secret_refusals_name_the_destination_or_answer_line(git_kb: Kb) -> None:
    question = _question(git_kb)
    before = question.read_bytes()
    secret = 'password = "hunter2hunter2"'
    answer = git_kb("resolve", QUESTION, "--answer", secret, "--obsolete")
    _failure(answer, "at answer line 1")
    assert "resolve: remove or redact it, then run kb resolve again" in answer.stderr
    assert question.read_bytes() == before

    destination_file = _question(git_kb, 'knowledge/password = "hunter2hunter2".md')
    destination_file.write_text("# Secret path target\n", encoding="utf-8")
    destination = git_kb(
        "resolve",
        QUESTION,
        "--answer",
        "A safe answer.",
        "--destination",
        'knowledge/password = "hunter2hunter2".md',
    )
    _failure(destination, "at destination")
    assert question.read_bytes() == before


def test_questions_evidence_and_recall_reflect_the_resolution(git_kb: Kb) -> None:
    relative = "questions/open/recall-resolution.md"
    question = _question(git_kb, relative)
    question.write_text(
        '---\ntitle: "Where is the Plex transcoding cache?"\ncontext: infra\n'
        "created: 2026-10-20T00:00:00Z\n---\n\nThe cache location is unclear.\n",
        encoding="utf-8",
    )
    resolved_relative = relative.replace("questions/open/", "questions/resolved/")

    result = git_kb(
        "resolve",
        relative,
        "--answer",
        "Plex uses /var/cache/plex.",
        "--destination",
        "knowledge/infra/plex.md#2",
    )
    assert result.returncode == 0, result.stderr

    open_questions = git_kb("questions")
    assert relative not in open_questions.stdout
    all_questions = git_kb("questions", "--all")
    assert resolved_relative in all_questions.stdout
    assert "| resolved |" in all_questions.stdout

    found = git_kb("evidence", "Plex", "cache", "--kind", "resolved-question")
    assert found.returncode == 0
    assert resolved_relative in found.stdout
    assert "| resolved question |" in found.stdout

    recalled = git_kb("recall", "transcoding", "cache")
    assert recalled.returncode == 0
    assert "knowledge/infra/plex.md#2 | Transcoding" in recalled.stdout
    assert resolved_relative not in recalled.stdout
