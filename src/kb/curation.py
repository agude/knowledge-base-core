"""Pure batch state, selection, validation, and transitions for guided curation."""

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Literal, cast

from kb.locators import parse_locator

SCHEMA_VERSION = 1
MAX_REPORT_ITEMS = 8
Disposition = Literal["incorporated", "duplicate", "ephemeral"]
Status = Literal["pending", "archiving", "complete", "deferred", "dropped"]
_RUN = re.compile(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{8}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SECTION = re.compile(r"[1-9][0-9]*(?:\.[1-9][0-9]*)?")
_DESTINATION_FRAGMENTS = frozenset({"title", "top"})
_WINDOWS_FORBIDDEN = frozenset('<>:"/\\|?*')
_TOP_FIELDS = (
    "schema_version",
    "id",
    "created",
    "max_bytes",
    "selected_bytes",
    "members",
)
_MEMBER_FIELDS = (
    "filename",
    "original_sha256",
    "original_bytes",
    "status",
    "disposition",
    "destinations",
    "reason",
    "archive_sha256",
)
_DISPOSITIONS = frozenset({"incorporated", "duplicate", "ephemeral"})
_STATUSES = frozenset({"pending", "archiving", "complete", "deferred", "dropped"})


class StateError(ValueError):
    """A batch state value violates the persisted schema or its invariants."""


class SelectionError(ValueError):
    """An explicit selection cannot be formed within the supplied byte budget."""


@dataclass(frozen=True)
class Destination:
    """A canonical knowledge locator and its heading at the time of completion."""

    locator: str
    heading: str | None

    def __post_init__(self) -> None:
        validate_destination(self)


@dataclass(frozen=True)
class Member:
    """One selected observation and its persisted outcome or recovery intent."""

    filename: str
    original_sha256: str
    original_bytes: int
    status: Status = "pending"
    disposition: Disposition | None = None
    destinations: tuple[Destination, ...] = ()
    reason: str | None = None
    archive_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_member(self)


@dataclass(frozen=True)
class Batch:
    """The versioned, local state for one selected group of observations."""

    schema_version: int
    id: str
    created: str
    max_bytes: int
    selected_bytes: int
    members: tuple[Member, ...]

    def __post_init__(self) -> None:
        validate_batch(self)


@dataclass(frozen=True)
class PendingInput:
    """An observation snapshot supplied to the pure selector."""

    filename: str
    content: bytes
    created_date: date | None

    @property
    def size(self) -> int:
        """The original UTF-8 byte count used by the selection budget."""
        return len(self.content)


@dataclass(frozen=True)
class Selection:
    """The chosen inputs and the reports for inputs that did not fit."""

    selected: tuple[PendingInput, ...]
    skipped: tuple[PendingInput, ...]
    larger_than_budget: tuple[PendingInput, ...]
    selected_bytes: int


def make_run_id(when: datetime, suffix: str) -> str:
    """Build a portable batch identifier from UTC time and an injected random suffix."""
    if when.tzinfo is None or when.utcoffset() is None:
        raise StateError("batch timestamp must be timezone-aware")
    if not re.fullmatch(r"[0-9a-f]{8}", suffix):
        raise StateError("batch suffix must be eight lowercase hexadecimal digits")
    return f"{when.astimezone(UTC):%Y%m%dT%H%M%S}-{suffix}"


def make_member(filename: str, content: bytes) -> Member:
    """Snapshot one input's name, exact byte length, and SHA-256."""
    return Member(
        filename=filename,
        original_sha256=hashlib.sha256(content).hexdigest(),
        original_bytes=len(content),
    )


def select(
    inputs: Iterable[PendingInput],
    max_bytes: int,
    explicit_names: Iterable[str] | None = None,
) -> Selection:
    """Select inputs in date/name order, or preserve an explicit caller order."""
    _nonnegative_int(max_bytes, "max_bytes")
    candidates = tuple(inputs)
    names = [item.filename for item in candidates]
    for name in names:
        validate_filename(name)
    if len(names) != len(set(names)):
        raise SelectionError("duplicate pending filename")

    by_name = {item.filename: item for item in candidates}
    if explicit_names is not None:
        requested = tuple(explicit_names)
        for name in requested:
            validate_filename(name)
        if len(requested) != len(set(requested)):
            raise SelectionError("duplicate filename in explicit selection")
        missing = [name for name in requested if name not in by_name]
        if missing:
            raise SelectionError("pending observation not found: " + ", ".join(missing))
        selected = tuple(by_name[name] for name in requested)
        total = sum(item.size for item in selected)
        if total > max_bytes:
            raise SelectionError(
                f"explicit selection is {total} bytes, over --max-bytes {max_bytes}"
            )
        if max_bytes == 0:
            return Selection((), selected, (), 0)
        return Selection(selected, (), (), total)

    ordered = sorted(
        candidates,
        key=lambda item: (
            item.created_date is None,
            item.created_date or date.max,
            item.filename,
        ),
    )
    if max_bytes == 0:
        zero_budget_skipped = tuple(ordered)
        zero_budget_larger = tuple(item for item in ordered if item.size > 0)
        return Selection((), zero_budget_skipped, zero_budget_larger, 0)

    chosen: list[PendingInput] = []
    skipped: list[PendingInput] = []
    larger: list[PendingInput] = []
    total = 0
    for item in ordered:
        if item.size > max_bytes:
            larger.append(item)
            skipped.append(item)
        elif item.size <= max_bytes - total:
            chosen.append(item)
            total += item.size
        else:
            skipped.append(item)
    return Selection(tuple(chosen), tuple(skipped), tuple(larger), total)


def make_batch(
    run_id: str,
    created: datetime,
    max_bytes: int,
    members: Iterable[Member],
) -> Batch:
    """Create a validated batch with byte totals derived from its members."""
    if created.tzinfo is None or created.utcoffset() is None:
        raise StateError("batch created timestamp must be timezone-aware")
    timestamp = created.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    ordered_members = tuple(members)
    total = sum(member.original_bytes for member in ordered_members)
    return Batch(SCHEMA_VERSION, run_id, timestamp, max_bytes, total, ordered_members)


def render_batch(batch: Batch) -> str:
    """Serialize validated state as stable UTF-8 JSON with a final newline."""
    validate_batch(batch)
    return json.dumps(_batch_object(batch), ensure_ascii=False, indent=2) + "\n"


def load_batch(text: str) -> Batch:
    """Parse strict JSON state, rejecting duplicate keys and malformed combinations."""
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, StateError) as error:
        raise StateError(f"invalid batch JSON: {error}") from error
    if not isinstance(value, dict):
        raise StateError("batch must be a JSON object")
    _exact_fields(value, _TOP_FIELDS, "batch")
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise StateError(f"unsupported batch schema version: {value['schema_version']!r}")
    members_value = value["members"]
    if not isinstance(members_value, list):
        raise StateError("batch members must be an array")
    members = tuple(_member_from_object(item) for item in members_value)
    return Batch(
        schema_version=value["schema_version"],
        id=_string(value["id"], "batch id"),
        created=_string(value["created"], "batch created"),
        max_bytes=_integer(value["max_bytes"], "batch max_bytes"),
        selected_bytes=_integer(value["selected_bytes"], "batch selected_bytes"),
        members=members,
    )


