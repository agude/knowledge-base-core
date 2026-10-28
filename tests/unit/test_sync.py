"""In-process coverage for the sync command and its git and filesystem helpers."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kb import config, dates, harvest, lock, model, observation, remote, secrets
from kb.commands import sync
from kb.errors import KbError
from kb.transcript_observation import ContentLine
from kb.transcripts import Message, Session

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
START = NOW - timedelta(hours=3)
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Sync Test",
    "GIT_AUTHOR_EMAIL": "sync@example.invalid",
    "GIT_COMMITTER_NAME": "Sync Test",
    "GIT_COMMITTER_EMAIL": "sync@example.invalid",
}


class FakeMsvcrt:
    """The Windows lock operations used by the in-process command simulation."""

    LK_NBLCK = 2
    LK_UNLCK = 0

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None:
        pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed.txt")
    git(root, "commit", "-q", "-m", "Seed")
    return root


def make_session(
    session_id: str | None = "session",
    *,
    app: str = "claude-code",
    text: str = "A user message.",
    malformed: int = 0,
    duplicates: int = 0,
) -> Session:
    return Session(
        app=app,  # type: ignore[arg-type]
        id=session_id,
        project="/fixture/project",
        parent_session=None,
        forked_from=None,
        messages=(Message("message-1", START, "user", text),),
        latest_timestamp=START,
        snapshot_complete=True,
        malformed_lines=malformed,
        duplicate_ids=duplicates,
    )


def make_plan(session: Session | None = None, *, part: int = 1) -> harvest.HarvestPlan:
    session = session or make_session()
    return harvest.HarvestPlan(session, part, session.messages, None)


def completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], returncode, stdout, stderr)


def completed_bytes(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([b"git"], returncode, stdout, stderr)


def observation_text(session: str = "saved") -> str:
    return (
        "---\n"
        'title: "Saved transcript"\n'
        "source: session-transcript\n"
        'host: "test-host"\n'
        "app: claude-code\n"
        f'session: "{session}"\n'
        "part: 1\n"
        'first_message: "message-1"\n'
        'last_message: "message-1"\n'
        "started: 2026-10-26T09:00:00Z\n"
        "ended: 2026-10-26T09:00:00Z\n"
        "created: 2026-10-26T12:00:00Z\n"
        "---\n\nBody.\n"
    )


def test_run_help_usage_and_exclusive_switches(capsys: pytest.CaptureFixture[str]) -> None:
    assert sync.run(["--help"]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb sync [--status]")
    for words in (["extra"], ["--status", "--dry-run"], ["--no-push", "--dry-run"]):
        with pytest.raises(KbError, match="Usage: kb sync"):
            sync.run(words)


def _patch_run_setup(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("KB_CONTENT", str(root))
    monkeypatch.setenv("KB_LOCK_WAIT", "0")
    monkeypatch.setattr(sync, "config_file", lambda *args: root / "config.toml")
    monkeypatch.setattr(config, "read_harvest_since", lambda _: None)
    monkeypatch.setattr(dates, "now", lambda _: NOW)
    monkeypatch.setattr(socket, "gethostname", lambda: "test-host.local")
    monkeypatch.setattr(lock, "git_dir", lambda _: root / ".git")


def test_windows_sync_ignores_a_held_legacy_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    _patch_run_setup(monkeypatch, root)
    legacy = root / ".observe.lock"
    legacy.mkdir()
    (legacy / "pid").write_text("12345\n", encoding="utf-8")
    selected_platforms: list[str] = []

    def windows_backend(platform: str) -> lock.Backend:
        selected_platforms.append(platform)
        return lock.MsvcrtBackend(FakeMsvcrt())

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(lock, "default_backend", windows_backend)
    monkeypatch.setattr(
        lock, "take_legacy_lock", lambda *args: pytest.fail("Windows tried the legacy lock")
    )
    monkeypatch.setattr(sync, "_sync", lambda *args: 0)

    assert sync.run([]) == 0
    assert selected_platforms == ["win32"]
    assert (legacy / "pid").read_text(encoding="utf-8") == "12345\n"


def test_run_dry_run_dispatches_without_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    _patch_run_setup(monkeypatch, root)
    called: list[tuple[object, ...]] = []

    def fake_dry_run(*args: object) -> int:
        called.append(args)
        return 7

    monkeypatch.setattr(sync, "_dry_run", fake_dry_run)
    monkeypatch.setattr(lock, "write_lock", lambda *args: pytest.fail("dry run locked"))

    assert sync.run(["--dry-run"]) == 7
    assert called[0][0:4] == (root, root / ".git", os.environ, "test-host")


def test_run_validates_wait_and_wraps_setup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    _patch_run_setup(monkeypatch, root)
    monkeypatch.setenv("KB_LOCK_WAIT", "bad")
    with pytest.raises(KbError, match="Usage: kb sync"):
        sync.run([])

    monkeypatch.setenv("KB_LOCK_WAIT", "0")
    monkeypatch.setattr(
        sync, "content_root", lambda *args: (_ for _ in ()).throw(KbError("bad root"))
    )
    with pytest.raises(KbError, match="sync: bad root"):
        sync.run([])

    monkeypatch.setattr(sync, "content_root", config.content_root)
    monkeypatch.setattr(
        config,
        "read_harvest_since",
        lambda _: (_ for _ in ()).throw(OSError("config read")),
    )
    with pytest.raises(KbError, match="sync: config read"):
        sync.run(["--dry-run"])


def test_run_dispatches_status_and_sync_and_wraps_lock_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    _patch_run_setup(monkeypatch, root)
    monkeypatch.setattr(lock, "write_lock", lambda *args: nullcontext())
    calls: list[str] = []

    def fake_status(*args: object) -> int:
        calls.append("status")
        return 2

    def fake_sync(*args: object) -> int:
        calls.append("sync")
        return 3

    monkeypatch.setattr(sync, "_status", fake_status)
    monkeypatch.setattr(sync, "_sync", fake_sync)
    assert sync.run(["--status"]) == 2
    assert sync.run(["--no-push"]) == 3
    assert calls == ["status", "sync"]

    @contextmanager
    def busy(*args: object) -> Iterator[None]:
        raise lock.LockBusy(4)
        yield

    monkeypatch.setattr(lock, "write_lock", busy)
    with pytest.raises(KbError, match=r"busy \(waited 4s"):
        sync.run([])


@pytest.mark.parametrize("message", ["sync: already labelled", "failure"])
def test_run_preserves_prefixed_errors_and_prefixes_other_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    root = make_repo(tmp_path / "content")
    _patch_run_setup(monkeypatch, root)
    monkeypatch.setattr(lock, "write_lock", lambda *args: nullcontext())
    monkeypatch.setattr(sync, "_sync", lambda *args: (_ for _ in ()).throw(KbError(message)))
    with pytest.raises(KbError) as error:
        sync.run([])
    assert str(error.value) == (message if message.startswith("sync:") else f"sync: {message}")


def test_run_wraps_unicode_errors_from_the_locked_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    _patch_run_setup(monkeypatch, root)
    monkeypatch.setattr(lock, "write_lock", lambda *args: nullcontext())
    monkeypatch.setattr(sync, "_sync", lambda *args: (_ for _ in ()).throw(UnicodeError("decode")))
    with pytest.raises(KbError, match="sync: decode"):
        sync.run([])


def test_sync_without_harvesting_runs_recovery_and_syncs_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "content")
    calls: list[str] = []
    monkeypatch.setattr(sync, "_recover", lambda *args: calls.append("recover"))
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: ())
    monkeypatch.setattr(sync, "_fetch_status", lambda _: (sync.RemoteStatus("main", 0, 0), None))
    monkeypatch.setattr(
        sync,
        "_sync_remote",
        lambda *args: (("Already in sync with origin/main.",), ()),
    )
    assert sync._sync(root, root / ".git", {}, "test-host", NOW, None, False) == 0
    assert calls == ["recover"]
    assert "Already in sync" in capsys.readouterr().out


def test_sync_reports_dirty_paths_and_recovery_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "content")
    monkeypatch.setattr(sync, "_recover", lambda *args: (_ for _ in ()).throw(KbError("broken")))
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: tuple(f"file-{i}" for i in range(12)))
    assert sync._sync(root, root / ".git", {}, "test-host", NOW, None, False) == 1
    captured = capsys.readouterr()
    assert "sync: recovery failed: broken" in captured.err
    assert captured.err.count("  file-") == 10


def test_dirty_worktree_without_other_errors_exits_successfully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "content")
    monkeypatch.setattr(sync, "_recover", lambda *args: None)
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: ("local.md",))
    assert sync._sync(root, root / ".git", {}, "host", NOW, None, False) == 0
    assert "not pulling or pushing" in capsys.readouterr().err


def test_sync_returns_fetch_error_and_combines_harvest_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "content")
    monkeypatch.setattr(sync, "_recover", lambda *args: None)
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: ())
    monkeypatch.setattr(sync, "_fetch_status", lambda _: (None, "sync: fetch failed"))
    assert sync._sync(root, root / ".git", {}, "test-host", NOW, None, False) == 1
    assert "sync: fetch failed" in capsys.readouterr().err


def test_sync_harvests_reports_record_counts_and_completes_remote_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_repo(tmp_path / "content")
    candidate = harvest.Candidate(make_session(malformed=1, duplicates=2), START)
    monkeypatch.setattr(
        sync,
        "_recover",
        lambda *args: (_ for _ in ()).throw(OSError("recovery")),
    )
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((candidate,), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(harvest, "reconstruct_state", lambda *args: harvest.HarvestState({}, {}))
    monkeypatch.setattr(
        harvest,
        "select_candidates",
        lambda *args: harvest.Selection((), 0, 0, ("rewrite warning",)),
    )
    monkeypatch.setattr(
        sync,
        "_write_selection",
        lambda *args: (sync.WriteResult(1, ()), 2, 20, 1, {"Secret": 1}),
    )
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: ())
    monkeypatch.setattr(sync, "_fetch_status", lambda _: (sync.RemoteStatus("main", 0, 0), None))
    monkeypatch.setattr(sync, "_sync_remote", lambda *args: ((), ("sync: push failed",)))
    assert sync._sync(root, root / ".git", {}, "host", NOW, START, False) == 1
    captured = capsys.readouterr()
    assert "Harvested: 1" in captured.out
    assert "1 malformed line(s), 2 duplicate message ID(s)" in captured.out
    assert "Secret: 1" in captured.out
    assert "rewrite warning" in captured.err and "sync: push failed" in captured.err


def test_sync_pushes_after_a_session_is_skipped_then_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_repo(tmp_path / "content")
    candidate = harvest.Candidate(make_session(), START)
    monkeypatch.setattr(sync, "_recover", lambda *args: None)
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((candidate,), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(harvest, "reconstruct_state", lambda *args: harvest.HarvestState({}, {}))
    monkeypatch.setattr(harvest, "select_candidates", lambda *args: harvest.Selection((), 0, 0, ()))
    monkeypatch.setattr(
        sync,
        "_write_selection",
        lambda *args: (
            sync.WriteResult(0, ("sync: skipped session session: possible secrets remain",)),
            0,
            0,
            0,
            {},
        ),
    )
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: ())
    monkeypatch.setattr(sync, "_fetch_status", lambda _: (sync.RemoteStatus("main", 1, 0), None))
    monkeypatch.setattr(sync, "_sync_remote", lambda *args: (("Pushed: 1 commit(s)",), ()))
    assert sync._sync(root, root / ".git", {}, "host", NOW, START, False) == 1
    captured = capsys.readouterr()
    assert "Pushed: 1 commit(s)" in captured.out
    assert "sync: skipped session session" in captured.err


def test_sync_with_harvest_and_dirty_tree_stops_remote_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    monkeypatch.setattr(sync, "_recover", lambda *args: None)
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(harvest, "reconstruct_state", lambda *args: harvest.HarvestState({}, {}))
    monkeypatch.setattr(harvest, "select_candidates", lambda *args: harvest.Selection((), 0, 0, ()))
    monkeypatch.setattr(
        sync,
        "_write_selection",
        lambda *args: (sync.WriteResult(0, ("sync: skipped session x",)), 0, 0, 0, {}),
    )
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: ("local",))
    monkeypatch.setattr(sync, "_fetch_status", lambda _: pytest.fail("dirty tree fetched"))
    assert sync._sync(root, root / ".git", {}, "host", NOW, START, True) == 1


def test_status_reports_backlog_and_remote_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "content")
    monkeypatch.setattr(sync, "_fetch_status", lambda _: (None, "sync: remote failed"))
    assert sync._status(root, {}, "test-host", NOW, None) == 1
    assert "sync: remote failed" in capsys.readouterr().err

    candidate = harvest.Candidate(make_session(), START)
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((candidate,), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(sync, "_fetch_status", lambda _: (sync.RemoteStatus("main", 2, 3), None))
    assert sync._status(root, {}, "test-host", NOW, START - timedelta(days=1)) == 0
    captured = capsys.readouterr().out
    assert "Ready: 1" in captured and "Ahead: 2" in captured and "Behind: 3" in captured

    monkeypatch.setattr(
        sync,
        "_scan_transcripts",
        lambda _: sync.ScanResult((candidate,), (sync.Failure("broken", "cannot read"),)),
    )
    assert sync._status(root, {}, "test-host", NOW, START - timedelta(days=1)) == 1
    assert "sync: skipped session broken: cannot read" in capsys.readouterr().err


def test_dry_run_without_cutoff_and_with_preparation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "content")
    assert sync._dry_run(root, root / ".git", {}, "host", NOW, None) == 0
    assert "Totals: 0 sessions" in capsys.readouterr().out
    candidate = harvest.Candidate(make_session(), START)
    plan = make_plan()
    selection = harvest.Selection((plan,), 1, 0, ("rewritten",))
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((candidate,), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(harvest, "reconstruct_state", lambda *args: harvest.HarvestState({}, {}))
    monkeypatch.setattr(harvest, "select_candidates", lambda *args: selection)
    monkeypatch.setattr(sync, "_prepare", lambda *args: sync.Prepared(None, "bad", 0, {}))
    assert sync._dry_run(root, root / ".git", {}, "host", NOW, START) == 1
    captured = capsys.readouterr()
    assert "sync: skipped session session: bad" in captured.err
    assert "rewritten" in captured.err


def test_dry_run_reports_prepared_observations_redactions_and_record_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = make_repo(tmp_path / "content")
    candidate = harvest.Candidate(make_session(malformed=2, duplicates=1), START)
    plan = make_plan(candidate.session, part=2)
    selection = harvest.Selection((plan,), 1, 0, ())
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((candidate,), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(harvest, "reconstruct_state", lambda *args: harvest.HarvestState({}, {}))
    monkeypatch.setattr(harvest, "select_candidates", lambda *args: selection)
    monkeypatch.setattr(
        sync,
        "_prepare",
        lambda *args: sync.Prepared("rendered", None, 2, {"Secret": 1}),
    )
    assert sync._dry_run(root, root / ".git", {}, "host", NOW, START) == 0
    output = capsys.readouterr().out
    assert "claude-code session part 2: 2 messages" in output
    assert "Totals: 1 sessions, 2 messages, 8 bytes, 1 redacted lines" in output
    assert "2 malformed line(s), 1 duplicate message ID(s)" in output
    assert "Secret: 1" in output


def test_dry_run_wraps_filesystem_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_repo(tmp_path / "content")
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(KbError, match="sync: dry-run failed: no"):
        sync._dry_run(root, root / ".git", {}, "host", NOW, START)


def test_scan_transcripts_parses_claude_and_codex_and_reports_bad_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude_root = tmp_path / "claude"
    codex_root = tmp_path / "codex"
    project = claude_root / "projects" / "demo"
    agent = project / "parent" / "subagents"
    agent.mkdir(parents=True)
    codex_dir = codex_root / "sessions" / "2026" / "10"
    codex_dir.mkdir(parents=True)
    (project / "main.jsonl").write_text(
        '{"type":"user","uuid":"u","timestamp":"2026-10-26T09:00:00Z",'
        '"cwd":"/work","message":{"role":"user","content":"hi"}}\n',
        encoding="utf-8",
    )
    (claude_root / "projects" / "not-a-project.jsonl").write_text("{}\n", encoding="utf-8")
    (agent / "agent-worker.jsonl").write_text("{}\n", encoding="utf-8")
    (project / "bad.jsonl").write_bytes(b"\xff\n")
    (codex_dir / "rollout-codex.jsonl").write_text(
        '{"type":"session_meta","payload":{"id":"codex","cwd":"/codex"}}\n',
        encoding="utf-8",
    )
    result = sync._scan_transcripts(
        {"CLAUDE_CONFIG_DIR": str(claude_root), "CODEX_HOME": str(codex_root)}
    )
    assert {candidate.session.id for candidate in result.candidates} == {
        "main",
        "agent-worker",
        "codex",
    }
    assert any(failure.reason == "transcript is not UTF-8" for failure in result.failures)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    empty = sync._scan_transcripts({})
    assert empty == sync.ScanResult((), ())


def test_read_candidate_reports_io_and_identity_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failures: list[sync.Failure] = []
    candidates: list[harvest.Candidate] = []
    missing = tmp_path / "missing.jsonl"
    sync._read_candidate(missing, failures, candidates, "claude-code")
    assert failures[-1].reason.startswith("cannot read transcript")
    invalid = tmp_path / "rollout-no-id.jsonl"
    invalid.write_text("{}\n", encoding="utf-8")
    sync._read_candidate(invalid, failures, candidates, "codex")
    assert failures[-1].reason == "no filename-matching session metadata"
    valid = tmp_path / "good.jsonl"
    valid.write_text("{}\n", encoding="utf-8")
    original = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, **kwargs: (
            (_ for _ in ()).throw(PermissionError(13, "Denied", str(self)))
            if self == valid
            else original(self, **kwargs)
        ),
    )
    sync._read_candidate(valid, failures, candidates, "claude-code")
    assert "Denied" in failures[-1].reason


def test_head_records_reads_committed_observation_and_ignores_old_fields(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "content")
    pending = root / "observations" / "pending"
    pending.mkdir(parents=True)
    (pending / "saved.md").write_text(observation_text(), encoding="utf-8")
    git(root, "add", "observations")
    git(root, "commit", "-q", "-m", "Save transcript")
    records = sync._head_records(root)
    assert len(records) == 1
    assert records[0].session == "saved" and records[0].part == 1


def test_head_records_handles_tree_and_batch_errors_and_empty_trees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path()
    monkeypatch.setattr(
        sync,
        "_git_bytes",
        lambda *args, **kwargs: completed_bytes(1, b"", b"tree error"),
    )
    with pytest.raises(KbError, match="cannot list committed observations: tree error"):
        sync._head_records(root)
    monkeypatch.setattr(sync, "_git_bytes", lambda *args, **kwargs: completed_bytes(0, b""))
    assert sync._head_records(root) == ()

    oid = "a" * 40
    tree = f"100644 blob {oid}\tobservations/pending/saved.md\0".encode()
    calls = iter((completed_bytes(0, tree), completed_bytes(1, b"", b"batch error")))
    monkeypatch.setattr(sync, "_git_bytes", lambda *args, **kwargs: next(calls))
    with pytest.raises(KbError, match="cannot read committed observations: batch error"):
        sync._head_records(root)


def test_head_records_skips_non_md_non_blob_and_undecodable_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oid = b"a" * 40
    tree = (
        b"100644 tree "
        + oid
        + b"\tobservations/pending/directory\0"
        + b"100644 blob "
        + oid
        + b"\tobservations/pending/ignored.txt\0"
        + b"100644 blob "
        + oid
        + b"\tobservations/pending/\xff.md\0"
    )
    monkeypatch.setattr(sync, "_git_bytes", lambda *args, **kwargs: completed_bytes(0, tree))
    assert sync._head_records(Path()) == ()

    object_id = b"b" * 40
    one_record_tree = b"100644 blob " + object_id + b"\tobservations/pending/old.md\0"
    old_text = observation_text().replace("session-transcript", "session").encode()
    batch = object_id + b" blob " + str(len(old_text)).encode() + b"\n" + old_text + b"\n"
    calls = iter((completed_bytes(0, one_record_tree), completed_bytes(0, batch)))
    monkeypatch.setattr(sync, "_git_bytes", lambda *args, **kwargs: next(calls))
    assert sync._head_records(Path()) == ()

    invalid_text = object_id + b" blob 1\n\xff\n"
    calls = iter((completed_bytes(0, one_record_tree), completed_bytes(0, invalid_text)))
    monkeypatch.setattr(sync, "_git_bytes", lambda *args, **kwargs: next(calls))
    assert sync._head_records(Path()) == ()


@pytest.mark.parametrize(
    ("batch", "message"),
    [
        (b"", "truncated observation batch"),
        (b"invalid header\n", "invalid observation header"),
        (b"a blob 5\nxy\n", "truncated observation"),
        (b"a blob 3\nabc", "invalid observation separator"),
    ],
)
def test_head_records_rejects_truncated_cat_file_output(
    monkeypatch: pytest.MonkeyPatch, batch: bytes, message: str
) -> None:
    oid = "a" * 40
    tree = f"100644 blob {oid}\tobservations/pending/saved.md\0".encode()
    calls = iter((completed_bytes(0, tree), completed_bytes(0, batch)))
    monkeypatch.setattr(sync, "_git_bytes", lambda *args, **kwargs: next(calls))
    with pytest.raises(KbError, match=message):
        sync._head_records(Path())


@pytest.mark.parametrize(
    ("source", "app", "part", "expected_app", "expected_part"),
    [
        ("session-transcript", "claude-code", "2", "claude-code", 2),
        ("session-transcript", "codex", "bad", "codex", None),
        ("session-transcript", "unknown", "-1", None, None),
    ],
)
def test_record_from_document_maps_supported_fields(
    source: str, app: str, part: str, expected_app: str | None, expected_part: int | None
) -> None:
    text = observation_text().replace("source: session-transcript", f"source: {source}")
    text = text.replace("app: claude-code", f"app: {app}").replace("part: 1", f"part: {part}")
    record = sync._record_from_document(model.parse("record.md", text))
    assert record is not None
    assert record.app == expected_app and record.part == expected_part


def test_record_from_document_ignores_non_transcript_observations() -> None:
    document = model.parse("old.md", observation_text().replace("session-transcript", "session"))
    assert sync._record_from_document(document) is None


def test_recover_cleans_temp_and_only_this_hosts_uncommitted_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    git_dir = root / ".git"
    scratch = git_dir / "kb-tmp"
    (scratch / "nested").mkdir(parents=True)
    (scratch / "nested" / "temp").write_text("x", encoding="utf-8")
    pending = root / "observations" / "pending"
    pending.mkdir(parents=True)
    owned = pending / "owned.md"
    other = pending / "other.md"
    committed = pending / "committed.md"
    owned.write_text(observation_text("owned"), encoding="utf-8")
    other.write_text(
        observation_text("other").replace('host: "test-host"', 'host: "other"'), encoding="utf-8"
    )
    committed.write_text(observation_text("committed"), encoding="utf-8")
    git(root, "add", str(committed.relative_to(root)))
    git(root, "commit", "-q", "-m", "Commit one")
    calls: list[str] = []
    original = sync._git

    def track(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("rm",):
            calls.append(args[-1])
        return original(repo, *args)

    monkeypatch.setattr(sync, "_git", track)
    sync._recover(root, git_dir, "test-host")
    assert list(scratch.iterdir()) == []
    assert not owned.exists() and other.exists() and committed.exists()
    assert calls == ["observations/pending/owned.md"]


def test_recover_skips_missing_pending_and_symlink_entries(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "content")
    sync._recover(root, root / ".git", "test-host")
    pending = root / sync.PENDING
    pending.mkdir(parents=True)
    target = tmp_path / "target"
    target.write_text("keep", encoding="utf-8")
    (pending / "link.md").symlink_to(target)
    (pending / "not-a-file.md").mkdir()
    (pending / "invalid.md").write_bytes(b"\xff")
    sync._recover(root, root / ".git", "test-host")
    assert target.read_text(encoding="utf-8") == "keep"


def test_recover_reports_unstage_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_repo(tmp_path / "content")
    pending = root / sync.PENDING
    pending.mkdir(parents=True)
    (pending / "interrupted.md").write_text(observation_text("interrupted"), encoding="utf-8")
    calls = iter((completed(1), completed(1)))
    monkeypatch.setattr(sync, "_git", lambda *args: next(calls))
    with pytest.raises(KbError, match="cannot unstage interrupted observation"):
        sync._recover(root, root / ".git", "test-host")


def test_empty_directory_handles_symlinks_files_and_nested_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    sync._empty_directory(link)
    assert target.exists() and not link.exists()
    file = tmp_path / "file"
    file.write_text("x", encoding="utf-8")
    sync._empty_directory(file)
    assert not file.exists()
    directory = tmp_path / "dir"
    (directory / "nested").mkdir(parents=True)
    (directory / "nested" / "file").write_text("x", encoding="utf-8")
    (directory / "nested" / "link").symlink_to(target)
    (directory / "file").write_text("x", encoding="utf-8")
    (directory / "link").symlink_to(target)
    special = directory / "special"
    special.write_text("keep", encoding="utf-8")
    is_symlink = Path.is_symlink
    is_file = Path.is_file
    is_dir = Path.is_dir
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: False if path == special else is_symlink(path)
    )
    monkeypatch.setattr(Path, "is_file", lambda path: False if path == special else is_file(path))
    monkeypatch.setattr(Path, "is_dir", lambda path: False if path == special else is_dir(path))
    sync._empty_directory(directory)
    assert directory.is_dir() and list(directory.iterdir()) == [special]
    sync._empty_directory(tmp_path / "absent")


def test_scanner_workspace_preserves_or_cleans_and_rejects_symlink(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    with sync._scanner_workspace(git_dir, preserve=True) as directory:
        assert directory.is_dir()
    assert not (git_dir / sync.TMP).exists()
    scratch = git_dir / sync.TMP
    scratch.mkdir()
    before = scratch.stat().st_mtime_ns
    with sync._scanner_workspace(git_dir, preserve=True):
        pass
    assert scratch.is_dir() and scratch.stat().st_mtime_ns == before
    with sync._scanner_workspace(git_dir, preserve=False):
        pass
    assert scratch.is_dir() and list(scratch.iterdir()) == []
    with pytest.raises(RuntimeError), sync._scanner_workspace(git_dir, preserve=True):
        raise RuntimeError("leave")
    scratch.rmdir()
    scratch.symlink_to(git_dir)
    with (
        pytest.raises(KbError, match="symbolic link"),
        sync._scanner_workspace(git_dir, preserve=True),
    ):
        pass


def test_write_selection_commits_prepared_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(secrets, "findings", lambda *args: [])
    scan = tmp_path / "scanner"
    scan.mkdir()
    result, messages, byte_count, redacted, detectors = sync._write_selection(
        root, (make_plan(),), scan, "test-host", NOW
    )
    assert result.count == 1 and result.failures == ()
    assert messages == 1 and byte_count > 0 and redacted == 0 and detectors == {}
    assert git(root, "log", "-1", "--format=%s").strip() == "Observe: 1 session transcript(s)"


def test_write_selection_collects_detector_counts_and_handles_no_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    scan = tmp_path / "scanner"
    scan.mkdir()
    monkeypatch.setattr(
        sync,
        "_prepare",
        lambda *args: sync.Prepared("rendered", None, 3, {"Secret": 2}),
    )
    monkeypatch.setattr(sync, "_publish", lambda *args: "observations/pending/new.md")
    monkeypatch.setattr(sync, "_commit_observations", lambda *args: None)
    result, messages, byte_count, redacted, detectors = sync._write_selection(
        root, (make_plan(),), scan, "host", NOW
    )
    assert result.count == 1
    assert (messages, byte_count, redacted, detectors) == (3, len("rendered"), 2, {"Secret": 2})
    empty, *_ = sync._write_selection(root, (), scan, "host", NOW)
    assert empty.count == 0


def test_write_selection_cleans_after_publish_and_commit_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    scan = tmp_path / "scanner"
    scan.mkdir()
    monkeypatch.setattr(sync, "_prepare", lambda *args: sync.Prepared("text", None, 1, {}))
    published = iter(("observations/pending/first.md",))
    monkeypatch.setattr(sync, "_publish", lambda *args: next(published))
    monkeypatch.setattr(sync, "_commit_observations", lambda *args: "sync: commit failed")
    result, messages, byte_count, redacted, detectors = sync._write_selection(
        root, (make_plan(),), scan, "host", NOW
    )
    assert result.count == 0 and result.failures == ("sync: commit failed",)
    assert (messages, byte_count, redacted, detectors) == (0, 0, 0, {})

    monkeypatch.setattr(sync, "_prepare", lambda *args: sync.Prepared(None, "bad", 0, {}))
    monkeypatch.setattr(sync, "_publish", lambda *args: (_ for _ in ()).throw(OSError("publish")))
    result, *_ = sync._write_selection(root, (make_plan(),), scan, "host", NOW)
    assert "skipped session session: bad" in result.failures[0]


def test_write_selection_rolls_back_prior_publications_on_publish_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    scan = tmp_path / "scanner"
    scan.mkdir()
    second = make_plan(make_session("second"))
    monkeypatch.setattr(sync, "_prepare", lambda *args: sync.Prepared("text", None, 1, {}))
    paths = iter(("observations/pending/first.md", None))

    def publish(*args: object) -> str:
        path = next(paths)
        if path is None:
            raise KbError("blocked")
        return path

    removed: list[tuple[str, ...]] = []
    monkeypatch.setattr(sync, "_publish", publish)
    monkeypatch.setattr(sync, "_remove_paths", lambda _root, paths: removed.append(tuple(paths)))
    result, *_ = sync._write_selection(root, (make_plan(), second), scan, "host", NOW)
    assert result.count == 0 and removed == [("observations/pending/first.md",)]
    assert "skipped session second" in result.failures[0]


def test_prepare_handles_redaction_title_and_validation_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(make_session(text="password is here"))
    calls: list[str] = []

    def find(_directory: Path, text: str) -> list[tuple[str, int]]:
        calls.append(text)
        return [("Secret Keyword", 1)] if "password is here" in text else []

    monkeypatch.setattr(secrets, "findings", find)
    result = sync._prepare(plan, tmp_path, "host", NOW)
    assert result.reason is None and result.redacted_lines == 2
    assert "Session transcript (1 messages)" in (result.text or "")

    monkeypatch.setattr(secrets, "findings", lambda *_: [])
    monkeypatch.setattr(
        sync, "render_observation", lambda *args: (_ for _ in ()).throw(ValueError("bad"))
    )
    assert "invalid observation: bad" in (sync._prepare(plan, tmp_path, "host", NOW).reason or "")
    monkeypatch.setattr(sync, "render_observation", lambda *args: "rendered")
    monkeypatch.setattr(sync, "validate_observation", lambda *args: ("title",))
    assert "observation validation failed: title" in (
        sync._prepare(plan, tmp_path, "host", NOW).reason or ""
    )

    base = make_session()
    assistant = Session(
        app=base.app,
        id=base.id,
        project=base.project,
        parent_session=None,
        forked_from=None,
        messages=(Message("answer", START, "assistant", "Answer."),),
        latest_timestamp=START,
        snapshot_complete=True,
    )
    monkeypatch.setattr(sync, "validate_observation", lambda *args: ())
    assert sync._prepare(make_plan(assistant), tmp_path, "host", NOW).reason is None


def test_prepare_skips_secrets_that_survive_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan()
    monkeypatch.setattr(secrets, "findings", lambda *_: [("Secret Keyword", 1)])
    monkeypatch.setattr(
        sync, "redact_messages", lambda messages, findings, locations: (messages, 0)
    )
    result = sync._prepare(plan, tmp_path, "host", NOW)
    assert result.text is None and "remain after three redaction passes" in (result.reason or "")


def test_prepare_allows_findings_to_clear_after_the_last_redaction_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = iter(([("Secret Keyword", 1)] * 3, []))
    monkeypatch.setattr(secrets, "findings", lambda *_: next(calls))
    monkeypatch.setattr(
        sync, "redact_messages", lambda messages, findings, locations: (messages, 0)
    )
    assert sync._prepare(make_plan(), tmp_path, "host", NOW).reason is None


def test_prepare_checks_for_secrets_after_the_final_redaction_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = make_session()
    assistant = Session(
        app=base.app,
        id=base.id,
        project=base.project,
        parent_session=None,
        forked_from=None,
        messages=(Message("answer", START, "assistant", "Answer."),),
        latest_timestamp=START,
        snapshot_complete=True,
    )
    findings = [[("Secret Keyword", 1)]] * 3 + [[]]
    calls = iter(findings)
    monkeypatch.setattr(secrets, "findings", lambda *_: next(calls))
    monkeypatch.setattr(sync, "redact_messages", lambda messages, matches, locations: (messages, 0))
    assert sync._prepare(make_plan(assistant), tmp_path, "host", NOW).reason is None


def test_detector_line_accounting_ignores_bad_and_repeated_findings() -> None:
    counts: dict[str, set[ContentLine | str]] = {}
    locations = (ContentLine(0, 0, 0),)
    sync._record_detector_lines(counts, (("First", 1), ("Second", 1), ("Bad", 9)), locations)
    sync._record_detector_lines(counts, (("First", 1),), locations)
    sync._record_detector_lines(counts, (("Title", 1),), (), "title")
    assert sync._detector_counts(counts) == {"First": 1, "Title": 1}


def test_publish_tries_again_after_a_name_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    scan = tmp_path / "scanner"
    scan.mkdir()
    pending = root / sync.PENDING
    pending.mkdir(parents=True)
    collision = "20261026T120000-00000000.md"
    (pending / collision).write_text("existing", encoding="utf-8")
    names = iter(bytes.fromhex(value) for value in ("aaaaaaaa", "00000000", "00000001"))
    monkeypatch.setattr(os, "urandom", lambda _: next(names))
    monkeypatch.setattr(
        observation, "file_name", lambda _now, suffix: f"20261026T120000-{suffix}.md"
    )
    path = sync._publish(root, scan, "new", NOW)
    assert path.endswith("00000001.md")
    assert (root / path).read_text(encoding="utf-8") == "new"


def test_publish_fails_after_all_names_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    scan = tmp_path / "scanner"
    scan.mkdir()
    pending = root / sync.PENDING
    pending.mkdir(parents=True)
    suffixes = [f"{index:08x}" for index in range(sync.MAX_NAME_TRIES)]
    for suffix in suffixes:
        (pending / f"20261026T120000-{suffix}.md").write_text("old", encoding="utf-8")
    random_values = iter(bytes.fromhex(value) for value in ["aaaaaaaa", *suffixes])
    monkeypatch.setattr(os, "urandom", lambda _: next(random_values))
    monkeypatch.setattr(
        observation, "file_name", lambda _now, suffix: f"20261026T120000-{suffix}.md"
    )
    with pytest.raises(KbError, match="no free file name"):
        sync._publish(root, scan, "new", NOW)
    assert list(scan.iterdir()) == []


def test_commit_observations_cleans_up_staging_and_paths_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "content")
    pending = root / sync.PENDING
    pending.mkdir(parents=True)
    path = "observations/pending/new.md"
    (root / path).write_text("new", encoding="utf-8")
    calls = iter((completed(1, stderr="add failed\n"), completed()))
    monkeypatch.setattr(sync, "_git", lambda *args: next(calls))
    assert sync._commit_observations(root, (path,)) == "sync: commit failed: add failed"
    assert not (root / path).exists()

    (root / path).write_text("new", encoding="utf-8")
    calls = iter((completed(), completed(1, stderr=""), completed()))
    monkeypatch.setattr(sync, "_git", lambda *args: next(calls))
    assert sync._commit_observations(root, (path,)) == "sync: commit failed"
    assert not (root / path).exists()


@pytest.mark.parametrize(
    ("status", "stdout", "stderr", "expected"),
    [
        (" M file\n?? .observe.lock\n?? .observe.lock/pid\n", 0, "", ("file",)),
        ("R  old -> new\n", 0, "", ("new",)),
        ("", 1, "broken", "error"),
    ],
)
def test_dirty_paths_handles_changes_renames_lock_and_errors(
    monkeypatch: pytest.MonkeyPatch, status: str, stdout: int, stderr: str, expected: object
) -> None:
    monkeypatch.setattr(remote, "_git", lambda *args: completed(stdout, status, stderr))
    if expected == "error":
        with pytest.raises(KbError, match="cannot inspect working tree: broken"):
            sync._dirty_paths(Path())
    else:
        assert sync._dirty_paths(Path()) == expected


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([(1, "", "")], "detached"),
        ([(0, "main\n", ""), (1, "", "")], "no origin"),
        ([(0, "main\n", ""), (0, "url\n", ""), (1, "", "offline")], "fetch origin/main failed"),
        ([(0, "main\n", ""), (0, "url\n", ""), (0, "", ""), (1, "", "")], "does not exist"),
        (
            [(0, "main\n", ""), (0, "url\n", ""), (0, "", ""), (0, "", ""), (1, "", "bad")],
            "cannot compare",
        ),
        (
            [(0, "main\n", ""), (0, "url\n", ""), (0, "", ""), (0, "", ""), (0, "bad", "")],
            "invalid ahead/behind",
        ),
    ],
)
def test_fetch_status_reports_git_failures(
    monkeypatch: pytest.MonkeyPatch,
    results: list[tuple[int, str, str]],
    expected: str,
) -> None:
    queued = iter(completed(*result) for result in results)
    monkeypatch.setattr(remote, "_git", lambda *args: next(queued))
    status, error = sync._fetch_status(Path())
    assert status is None and expected in (error or "")


def test_fetch_status_parses_valid_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    queued = iter(
        (
            completed(0, "main\n"),
            completed(0, "url\n"),
            completed(),
            completed(),
            completed(0, "2 4\n"),
        )
    )
    monkeypatch.setattr(remote, "_git", lambda *args: next(queued))
    assert sync._fetch_status(Path()) == (sync.RemoteStatus("main", 2, 4), None)


@pytest.mark.parametrize(
    ("status", "no_push", "results", "actions", "errors"),
    [
        (sync.RemoteStatus("main", 0, 0), False, [], ("Already in sync with origin/main.",), ()),
        (sync.RemoteStatus("main", 2, 0), True, [], (), ()),
        (sync.RemoteStatus("main", 2, 0), False, [(0, "", "")], ("Pushed: 2 commit(s)",), ()),
        (
            sync.RemoteStatus("main", 2, 0),
            False,
            [(1, "", "offline")],
            (),
            ("sync: push origin/main failed: offline",),
        ),
        (sync.RemoteStatus("main", 0, 3), True, [(0, "", "")], ("Pulled: 3 commit(s)",), ()),
        (
            sync.RemoteStatus("main", 2, 3),
            False,
            [(1, "", ""), (0, "", "")],
            (),
            ("sync: rebase onto origin/main failed; local commits kept",),
        ),
    ],
)
def test_sync_remote_handles_ahead_behind_and_push_modes(
    monkeypatch: pytest.MonkeyPatch,
    status: sync.RemoteStatus,
    no_push: bool,
    results: list[tuple[int, str, str]],
    actions: tuple[str, ...],
    errors: tuple[str, ...],
) -> None:
    calls: list[tuple[str, ...]] = []
    queued = iter(completed(*result) for result in results)

    def run_git(_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return next(queued)

    monkeypatch.setattr(remote, "_git", run_git)
    assert sync._sync_remote(Path(), status, no_push) == (actions, errors)
    if errors and "rebase" in errors[0]:
        assert calls[-1] == ("rebase", "--abort")
