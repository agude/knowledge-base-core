"""Publication snapshots resolve links and read blob bytes without using worktree targets."""

import subprocess
import sys
from pathlib import Path

import pytest

from kb import lint, model, snapshot
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
    content = snapshot.GitFiles(tmp_path, files)

    assert content.read_bytes("knowledge/alias.md") == ARTICLE.encode()
    assert content.is_file("knowledge/alias.md")


def test_index_rebases_absolute_internal_links(tmp_path: Path) -> None:
    content = snapshot.GitFiles(
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
    content = snapshot.GitFiles(tmp_path, {"knowledge/alias.md": ("120000", link)})

    with pytest.raises(ValueError):
        content.read_bytes("knowledge/alias.md")


def test_index_refuses_a_missing_link_target(tmp_path: Path) -> None:
    content = snapshot.GitFiles(tmp_path, {"knowledge/alias.md": ("120000", b"missing.md")})

    assert not content.is_file("knowledge/alias.md")
    with pytest.raises(FileNotFoundError):
        content.read_bytes("knowledge/alias.md")


@pytest.mark.parametrize("indexed", [False, True])
@pytest.mark.parametrize("sibling_has_anchor", [False, True])
def test_article_link_references_use_the_link_directory(
    tmp_path: Path, indexed: bool, sibling_has_anchor: bool
) -> None:
    article = ARTICLE + "\nSee [sibling](sibling.md#unique-anchor).\n"
    root = repo(
        tmp_path / "repo",
        {
            "sources/real.md": article.encode(),
            "sources/sibling.md": (
                ARTICLE if sibling_has_anchor else ARTICLE + "\n## Unique anchor\n"
            ).encode(),
            "knowledge/sibling.md": (
                ARTICLE + "\n## Unique anchor\n" if sibling_has_anchor else ARTICLE
            ).encode(),
        },
    )
    (root / "knowledge/alias.md").symlink_to("../sources/real.md")
    git(root, "add", "--", "knowledge/alias.md")
    content = snapshot.read_index(root) if indexed else snapshot.Worktree(root)
    document = model.parse("knowledge/alias.md", article)

    findings = lint.reference_findings(root, document, {}, content=content)

    if sibling_has_anchor:
        assert findings == []
    else:
        assert len(findings) == 1
        assert findings[0].target == "knowledge/sibling.md"
        assert "missing local Markdown link anchor" in findings[0].message


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


def test_head_snapshot_uses_committed_bytes_and_content_relative_paths(tmp_path: Path) -> None:
    root = repo(tmp_path / "repo", {"content/knowledge/a.md": ARTICLE.encode(), "outside.md": b"x"})
    nested = root / "content"
    (nested / "knowledge/a.md").write_bytes(b"unstaged")

    baseline = snapshot.read_head(nested, "curate")

    assert baseline.markdown_files() == ["knowledge/a.md"]
    assert baseline.read_bytes("knowledge/a.md") == ARTICLE.encode()
    assert not baseline.is_file("outside.md")


def test_an_unborn_head_has_an_empty_baseline(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    assert snapshot.read_head(tmp_path, "hook").files == {}


def test_an_unreadable_head_is_not_an_empty_baseline(tmp_path: Path) -> None:
    root = repo(tmp_path / "repo", {"knowledge/a.md": ARTICLE.encode()})
    (root / ".git/HEAD").write_text("invalid head\n", encoding="utf-8")

    with pytest.raises(KbError, match="curate: cannot read publication baseline HEAD"):
        snapshot.read_head(root, "curate")
