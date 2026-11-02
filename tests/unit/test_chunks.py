"""Tests for the transcript chunker: merging, splitting, message kinds, and injected text."""

from datetime import UTC, datetime

import pytest

from kb import chunks
from kb.model import Document, parse
from kb.transcript_observation import render
from kb.transcripts import Message, Session

FRONT = (
    "---\n"
    "title: Transcript\n"
    "source: session-transcript\n"
    'session: "s"\n'
    'first_message: "m1"\n'
    'last_message: "m2"\n'
    "part: 1\n"
    "started: 2026-10-20T00:00:00Z\n"
    "ended: 2026-10-20T23:00:00Z\n"
    "created: 2026-10-21T00:00:00Z\n"
    "---\n\n"
)


def addressable(texts: list[str]) -> Document:
    """A valid transcript whose messages are ## 1. ..., ## 2. ..., and so on."""
    body = "".join(
        f"## {number}. {'user' if number % 2 else 'assistant'}, 2026-10-20T00:{number:02d}:00Z\n\n"
        f"{text}\n\n"
        for number, text in enumerate(texts, 1)
    )
    return parse("observations/archived/t.md", FRONT + body)


def plain(text: str) -> Document:
    return parse("observations/archived/p.md", f"---\ntitle: Plain\n---\n\n{text}\n")


def legacy(*parts: tuple[str, str]) -> Document:
    body = "".join(f"### {role}\n\n{text}\n\n" for role, text in parts)
    return parse("observations/archived/l.md", "---\ntitle: Legacy\n---\n\n" + body)


def text_of(chunk: chunks.Chunk) -> str:
    return "\n".join(chunk.lines)


def test_short_messages_merge_forward_until_the_threshold() -> None:
    texts = [f"{number}" + "a" * 299 for number in range(1, 7)]
    found = chunks.chunks(addressable(texts))

    assert [chunk.number for chunk in found] == [1, 5]
    assert all(f"{number}aaa" in text_of(found[0]) for number in range(1, 5))
    assert "5aaa" not in text_of(found[0])
    assert "5aaa" in text_of(found[1]) and "6aaa" in text_of(found[1])


def test_each_message_starts_a_chunk_when_it_already_reaches_the_threshold() -> None:
    texts = [f"{number}" + "b" * 1100 for number in range(1, 4)]
    found = chunks.chunks(addressable(texts))

    assert [chunk.number for chunk in found] == [1, 2, 3]


def test_a_long_message_splits_at_blank_lines_into_about_target_pieces() -> None:
    paragraphs = [f"P{number} " + "x" * 997 for number in range(1, 6)]
    found = chunks.chunks(addressable(["\n\n".join(paragraphs)]))

    assert [chunk.number for chunk in found] == [1, 1, 1]
    assert [len(chunk.lines) for chunk in found] == [3, 3, 1]
    assert found[0].lines[0].startswith("P1 ") and found[0].lines[-1].startswith("P2 ")
    assert found[1].lines[0].startswith("P3 ") and found[2].lines == (paragraphs[4],)


def test_a_piece_never_splits_inside_a_code_fence() -> None:
    fence = "```\n" + "\n\n".join(f"code {index} " + "c" * 800 for index in range(3)) + "\n```"
    text = "p" * 1500 + "\n\n" + fence + "\n\n" + "q" * 1000
    found = chunks.chunks(addressable([text]))

    fenced_pieces = [
        chunk for chunk in found if any(line.startswith("```") for line in chunk.lines)
    ]
    assert len(fenced_pieces) == 1
    fence_lines = [line for line in fenced_pieces[0].lines if line.startswith("```")]
    assert len(fence_lines) == 2
    assert any(line.startswith("code 2 ") for line in fenced_pieces[0].lines)


def test_rendered_storage_fences_are_unwrapped_before_message_cleaning_and_splitting() -> None:
    timestamp = datetime(2026, 10, 20, tzinfo=UTC)
    messages = (
        Message("m1", timestamp, "user", "# AGENTS.md instructions for /repo\n\nDiscard this."),
        Message(
            "m2",
            timestamp,
            "assistant",
            "# Keep this heading\n\ninline ~~~~~ marker\n\n"
            + "\n\n".join("prose " + "x" * 998 for _ in range(5))
            + "\n\n```python\nprint('authored')\n```",
            ("printf 'preserve this command'\n",),
        ),
    )
    session = Session("claude-code", "session", "/repo", None, None, messages, timestamp, True)
    rendered = render(session, messages, 1, "host", timestamp)

    found = chunks.chunks(parse("observations/archived/rendered.md", rendered))
    text = "\n".join(text_of(chunk) for chunk in found)

    assert len(found) > 1
    assert "AGENTS.md" not in text and "Discard this." not in text
    assert "# Keep this heading" in text
    assert "prose " in text
    assert "inline ~~~~~ marker" in text
    assert "```python\nprint('authored')\n```" in text
    assert "~~~~text" not in text
    assert "~~~~sh" in text and "preserve this command" in text


