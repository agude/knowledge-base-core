"""Pure publication rules and the validation they classify."""

from pathlib import Path

import pytest

from kb import lint, publish

ARTICLE = (
    "---\ntitle: Backups\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
    "# Backups\n\n## 1. Schedule\n\nNightly.\n"
)


def _write(root: Path, relpath: str, text: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_article_changes_use_new_paths_and_ignore_deletions_and_other_files() -> None:
    changes = [
        publish.Change("A", "knowledge/new.md"),
        publish.Change("M", "knowledge/old.md"),
        publish.Change("R", "knowledge/renamed.md", "knowledge/was.md"),
        publish.Change("C", "knowledge/copy.md", "knowledge/old.md"),
        publish.Change("T", "knowledge/type.md"),
        publish.Change("D", "knowledge/gone.md"),
        publish.Change("A", "sources/tool.md"),
        publish.Change("A", "knowledge/notes.txt"),
    ]

    assert publish.changed_articles(changes) == (
        "knowledge/copy.md",
        "knowledge/new.md",
        "knowledge/old.md",
        "knowledge/renamed.md",
        "knowledge/type.md",
    )


def test_vanished_paths_are_deleted_files_and_rename_sources() -> None:
    changes = [
        publish.Change("D", "knowledge/gone.md"),
        publish.Change("R", "knowledge/new.md", "knowledge/was.md"),
        publish.Change("A", "knowledge/added.md"),
    ]

    assert publish.vanished_paths(changes) == frozenset({"knowledge/gone.md", "knowledge/was.md"})


@pytest.mark.parametrize(
    ("change", "topology"),
    [
        (publish.Change("D", "knowledge/a.md"), True),
        (publish.Change("R", "knowledge/b.md", "knowledge/a.md"), True),
        (publish.Change("D", "sources/tool.md"), True),
        (publish.Change("R", "sources/new.md", "sources/old.md"), True),
        (publish.Change("D", "observations/archived/20261001T120000-abcdef12.md"), True),
        (publish.Change("R", "observations/archived/n.md", "observations/archived/o.md"), True),
        (publish.Change("D", "observations/pending/20261001T120000-abcdef12.md"), False),
        (publish.Change("A", "observations/archived/20261001T120000-abcdef12.md"), False),
        (publish.Change("M", "knowledge/a.md"), False),
        (publish.Change("D", "questions/open/20261001T120000-abcdef12.md"), False),
    ],
)
def test_topology_change_is_a_removed_or_moved_protected_path(
    change: publish.Change, topology: bool
) -> None:
    assert publish.topology_change([change]) is topology


def test_pending_to_archived_move_is_not_a_topology_change() -> None:
    changes = [
        publish.Change("D", "observations/pending/x.md"),
        publish.Change("A", "observations/archived/x.md"),
    ]

    assert publish.topology_change(changes) is False


def test_classification_blocks_changed_articles_and_removed_targets_only() -> None:
    findings = [
        lint.Finding("knowledge/changed.md", 3, "error", "bad heading"),
        lint.Finding(
            "knowledge/other.md",
            4,
            "error",
            "missing local Markdown link target: gone.md",
            "knowledge/gone.md",
        ),
        lint.Finding(
            "knowledge/other.md",
            5,
            "error",
            "missing local Markdown link target: x.md",
            "knowledge/x.md",
        ),
        lint.Finding("knowledge/other.md", 6, "warning", "H2 is long"),
    ]

    verdict = publish.classify(
        findings,
        frozenset({"knowledge/changed.md"}),
        frozenset({"knowledge/gone.md"}),
    )

    assert [finding.line for finding in verdict.blocking] == [3, 4]
    assert [finding.line for finding in verdict.preexisting] == [5, 6]


def test_validate_requires_ttl_only_for_changed_articles(tmp_path: Path) -> None:
    no_ttl = "---\ntitle: T\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n# T\n\n## 1. A\n\nX.\n"
    _write(tmp_path, "knowledge/old.md", no_ttl)
    _write(tmp_path, "knowledge/new.md", no_ttl)

    unchanged = publish.validate(tmp_path, [])
    assert unchanged.blocking == ()
    assert unchanged.preexisting == ()

    changed = publish.validate(tmp_path, [publish.Change("A", "knowledge/new.md")])
    assert [finding.path for finding in changed.blocking] == ["knowledge/new.md"]
    assert [finding.message for finding in changed.blocking] == ["front matter missing ttl"]
    assert changed.preexisting == ()


def test_validate_blocks_an_unchanged_reference_to_a_deleted_article(tmp_path: Path) -> None:
    _write(
        tmp_path, "knowledge/index.md", ARTICLE.replace("# Backups", "# Index") + "\n[b](b.md)\n"
    )
    _write(tmp_path, "knowledge/b.md", ARTICLE)
    (tmp_path / "knowledge/b.md").unlink()

    verdict = publish.validate(tmp_path, [publish.Change("D", "knowledge/b.md")])

    assert [finding.path for finding in verdict.blocking] == ["knowledge/index.md"]
    assert verdict.blocking[0].target == "knowledge/b.md"
    assert verdict.preexisting == ()


def test_validate_keeps_a_missing_non_markdown_source_preexisting(tmp_path: Path) -> None:
    text = ARTICLE.replace("ttl: domain\n", "ttl: domain\nsources:\n  - sources/gone.txt\n")
    _write(tmp_path, "knowledge/a.md", text)

    verdict = publish.validate(tmp_path, [])

    assert verdict.blocking == ()
    assert [finding.message for finding in verdict.preexisting] == [
        "missing local source reference: sources/gone.txt"
    ]


def test_validate_refuses_a_changed_article_that_is_not_utf8(tmp_path: Path) -> None:
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge/bad.md").write_bytes(b"\xff\xfe# Bad\n")

    verdict = publish.validate(tmp_path, [publish.Change("A", "knowledge/bad.md")])

    assert "article is not valid UTF-8" in [finding.message for finding in verdict.blocking]
