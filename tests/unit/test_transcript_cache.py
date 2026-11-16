"""Tests for the transcript cache: reuse while a file is unchanged, no stored text, and writes."""

import os
import pickle
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from kb import harvest, token_cache, transcript_cache
from kb.commands import curate_triage, sync
from kb.hosts import claude

LINE = (
    '{"type":"user","uuid":"u","timestamp":"2026-10-26T09:00:00Z",'
    '"cwd":"/work","message":{"role":"user","content":"hi"}}\n'
)
SECOND_LINE = (
    '{"type":"user","uuid":"v","timestamp":"2026-10-26T09:01:00Z",'
    '"cwd":"/work","message":{"role":"user","content":"again"}}\n'
)
MARKED_LINE = LINE.replace('"hi"', '"private-marker"')
LATER = datetime(2030, 1, 1, tzinfo=UTC)


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


def cache_file(root: Path) -> Path:
    return root / "cache" / "transcripts.pickle"


def stored_entries(root: Path) -> dict[str, Any]:
    with cache_file(root).open("rb") as handle:
        return dict(pickle.load(handle)["entries"])


def write_entries(root: Path, entries: Mapping[str, object]) -> None:
    """Write a cache file with the current format and code version, holding entries."""
    payload = {
        "format": transcript_cache.FORMAT,
        "fingerprint": token_cache.fingerprint(),
        "entries": entries,
    }
    cache_file(root).parent.mkdir(exist_ok=True)
    cache_file(root).write_bytes(pickle.dumps(payload))