@pytest.mark.parametrize(
    ("marker", "shorter", "different"), (("~", "~~~", "```"), ("`", "```", "~~~"))
)
def test_fence_tracker_requires_a_valid_matching_closer(
    marker: str, shorter: str, different: str
) -> None:
    fence = marker * 4
    block = [
        f"{fence}lang",
        "prefix " + "p" * 2100,
        shorter,
        different,
        f"{fence} trailing text",
        "",
        "middle " + "x" * 2100,
        fence,
    ]
    found = chunks.chunks(addressable(["before " + "p" * 1500 + "\n\n" + "\n".join(block)]))

    containing = [chunk for chunk in found if f"{fence}lang" in chunk.lines]
    assert len(containing) == 1
    assert "middle " + "x" * 2100 in text_of(containing[0])
    assert "prefix " + "p" * 2100 in text_of(containing[0])


def test_a_fenced_block_longer_than_the_target_stays_whole() -> None:
    block = ["```", "first", "", *(["middle " * 100, ""] * 8), "last", "```"]
    text = "before text\n\n" + "\n".join(block) + "\n\nafter text"
    found = chunks.chunks(addressable([text]))

    assert "\n".join(block) in "\n".join(text_of(chunk) for chunk in found)
    assert all(text_of(chunk).count("```") % 2 == 0 for chunk in found)


def test_a_long_message_without_blank_lines_is_one_piece() -> None:
    found = chunks.chunks(addressable(["y" * 4500]))
    assert [len(chunk.lines) for chunk in found] == [1]


def test_legacy_messages_make_chunks_without_message_numbers() -> None:
    found = chunks.chunks(legacy(("user", "Which share?"), ("assistant", "The family share.")))

    assert [chunk.number for chunk in found] == [chunks.NO_MESSAGE]
    assert "Which share?" in text_of(found[0])
    assert "The family share." in text_of(found[0])


def test_a_file_with_no_message_headings_is_one_chunk_with_its_whole_body() -> None:
    found = chunks.chunks(plain("Plain text.\n\nSecond paragraph."))

    assert found == (
        chunks.Chunk(
            chunks.NO_MESSAGE,
            chunks.NO_MESSAGE,
            None,
            None,
            0,
            ("Plain text.", "", "Second paragraph."),
        ),
    )


def test_injected_instructions_and_reminders_are_removed_before_chunking() -> None:
    found = chunks.chunks(
        addressable(
            [
                "Keep this <INSTRUCTIONS>secret rules\nacross lines</INSTRUCTIONS> visible.",
                "Also <system-reminder>hidden note</system-reminder> here.",
            ]
        )
    )

    text = "\n".join(text_of(chunk) for chunk in found)
    assert "secret" not in text and "hidden" not in text
    assert "Keep this  visible." in text
    assert "Also  here." in text


def test_an_agents_instruction_message_is_dropped_from_the_chunks() -> None:
    found = chunks.chunks(
        addressable(
            [
                "# AGENTS.md instructions for /repo\n\nBe terse.",
                "The real question.",
            ]
        )
    )

    text = "\n".join(text_of(chunk) for chunk in found)
    assert "AGENTS.md" not in text and "Be terse" not in text
    assert "The real question." in text


def test_visible_blanks_injected_text_and_keeps_every_line_and_section() -> None:
    document = addressable(
        [
            "# AGENTS.md instructions for /repo\n\nBe terse.",
            "Keep this <INSTRUCTIONS>secret rules\nacross lines</INSTRUCTIONS> visible.",
            "The real question with <system-reminder>hidden note</system-reminder> here.",
        ]
    )

    view = chunks.visible(document)

    assert len(view.lines) == len(document.lines)
    assert view.sections == document.sections
    assert view.heading_lines == document.heading_lines
    text = "\n".join(view.lines)
    assert "secret" not in text and "Be terse" not in text and "hidden" not in text
    assert "AGENTS" not in text
    assert "visible." in text and "The real question with" in text and "here." in text
    assert document.lines != view.lines


