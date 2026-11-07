"""Publication snapshots resolve links and read blob bytes without using worktree targets."""

import subprocess
import sys
from pathlib import Path

import pytest

from kb import snapshot
from kb.errors import KbError

from .test_hook import ARTICLE, git, repo


def test_index_reads_binary_blobs_and_names_without_text_line_splitting(tmp_path: Path) -> None:
    name = "knowledge/café name.md" if sys.platform == "win32" else "knowledge/café\nname.md"
    files = {name: ARTICLE.encode(), "sources/raw.bin": b"\x00\xff\r\n"}
    root = repo(tmp_path / "content", files)
    (root / "sources/raw.bin").write_bytes(b"unstaged")

    content = snapshot.read_index(root)

    assert content.markdown_files() == [name]
    for name, data in files.items():
        assert content.read_bytes(name) == data


def test_index_keeps_content_subdirectory_paths_and_ignores_submodules(tmp_path: Path) -> None:
    root = repo(
        tmp_path / "repo",
        {"content/knowledge/a.md": ARTICLE.encode(), "outside.md": b"outside"},
    )
    head = git(root, "rev-parse", "HEAD").strip()
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{head},content/vendor")

    content = snapshot.read_index(root / "content")

    assert content.markdown_files() == ["knowledge/a.md"]
    assert content.read_bytes("knowledge/a.md") == ARTICLE.encode()
    assert not content.is_file("vendor")
    assert not content.is_file("outside.md")


@pytest.mark.parametrize("link", [b"real.md", b"../sources/real.md"])
def test_index_follows_internal_links_without_reading_worktree_targets(
    tmp_path: Path, link: bytes
) -> None:
    files = {
        "knowledge/alias.md": ("120000", link),
        "knowledge/real.md": ("100644", ARTICLE.encode()),
        "sources/real.md": ("100644", ARTICLE.encode()),
    }
    content = snapshot.Index(tmp_path, files)

    assert content.read_bytes("knowledge/alias.md") == ARTICLE.encode()
    assert content.is_file("knowledge/alias.md")


def test_index_rebases_absolute_internal_links(tmp_path: Path) -> None:
    content = snapshot.Index(
        tmp_path,
        {
            "knowledge/alias.md": ("120000", str(tmp_path / "sources/real.md").encode()),
            "sources/real.md": ("100644", b"target"),
        },
    )

    assert content.resolve("knowledge/alias.md") == "sources/real.md"
    assert content.read_bytes("knowledge/alias.md") == b"target"


@pytest.mark.parametrize("link", [b"../../external.md", b"/outside.md", b"alias.md"])
def test_index_refuses_escaping_and_cyclic_links(tmp_path: Path, link: bytes) -> None:
    content = snapshot.Index(tmp_path, {"knowledge/alias.md": ("120000", link)})

    with pytest.raises(ValueError):
        content.read_bytes("knowledge/alias.md")


def test_index_refuses_a_missing_link_target(tmp_path: Path) -> None:
    content = snapshot.Index(tmp_path, {"knowledge/alias.md": ("120000", b"missing.md")})

    assert not content.is_file("knowledge/alias.md")
    with pytest.raises(FileNotFoundError):
        content.read_bytes("knowledge/alias.md")


def test_unmerged_entries_are_not_a_valid_publication_snapshot(tmp_path: Path) -> None:
    root = repo(tmp_path / "repo", {"knowledge/a.md": ARTICLE.encode()})
    object_id = git(root, "rev-parse", "HEAD:knowledge/a.md").strip()
    subprocess.run(
        ["git", "update-index", "--index-info"],
        cwd=root,
        input=f"100644 {object_id} 1\tknowledge/a.md\n",
        text=True,
        check=True,
    )

    with pytest.raises(KbError, match="unmerged index"):
        snapshot.read_index(root)
