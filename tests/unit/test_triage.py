"""Tests for the rules that file transcripts in the archive instead of the curation queue."""

import pytest

from kb import model, triage
from kb.transcripts import Session


def document(*fields: str) -> model.Document:
    front = "".join(f"{field}\n" for field in fields)
    return model.parse("observation.md", f"---\n{front}---\n\nBody\n")


def test_a_transcript_with_a_parent_session_is_delegated() -> None:
    observed = document("source: session-transcript", 'parent_session: "parent"')

    assert triage.from_front_matter(observed) == "delegated"


@pytest.mark.parametrize(
    "fields",
    [
        ("source: session-transcript",),
        ("source: session-transcript", 'parent_session: ""'),
        ("source: observe", 'parent_session: "parent"'),
        ('parent_session: "parent"',),
        ("source: session-transcript", 'parent_session: "parent"', "triage: delegated"),
        ("source: session-transcript", 'parent_session: "parent"', "triage: curation"),
    ],
    ids=[
        "no parent",
        "empty parent",
        "not a transcript",
        "no source",
        "already triaged",
        "triaged by another rule",
    ],
)
def test_other_observations_are_not_triaged(fields: tuple[str, ...]) -> None:
    assert triage.from_front_matter(document(*fields)) is None


def test_a_file_without_front_matter_is_not_triaged() -> None:
    assert triage.from_front_matter(model.parse("observation.md", "Body\n")) is None


def session(parent: str | None = None, invoked: tuple[str, ...] = ()) -> Session:
    return Session(
        app="codex",
        id="session",
        project="/work",
        parent_session=parent,
        forked_from=None,
        messages=(),
        latest_timestamp=None,
        snapshot_complete=True,
        invoked=invoked,
    )


def test_a_session_with_a_parent_is_delegated_before_curation() -> None:
    assert triage.for_session(session("parent", ("curate",))) == "delegated"


def test_a_session_that_invoked_curate_is_a_curation_run() -> None:
    assert triage.for_session(session(invoked=("model", "curate"))) == "curation"


@pytest.mark.parametrize(
    "candidate",
    [session(), session(""), session(invoked=("curator", "goal"))],
    ids=["plain", "empty parent", "other skills"],
)
def test_other_sessions_are_not_triaged(candidate: Session) -> None:
    assert triage.for_session(candidate) is None