def test_visible_removes_injected_text_from_legacy_messages() -> None:
    document = legacy(("user", "Plain <system-reminder>hidden</system-reminder> words."))

    text = "\n".join(chunks.visible(document).lines)

    assert "hidden" not in text and "Plain" in text and "words." in text


def test_visible_returns_the_same_lines_when_nothing_is_injected() -> None:
    document = addressable(["Nothing injected here."])
    assert chunks.visible(document).lines == document.lines


def test_an_agents_prefix_in_an_assistant_message_is_kept() -> None:
    found = chunks.chunks(addressable(["AGENTS.md instructions for /repo are shown above."]))
    assert "AGENTS.md instructions for /repo are shown above." in text_of(found[0])


def test_a_chunk_number_is_the_number_of_its_first_message() -> None:
    found = chunks.chunks(addressable(["a" * 1100, "b" * 10, "c" * 1100, "d" * 10]))

    assert [chunk.number for chunk in found] == [1, 2, 4]
    assert "b" * 10 in text_of(found[1]) and "c" * 1100 in text_of(found[1])


def test_legacy_message_keeps_prose_beneath_other_headings() -> None:
    document = parse(
        "observations/archived/l.md",
        "---\ntitle: Legacy\n---\n\n# Title\n\n### user\n\nQ?\n\n## Notes\n\nSide note.\n",
    )
    found = chunks.chunks(document)

    assert [chunk.number for chunk in found] == [chunks.NO_MESSAGE]
    assert "Q?" in text_of(found[0])
    assert "## Notes" in text_of(found[0])
    assert "Side note." in text_of(found[0])


def test_blank_lines_left_by_removed_text_are_trimmed_at_both_ends() -> None:
    found = chunks.chunks(
        addressable(
            [
                "<system-reminder>note</system-reminder>\n\nHello there.",
                "Goodbye.\n<system-reminder>note</system-reminder>",
            ]
        )
    )

    assert text_of(found[0]).startswith("\n") is False
    assert text_of(found[0]).splitlines()[0] == "Hello there."
    assert text_of(found[0]).endswith("Goodbye.")


def test_a_merged_chunk_records_its_first_and_last_message_and_timestamps() -> None:
    found = chunks.chunks(addressable(["a" * 300, "b" * 300, "c" * 300, "d" * 300, "e" * 1100]))

    assert [(chunk.number, chunk.last, chunk.piece) for chunk in found] == [(1, 4, 0), (5, 5, 0)]
    assert found[0].started == datetime(2026, 10, 20, 0, 1, tzinfo=UTC)
    assert found[0].ended == datetime(2026, 10, 20, 0, 4, tzinfo=UTC)
    assert found[1].started == found[1].ended == datetime(2026, 10, 20, 0, 5, tzinfo=UTC)


def test_split_pieces_record_their_message_and_a_one_based_piece_index() -> None:
    paragraphs = [f"P{number} " + "x" * 997 for number in range(1, 6)]
    found = chunks.chunks(addressable(["short", "\n\n".join(paragraphs), "tail"]))

    split = [chunk for chunk in found if chunk.number == 2]
    assert [chunk.piece for chunk in split] == [1, 2, 3]
    assert all(chunk.last == 2 for chunk in split)
    assert all(
        chunk.started == chunk.ended == datetime(2026, 10, 20, 0, 2, tzinfo=UTC) for chunk in split
    )
    assert [(chunk.number, chunk.piece) for chunk in found] == [
        (1, 0),
        (2, 1),
        (2, 2),
        (2, 3),
        (3, 0),
    ]


def test_legacy_chunks_record_no_message_range_or_timestamps() -> None:
    found = chunks.chunks(legacy(("user", "Which share?"), ("assistant", "The family share.")))

    assert [
        (chunk.number, chunk.last, chunk.started, chunk.ended, chunk.piece) for chunk in found
    ] == [(chunks.NO_MESSAGE, chunks.NO_MESSAGE, None, None, 0)]


def test_best_chunk_has_the_most_distinct_query_terms() -> None:
    filler = "x " * 600
    document = addressable([filler + "alpha", filler + "beta gamma"])

    best = chunks.best(document, ("beta", "gamma"))

    assert best is not None
    assert best.number == 2


def test_best_chunk_is_none_when_no_chunk_holds_a_query_term() -> None:
    filler = "x " * 600
    document = addressable([filler + "alpha", filler + "beta"])

    assert chunks.best(document, ("zebra",)) is None


def test_best_chunk_is_none_when_injected_text_leaves_no_message() -> None:
    document = addressable(["# AGENTS.md instructions for the project"])

    assert chunks.best(document, ("project",)) is None
