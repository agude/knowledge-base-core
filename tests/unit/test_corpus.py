"""Tests for finding, resolving, and reading content files, against a copy of the fixture."""

import shutil
from pathlib import Path

import pytest

from kb import corpus
from kb.errors import KbError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A writable copy of the content fixture, resolved as the context resolves it."""
    copy = tmp_path / "content"
    shutil.copytree(FIXTURE, copy)
    return copy.resolve()


def test_markdown_files_under_a_directory_are_sorted_and_relative(root: Path) -> None:
    files = corpus.markdown_files(root, "knowledge/infra")
    assert files == [
        "knowledge/infra/backups.md",
        "knowledge/infra/nas.md",
        "knowledge/infra/plex.md",
        "knowledge/infra/shelf-counts.md",
        "knowledge/infra/shelves.md",
        "knowledge/infra/syncthing.md",
    ]


def test_markdown_files_skip_hidden_directories_and_other_files(root: Path) -> None:
    (root / ".hidden").mkdir()
    (root / ".hidden" / "secret.md").write_text("# Hidden\n", encoding="utf-8")
    (root / "knowledge" / "notes.txt").write_text("not markdown\n", encoding="utf-8")
    found = corpus.markdown_files(root, ".")
    assert all(not path.startswith(".hidden") for path in found)
    assert "knowledge/notes.txt" not in found


def test_markdown_files_of_a_single_file_or_missing_path(root: Path) -> None:
    assert corpus.markdown_files(root, "knowledge/infra/nas.md") == ["knowledge/infra/nas.md"]
    assert corpus.markdown_files(root, "knowledge/nope.md") == []
    (root / "plain.txt").write_text("x\n", encoding="utf-8")
    assert corpus.markdown_files(root, "plain.txt") == []


def test_markdown_files_leave_out_links_that_resolve_outside(root: Path) -> None:
    outside = root.parent / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    (root / "knowledge" / "leak.md").symlink_to(outside)
    assert "knowledge/leak.md" not in corpus.markdown_files(root, "knowledge")


def test_resolve_path_accepts_content_relative_and_knowledge_relative_paths(root: Path) -> None:
    assert corpus.resolve_path(root, "knowledge/infra/nas.md", "kb read") == (
        "knowledge/infra/nas.md"
    )
    assert corpus.resolve_path(root, "infra/nas.md", "kb read") == "knowledge/infra/nas.md"
    assert corpus.resolve_path(root, "knowledge", "kb read") == "knowledge"


def test_resolve_path_accepts_a_unique_file_name(root: Path) -> None:
    assert corpus.resolve_path(root, "plex.md", "kb read") == "knowledge/infra/plex.md"


def test_resolve_path_reports_an_ambiguous_file_name(root: Path) -> None:
    with pytest.raises(KbError) as error:
        corpus.resolve_path(root, "backups.md", "kb read")
    assert str(error.value) == (
        'kb read: "backups.md" matches 2 files:\n'
        "  knowledge/infra/backups.md\n"
        "  knowledge/rules/backups.md"
    )


def test_resolve_path_returns_none_when_nothing_matches(root: Path) -> None:
    assert corpus.resolve_path(root, "knowledge/nope.md", "kb read") is None
    assert corpus.resolve_path(root, "nope.md", "kb read") is None
    assert corpus.resolve_path(root, "infra/nope/x.md", "kb read") is None
    assert corpus.resolve_path(root, "", "kb read") is None


def test_resolve_path_refuses_a_relative_path_outside_the_repository(root: Path) -> None:
    (root.parent / "outside.md").write_text("# Outside\n", encoding="utf-8")
    with pytest.raises(KbError, match=r"^kb read: \.\./outside\.md resolves outside"):
        corpus.resolve_path(root, "../outside.md", "kb read")


def test_resolve_path_refuses_a_symlink_outside_the_repository(root: Path) -> None:
    outside = root.parent / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    (root / "knowledge" / "leak.md").symlink_to(outside)
    with pytest.raises(KbError, match=r"^kb read: knowledge/leak\.md resolves outside"):
        corpus.resolve_path(root, "knowledge/leak.md", "kb read")


def test_resolve_path_refuses_an_absolute_path_outside_the_repository(root: Path) -> None:
    outside = root.parent / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    with pytest.raises(KbError, match=r"resolves outside"):
        corpus.resolve_path(root, str(outside), "kb read")


def test_read_document_parses_the_file_bytes(root: Path) -> None:
    document = corpus.read_document(root, "knowledge/infra/nas.md")
    assert document.path == "knowledge/infra/nas.md"
    assert document.title == "NAS"


def test_read_document_keeps_crlf_out_of_the_lines(root: Path) -> None:
    document = corpus.read_document(root, "knowledge/rules/crlf-line-endings.md")
    assert all("\r" not in line for line in document.lines)


def test_read_document_drops_a_byte_order_mark_and_replaces_bad_bytes(root: Path) -> None:
    (root / "knowledge" / "bom.md").write_bytes(b"\xef\xbb\xbf---\ntitle: B\xff\n---\n")
    document = corpus.read_document(root, "knowledge/bom.md")
    assert document.title == "B\ufffd"


def test_read_document_reports_a_missing_file(root: Path) -> None:
    with pytest.raises(KbError, match=r"^kb: cannot read knowledge/missing\.md: "):
        corpus.read_document(root, "knowledge/missing.md")


@pytest.mark.parametrize(
    ("relpath", "curated"),
    [
        ("knowledge/a.md", True),
        ("sources/a.md", True),
        ("observations/pending/a.md", False),
        ("questions/open/a.md", False),
        ("AGENTS.md", False),
    ],
)
def test_is_curated_covers_knowledge_and_sources_only(relpath: str, curated: bool) -> None:
    assert corpus.is_curated(relpath) is curated


def test_markdown_files_skip_hidden_files(root: Path) -> None:
    (root / "knowledge" / ".draft.md").write_text("# Draft\n", encoding="utf-8")
    assert "knowledge/.draft.md" not in corpus.markdown_files(root, "knowledge")
