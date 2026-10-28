"""The outcome record that `kb sync` writes on each exit path, and the non-fetching backlog."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kb import __version__, harvest, sync_state
from kb.commands import sync
from kb.errors import KbError
from kb.transcripts import Message, Session

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
START = NOW - timedelta(hours=3)


def make_session() -> Session:
    return Session(
        app="claude-code",
        id="session",
        project="/fixture/project",
        parent_session=None,
        forked_from=None,
        messages=(Message("message-1", START, "user", "A user message."),),
        latest_timestamp=START,
        snapshot_complete=True,
        malformed_lines=0,
        duplicate_ids=0,
    )


def stub_steps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dirty: tuple[str, ...] = (),
    fetch_error: str | None = None,
    remote_errors: tuple[str, ...] = (),
) -> None:
    """Replace the recovery, worktree, fetch, and remote steps with fixed answers."""
    monkeypatch.setattr(sync, "_recover", lambda *args: None)
    monkeypatch.setattr(sync, "_dirty_paths", lambda _: dirty)
    if fetch_error is None:
        monkeypatch.setattr(
            sync, "_fetch_status", lambda _: (sync.RemoteStatus("main", 0, 0), None)
        )
    else:
        monkeypatch.setattr(sync, "_fetch_status", lambda _: (None, fetch_error))
    monkeypatch.setattr(sync, "_sync_remote", lambda *args: ((), remote_errors))


def run_sync(root: Path, now: datetime = NOW, harvest_since: datetime | None = None) -> int:
    return sync._sync(root, root / ".git", {}, "test-host", now, harvest_since, False)


def record(root: Path) -> sync_state.SyncState:
    state = sync_state.read(root / ".git")
    assert state is not None
    return state


def test_each_regular_run_records_its_outcome_and_keeps_the_exchange_across_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_steps(monkeypatch)
    assert run_sync(tmp_path, EARLIER) == 0
    assert record(tmp_path) == sync_state.SyncState(__version__, EARLIER, "ok", EARLIER, None)

    stub_steps(monkeypatch, dirty=("local.md",))
    assert run_sync(tmp_path, NOW) == 0
    assert record(tmp_path) == sync_state.SyncState(__version__, NOW, "dirty", EARLIER, None)

    stub_steps(monkeypatch, fetch_error="sync: no origin remote")
    assert run_sync(tmp_path, NOW) == 1
    assert record(tmp_path) == sync_state.SyncState(
        __version__, NOW, "error", EARLIER, "sync: no origin remote"
    )

    stub_steps(monkeypatch)
    assert run_sync(tmp_path, NOW) == 0
    assert record(tmp_path) == sync_state.SyncState(__version__, NOW, "ok", NOW, None)


def test_a_remote_failure_records_error_with_only_its_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_steps(monkeypatch, remote_errors=("sync: push origin/main failed: rejected\nhint: fetch",))

    assert run_sync(tmp_path) == 1

    state = record(tmp_path)
    assert (state.last_outcome, state.last_exchange) == ("error", None)
    assert state.message == "sync: push origin/main failed: rejected"


def test_an_empty_failure_line_is_recorded_as_a_generic_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_steps(monkeypatch, fetch_error="")

    assert run_sync(tmp_path) == 1

    assert record(tmp_path).message == "sync failed"


def test_a_dirty_worktree_with_a_failure_records_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_steps(monkeypatch, dirty=("local.md",))
    monkeypatch.setattr(sync, "_recover", lambda *args: (_ for _ in ()).throw(KbError("broken")))

    assert run_sync(tmp_path) == 1

    state = record(tmp_path)
    assert state.last_outcome == "error"
    assert state.message == "sync: recovery failed: broken"


def test_a_skipped_session_records_an_error_with_its_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_steps(monkeypatch)
    candidate = harvest.Candidate(make_session(), START)
    skipped = "sync: skipped session session: possible secrets remain"
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((candidate,), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(harvest, "reconstruct_state", lambda *args: harvest.HarvestState({}, {}))
    monkeypatch.setattr(harvest, "select_candidates", lambda *args: harvest.Selection((), 0, 0, ()))
    monkeypatch.setattr(
        sync,
        "_write_selection",
        lambda *args: (sync.WriteResult(0, (skipped,)), 0, 0, 0, {}),
    )

    assert run_sync(tmp_path, NOW, START) == 1

    state = record(tmp_path)
    assert (state.last_outcome, state.message) == ("error", skipped)


def test_an_exception_during_the_run_records_an_error_and_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_steps(monkeypatch)
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((), ()))
    monkeypatch.setattr(
        sync,
        "_head_records",
        lambda _: (_ for _ in ()).throw(KbError("cannot list committed observations: boom")),
    )

    with pytest.raises(KbError, match="boom"):
        run_sync(tmp_path, NOW, START)

    state = record(tmp_path)
    assert state.last_outcome == "error"
    assert state.message == "sync: cannot list committed observations: boom"


def test_a_failed_record_write_is_reported_and_keeps_the_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_steps(monkeypatch)

    def refuse(git_directory: Path, state: sync_state.SyncState) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(sync_state, "write", refuse)

    assert run_sync(tmp_path) == 0
    assert (
        "sync: cannot record sync outcome: [Errno 28] No space left on device"
        in capsys.readouterr().err
    )

    stub_steps(monkeypatch, fetch_error="sync: no origin remote")
    assert run_sync(tmp_path) == 1
    assert "sync: cannot record sync outcome" in capsys.readouterr().err


def test_an_unreadable_previous_record_is_replaced_without_an_exchange_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb_directory = tmp_path / ".git" / "kb"
    kb_directory.mkdir(parents=True)
    (kb_directory / "sync-state.json").write_text("not json", encoding="utf-8")
    stub_steps(monkeypatch, dirty=("local.md",))

    assert run_sync(tmp_path) == 0

    state = record(tmp_path)
    assert (state.last_outcome, state.last_exchange) == ("dirty", None)


def test_backlog_reads_head_and_selects_without_fetching_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = harvest.Candidate(make_session(), START)
    monkeypatch.setattr(sync, "_scan_transcripts", lambda _: sync.ScanResult((candidate,), ()))
    monkeypatch.setattr(sync, "_head_records", lambda _: ())
    monkeypatch.setattr(sync, "_fetch_status", lambda _: pytest.fail("the backlog fetched origin"))

    found = sync.backlog(tmp_path, {}, "test-host", NOW, START - timedelta(days=1))

    assert (found.selection.ready_count, found.selection.waiting_count) == (1, 0)
    assert found.scan.failures == ()
