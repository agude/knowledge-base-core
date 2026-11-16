"""Tests for the transcript cache: reuse while a file is unchanged, and rebuild when it is not."""

import os
import pickle
import subprocess
from pathlib import Path

import pytest

from kb import token_cache
from kb.commands import sync
from kb.hosts import claude

LINE = (
    '{"type":"user","uuid":"u","timestamp":"2026-10-26T09:00:00Z",'
    '"cwd":"/work","message":{"role":"user","content":"hi"}}\n'
)
SECOND_LINE = (
    '{"type":"user","uuid":"v","timestamp":"2026-10-26T09:01:00Z",'
    '"cwd":"/work","message":{"role":"user","content":"again"}}\n'
)


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    path = tmp_path / "claude" / "projects" / "demo" / "main.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(LINE, encoding="utf-8")
    return path


@pytest.fixture
def environ(tmp_path: Path, transcript: Path) -> dict[str, str]:
    return {
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
        "CODEX_HOME": str(tmp_path / "codex"),
        "GOOSE_PATH_ROOT": str(tmp_path / "goose"),
    }


@pytest.fixture
def root(tmp_path: Path) -> Path:
    content = tmp_path / "content"
    content.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=content, check=True)
    (content / ".gitignore").write_text("/cache/\n", encoding="utf-8")
    return content


@pytest.fixture
def parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The session id of every Claude transcript that the scan parses, in order."""
    calls: list[str] = []
    original = claude.parse

    def counted(text: str, stem: str, parent: str | None) -> object:
        calls.append(stem)
        return original(text, stem, parent)

    monkeypatch.setattr(claude, "parse", counted)
    return calls


def stored_paths(root: Path) -> set[str]:
    with (root / "cache" / "transcripts.pickle").open("rb") as handle:
        return set(pickle.load(handle)["entries"])


def test_an_unchanged_transcript_is_not_parsed_again(
    root: Path, environ: dict[str, str], parses: list[str]
) -> None:
    first = sync.scan_transcripts(environ, root)
    cache_file = root / "cache" / "transcripts.pickle"
    written = cache_file.stat().st_mtime_ns

    second = sync.scan_transcripts(environ, root)

    assert parses == ["main"]
    assert second == first
    assert cache_file.stat().st_mtime_ns == written


def test_a_changed_transcript_is_parsed_again_when_its_size_or_mtime_changes(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    sync.scan_transcripts(environ, root)

    transcript.write_text(LINE + SECOND_LINE, encoding="utf-8")
    parses.clear()
    grown = sync.scan_transcripts(environ, root)
    assert parses == ["main"]
    assert grown == sync.scan_transcripts(environ)

    status = transcript.stat()
    os.utime(transcript, ns=(status.st_atime_ns, status.st_mtime_ns + 1_000_000_000))
    parses.clear()
    touched = sync.scan_transcripts(environ, root)
    assert parses == ["main"]
    assert touched == sync.scan_transcripts(environ)


def test_a_removed_transcript_leaves_the_cache(
    root: Path, environ: dict[str, str], transcript: Path
) -> None:
    sync.scan_transcripts(environ, root)
    assert stored_paths(root) == {str(transcript)}

    transcript.unlink()
    result = sync.scan_transcripts(environ, root)

    assert result.candidates == ()
    assert stored_paths(root) == set()


def test_an_unreadable_cache_file_is_replaced(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    cache_file = root / "cache" / "transcripts.pickle"
    cache_file.parent.mkdir()
    cache_file.write_bytes(b"not a pickle")

    result = sync.scan_transcripts(environ, root)

    assert parses == ["main"]
    assert result == sync.scan_transcripts(environ)
    assert stored_paths(root) == {str(transcript)}


def test_a_cache_of_another_shape_or_from_other_code_is_replaced(
    root: Path, environ: dict[str, str], parses: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_file = root / "cache" / "transcripts.pickle"
    cache_file.parent.mkdir()
    cache_file.write_bytes(pickle.dumps(["not", "a", "cache"]))
    sync.scan_transcripts(environ, root)
    assert parses == ["main"]

    monkeypatch.setattr(token_cache, "fingerprint", lambda *_: "other-kb-code")
    sync.scan_transcripts(environ, root)

    assert parses == ["main", "main"]


def test_a_cache_that_git_does_not_ignore_is_not_written(
    root: Path, environ: dict[str, str]
) -> None:
    (root / ".gitignore").unlink()

    result = sync.scan_transcripts(environ, root)

    assert len(result.candidates) == 1
    assert not (root / "cache").exists()


def test_a_cache_that_cannot_be_written_warns_and_the_scan_still_succeeds(
    root: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "cache").write_text("a file, not a directory\n", encoding="utf-8")

    result = sync.scan_transcripts(environ, root)

    assert len(result.candidates) == 1
    assert "transcript cache not written" in capsys.readouterr().err
