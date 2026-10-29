"""Tests for listing questions by status, date, and canonical context."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from kb.commands import questions
from kb.context import Context
from kb.errors import KbError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"


@pytest.fixture
def context(tmp_path: Path) -> Context:
    """An isolated content fixture for question listing."""
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    return Context(root=root.resolve(), today=date(2026, 10, 26))


def add_question(
    root: Path,
    relative: str,
    title: str,
    context: str | None,
    created: str | None,
) -> None:
    """Add a small synthetic question to an isolated content tree."""
    fields = [f"title: {title}"]
    if context is not None:
        fields.append(f"context: {context}")
    if created is not None:
        fields.append(f"created: {created}")
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + "\n".join(fields) + "\n---\n\nQuestion body.\n", encoding="utf-8")


def test_default_listing_uses_open_questions_and_preserves_legacy_context(context: Context) -> None:
    assert questions.answer(context, False, 20, None) == (
        "Questions: 1; shown: 1\n"
        "questions/open/20261001T090000-bbbb2222.md | 2026-10-01 | open | infra | "
        "Who owns the backup disk?\n"
        "Read with: kb read <locator>\n"
    )


def test_resolved_rows_invalid_dates_and_missing_context_sort_correctly(context: Context) -> None:
    add_question(
        context.root, "questions/open/a.md", "Newest", "knowledge/infra/child", "2026-10-20"
    )
    add_question(context.root, "questions/open/b.md", "Invalid", "infra", "bad-date")
    add_question(context.root, "questions/open/c.md", "Missing context", None, None)
    text = questions.answer(context, True, 20, None)
    lines = text.splitlines()
    assert lines[0] == "Questions: 5; shown: 5"
    assert lines[1].startswith("questions/open/a.md | 2026-10-20 | open | knowledge/infra/child")
    assert [line.split(" | ", 1)[0] for line in lines[1:-1]] == [
        "questions/open/a.md",
        "questions/open/20261001T090000-bbbb2222.md",
        "questions/resolved/20260915T120000-cccc3333.md",
        "questions/open/b.md",
        "questions/open/c.md",
    ]
    assert lines[-3] == "questions/open/b.md |  | open | infra | Invalid"
    assert lines[-2] == "questions/open/c.md |  | open | - | Missing context"


def test_context_filter_includes_descendants_but_not_component_prefixes(context: Context) -> None:
    add_question(context.root, "questions/open/inside.md", "Inside", "knowledge/infra/child", None)
    add_question(
        context.root, "questions/open/outside.md", "Outside", "knowledge/infrastructure", None
    )
    scope = questions._scope(context.root, "infra")
    assert scope == "knowledge/infra"
    text = questions.answer(context, False, 20, scope)
    assert text.startswith("Questions: 2; shown: 2\n")
    assert "questions/open/inside.md" in text
    assert "outside.md" not in text


def test_invalid_stored_context_is_visible_unfiltered_and_hidden_when_filtered(
    context: Context,
) -> None:
    add_question(
        context.root,
        "questions/open/invalid-context.md",
        "Invalid context",
        "/outside/area",
        None,
    )
    unfiltered = questions.answer(context, False, 20, None)
    assert "questions/open/invalid-context.md |  | open | - | Invalid context" in unfiltered
    filtered = questions.answer(context, False, 20, "knowledge/infra")
    assert "invalid-context.md" not in filtered


def test_missing_areas_filter_deleted_contexts_without_inference(context: Context) -> None:
    deleted = "knowledge/projects/shapez2/routing.md"
    moved = "knowledge/projects/shapez2/new-routing.md"
    add_question(context.root, "questions/open/deleted.md", "Deleted", deleted, None)
    (context.root / moved).parent.mkdir(parents=True, exist_ok=True)
    (context.root / moved).write_text("# New target\n", encoding="utf-8")
    assert questions._scope(context.root, deleted) == deleted
    assert questions.answer(context, False, 20, deleted).startswith("Questions: 1; shown: 1\n")
    assert questions.answer(context, False, 20, questions._scope(context.root, moved)) == (
        "No questions match.\n"
    )


def test_unsafe_supplied_context_has_no_matches_and_invalid_text_errors(context: Context) -> None:
    assert questions._scope(context.root, "knowledge/external.md") == "knowledge/external.md"
    assert questions._scope(context.root, "knowledge/future") == "knowledge/future"
    for value in ("", "../outside", "/absolute", "backups.md"):
        with pytest.raises(KbError):
            questions._scope(context.root, value)


def test_limit_is_applied_after_filtering_and_empty_listing_is_exact(context: Context) -> None:
    for number in range(4):
        add_question(
            context.root,
            f"questions/open/limit-{number}.md",
            f"Question {number}",
            "infra",
            f"2026-10-{20 - number}",
        )
    text = questions.answer(context, False, 2, "knowledge/infra")
    assert text.startswith("Questions: 5; shown: 2\n")
    assert "questions/open/limit-0.md" in text
    assert "questions/open/limit-1.md" in text
    assert "limit-2.md" not in text
    assert questions.answer(context, False, 20, "knowledge/none") == "No questions match.\n"


def test_run_help_default_listing_and_usage_errors(
    context: Context,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(questions, "load", lambda *args: context)
    assert questions.run(["--help"]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb questions [--context PATH]")
    assert questions.run([]) == 0
    assert capsys.readouterr().out.startswith("Questions: 1; shown: 1\n")
    with pytest.raises(KbError, match=r"^Usage: kb questions"):
        questions.run(["stray"])


def test_run_context_filter_outside_link_returns_empty_listing(
    context: Context,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outside = context.root.parent / "outside.md"
    outside.write_text("Private target.\n", encoding="utf-8")
    link = context.root / "knowledge" / "external.md"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")
    monkeypatch.setattr(questions, "load", lambda *args: context)
    assert questions.run(["--context", "knowledge/external.md"]) == 0
    assert capsys.readouterr().out == "No questions match.\n"


@pytest.mark.parametrize("message", ["questions: already prefixed", "config failure"])
def test_run_prefixes_only_unprefixed_read_errors(
    context: Context,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    def fail_load(*args: object) -> Context:
        raise KbError(message)

    monkeypatch.setattr(questions, "load", fail_load)
    expected = message if message.startswith("questions:") else f"questions: {message}"
    with pytest.raises(KbError) as error:
        questions.run([])
    assert str(error.value) == expected


def test_run_prefixes_os_errors_from_document_reads(
    context: Context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(questions, "load", lambda *args: context)

    def fail_rows(*args: object) -> list[questions.Row]:
        raise OSError("read failed")

    monkeypatch.setattr(questions, "_rows", fail_rows)
    with pytest.raises(KbError, match=r"^questions: read failed$"):
        questions.run([])
