"""Real committed legacy pointers, newly recovered calls, and repeated harvests."""

import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import harvest, lock
from kb.commands import sync
from kb.hosts import claude, codex
from kb.transcripts import Session

from .test_hook import git, repo

FIXTURES = Path(__file__).parents[1] / "fixtures/transcripts/identity-compatibility"
NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
OLD = datetime(2026, 10, 25, 9, tzinfo=UTC)


def parse(app: str, name: str) -> Session:
    text = (FIXTURES / f"{app}-{name}.jsonl").read_text(encoding="utf-8")
    return (
        codex.parse(text, f"rollout-{name}.jsonl") if app == "codex" else claude.parse(text, name)
    )


def legacy_repo(tmp_path: Path, app: str, *, pointer_only: bool = False) -> Path:
    suffix = "pointer-legacy" if pointer_only else "legacy"
    root = repo(
        tmp_path / "content",
        {"observations/pending/legacy.md": (FIXTURES / f"{app}-{suffix}.md").read_bytes()},
    )
    git(root, "config", "user.name", "Identity Test")
    git(root, "config", "user.email", "identity@example.invalid")
    return root


def commit_plans(root: Path, plans: tuple[harvest.HarvestPlan, ...]) -> None:
    directory = lock.git_dir(root, "sync")
    scan = directory / "kb-tmp" / "identity-test"
    scan.mkdir(parents=True)
    with lock.write_lock(directory, 0, lock.default_backend(sys.platform)):
        result, *_ = sync._write_selection(root, plans, scan, "host-a", NOW)
    assert result.failures == ()
    assert result.count == len(plans)


@pytest.mark.parametrize("app", ["codex", "claude"])
@pytest.mark.parametrize("pointer_only", [False, True])
@pytest.mark.parametrize("appended", [False, True])
def test_old_pointers_recover_dropped_calls_and_appended_messages_once(
    tmp_path: Path, app: str, pointer_only: bool, appended: bool
) -> None:
    root = legacy_repo(tmp_path, app, pointer_only=pointer_only)
    transcript = parse(app, "original")
    if not appended:
        transcript = replace(transcript, messages=transcript.messages[:-1])
    assert len(transcript.messages) == (6 if appended else 5)
    records = sync._head_records(root)
    state = harvest.reconstruct_state(records, (transcript,), "host-a")
    selection = harvest.select_candidates((harvest.Candidate(transcript, OLD),), state, NOW, None)
    assert selection.warnings == ()
    assert len(selection.plans) == 1
    selected = selection.plans[0]
    assert selected.part == 2
    expected = list(transcript.messages[2:4])
    if pointer_only:
        expected.append(transcript.messages[4])
    if appended:
        expected.append(transcript.messages[5])
    assert selected.messages == tuple(expected)

    commit_plans(root, selection.plans)
    state = harvest.reconstruct_state(sync._head_records(root), (transcript,), "host-a")
    again = harvest.select_candidates((harvest.Candidate(transcript, OLD),), state, NOW, None)
    assert again.plans == ()
    assert again.warnings == ()
    assert git(root, "rev-list", "--count", "HEAD").strip() == "2"


@pytest.mark.parametrize("app", ["codex", "claude"])
@pytest.mark.parametrize("original_available", [False, True])
def test_legacy_fork_prefixes_do_not_duplicate_retained_or_recovered_messages(
    tmp_path: Path, app: str, original_available: bool
) -> None:
    root = legacy_repo(tmp_path, app)
    original = parse(app, "original")
    fork = parse(app, "fork")
    sessions = (original, fork) if original_available else (fork,)
    state = harvest.reconstruct_state(sync._head_records(root), sessions, "host-a")
    candidates = tuple(harvest.Candidate(value, OLD) for value in sessions)
    selection = harvest.select_candidates(candidates, state, NOW, None)
    ids = [message.id for plan in selection.plans for message in plan.messages]
    expected = {message.id for message in fork.messages[2:4]} | {"fork-only"}
    if original_available:
        expected.add("appended")
    assert set(ids) == expected
    assert len(ids) == len(expected)
    assert selection.warnings == ()

    commit_plans(root, selection.plans)
    state = harvest.reconstruct_state(sync._head_records(root), sessions, "host-a")
    assert harvest.select_candidates(candidates, state, NOW, None).plans == ()
