"""Real Git status records and the four consumers of their paths."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import curation, git_status, remote
from kb.commands import curate, doctor
from kb.errors import KbError

from .test_hook import git, repo


@pytest.mark.parametrize(
    "middle",
    [
        " café name ",
        pytest.param(
            " -> ",
            marks=pytest.mark.skipif(os.name == "nt", reason="Windows forbids > in filenames"),
        ),
    ],
)
def test_status_consumers_keep_rename_names_and_count_one_record(
    tmp_path: Path, middle: str
) -> None:
    old = f"knowledge/old{middle}article.md"
    new = f"knowledge/new{middle}article.md"
    loose = "loose café note.md"
    root = repo(tmp_path / "repo", {old: b"Same contents.\n"})
    git(root, "mv", old, new)
    (root / loose).write_text("Untracked.\n", encoding="utf-8")
    before = git(root, "write-tree")

    assert set(remote.dirty_paths(root)) == {new, loose}
    assert doctor._dirty_count(root) == 2
    with pytest.raises(KbError) as refusal:
        curate._require_clean_tree(root)
    assert old in str(refusal.value) and new in str(refusal.value) and loose in str(refusal.value)
    entries = curate._worktree_entries(root)
    assert len(entries) == 2
    by_path = {entry.path: entry for entry in entries}
    assert by_path[new].old_path == old
    assert by_path[new].code == "R "
    assert by_path[loose].code == "??"
    assert git(root, "write-tree") == before
    assert (root / new).read_bytes() == b"Same contents.\n"


def test_rename_source_outside_content_stays_outside_in_every_path_consumer(tmp_path: Path) -> None:
    root = repo(
        tmp_path / "repo", {"outside.md": b"Same contents.\n", "content/knowledge/a.md": b"A\n"}
    )
    git(root, "mv", "outside.md", "content/knowledge/renamed.md")
    content = root / "content"

    assert remote.dirty_paths(content) == ("knowledge/renamed.md",)
    assert doctor._dirty_count(content) == 1
    with pytest.raises(KbError) as refusal:
        curate._require_clean_tree(content)
    assert "../outside.md" in str(refusal.value)
    entries = curate._worktree_entries(content)
    assert len(entries) == 1
    assert entries[0].path == "knowledge/renamed.md"
    assert entries[0].old_path == "../outside.md"
    batch = curation.make_batch(
        "20261026T120000-a1b2c3d4",
        datetime(2026, 10, 26, 12, tzinfo=UTC),
        100,
        (curation.defer_member(curation.Member("one.md", "a" * 64, 1), "Later"),),
    )
    with pytest.raises(KbError, match="uncommitted changes outside the batch") as refusal:
        curate._publication_changes(content, batch)
    assert "../outside.md" in str(refusal.value)


def test_publication_scopes_both_sides_of_a_rename(tmp_path: Path) -> None:
    root = repo(tmp_path / "repo", {"knowledge/old.md": b"Same contents.\n"})
    git(root, "mv", "knowledge/old.md", "knowledge/new.md")
    batch = curation.make_batch(
        "20261026T120000-a1b2c3d4",
        datetime(2026, 10, 26, 12, tzinfo=UTC),
        100,
        (curation.defer_member(curation.Member("one.md", "a" * 64, 1), "Later"),),
    )

    changes = curate._publication_changes(root, batch)

    assert [(change.status, change.path) for change in changes] == [
        ("A", "knowledge/new.md"),
        ("D", "knowledge/old.md"),
    ]


def test_porcelain_renames_and_copies_are_destination_first_with_opaque_paths() -> None:
    output = "R  new -> café.md\0?? old name.md\0C  copy.md\0source.md\0 M edited name.md\0"

    assert git_status.parse_porcelain(output) == [
        git_status.Entry("R ", "new -> café.md", "?? old name.md"),
        git_status.Entry("C ", "copy.md", "source.md"),
        git_status.Entry(" M", "edited name.md"),
    ]
    assert git_status.parse_porcelain("") == []


@pytest.mark.parametrize(
    "output", ["?? missing-nul", "R  new\0", "R  new\0\0", "?? \0", "bad\0", "?? okay\0\0"]
)
def test_malformed_porcelain_records_fail_with_the_command_context(output: str) -> None:
    with pytest.raises(KbError, match="curate: Git returned malformed"):
        git_status.parse_porcelain(output, command="curate")
