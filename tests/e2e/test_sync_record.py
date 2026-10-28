"""End-to-end checks of the sync outcome record that a regular `kb sync` writes."""

import json
from pathlib import Path

from .harness import NOW, Kb, run_git


def configure(kb: Kb) -> None:
    """Write an isolated config with the content root and transcript harvesting off."""
    kb.config_file.parent.mkdir(parents=True, exist_ok=True)
    kb.config_file.write_text(f'content = "{kb.content.as_posix()}"\n', encoding="utf-8")


def record_path(kb: Kb) -> Path:
    return kb.content / ".git" / "kb" / "sync-state.json"


def record_of(kb: Kb) -> dict[str, object]:
    loaded = json.loads(record_path(kb).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_a_regular_sync_records_its_outcome_and_status_and_dry_run_leave_it_unchanged(
    remote_git_kb: Kb,
) -> None:
    configure(remote_git_kb)
    version = remote_git_kb("--version").stdout.removeprefix("kb ").strip()

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert record_of(remote_git_kb) == {
        "schema_version": 1,
        "kb_version": version,
        "last_run": NOW,
        "last_outcome": "ok",
        "last_exchange": NOW,
        "message": None,
    }
    before = record_path(remote_git_kb).read_bytes()
    modified = record_path(remote_git_kb).stat().st_mtime_ns
    assert remote_git_kb("sync", "--status").returncode == 0
    assert remote_git_kb("sync", "--dry-run").returncode == 0
    assert record_path(remote_git_kb).read_bytes() == before
    assert record_path(remote_git_kb).stat().st_mtime_ns == modified
    assert str(remote_git_kb.content) not in before.decode("utf-8")


def test_a_dirty_run_then_a_failed_run_keep_the_last_exchange_time(remote_git_kb: Kb) -> None:
    configure(remote_git_kb)
    assert remote_git_kb("sync").returncode == 0
    later = {"KB_NOW": "2026-10-26T13:00:00Z"}
    scratch = remote_git_kb.content / "scratch.txt"
    scratch.write_text("local\n", encoding="utf-8")

    dirty = remote_git_kb("sync", env=later)

    assert dirty.returncode == 0, dirty.stderr
    state = record_of(remote_git_kb)
    assert (state["last_outcome"], state["last_exchange"], state["last_run"]) == (
        "dirty",
        NOW,
        "2026-10-26T13:00:00Z",
    )
    scratch.unlink()
    run_git(remote_git_kb.content, "remote", "remove", "origin")

    failed = remote_git_kb("sync", env=later)

    assert failed.returncode == 1
    state = record_of(remote_git_kb)
    assert (state["last_outcome"], state["last_exchange"], state["message"]) == (
        "error",
        NOW,
        "sync: no origin remote",
    )


def test_a_record_that_cannot_be_written_is_reported_and_keeps_the_exit_status(
    remote_git_kb: Kb,
) -> None:
    configure(remote_git_kb)
    (remote_git_kb.content / ".git" / "kb").write_text("not a directory\n", encoding="utf-8")

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert result.stderr.startswith("sync: cannot record sync outcome: ")
