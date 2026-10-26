"""Tests for article and section freshness."""

from datetime import date, timedelta

import pytest

from kb import freshness, model
from kb.model import Document

TODAY = date(2026, 10, 26)


def ago(days: int) -> str:
    """The date that is this many days before TODAY, as YYYY-MM-DD."""
    return (TODAY - timedelta(days=days)).isoformat()


def article(path: str, front: str, body: str = "## One\n\nText.\n") -> Document:
    return model.parse(path, f"---\n{front}---\n# Title\n\n{body}")


def knowledge(front: str, body: str = "## One\n\nText.\n") -> Document:
    return article("knowledge/topic.md", front, body)


def status_of(document: Document, locator: str = "") -> str:
    section = document.section(locator) if locator else None
    return freshness.status(document, section, TODAY)


@pytest.mark.parametrize(
    ("ttl", "days", "expected"),
    [
        ("people", 14, "fresh, verified {d}"),
        ("people", 15, "stale, verified {d} (ttl 14)"),
        ("status", 15, "stale, verified {d} (ttl 14)"),
        ("process", 60, "fresh, verified {d}"),
        ("process", 61, "stale, verified {d} (ttl 60)"),
        ("domain", 180, "fresh, verified {d}"),
        ("domain", 181, "stale, verified {d} (ttl 180)"),
        ("30", 30, "fresh, verified {d}"),
        ("30", 31, "stale, verified {d} (ttl 30)"),
        ('"90"', 90, "fresh, verified {d}"),
        ("weekly", 60, "fresh, verified {d}"),
        ("weekly", 61, "stale, verified {d} (ttl 60)"),
    ],
)
def test_each_ttl_form_sets_the_threshold(ttl: str, days: int, expected: str) -> None:
    verified = ago(days)
    document = knowledge(f"verified: {verified}\nttl: {ttl}\n")
    assert status_of(document) == expected.format(d=verified)


def test_a_missing_ttl_uses_the_sixty_day_default() -> None:
    assert status_of(knowledge(f"verified: {ago(60)}\n")) == f"fresh, verified {ago(60)}"
    assert status_of(knowledge(f"verified: {ago(61)}\n")) == (f"stale, verified {ago(61)} (ttl 60)")


def test_a_ttl_too_large_to_represent_is_invalid() -> None:
    document = knowledge(f"verified: {ago(1)}\nttl: 99999999999999999999\n")
    assert status_of(document) == "invalid"


def test_a_missing_verified_date_is_unknown() -> None:
    assert status_of(knowledge("ttl: domain\n")) == "unknown"


@pytest.mark.parametrize("value", ["2026-02-30", "soon", "2026-10-26T00:00:00Z"])
def test_a_malformed_verified_date_is_invalid(value: str) -> None:
    assert status_of(knowledge(f"verified: {value}\n")) == "invalid"


def test_a_future_date_is_fresh() -> None:
    assert status_of(knowledge("verified: 2026-11-01\nttl: people\n")) == (
        "fresh, verified 2026-11-01"
    )


def test_an_unresolved_conflict_adds_a_suffix() -> None:
    document = knowledge(f"verified: {ago(1)}\nconflict: unresolved\n")
    assert status_of(document) == f"fresh, verified {ago(1)}, conflict"


def test_a_resolved_conflict_adds_nothing() -> None:
    document = knowledge(f"verified: {ago(1)}\nconflict: resolved\n")
    assert status_of(document) == f"fresh, verified {ago(1)}"


def test_a_section_verified_date_and_ttl_override_the_article() -> None:
    document = knowledge(
        f"verified: {ago(1)}\nttl: domain\n",
        f"## One\n<!-- kb-section: verified={ago(100)}; ttl=process -->\n\nText.\n",
    )
    assert status_of(document, "1") == f"stale, verified {ago(100)} (ttl 60)"


def test_an_h3_inherits_its_h2_verified_date() -> None:
    document = knowledge(
        f"verified: {ago(1)}\n",
        f"## One\n<!-- kb-section: verified={ago(100)}; ttl=process -->\n\n### Sub\n",
    )
    assert status_of(document, "1.1") == f"stale, verified {ago(100)} (ttl 60)"


def test_a_section_without_its_own_date_uses_the_article() -> None:
    document = knowledge(f"verified: {ago(1)}\n", "## One\n\nText.\n")
    assert status_of(document, "1") == f"fresh, verified {ago(1)}"


def test_sources_documents_report_their_sync_date_and_never_go_stale() -> None:
    document = article("sources/vendor.md", f"synced: {ago(900)}\n")
    assert status_of(document) == f"source, synced {ago(900)}"


def test_sources_documents_without_a_sync_date_are_unknown() -> None:
    assert status_of(article("sources/vendor.md", "title: x\n")) == "unknown"


def test_sources_documents_with_a_malformed_sync_date_are_invalid() -> None:
    assert status_of(article("sources/vendor.md", "synced: nope\n")) == "invalid"


def test_sources_documents_ignore_verified() -> None:
    document = article("sources/vendor.md", f"verified: {ago(900)}\n")
    assert status_of(document) == "unknown"
