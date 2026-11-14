"""End-to-end tests for `kb edit`: section text from stdin placed in an article."""

from pathlib import Path

from .harness import Kb

ARTICLE = (
    "---\ntitle: Workflow\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n\n"
    "# Workflow\n\n## First\n\nFirst body.\n\n## Second\n\nSecond body.\n"
)


def _article(kb: Kb) -> Path:
    path = kb.content / "knowledge" / "workflow.md"
    path.write_text(ARTICLE, encoding="utf-8")
    return path


def test_help_lists_the_subcommands(git_kb: Kb) -> None:
    result = git_kb("edit", "--help")

    assert result.returncode == 0
    assert result.stdout.startswith(
        "Usage: kb edit {replace,append,insert,move,remove,ttl} ...\n\n"
    )
    insert = git_kb("edit", "insert", "--help")
    assert insert.stdout.startswith(
        "Usage: kb edit insert ARTICLE (--after FRAGMENT | --before FRAGMENT)\n"
    )


def test_insert_reports_the_new_locator_renumbering_and_missing_ttl(git_kb: Kb) -> None:
    path = _article(git_kb)

    result = git_kb(
        "edit",
        "insert",
        "knowledge/workflow.md",
        "--after",
        "top",
        stdin="## Zeroth\n\nNew first section.\n",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "Edited: knowledge/workflow.md\n"
        "  knowledge/workflow.md#1 | Zeroth\n"
        "Renumbered: knowledge/workflow.md#1 -> #2 | First\n"
        "Renumbered: knowledge/workflow.md#2 -> #3 | Second\n"
        "Note: knowledge/workflow.md has no ttl; curate finish requires one. "
        "Set it with: kb edit ttl knowledge/workflow.md TTL\n"
    )
    assert "# Workflow\n\n## Zeroth\n\nNew first section.\n\n## First\n" in path.read_text(
        encoding="utf-8"
    )


def test_replace_append_move_remove_and_ttl(git_kb: Kb) -> None:
    path = _article(git_kb)

    replaced = git_kb(
        "edit", "replace", "knowledge/workflow.md#2", stdin="## Second\n\n- Rewritten entry.\n"
    )
    appended = git_kb("edit", "append", "knowledge/workflow.md#1", stdin="Appended paragraph.")
    moved = git_kb("edit", "move", "knowledge/workflow.md#2", "--before", "1")
    removed = git_kb("edit", "remove", "knowledge/workflow.md#2")
    ttl = git_kb("edit", "ttl", "knowledge/workflow.md", "180")

    for result in (replaced, appended, moved, removed, ttl):
        assert result.returncode == 0, result.stderr
    assert appended.stdout.startswith(
        "Edited: knowledge/workflow.md\n  knowledge/workflow.md#1 | First\n"
    )
    assert path.read_text(encoding="utf-8") == (
        "---\ntitle: Workflow\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: 180\n---\n\n"
        "# Workflow\n\n## Second\n\n- Rewritten entry.\n"
    )
    assert "Note:" not in ttl.stdout


def test_a_missing_section_lists_the_articles_sections_and_writes_nothing(git_kb: Kb) -> None:
    path = _article(git_kb)

    result = git_kb("edit", "replace", "knowledge/workflow.md#7", stdin="## Seventh\n\nText.")

    assert result.returncode == 1
    assert result.stderr == (
        "edit: no section 7. Its sections:\n"
        "  knowledge/workflow.md#1 | First\n"
        "  knowledge/workflow.md#2 | Second\n"
    )
    assert path.read_text(encoding="utf-8") == ARTICLE


def test_an_edit_that_adds_a_lint_error_is_refused(git_kb: Kb) -> None:
    path = _article(git_kb)

    result = git_kb("edit", "append", "knowledge/workflow.md#1", stdin="See [missing](missing.md).")

    assert result.returncode == 1
    assert "edit: the edit would add lint errors; nothing was written:" in result.stderr
    assert path.read_text(encoding="utf-8") == ARTICLE


def test_secret_text_is_refused_before_writing(git_kb: Kb) -> None:
    path = _article(git_kb)

    result = git_kb(
        "edit",
        "append",
        "knowledge/workflow.md#1",
        stdin='Notes.\npassword = "hunter2hunter2"\n',
    )

    assert result.returncode == 1
    assert result.stderr == (
        "edit: possible secret in the text on stdin (Secret Keyword) at line 2\n"
    )
    assert path.read_text(encoding="utf-8") == ARTICLE


def test_usage_errors(git_kb: Kb) -> None:
    _article(git_kb)

    no_fragment = git_kb("edit", "remove", "knowledge/workflow.md")
    both = git_kb("edit", "move", "knowledge/workflow.md#1", "--after", "2", "--before", "2")
    bad_ttl = git_kb("edit", "ttl", "knowledge/workflow.md", "0")
    outside = git_kb("edit", "ttl", "observations/pending/x.md", "180")

    assert no_fragment.stderr == (
        "edit: remove needs a numbered section locator: ARTICLE#N or #N.M\n"
    )
    assert both.stderr == ("Usage: kb edit move LOCATOR (--after FRAGMENT | --before FRAGMENT)\n")
    assert bad_ttl.stderr == "edit: invalid TTL: 0\n"
    assert outside.returncode == 1