def test_an_unchanged_transcript_is_not_parsed_again(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    first = sync.scan_transcripts(environ, root, store=True)
    written = cache_file(root).stat().st_mtime_ns

    second = sync.scan_transcripts(environ, root, store=True)

    assert parses == ["main"]
    assert [candidate.source for candidate in second.candidates] == [transcript]
    assert second.candidates[0].session == transcript_cache.without_text(
        first.candidates[0].session
    )
    assert cache_file(root).stat().st_mtime_ns == written


def test_a_changed_transcript_is_parsed_again_when_its_size_or_mtime_changes(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    sync.scan_transcripts(environ, root, store=True)

    transcript.write_text(LINE + SECOND_LINE, encoding="utf-8")
    parses.clear()
    grown = sync.scan_transcripts(environ, root, store=True)
    assert parses == ["main"]
    assert grown == sync.scan_transcripts(environ)

    status = transcript.stat()
    os.utime(transcript, ns=(status.st_atime_ns, status.st_mtime_ns + 1_000_000_000))
    parses.clear()
    touched = sync.scan_transcripts(environ, root, store=True)
    assert parses == ["main"]
    assert touched == sync.scan_transcripts(environ)


def test_read_only_scans_leave_the_cache_unwritten(root: Path, environ: dict[str, str]) -> None:
    result = sync.scan_transcripts(environ, root)

    assert len(result.candidates) == 1
    assert not (root / "cache").exists()


def test_read_only_scans_reuse_a_stored_cache_without_rewriting_it(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    sync.scan_transcripts(environ, root, store=True)
    stored_size = stored_entries(root)[str(transcript)].size
    written = cache_file(root).stat().st_mtime_ns
    transcript.write_text(LINE + SECOND_LINE, encoding="utf-8")
    parses.clear()

    sync.scan_transcripts(environ, root)

    assert parses == ["main"]
    assert cache_file(root).stat().st_mtime_ns == written
    assert stored_entries(root)[str(transcript)].size == stored_size


def test_a_removed_transcript_leaves_the_cache(
    root: Path, environ: dict[str, str], transcript: Path
) -> None:
    sync.scan_transcripts(environ, root, store=True)
    assert set(stored_entries(root)) == {str(transcript)}

    transcript.unlink()
    result = sync.scan_transcripts(environ, root, store=True)

    assert result.candidates == ()
    assert stored_entries(root) == {}


def test_stored_sessions_keep_no_message_text(
    root: Path, environ: dict[str, str], transcript: Path
) -> None:
    transcript.write_text(MARKED_LINE, encoding="utf-8")

    sync.scan_transcripts(environ, root, store=True)
    rescanned = sync.scan_transcripts(environ, root, store=True)

    assert b"private-marker" not in cache_file(root).read_bytes()
    assert rescanned.candidates[0].session.messages[0].text == ""
    assert rescanned.candidates[0].session.messages[0].commands == ()


def test_a_cached_session_that_holds_text_is_replaced(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    status = transcript.stat()
    full = claude.parse(LINE, "main", None)
    parses.clear()
    write_entries(
        root,
        {str(transcript): transcript_cache.Stored(status.st_size, status.st_mtime_ns, full)},
    )

    sync.scan_transcripts(environ, root, store=True)

    assert parses == ["main"]
    assert stored_entries(root)[str(transcript)].session.messages[0].text == ""


def test_a_cached_session_of_the_wrong_shape_is_replaced(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    status = transcript.stat()
    write_entries(
        root,
        {
            str(transcript): transcript_cache.Stored(
                status.st_size,
                status.st_mtime_ns,
                "invalid-session",  # type: ignore[arg-type]
            )
        },
    )

    result = sync.scan_transcripts(environ, root, store=True)

    assert parses == ["main"]
    assert result == sync.scan_transcripts(environ)


def test_an_unreadable_cache_file_is_replaced(
    root: Path, environ: dict[str, str], transcript: Path, parses: list[str]
) -> None:
    cache_file(root).parent.mkdir()
    cache_file(root).write_bytes(b"not a pickle")

    result = sync.scan_transcripts(environ, root, store=True)

    assert parses == ["main"]
    assert result == sync.scan_transcripts(environ)
    assert set(stored_entries(root)) == {str(transcript)}


def test_a_cache_of_another_shape_or_from_other_code_is_replaced(
    root: Path, environ: dict[str, str], parses: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_file(root).parent.mkdir()
    cache_file(root).write_bytes(pickle.dumps(["not", "a", "cache"]))
    sync.scan_transcripts(environ, root, store=True)
    assert parses == ["main"]

    monkeypatch.setattr(token_cache, "fingerprint", lambda *_: "other-kb-code")
    sync.scan_transcripts(environ, root, store=True)

    assert parses == ["main", "main"]


def test_a_cached_plan_takes_its_text_from_the_transcript(
    root: Path, environ: dict[str, str], parses: list[str]
) -> None:
    sync.scan_transcripts(environ, root, store=True)
    parses.clear()
    scanned = sync.scan_transcripts(environ, root, store=True)
    assert parses == []

    selection = harvest.select_candidates(
        scanned.candidates, harvest.HarvestState({}, {}), LATER, None
    )
    hydrated, failures = sync._hydrated(selection, scanned.candidates)

    assert failures == ()
    assert [message.text for plan in hydrated.plans for message in plan.messages] == ["hi"]


def test_a_transcript_changed_after_the_scan_fails_its_cached_plan(
    root: Path, environ: dict[str, str], transcript: Path
) -> None:
    sync.scan_transcripts(environ, root, store=True)
    scanned = sync.scan_transcripts(environ, root, store=True)
    selection = harvest.select_candidates(
        scanned.candidates, harvest.HarvestState({}, {}), LATER, None
    )
    transcript.write_text(LINE.replace('"uuid":"u"', '"uuid":"w"'), encoding="utf-8")

    hydrated, failures = sync._hydrated(selection, scanned.candidates)

    assert hydrated.plans == ()
    assert [(failure.session, failure.reason) for failure in failures] == [
        ("main", "transcript changed after it was scanned")
    ]


def test_a_cache_that_git_does_not_ignore_is_not_written(
    root: Path, environ: dict[str, str]
) -> None:
    (root / ".gitignore").unlink()

    result = sync.scan_transcripts(environ, root, store=True)

    assert len(result.candidates) == 1
    assert not (root / "cache").exists()


def test_a_cache_that_cannot_be_written_warns_and_the_scan_still_succeeds(
    root: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    (root / "cache").write_text("a file, not a directory\n", encoding="utf-8")

    result = sync.scan_transcripts(environ, root, store=True)

    assert len(result.candidates) == 1
    assert "transcript cache not written" in capsys.readouterr().err


def test_a_dry_run_triage_plan_leaves_the_cache_unwritten(
    root: Path, environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    curate_triage._triage_plan(root, store=False)
    assert not (root / "cache").exists()

    curate_triage._triage_plan(root, store=True)
    assert cache_file(root).is_file()
