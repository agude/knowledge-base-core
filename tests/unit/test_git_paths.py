"""Content-relative conversions for Git paths."""

import subprocess
from pathlib import Path

import pytest

from kb import git_paths
from kb.errors import KbError


def test_repository_prefix_is_empty_at_the_root_and_slash_terminated_below_it(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    nested = repository / "content" / "notes"
    nested.mkdir(parents=True)

    assert git_paths.repository_prefix(repository, "test") == ""
    assert git_paths.repository_prefix(nested, "test") == "content/notes/"


def test_repository_paths_convert_to_content_paths_without_claiming_outside_files() -> None:
    prefix = "content/notes/"

    assert git_paths.to_content_path("content/notes/knowledge/a.md", prefix) == "knowledge/a.md"
    assert git_paths.to_content_path("content/notes", prefix) == "."
    assert git_paths.to_content_path("README.md", prefix) == "../../README.md"


def test_content_path_converts_for_head_and_refuses_parent_paths() -> None:
    assert git_paths.to_repository_path("observations/pending/a.md", "content/") == (
        "content/observations/pending/a.md"
    )
    with pytest.raises(ValueError, match="must not escape"):
        git_paths.to_repository_path("../outside.md", "content/")


def test_repository_prefix_reports_the_command_for_nonrepositories(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="test: the content repository is not a git repository"):
        git_paths.repository_prefix(tmp_path, "test")
