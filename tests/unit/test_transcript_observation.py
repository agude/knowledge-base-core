"""Tests for pure transcript titles, redaction, fenced rendering, and validation."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from kb import transcript_observation
from kb.transcripts import Message, Session

CREATED = datetime(2026, 10, 26, 12, 0, 5, tzinfo=UTC)


def make_session(
    *,
    session_id: str | None = "session-id",
    parent: str | None = None,
    project: str = '/work/agent "project"',
) -> Session:
    return Session(
        app="claude-code",
        id=session_id,
        project=project,
        parent_session=parent,
        forked_from=None,
        messages=(),
        latest_timestamp=None,
        snapshot_complete=True,
    )


def messages() -> tuple[Message, ...]:
    return (
        Message(
            "user-1",
            datetime(2026, 10, 25, 8, tzinfo=UTC),
            "user",
            "First user line.\nSecond line.",
        ),
        Message(
            "assistant-1",
            datetime(2026, 10, 25, 8, 1, tzinfo=UTC),
            "assistant",
            "Answer with a heading:\n## Inside the message\n~~~~sh\nprintf ok\n~~~~",
            ("printf 'answer'\nsecond ~~~~~",),
        ),
    )


def test_title_candidates_use_the_first_user_line_and_cap_it_at_sixty_chars() -> None:
    content = "x" * 80
    values = (
        Message("assistant", CREATED, "assistant", "Answer first."),
        Message("user", CREATED, "user", f"\n{content}\nSecond line."),
    )

    fallback, title, excerpt = transcript_observation.title_candidates(values)

    assert fallback == "Session transcript (2 messages)"
    assert title == f"{fallback}: {'x' * 60}"
    assert excerpt == "x" * 60


def test_title_candidates_fall_back_when_there_is_no_user_excerpt() -> None:
    values = (Message("assistant", CREATED, "assistant", "Answer."),)
    assert transcript_observation.title_candidates(values) == (
        "Session transcript (1 messages)",
        "Session transcript (1 messages)",
        None,
    )


def test_title_candidates_skip_blank_user_messages_before_finding_excerpt() -> None:
    values = (
        Message("blank", CREATED, "user", " \n"),
        Message("answer", CREATED, "assistant", "Answer."),
        Message("next-user", CREATED, "user", "Use this line."),
    )
    assert transcript_observation.title_candidates(values) == (
        "Session transcript (3 messages)",
        "Session transcript (3 messages): Use this line.",
        "Use this line.",
    )


def test_title_after_scan_drops_only_a_flagged_excerpt() -> None:
    values = (Message("user", CREATED, "user", "Password = fixture."),)
    assert transcript_observation.title_after_scan(values, ()) == (
        "Session transcript (1 messages): Password = fixture.",
        0,
    )
    assert transcript_observation.title_after_scan(values, (("Secret Keyword", 1),)) == (
        "Session transcript (1 messages)",
        1,
    )
    assistant_only = (Message("assistant", CREATED, "assistant", "Answer."),)
    assert transcript_observation.title_after_scan(assistant_only, (("Secret Keyword", 1),)) == (
        "Session transcript (1 messages)",
        0,
    )


def test_scan_text_contains_only_message_and_command_lines_with_locations() -> None:
    scan, locations = transcript_observation.scan_text(messages())

    assert scan == (
        "First user line.\nSecond line.\nAnswer with a heading:\n## Inside the message\n"
        "~~~~sh\nprintf ok\n~~~~\nprintf 'answer'\nsecond ~~~~~\n"
    )
    assert locations[0].message_index == 0
    assert locations[1].line_index == 1
    assert locations[2].message_index == 1
    assert locations[2].command_index is None
    assert locations[7].command_index == 0
    assert locations[8].line_index == 1
    assert transcript_observation.scan_text(())[0] == ""


def test_redact_messages_replaces_only_finding_lines_in_text_and_commands() -> None:
    source = messages()
    scan, locations = transcript_observation.scan_text(source)
    assert scan

    redacted, count = transcript_observation.redact_messages(
        source,
        (("Secret Keyword", 2), ("Other Detector", 2), ("AWS Access Key", 8), ("Bad", 99)),
        locations,
    )

    assert count == 2
    assert redacted[0].text == "First user line.\n[redacted: Secret Keyword]"
    assert redacted[1].commands == ("[redacted: AWS Access Key]\nsecond ~~~~~",)
    assert redacted[1].text == source[1].text


def test_redact_messages_with_no_valid_findings_returns_original_content() -> None:
    source = messages()
    scan, locations = transcript_observation.scan_text(source)
    assert scan
    redacted, count = transcript_observation.redact_messages(
        source, (("Bad", 0), ("Bad", 500)), locations
    )
    assert redacted == source
    assert count == 0


def test_render_writes_required_fields_and_safe_fences() -> None:
    source = messages()
    session = make_session(parent="parent-id")

    rendered = transcript_observation.render(
        session,
        source,
        2,
        'fedora "host"',
        datetime(2026, 10, 26, 5, 0, 5, tzinfo=timezone(timedelta(hours=-7))),
        forked_from="fork-owner",
    )

    assert 'title: "Session transcript (2 messages): First user line."' in rendered
    assert 'source: session-transcript\nproject: "/work/agent \\"project\\""' in rendered
    assert 'host: "fedora \\"host\\""' in rendered
    assert 'app: claude-code\nsession: "session-id"\nparent_session: "parent-id"\n' in rendered
    assert 'forked_from: "fork-owner"\npart: 2\n' in rendered
    assert 'first_message: "user-1"\nlast_message: "assistant-1"' in rendered
    assert "created: 2026-10-26T12:00:05Z\n---\n\n## 1. user, 2026-10-25T08:00:00Z" in rendered
    assert "~~~~~text\nAnswer with a heading:" in rendered
    assert "~~~~~~sh\nprintf 'answer'\nsecond ~~~~~\n~~~~~~" in rendered
    assert "## 2. assistant, 2026-10-25T08:01:00Z" in rendered
    assert (
        transcript_observation.validate(
            rendered,
            session,
            source,
            2,
            'fedora "host"',
            datetime(2026, 10, 26, 5, 0, 5, tzinfo=timezone(timedelta(hours=-7))),
            forked_from="fork-owner",
        )
        == ()
    )


def test_render_preserves_trailing_newline_and_handles_command_only_messages() -> None:
    session = make_session()
    values = (Message("command", CREATED, "assistant", "", ("printf ok\n",)),)
    rendered = transcript_observation.render(session, values, 1, "host", CREATED)
    assert "## 1. assistant, 2026-10-26T12:00:05Z\n\n~~~~sh\nprintf ok\n~~~~" in rendered
    assert transcript_observation.validate(rendered, session, values, 1, "host", CREATED) == ()
    scan, locations = transcript_observation.scan_text(values)
    assert scan == "printf ok\n\n"
    redacted, count = transcript_observation.redact_messages(
        values, (("Secret Keyword", 1),), locations
    )
    assert count == 1
    assert redacted[0].text == ""
    assert redacted[0].commands == ("[redacted: Secret Keyword]\n",)


def test_render_and_validate_accept_an_explicit_safe_title() -> None:
    session = make_session()
    values = messages()
    rendered = transcript_observation.render(
        session, values, 1, "host", CREATED, title="Session transcript (2 messages)"
    )
    assert 'title: "Session transcript (2 messages)"' in rendered
    assert (
        transcript_observation.validate(
            rendered,
            session,
            values,
            1,
            "host",
            CREATED,
            title="Session transcript (2 messages)",
        )
        == ()
    )


def test_render_without_excerpt_uses_the_fallback_title() -> None:
    session = make_session()
    values = (Message("assistant", CREATED, "assistant", "Answer."),)
    rendered = transcript_observation.render(session, values, 1, "host", CREATED)
    assert 'title: "Session transcript (1 messages)"' in rendered


@pytest.mark.parametrize(
    ("session", "values", "part", "message"),
    [
        (make_session(session_id=None), messages(), 1, "session ID"),
        (make_session(), (), 1, "at least one message"),
        (make_session(), messages(), 0, "part must be positive"),
    ],
)
def test_render_refuses_invalid_session_parts(
    session: Session, values: tuple[Message, ...], part: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        transcript_observation.render(session, values, part, "host", CREATED)


def test_validate_reports_front_matter_and_message_heading_mismatches() -> None:
    session = make_session(parent="parent-id")
    values = messages()
    rendered = transcript_observation.render(session, values, 1, "host", CREATED)
    invalid = rendered.replace("app: claude-code", "app: other").replace(
        "## 2. assistant", "# 2. assistant"
    )

    failures = transcript_observation.validate(invalid, session, values, 1, "host", CREATED)

    assert failures == ("app", "message headings")


def test_validate_rejects_unexpected_optional_fields_and_missing_identity() -> None:
    session = make_session()
    values = messages()
    rendered = transcript_observation.render(session, values, 1, "host", CREATED)
    invalid = rendered.replace(
        'session: "session-id"', 'session: "session-id"\nparent_session: "unexpected"'
    )
    assert transcript_observation.validate(invalid, session, values, 1, "host", CREATED) == (
        "parent_session",
    )
    assert transcript_observation.validate(
        rendered, make_session(session_id=None), values, 1, "host", CREATED
    ) == ("missing session ID or messages",)
    assert transcript_observation.validate(rendered, session, (), 1, "host", CREATED) == (
        "missing session ID or messages",
    )