def validate_batch(batch: Batch) -> None:
    """Raise StateError unless the batch and every member satisfy the schema."""
    if type(batch.schema_version) is not int or batch.schema_version != SCHEMA_VERSION:
        raise StateError(f"unsupported batch schema version: {batch.schema_version!r}")
    validate_run_id(batch.id)
    _validate_timestamp(batch.created)
    _nonnegative_int(batch.max_bytes, "max_bytes")
    _nonnegative_int(batch.selected_bytes, "selected_bytes")
    if not batch.members:
        raise StateError("batch must contain at least one member")
    filenames = [member.filename for member in batch.members]
    if len(filenames) != len(set(filenames)):
        raise StateError("batch contains duplicate filenames")
    for member in batch.members:
        validate_member(member)
    total = sum(member.original_bytes for member in batch.members)
    if batch.selected_bytes != total:
        raise StateError(f"selected_bytes is {batch.selected_bytes}, expected {total}")
    if total > batch.max_bytes:
        raise StateError("selected bytes exceed max_bytes")


def validate_member(member: Member) -> None:
    """Raise StateError unless a member's path, hashes, and outcome agree."""
    validate_filename(member.filename)
    _validate_hash(member.original_sha256, "original_sha256")
    _nonnegative_int(member.original_bytes, "original_bytes")
    if member.status not in _STATUSES:
        raise StateError(f"invalid member status: {member.status!r}")
    for destination in member.destinations:
        validate_destination(destination)
    locators = [destination.locator for destination in member.destinations]
    if len(locators) != len(set(locators)):
        raise StateError("member contains duplicate destinations")

    if member.status == "pending":
        if _has_outcome(member):
            raise StateError("pending member cannot contain an outcome")
        return
    if member.status in ("archiving", "complete"):
        if member.disposition not in _DISPOSITIONS:
            raise StateError(f"{member.status} member needs a valid disposition")
        _validate_outcome_fields(member)
        _validate_hash(member.archive_sha256, "archive_sha256")
        return
    if member.status in ("deferred", "dropped") and (
        member.disposition is not None
        or member.destinations
        or member.archive_sha256 is not None
        or not _valid_reason(member.reason)
    ):
        raise StateError(f"{member.status} member needs only a nonempty single-line reason")


