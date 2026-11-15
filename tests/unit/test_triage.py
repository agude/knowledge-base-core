"""Tests for the rules that file transcripts in the archive instead of the curation queue."""

import pytest

from kb import model, triage


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
