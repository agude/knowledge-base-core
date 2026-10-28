"""Pure selection and persisted batch-state contracts."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from kb import curation, evidence, model

RUN = "20261028T120000-a1b2c3d4"
HASH = "a" * 64


def item(name: str, size: int, created: date | None) -> curation.PendingInput:
    return curation.PendingInput(name, b"x" * size, created)


def make_batch(*members: curation.Member, maximum: int | None = None) -> curation.Batch:
    total = sum(member.original_bytes for member in members)
    return curation.Batch(
        schema_version=1,
        id=RUN,
        created="2026-10-28T12:00:00Z",
        max_bytes=total if maximum is None else maximum,
        selected_bytes=total,
        members=members,
    )


def pending(name: str = "20261028T120000-a1b2c3d4.md", size: int = 3) -> curation.Member:
    return curation.Member(name, HASH, size)


def test_run_id_uses_utc_time_and_injected_suffix() -> None:
    when = datetime(2026, 10, 28, 5, 2, 3, tzinfo=UTC)

    assert curation.make_run_id(when, "0123abcd") == "20261028T050203-0123abcd"


@pytest.mark.parametrize(
    ("when", "suffix"),
    [
        (datetime(2026, 10, 28), "0123abcd"),
        (datetime(2026, 10, 28, tzinfo=UTC), "ABCDEF12"),
        (datetime(2026, 10, 28, tzinfo=UTC), "short"),
    ],
)
def test_run_id_rejects_naive_time_and_bad_suffix(when: datetime, suffix: str) -> None:
    with pytest.raises(curation.StateError):
        curation.make_run_id(when, suffix)


def test_automatic_selection_uses_dates_then_filename_and_continues_after_skips() -> None:
    inputs = [
        item("later.md", 2, date(2026, 10, 4)),
        item("same-b.md", 4, date(2026, 10, 3)),
        item("same-a.md", 4, date(2026, 10, 3)),
        item("early.md", 2, date(2026, 10, 2)),
        item("oversized.md", 7, date(2026, 10, 1)),
    ]

    selected = curation.select(inputs, 6)

    assert [entry.filename for entry in selected.selected] == ["early.md", "same-a.md"]
    assert selected.selected_bytes == 6
    assert [entry.filename for entry in selected.skipped] == [
        "oversized.md",
        "same-b.md",
        "later.md",
    ]
    assert [entry.filename for entry in selected.larger_than_budget] == ["oversized.md"]


def test_missing_and_invalid_created_dates_sort_after_valid_dates_by_filename() -> None:
    documents = [
        ("missing.md", model.parse("missing.md", "---\ntitle: Missing\n---\n")),
        (
            "invalid.md",
            model.parse("invalid.md", "---\ntitle: Invalid\ncreated: never\n---\n"),
        ),
        (
            "valid.md",
            model.parse("valid.md", "---\ntitle: Valid\ncreated: 2026-10-01T10:00:00Z\n---\n"),
        ),
    ]
    dates = {name: evidence.created_date(document) for name, document in documents}
    selected = curation.select(
        [item(name, 1, dates[name]) for name, _document in documents],
        3,
    )

    assert [entry.filename for entry in selected.selected] == [
        "valid.md",
        "invalid.md",
        "missing.md",
    ]


def test_zero_budget_selects_nothing_and_exact_fits_are_included() -> None:
    inputs = [item("empty.md", 0, date(2026, 10, 1)), item("one.md", 1, None)]

    zero = curation.select(inputs, 0)
    exact = curation.select(inputs, 1)

    assert zero.selected == ()
    assert zero.selected_bytes == 0
    assert [entry.filename for entry in zero.skipped] == ["empty.md", "one.md"]
    assert [entry.filename for entry in zero.larger_than_budget] == ["one.md"]
    assert [entry.filename for entry in exact.selected] == ["empty.md", "one.md"]
    assert exact.selected_bytes == 1
    explicit_zero = curation.select([item("empty.md", 0, None)], 0, ["empty.md"])
    assert explicit_zero.selected == ()
    assert explicit_zero.skipped[0].filename == "empty.md"


def test_explicit_selection_preserves_order_and_enforces_budget() -> None:
    inputs = [item("first.md", 2, None), item("second.md", 4, None)]

    selected = curation.select(inputs, 6, ["second.md", "first.md"])

    assert [entry.filename for entry in selected.selected] == ["second.md", "first.md"]
    assert selected.selected_bytes == 6
    with pytest.raises(curation.SelectionError, match="over --max-bytes"):
        curation.select(inputs, 5, ["second.md", "first.md"])


@pytest.mark.parametrize("names", [["first.md", "first.md"], ["../first.md"], ["absent.md"]])
def test_explicit_selection_rejects_duplicates_unsafe_names_and_missing_items(
    names: list[str],
) -> None:
    with pytest.raises((curation.SelectionError, curation.StateError)):
        curation.select([item("first.md", 2, None)], 10, names)


def test_manifest_round_trips_with_stable_order_and_final_newline() -> None:
    destination = curation.Destination("knowledge/network.md#2", "VPN access")
    complete = curation.begin_archive(pending(), "incorporated", [destination], None, "b" * 64)
    batch = make_batch(curation.finish_archive(complete))

    rendered = curation.render_batch(batch)

    assert rendered.endswith("\n")
    assert rendered.index('"schema_version"') < rendered.index('"members"')
    assert rendered.index('"filename"') < rendered.index('"original_sha256"')
    assert curation.load_batch(rendered) == batch


def test_manifest_loader_accepts_object_fields_in_any_order() -> None:
    value = json.loads(curation.render_batch(make_batch(pending())))
    value = dict(reversed(list(value.items())))
    value["members"] = [dict(reversed(list(value["members"][0].items())))]

    assert curation.load_batch(json.dumps(value)).members == (pending(),)


@pytest.mark.parametrize(
    "text",
    [
        '{"schema_version":1,"schema_version":1}',
        '{"schema_version":NaN}',
        "[]",
    ],
)
def test_manifest_loader_rejects_duplicate_keys_non_json_constants_and_wrong_root(
    text: str,
) -> None:
    with pytest.raises(curation.StateError):
        curation.load_batch(text)


def test_manifest_loader_rejects_unknown_fields_and_unsupported_schema() -> None:
    value = json.loads(curation.render_batch(make_batch(pending())))
    value["unexpected"] = 1
    with pytest.raises(curation.StateError, match="unknown unexpected"):
        curation.load_batch(json.dumps(value))
    value.pop("unexpected")
    value["schema_version"] = 2
    with pytest.raises(curation.StateError, match="unsupported"):
        curation.load_batch(json.dumps(value))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(selected_bytes=99),
        lambda value: value.update(max_bytes=1),
        lambda value: value["members"][0].update(original_sha256="BAD"),
        lambda value: value["members"][0].update(filename="../outside.md"),
        lambda value: value["members"][0].update(status="archiving"),
        lambda value: value["members"][0].update(status="dropped"),
        lambda value: value["members"][0].update(original_bytes=True),
    ],
)
def test_manifest_loader_rejects_bad_totals_hashes_paths_and_state_combinations(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    value = json.loads(curation.render_batch(make_batch(pending())))
    mutate(value)

    with pytest.raises(curation.StateError):
        curation.load_batch(json.dumps(value))


def test_manifest_rejects_duplicate_member_names_and_bad_run_identifiers() -> None:
    with pytest.raises(curation.StateError, match="duplicate filenames"):
        make_batch(pending(), pending())
    with pytest.raises(curation.StateError, match="unsafe batch id"):
        replace(make_batch(pending()), id="../bad")


@pytest.mark.parametrize(
    ("locator", "heading"),
    [
        ("../knowledge/a.md#1", "Heading"),
        ("knowledge/a.md#01", "Heading"),
        ("knowledge/a.md#Heading", "Heading"),
        ("knowledge/a.md#1", None),
        ("knowledge/a.md", "Whole article"),
    ],
)
def test_destinations_require_safe_canonical_locator_heading_pairs(
    locator: str, heading: str | None
) -> None:
    with pytest.raises(curation.StateError):
        curation.Destination(locator, heading)


def test_member_state_transitions_preserve_outcomes_and_require_pending_state() -> None:
    original = pending()
    destination = curation.Destination("knowledge/network.md#2", "VPN access")

    archiving = curation.begin_archive(original, "incorporated", [destination], None, "b" * 64)
    complete = curation.finish_archive(archiving)
    deferred = curation.defer_member(pending("deferred.md"), "Need owner input")
    dropped = curation.drop_member(pending("dropped.md"), "Input changed")

    assert complete.status == "complete"
    assert complete.destinations == (destination,)
    assert deferred.status == "deferred" and deferred.reason == "Need owner input"
    assert dropped.status == "dropped" and dropped.reason == "Input changed"
    assert curation.is_settled(make_batch(complete, deferred, dropped))
    with pytest.raises(curation.StateError, match="cannot defer"):
        curation.defer_member(complete, "later")


@pytest.mark.parametrize(
    ("disposition", "destinations", "reason"),
    [
        ("incorporated", (), None),
        ("duplicate", (), None),
        ("ephemeral", (), None),
        ("ephemeral", (), "two\nlines"),
        ("incorporated", (), "reason"),
        ("duplicate", (), "reason"),
    ],
)
def test_archive_intent_rejects_invalid_disposition_combinations(
    disposition: str,
    destinations: tuple[curation.Destination, ...],
    reason: str | None,
) -> None:
    with pytest.raises(curation.StateError):
        curation.begin_archive(pending(), disposition, destinations, reason, "b" * 64)  # type: ignore[arg-type]


def test_defer_and_drop_reasons_must_be_nonempty_and_single_line() -> None:
    for transition in (curation.defer_member, curation.drop_member):
        for reason in ("", " \t ", "two\nlines", "two\rlines"):
            with pytest.raises(curation.StateError):
                transition(pending(), reason)


def test_replace_member_is_immutable_and_requires_membership() -> None:
    batch = make_batch(pending())
    deferred = curation.defer_member(batch.members[0], "Need owner input")

    changed = curation.replace_member(batch, deferred)

    assert batch.members[0].status == "pending"
    assert changed.members[0] == deferred
    with pytest.raises(curation.StateError, match="not a batch member"):
        curation.replace_member(batch, pending("other.md"))
