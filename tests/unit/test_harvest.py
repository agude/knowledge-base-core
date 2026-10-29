"""Tests for committed harvest-state reconstruction, readiness, and fork selection."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kb.harvest import Candidate, HarvestRecord, HarvestState, reconstruct_state, select_candidates
from kb.transcripts import App, Message, Role, Session

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
SINCE = datetime(2026, 10, 24, tzinfo=UTC)
OLD = datetime(2026, 10, 25, 8, tzinfo=UTC)


def message(
    message_id: str,
    timestamp: datetime = OLD,
    role: Role = "user",
    text: str | None = None,
) -> Message:
    return Message(message_id, timestamp, role, text or f"Text for {message_id}.")


def session(
    session_id: str | None,
    *messages: Message,
    app: App = "claude-code",
    latest: datetime | None = None,
    complete: bool = True,
) -> Session:
    return Session(
        app=app,
        id=session_id,
        project="/fixture/project",
        parent_session=None,
        forked_from=None,
        messages=tuple(messages),
        latest_timestamp=latest,
        snapshot_complete=complete,
    )


def record(
    *,
    source: str | None = "session-transcript",
    host: str | None = "host-a",
    app: App | None = "claude-code",
    session_id: str | None = "session-a",
    part: int | None = 1,
    first: str | None = "message-1",
    last: str | None = "message-2",
    started: datetime | None = OLD,
    ended: datetime | None = OLD + timedelta(minutes=1),
    created: datetime | None = NOW - timedelta(hours=1),
    forked_from: str | None = None,
) -> HarvestRecord:
    return HarvestRecord(
        source,
        host,
        app,
        session_id,
        part,
        first,
        last,
        started,
        ended,
        created,
        forked_from,
    )


def empty_state() -> HarvestState:
    return HarvestState({}, {})


def test_reconstruct_state_uses_highest_part_for_this_host_and_maps_ranges() -> None:
    transcript = session(
        "session-a",
        message("message-1"),
        message("message-2", OLD + timedelta(minutes=1), "assistant"),
        message("message-3", OLD + timedelta(minutes=2)),
        message("message-4", OLD + timedelta(minutes=3), "assistant"),
    )
    records = (
        record(first="message-1", last="message-2", ended=OLD + timedelta(minutes=1), part=1),
        record(
            first="message-3",
            last="message-4",
            started=OLD + timedelta(minutes=2),
            ended=OLD + timedelta(minutes=3),
            part=2,
        ),
        record(part=3, host="other-host"),
        record(part=4, source="session"),
    )

    state = reconstruct_state(records, (transcript,), "host-a")

    assert state.parts[("claude-code", "session-a")].part == 2
    assert state.parts[("claude-code", "session-a")].last_message == "message-4"
    assert state.owners == {
        ("claude-code", "message-1"): ("claude-code", "session-a"),
        ("claude-code", "message-2"): ("claude-code", "session-a"),
        ("claude-code", "message-3"): ("claude-code", "session-a"),
        ("claude-code", "message-4"): ("claude-code", "session-a"),
    }


def test_reconstruct_state_uses_earlier_owner_and_ignores_invalid_front_matter_values() -> None:
    base = record()
    invalid = (
        replace(base, source="session"),
        replace(base, host="other-host"),
        replace(base, app=None),
        replace(base, session=None),
        replace(base, session=""),
        replace(base, part=None),
        replace(base, part=True),
        replace(base, part=0),
        replace(base, first_message=None),
        replace(base, first_message=""),
        replace(base, last_message=None),
        replace(base, last_message=""),
        replace(base, started=None),
        replace(base, ended=None),
        replace(base, ended=datetime(2026, 10, 25, 9)),
        replace(base, created=datetime(2026, 10, 25, 9)),
    )
    state = reconstruct_state((base, *invalid), (), "host-a")
    assert state.parts[("claude-code", "session-a")].part == 1
    assert state.owners[("claude-code", "message-1")] == ("claude-code", "session-a")


def test_reconstruct_state_falls_back_to_timestamp_range_when_ids_changed() -> None:
    changed = session(
        "session-a",
        message("new-1", OLD),
        message("new-2", OLD + timedelta(minutes=1)),
        message("new-3", OLD + timedelta(minutes=2)),
    )
    saved = record(
        first="old-first",
        last="old-last",
        started=OLD,
        ended=OLD + timedelta(minutes=1),
    )

    state = reconstruct_state((saved,), (changed,), "host-a")

    assert state.owners == {
        ("claude-code", "new-1"): ("claude-code", "session-a"),
        ("claude-code", "new-2"): ("claude-code", "session-a"),
    }


def test_reconstruct_state_uses_endpoint_ids_when_transcript_is_absent_or_range_unknown() -> None:
    saved = record(first="old-first", last="old-last")

    state = reconstruct_state((saved,), (), "host-a")

    assert set(state.owners) == {
        ("claude-code", "old-first"),
        ("claude-code", "old-last"),
    }
    one_endpoint = reconstruct_state((record(first="only", last="only"),), (), "host-a")
    assert set(one_endpoint.owners) == {("claude-code", "only")}


def test_reconstruct_state_uses_highest_part_then_newest_created_for_ties() -> None:
    older = record(part=2, last="part-2-old", created=NOW - timedelta(hours=2))
    newer = record(part=2, last="part-2-new", created=NOW - timedelta(hours=1))
    lower = record(part=1, last="part-1", created=NOW)
    state = reconstruct_state((older, lower, newer), (), "host-a")
    part = state.parts[("claude-code", "session-a")]
    assert (part.part, part.last_message, part.created) == (2, "part-2-new", newer.created)


def test_selection_applies_cutoff_idle_time_and_snapshot_completeness() -> None:
    ready = session("ready", message("ready-1"), latest=OLD)
    waiting_activity = session("active", message("active-1"), latest=NOW - timedelta(minutes=30))
    waiting_snapshot = session("partial", message("partial-1"), latest=OLD, complete=False)
    before_cutoff = session("old", message("old-1", SINCE - timedelta(seconds=1)), latest=OLD)
    exactly_cutoff = session("boundary", message("boundary-1", SINCE), latest=OLD)
    no_id = session(None, message("idless-1"), latest=OLD)
    candidates = (
        Candidate(waiting_activity, OLD),
        Candidate(ready, OLD),
        Candidate(waiting_snapshot, OLD),
        Candidate(before_cutoff, OLD),
        Candidate(exactly_cutoff, OLD),
        Candidate(no_id, OLD),
    )

    selected = select_candidates(candidates, empty_state(), NOW, SINCE)

    assert selected.ready_count == 2
    assert selected.waiting_count == 2
    assert [plan.session.id for plan in selected.plans] == ["boundary", "ready"]
    assert all(plan.messages[0].timestamp >= SINCE for plan in selected.plans)


def test_selection_uses_mtime_when_no_record_has_a_timestamp_and_requires_sixty_minutes() -> None:
    no_timestamp = session("mtime", message("mtime-1"))
    exactly_idle = Candidate(no_timestamp, NOW - timedelta(minutes=60))
    too_recent = Candidate(no_timestamp, NOW - timedelta(minutes=59))

    selected = select_candidates((too_recent, exactly_idle), empty_state(), NOW, None)

    assert selected.ready_count == 1
    assert selected.waiting_count == 1
    assert [plan.session.id for plan in selected.plans] == ["mtime"]


def test_selection_uses_the_later_of_record_timestamp_and_file_mtime() -> None:
    stale_message_recent_file = Candidate(
        session("active-file", message("active-file-1"), latest=OLD),
        NOW - timedelta(minutes=10),
    )
    old_file_recent_record = Candidate(
        session("active-record", message("active-record-1"), latest=NOW - timedelta(minutes=10)),
        OLD,
    )
    selected = select_candidates(
        (stale_message_recent_file, old_file_recent_record), empty_state(), NOW, None
    )
    assert selected.ready_count == 0
    assert selected.waiting_count == 2
    assert selected.plans == ()


def test_selection_starts_after_saved_last_message_and_increments_the_part() -> None:
    transcript = session(
        "session-a",
        message("one"),
        message("two", OLD + timedelta(minutes=1), "assistant"),
        message("three", OLD + timedelta(days=1)),
        latest=OLD + timedelta(days=1),
    )
    saved = record(first="one", last="two", part=3, ended=OLD + timedelta(minutes=1))
    state = reconstruct_state((saved,), (transcript,), "host-a")

    selected = select_candidates((Candidate(transcript, OLD),), state, NOW, SINCE)

    assert selected.plans[0].part == 4
    assert [message.id for message in selected.plans[0].messages] == ["three"]


def test_selection_warns_and_continues_after_ended_when_saved_id_is_missing() -> None:
    transcript = session(
        "session-a",
        message("rewritten-old", OLD),
        message("later", OLD + timedelta(minutes=2)),
        latest=OLD + timedelta(minutes=2),
    )
    state = reconstruct_state(
        (record(first="missing-first", last="missing-last", ended=OLD + timedelta(minutes=1)),),
        (),
        "host-a",
    )

    selected = select_candidates((Candidate(transcript, OLD),), state, NOW, SINCE)

    assert [message.id for message in selected.plans[0].messages] == ["later"]
    assert selected.plans[0].part == 2
    assert len(selected.warnings) == 1
    assert "session-a" in selected.warnings[0]


def test_selection_orders_ready_sessions_by_first_message_time_then_session_id() -> None:
    later = Candidate(session("b", message("later", OLD + timedelta(minutes=2))), OLD)
    tied_b = Candidate(session("b-tie", message("tie-b", OLD)), OLD)
    tied_a = Candidate(session("a-tie", message("tie-a", OLD)), OLD)
    selected = select_candidates((later, tied_b, tied_a), empty_state(), NOW, None)
    assert [plan.session.id for plan in selected.plans] == ["a-tie", "b-tie", "b"]


def test_selection_limits_to_fifty_oldest_ready_sessions() -> None:
    candidates = tuple(
        Candidate(
            session(
                f"session-{number:03d}",
                message(f"message-{number}", OLD + timedelta(minutes=number)),
            ),
            OLD,
        )
        for number in range(60)
    )

    selected = select_candidates(candidates, empty_state(), NOW, None, limit=100)

    assert selected.ready_count == 60
    assert len(selected.plans) == 50
    assert selected.plans[0].session.id == "session-000"
    assert selected.plans[-1].session.id == "session-049"


def test_fully_owned_forks_do_not_use_the_session_limit() -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures/transcripts/fully-owned-forks.txt"
    fixture_rows = [line.split() for line in fixture_path.read_text(encoding="utf-8").splitlines()]
    candidates: list[Candidate] = []
    owners: dict[tuple[App, str], tuple[App, str]] = {}

    for index, (kind, session_id, message_id, owner_id) in enumerate(fixture_rows):
        transcript = session(
            session_id,
            message(message_id, OLD + timedelta(minutes=index)),
        )
        candidates.append(Candidate(transcript, OLD))
        if kind == "fork":
            owners[("claude-code", message_id)] = ("claude-code", owner_id)

    selected = select_candidates(candidates, HarvestState({}, owners), NOW, None)

    assert selected.ready_count == 51
    assert [plan.session.id for plan in selected.plans] == ["ordinary-ready"]


def test_selection_skips_only_a_leading_prefix_owned_by_another_session() -> None:
    original = session(
        "a-original",
        message("shared-1"),
        message("shared-2", OLD + timedelta(minutes=1), "assistant"),
        message("original-only", OLD + timedelta(minutes=2)),
    )
    fork = session(
        "z-fork",
        message("shared-1"),
        message("shared-2", OLD + timedelta(minutes=1), "assistant"),
        message("fork-only", OLD + timedelta(minutes=3)),
    )

    selected = select_candidates(
        (Candidate(fork, OLD), Candidate(original, OLD)), empty_state(), NOW, None
    )

    assert [plan.session.id for plan in selected.plans] == ["a-original", "z-fork"]
    fork_plan = selected.plans[1]
    assert [message.id for message in fork_plan.messages] == ["fork-only"]
    assert fork_plan.forked_from == "a-original"


def test_selection_uses_existing_owner_across_runs_and_preserves_single_owner_prefix() -> None:
    original = session(
        "a-original",
        message("shared", OLD),
        message("original-only", OLD + timedelta(minutes=3)),
    )
    state = HarvestState({}, {("claude-code", "shared"): ("claude-code", "z-fork")})

    selected = select_candidates((Candidate(original, OLD),), state, NOW, None)

    assert [message.id for message in selected.plans[0].messages] == ["original-only"]
    assert selected.plans[0].forked_from == "z-fork"


def test_selection_does_not_skip_same_session_ids_or_nonleading_shared_ids() -> None:
    same_session = session(
        "same", message("shared", OLD), message("own", OLD + timedelta(minutes=1))
    )
    state = HarvestState({}, {("claude-code", "shared"): ("claude-code", "same")})
    own = select_candidates((Candidate(same_session, OLD),), state, NOW, None)
    assert [message.id for message in own.plans[0].messages] == ["shared", "own"]
    assert own.plans[0].forked_from is None

    nonleading = session(
        "other",
        message("new-first", OLD),
        message("shared", OLD + timedelta(minutes=1)),
        message("new-last", OLD + timedelta(minutes=2)),
    )
    state_with_owner = HarvestState({}, {("claude-code", "shared"): ("claude-code", "owner")})
    plan = select_candidates((Candidate(nonleading, OLD),), state_with_owner, NOW, None).plans[0]
    assert [message.id for message in plan.messages] == ["new-first", "shared", "new-last"]
    assert plan.forked_from is None


def test_selection_omits_a_session_when_every_new_message_is_already_owned() -> None:
    fork = session("fork", message("shared", OLD))
    state = HarvestState({}, {("claude-code", "shared"): ("claude-code", "owner")})
    selected = select_candidates((Candidate(fork, OLD),), state, NOW, None)
    assert selected.ready_count == 1
    assert selected.plans == ()


def test_selection_keeps_message_ids_separate_between_apps() -> None:
    codex = session("codex", message("same-id"), app="codex")
    state = HarvestState({}, {("claude-code", "same-id"): ("claude-code", "claude-owner")})
    selected = select_candidates((Candidate(codex, OLD),), state, NOW, None)
    assert [message.id for message in selected.plans[0].messages] == ["same-id"]


@pytest.mark.parametrize("limit", [0, -1])
def test_selection_refuses_nonpositive_session_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        select_candidates((), empty_state(), NOW, None, limit)


def test_selection_refuses_naive_clock_cutoff_or_modification_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        select_candidates((), empty_state(), datetime(2026, 10, 26, 12), None)
    with pytest.raises(ValueError, match="timezone-aware"):
        select_candidates((), empty_state(), NOW, datetime(2026, 10, 24))
    candidate = Candidate(session("naive", message("x")), datetime(2026, 10, 25, 8))
    with pytest.raises(ValueError, match="timezone-aware"):
        select_candidates((candidate,), empty_state(), NOW, None)