def validate_destination(destination: Destination) -> None:
    """Validate a canonical knowledge locator and its paired heading snapshot."""
    if not isinstance(destination.locator, str) or not destination.locator:
        raise StateError("destination locator must be a nonempty string")
    locator = parse_locator(destination.locator)
    path = locator.path
    path_object = PurePosixPath(path)
    if (
        not path.startswith("knowledge/")
        or not path.endswith(".md")
        or "\\" in path
        or path_object.is_absolute()
        or path_object.as_posix() != path
        or any(part in ("", ".", "..") for part in path.split("/"))
    ):
        raise StateError(f"unsafe destination path: {path!r}")
    if (
        locator.fragment is not None
        and locator.fragment not in _DESTINATION_FRAGMENTS
        and not _SECTION.fullmatch(locator.fragment)
    ):
        raise StateError(f"invalid destination fragment: {locator.fragment!r}")
    canonical = path if locator.fragment is None else f"{path}#{locator.fragment}"
    if destination.locator != canonical:
        raise StateError(f"destination locator is not canonical: {destination.locator!r}")
    if locator.fragment is None:
        if destination.heading is not None:
            raise StateError("whole-article destination must not have a heading")
    elif not _valid_reason(destination.heading):
        raise StateError("fragment destination needs a nonempty single-line heading")


def begin_archive(
    member: Member,
    disposition: Disposition,
    destinations: Iterable[Destination],
    reason: str | None,
    archive_sha256: str,
) -> Member:
    """Record a recoverable archive intent for a pending member."""
    if member.status != "pending":
        raise StateError(f"cannot archive member in {member.status} state")
    updated = replace(
        member,
        status="archiving",
        disposition=disposition,
        destinations=tuple(destinations),
        reason=reason,
        archive_sha256=archive_sha256,
    )
    validate_member(updated)
    return updated


def finish_archive(member: Member) -> Member:
    """Mark a persisted archive intent complete without changing its outcome."""
    if member.status != "archiving":
        raise StateError(f"cannot finish member in {member.status} state")
    return replace(member, status="complete")


def defer_member(member: Member, reason: str) -> Member:
    """Defer an unchanged pending member with a single-line reason."""
    if member.status != "pending":
        raise StateError(f"cannot defer member in {member.status} state")
    updated = replace(member, status="deferred", reason=reason)
    validate_member(updated)
    return updated


def drop_member(member: Member, reason: str) -> Member:
    """Drop a changed or missing pending member without describing file operations."""
    if member.status != "pending":
        raise StateError(f"cannot drop member in {member.status} state")
    updated = replace(member, status="dropped", reason=reason)
    validate_member(updated)
    return updated


def replace_member(batch: Batch, updated: Member) -> Batch:
    """Return a validated batch with one existing member replaced by filename."""
    members = tuple(
        updated if member.filename == updated.filename else member for member in batch.members
    )
    if all(member.filename != updated.filename for member in batch.members):
        raise StateError(f"not a batch member: {updated.filename}")
    return replace(batch, members=members)


def is_settled(batch: Batch) -> bool:
    """Whether every member has a final local outcome, ready for publication."""
    return all(member.status in {"complete", "deferred", "dropped"} for member in batch.members)


def validate_filename(filename: str) -> None:
    """Refuse paths and names that can escape the direct pending directory."""
    if (
        not isinstance(filename, str)
        or not filename
        or filename.startswith(".")
        or not filename.endswith(".md")
        or filename in {".", ".."}
        or any(character in _WINDOWS_FORBIDDEN or ord(character) < 32 for character in filename)
        or filename.endswith((".", " "))
        or PurePosixPath(filename).name != filename
    ):
        raise StateError(f"unsafe pending filename: {filename!r}")


