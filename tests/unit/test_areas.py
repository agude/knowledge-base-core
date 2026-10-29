"""Normalization and safe comparison for question contexts."""

import shutil
from pathlib import Path

import pytest

from kb import areas
from kb.errors import KbError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    content = tmp_path / "content"
    shutil.copytree(FIXTURE, content)
    return content.resolve()


def test_resolves_content_relative_knowledge_relative_and_unique_names(root: Path) -> None:
    assert areas.for_storage(root, "knowledge/infra/nas.md", "kb gap") == "knowledge/infra/nas.md"
    assert areas.for_storage(root, "./infra/./nas.md/", "kb gap") == "knowledge/infra/nas.md"
    assert areas.for_storage(root, "nas.md", "kb gap") == "knowledge/infra/nas.md"
    assert areas.for_storage(root, r"infra\nas.md", "kb gap") == "knowledge/infra/nas.md"


def test_retains_deleted_paths_without_inferring_a_new_target(root: Path) -> None:
    deleted = "knowledge/projects/shapez2/routing.md"
    moved = "knowledge/projects/shapez2/new-routing.md"
    assert areas.for_storage(root, deleted, "kb gap") == deleted
    assert areas.canonical_area(root, deleted) == deleted
    assert not areas.overlaps(deleted, moved)


def test_missing_shorthand_defaults_to_knowledge(root: Path) -> None:
    assert areas.for_storage(root, "future/area", "kb gap") == "knowledge/future/area"
    assert areas.canonical_area(root, "future/area") == "knowledge/future/area"


def test_ambiguous_stored_context_does_not_match_but_supplied_context_errors(root: Path) -> None:
    assert areas.canonical_area(root, "backups.md") is None
    with pytest.raises(KbError, match=r'"backups.md" matches 2 files'):
        areas.for_storage(root, "backups.md", "kb gap")


def test_directory_and_markdown_contexts_are_distinct(root: Path) -> None:
    directory = root / "knowledge" / "infra" / "backups"
    directory.mkdir()
    directory_area = areas.canonical_area(root, "knowledge/infra/backups")
    article_area = areas.canonical_area(root, "knowledge/infra/backups.md")
    assert directory_area == "knowledge/infra/backups"
    assert article_area == "knowledge/infra/backups.md"
    assert not areas.overlaps(directory_area, article_area)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "../outside",
        "knowledge/../outside",
        "/absolute",
        r"C:\outside",
        "file.md#2",
        "bad\x7fpath",
    ],
)
def test_rejects_invalid_supplied_context_text(root: Path, value: str) -> None:
    with pytest.raises(KbError):
        areas.for_storage(root, value, "kb gap")


def test_internal_symlink_aliases_resolve_on_both_sides(root: Path) -> None:
    alias = root / "knowledge" / "infra-alias"
    alias.symlink_to(root / "knowledge" / "infra", target_is_directory=True)
    stored_context = areas.canonical_area(root, "knowledge/infra-alias")
    requested_scope = areas.canonical_area(root, "knowledge/infra")
    requested_alias = areas.canonical_area(root, "infra-alias")
    assert stored_context == "knowledge/infra"
    assert requested_scope == requested_alias == "knowledge/infra"
    assert areas.overlaps(stored_context, requested_alias)


def test_external_symlink_is_preserved_for_storage_but_never_matches(
    root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("Private target content.\n", encoding="utf-8")
    link = root / "knowledge" / "external.md"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")

    assert areas.for_storage(root, "knowledge/external.md", "kb gap") == "knowledge/external.md"
    assert areas.canonical_area(root, "knowledge/external.md") is None
