"""Pure reconstruction and selection rules for transcript harvesting."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from kb.meta import TranscriptMeta
from kb.transcripts import App, Message, Session

IDLE_TIME = timedelta(minutes=60)
MAX_SESSIONS = 50
SessionKey = tuple[App, str]
MessageKey = tuple[App, str]
HarvestRecord = TranscriptMeta
"""The harvest-related fields read from one committed observation's front matter."""


@dataclass(frozen=True)
class PartState:
    """The latest committed part for one app and session."""

    part: int
    last_message: str
    ended: datetime
    created: datetime | None


@dataclass(frozen=True)
class HarvestState:
    """Committed part pointers and message IDs already owned by a session."""

    parts: Mapping[SessionKey, PartState]
    owners: Mapping[MessageKey, SessionKey]
    recovered: frozenset[MessageKey] = frozenset()


@dataclass(frozen=True)
class Candidate:
    """A parsed transcript plus the file modification time from its scanner."""

    session: Session
    modified: datetime


@dataclass(frozen=True)
class HarvestPlan:
    """The messages to render as one observation for a session part."""

    session: Session
    part: int
    messages: tuple[Message, ...]
    forked_from: str | None


@dataclass(frozen=True)
class Selection:
    """Ready plans, backlog counts, and warnings about rewritten transcripts."""

    plans: tuple[HarvestPlan, ...]
    ready_count: int
    waiting_count: int
    warnings: tuple[str, ...]
    ready_modified: tuple[datetime, ...] = ()


@dataclass(frozen=True)
class _LegacyView:
    """The old parser's retained messages and indexed legacy endpoint positions."""

    messages: tuple[Message, ...]
    positions: Mapping[str, int]

    def range(self, record: HarvestRecord) -> tuple[Message, ...] | None:
        start = self.positions.get(record.first_message or "")
        end = self.positions.get(record.last_message or "")
        if start is None or end is None or start > end:
            return None
        return self.messages[start : end + 1]


def reconstruct_state(
    records: Iterable[HarvestRecord], sessions: Iterable[Session], host: str
) -> HarvestState:
    """Rebuild committed session pointers and message ownership for this host."""
    session_by_key = {
        (session.app, session.id): session for session in sessions if session.id is not None
    }
    views: dict[SessionKey, _LegacyView] = {}
    copies: dict[MessageKey, list[_LegacyView]] = {}
    for key, session in session_by_key.items():
        messages = tuple(message for message in session.messages if not message.legacy_duplicate)
        view = _LegacyView(
            messages,
            {message.legacy_id or message.id: index for index, message in enumerate(messages)},
        )
        views[key] = view
        for identity in view.positions:
            copies.setdefault((session.app, identity), []).append(view)
    accepted = [record for record in records if _valid_record(record, host)]
    parts: dict[SessionKey, PartState] = {}
    selected_records: dict[SessionKey, HarvestRecord] = {}
    for record in accepted:
        assert record.app is not None and record.session is not None
        assert (
            record.part is not None and record.last_message is not None and record.ended is not None
        )
        key = (record.app, record.session)
        previous = selected_records.get(key)
        if previous is None or _part_order(record) >= _part_order(previous):
            selected_records[key] = record
            parts[key] = PartState(
                record.part,
                record.last_message,
                record.ended,
                record.created,
            )

    owners: dict[MessageKey, SessionKey] = {}
    legacy_owners: dict[MessageKey, SessionKey] = {}
    for record in sorted(accepted, key=_ownership_order):
        assert record.app is not None and record.session is not None
        assert record.first_message is not None and record.last_message is not None
        assert record.started is not None and record.ended is not None
        key = (record.app, record.session)
        message_ids, legacy_ids = _record_ownership(record, views, copies)
        for message_id in legacy_ids:
            legacy_owners.setdefault((record.app, message_id), key)
        for message_id in message_ids:
            owners.setdefault((record.app, message_id), key)
    recovered: set[MessageKey] = set()
    for session in session_by_key.values():
        for message in session.messages:
            owner = legacy_owners.get((session.app, message.legacy_id or message.id))
            message_key = (session.app, message.id)
            if owner is None:
                continue
            if not message.legacy_duplicate:
                owners.setdefault(message_key, owner)
            elif message_key not in owners:
                recovered.add(message_key)
    return HarvestState(parts=parts, owners=owners, recovered=frozenset(recovered))