def validate_run_id(run_id: str) -> None:
    """Refuse nonportable batch identifiers and invalid timestamp portions."""
    if not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None:
        raise StateError(f"unsafe batch id: {run_id!r}")
    try:
        datetime.strptime(run_id[:15], "%Y%m%dT%H%M%S")
    except ValueError as error:
        raise StateError(f"unsafe batch id: {run_id!r}") from error


def _member_from_object(value: object) -> Member:
    if not isinstance(value, dict):
        raise StateError("batch member must be a JSON object")
    _exact_fields(value, _MEMBER_FIELDS, "batch member")
    destinations_value = value["destinations"]
    if not isinstance(destinations_value, list):
        raise StateError("member destinations must be an array")
    destinations = tuple(_destination_from_object(item) for item in destinations_value)
    disposition_value = value["disposition"]
    if disposition_value is not None and (
        not isinstance(disposition_value, str) or disposition_value not in _DISPOSITIONS
    ):
        raise StateError(f"invalid member disposition: {disposition_value!r}")
    status_value = value["status"]
    if not isinstance(status_value, str) or status_value not in _STATUSES:
        raise StateError(f"invalid member status: {status_value!r}")
    return Member(
        filename=_string(value["filename"], "member filename"),
        original_sha256=_string(value["original_sha256"], "member original_sha256"),
        original_bytes=_integer(value["original_bytes"], "member original_bytes"),
        status=cast(Status, status_value),
        disposition=cast(Disposition | None, disposition_value),
        destinations=destinations,
        reason=_nullable_string(value["reason"], "member reason"),
        archive_sha256=_nullable_string(value["archive_sha256"], "member archive_sha256"),
    )


def _destination_from_object(value: object) -> Destination:
    if not isinstance(value, dict):
        raise StateError("member destination must be a JSON object")
    _exact_fields(value, ("locator", "heading"), "member destination")
    return Destination(
        locator=_string(value["locator"], "destination locator"),
        heading=_nullable_string(value["heading"], "destination heading"),
    )


def _batch_object(batch: Batch) -> dict[str, object]:
    return {
        "schema_version": batch.schema_version,
        "id": batch.id,
        "created": batch.created,
        "max_bytes": batch.max_bytes,
        "selected_bytes": batch.selected_bytes,
        "members": [_member_object(member) for member in batch.members],
    }


def _member_object(member: Member) -> dict[str, object]:
    return {
        "filename": member.filename,
        "original_sha256": member.original_sha256,
        "original_bytes": member.original_bytes,
        "status": member.status,
        "disposition": member.disposition,
        "destinations": [
            {"locator": destination.locator, "heading": destination.heading}
            for destination in member.destinations
        ],
        "reason": member.reason,
        "archive_sha256": member.archive_sha256,
    }


def _validate_outcome_fields(member: Member) -> None:
    if member.disposition in {"incorporated", "duplicate"}:
        if not member.destinations or member.reason is not None:
            raise StateError(f"{member.disposition} member needs destinations and no reason")
    elif member.disposition == "ephemeral" and (
        member.destinations or not _valid_reason(member.reason)
    ):
        raise StateError("ephemeral member needs a reason and no destinations")


def _has_outcome(member: Member) -> bool:
    return any(
        (
            member.disposition is not None,
            bool(member.destinations),
            member.reason is not None,
            member.archive_sha256 is not None,
        )
    )


def _validate_timestamp(value: str) -> None:
    if not isinstance(value, str):
        raise StateError("batch created timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StateError("batch created timestamp must be an ISO UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise StateError("batch created timestamp must be an ISO UTC timestamp")


def _validate_hash(value: str | None, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StateError(f"{name} must be a lowercase SHA-256 hash")


def _valid_reason(value: str | None) -> bool:
    return (
        isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value
    )


def _nonnegative_int(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise StateError(f"{name} must be a nonnegative integer")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise StateError(f"{name} must be a string")
    return value


def _nullable_string(value: object, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise StateError(f"{name} must be a string or null")
    return value


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise StateError(f"{name} must be an integer")
    return value


def _exact_fields(value: Mapping[str, object], fields: tuple[str, ...], name: str) -> None:
    if tuple(value) != fields:
        missing = [field for field in fields if field not in value]
        extra = [field for field in value if field not in fields]
        if missing or extra:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("unknown " + ", ".join(extra))
            raise StateError(f"{name} has " + " and ".join(details))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise StateError(f"invalid JSON constant: {value}")