def select_candidates(
    candidates: Iterable[Candidate],
    state: HarvestState,
    now: datetime,
    harvest_since: datetime | None,
    limit: int = MAX_SESSIONS,
) -> Selection:
    """Choose ready messages in timestamp order and assign shared prefixes once."""
    if limit < 1:
        raise ValueError("the session limit must be positive")
    limit = min(limit, MAX_SESSIONS)
    now_utc = _utc(now)
    since_utc = None if harvest_since is None else _utc(harvest_since)
    warnings: list[str] = []
    ready: list[tuple[Candidate, tuple[Message, ...], int]] = []
    waiting = 0

    for candidate in candidates:
        session = candidate.session
        if session.id is None:
            continue
        key = (session.app, session.id)
        previous = state.parts.get(key)
        messages, missing_pointer = _after_saved_part(session.messages, previous)
        after_ids = {message.id for message in messages}
        messages = tuple(
            message
            for message in session.messages
            if (message.id in after_ids or (session.app, message.id) in state.recovered)
            and (previous is None or state.owners.get((session.app, message.id)) != key)
        )
        if missing_pointer:
            assert previous is not None
            warnings.append(
                f"session {session.id}: saved last_message {previous.last_message} is missing; "
                "continuing after ended"
            )
        if since_utc is not None:
            messages = tuple(message for message in messages if message.timestamp >= since_utc)
        if not messages:
            continue

        modified = _utc(candidate.modified)
        latest_activity = session.latest_timestamp
        activity = modified if latest_activity is None else max(modified, latest_activity)
        is_ready = session.snapshot_complete and now_utc - activity >= IDLE_TIME
        if is_ready:
            part = 1 if previous is None else previous.part + 1
            ready.append((candidate, messages, part))
        else:
            waiting += 1

    ready.sort(key=lambda item: (item[1][0].timestamp, item[0].session.id or ""))
    owners = dict(state.owners)
    plans: list[HarvestPlan] = []
    for candidate, messages, part in ready:
        session = candidate.session
        assert session.id is not None
        key = (session.app, session.id)
        remaining: list[Message] = []
        skipped_owner: SessionKey | None = None
        in_prefix = True
        for message in messages:
            owner = owners.get((session.app, message.id))
            if in_prefix and owner is not None and owner != key:
                if skipped_owner is None:
                    skipped_owner = owner
                continue
            if (session.app, message.id) not in state.recovered:
                in_prefix = False
            remaining.append(message)
        if remaining:
            plans.append(
                HarvestPlan(
                    session=session,
                    part=part,
                    messages=tuple(remaining),
                    forked_from=None if skipped_owner is None else skipped_owner[1],
                )
            )
            for message in remaining:
                owners.setdefault((session.app, message.id), key)
            if len(plans) == limit:
                break
    ready_times = tuple(_utc(candidate.modified) for candidate, _, _ in ready)
    return Selection(tuple(plans), len(ready), waiting, tuple(warnings), ready_times)


def _valid_record(record: HarvestRecord, host: str) -> bool:
    """Whether a committed observation contains enough matching state to use."""
    return (
        record.source == "session-transcript"
        and record.host == host
        and record.app in ("claude-code", "codex", "goose")
        and isinstance(record.session, str)
        and bool(record.session)
        and isinstance(record.part, int)
        and not isinstance(record.part, bool)
        and record.part > 0
        and isinstance(record.first_message, str)
        and bool(record.first_message)
        and isinstance(record.last_message, str)
        and bool(record.last_message)
        and _is_aware(record.started)
        and _is_aware(record.ended)
        and (record.created is None or _is_aware(record.created))
    )


def _part_order(record: HarvestRecord) -> tuple[int, datetime]:
    """Order committed records by part, then by creation time for duplicate parts."""
    assert record.part is not None
    created = (
        _utc(record.created) if record.created is not None else datetime.min.replace(tzinfo=UTC)
    )
    return record.part, created


def _ownership_order(record: HarvestRecord) -> tuple[datetime, bool, str]:
    """Prefer earlier observations and the non-skipping side of a same-run fork."""
    created = (
        _utc(record.created) if record.created is not None else datetime.min.replace(tzinfo=UTC)
    )
    return created, record.forked_from is not None, record.session or ""


def _record_ownership(
    record: HarvestRecord,
    views: Mapping[SessionKey, _LegacyView],
    copies: Mapping[MessageKey, list[_LegacyView]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return exact current membership and, for a legacy record, its represented old IDs."""
    if record.message_ids is not None:
        return record.message_ids, ()
    assert record.app is not None and record.session is not None
    assert record.first_message is not None and record.last_message is not None
    assert record.started is not None and record.ended is not None
    view = views.get((record.app, record.session))
    if view is None:
        view = next(
            (
                value
                for value in copies.get((record.app, record.first_message), [])
                if value.range(record) is not None
            ),
            None,
        )
    if view is None:
        endpoints = _endpoints(record)
        return endpoints, endpoints
    matched = view.range(record)
    if matched is None:
        started, ended = _utc(record.started), _utc(record.ended)
        matched = tuple(
            message for message in view.messages if started <= message.timestamp <= ended
        )
    if not matched:
        endpoints = _endpoints(record)
        return endpoints, endpoints
    return (
        tuple(message.id for message in matched),
        tuple(message.legacy_id or message.id for message in matched),
    )


def _endpoints(record: HarvestRecord) -> tuple[str, ...]:
    """Fallback ownership when the transcript file for a committed session is absent."""
    assert record.first_message is not None and record.last_message is not None
    if record.first_message == record.last_message:
        return (record.first_message,)
    return (record.first_message, record.last_message)


def _after_saved_part(
    messages: tuple[Message, ...], previous: PartState | None
) -> tuple[tuple[Message, ...], bool]:
    """Return messages after the saved pointer, or after ended when that ID disappeared."""
    if previous is None:
        return messages, False
    index = next(
        (index for index, message in enumerate(messages) if message.id == previous.last_message),
        None,
    )
    if index is None:
        index = next(
            (
                index
                for index, message in enumerate(messages)
                if not message.legacy_duplicate and message.legacy_id == previous.last_message
            ),
            None,
        )
    if index is not None:
        return messages[index + 1 :], False
    ended = _utc(previous.ended)
    return tuple(message for message in messages if message.timestamp > ended), True


def _is_aware(value: datetime | None) -> bool:
    """Whether a datetime has a usable UTC offset."""
    return value is not None and value.tzinfo is not None and value.utcoffset() is not None


def _utc(value: datetime) -> datetime:
    """Normalize a timezone-aware datetime to UTC."""
    if not _is_aware(value):
        raise ValueError("the timestamp must be timezone-aware")
    return value.astimezone(UTC)
