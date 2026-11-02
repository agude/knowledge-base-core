"""The cached records and their derivations: chunk tokens, message tokens, and search units.

The chunk tokens must equal the chunks that chunks.chunks forms from the same file, with and
without a date bound, on every fixture transcript.
"""

from pathlib import Path

from kb import chunks, corpus, entries, search, token_cache
from kb.model import Document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SESSION_FRONT = (
    "---\n"
    "title: Session transcript: long\n"
    "source: session-transcript\n"
    "session: long-session\n"
    "part: 1\n"
    "first_message: long-1\n"
    "last_message: long-3\n"
    "started: 2026-10-01T09:00:00Z\n"
    "ended: 2026-10-01T10:00:00Z\n"
    "created: 2026-10-01T10:05:00Z\n"
    "---\n\n"
)


def reference_unit(document: Document) -> search.Unit:
    """The unit of an evidence file: its title and all of its text, as evidence built it first."""
    body = document.prose(document.body_start, len(document.lines))
    return search.make_unit(document.title or "", (), (), body)


def transcript(messages: list[str]) -> str:
    """A transcript with one addressable message per text, timestamped one minute apart."""
    sections = [
        f"## {number}. user, 2026-10-01T09:{number:02d}:00Z\n\n{text}"
        for number, text in enumerate(messages, 1)
    ]
    return SESSION_FRONT + "\n\n".join(sections) + "\n"


def loaded_fixtures(tmp_path: Path) -> tuple[Path, dict[str, entries.Entry]]:
    """Every fixture file written as an archived observation, with its cache entry."""
    root = tmp_path / "content"
    names = []
    for file in sorted(FIXTURES.rglob("*.md")):
        relpath = "observations/archived/" + "-".join(file.relative_to(FIXTURES).parts)
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.read_text(encoding="utf-8"), encoding="utf-8")
        names.append(relpath)
    return root, token_cache.load(root, names)


def eligible_on_even_minutes(moment: object) -> bool:
    return moment is None or moment.minute % 2 == 0  # type: ignore[attr-defined]


def test_chunk_tokens_equal_the_chunks_of_every_fixture_transcript(tmp_path: Path) -> None:
    root, loaded = loaded_fixtures(tmp_path)
    transcripts = 0
    for relpath, entry in loaded.items():
        if not entry.parts:
            continue
        transcripts += 1
        document = corpus.read_document(root, relpath)
        for bound in (None, eligible_on_even_minutes):
            expected = [
                (
                    found.number,
                    found.last,
                    found.started,
                    found.ended,
                    found.piece,
                    tuple(token for line in found.lines for token in search.index_tokens(line)),
                )
                for found in chunks.chunks(document, bound)
            ]
            actual = [
                (found.number, found.last, found.started, found.ended, found.piece, found.body)
                for found in entries.chunk_tokens(entry, bound)
            ]
            assert actual == expected, (relpath, bound)
    assert transcripts > 0


def test_message_bodies_join_the_pieces_of_a_split_message(tmp_path: Path) -> None:
    paragraphs = [f"Paragraph {number} " + "word " * 200 for number in range(1, 8)]
    text = "\n\n".join(paragraphs)
    relpath = "observations/archived/split.md"
    (tmp_path / "content" / "observations" / "archived").mkdir(parents=True)
    (tmp_path / "content" / relpath).write_text(
        transcript(["short question", text]), encoding="utf-8"
    )
    entry = token_cache.load(tmp_path / "content", [relpath])[relpath]

    pieces = [part for part in entry.parts if part.number == 2]
    assert len(pieces) > 1
    assert [part.piece for part in pieces] == list(range(1, len(pieces) + 1))
    assert entries.message_bodies(entry)[2] == frozenset(search.index_tokens(text))
    # Each piece of a split message is a chunk of its own.
    chunk_numbers = [(found.number, found.piece) for found in entries.chunk_tokens(entry)]
    assert chunk_numbers.count((2, 1)) == 1
    assert [found.piece for found in entries.chunk_tokens(entry) if found.number == 2] == list(
        range(1, len(pieces) + 1)
    )


def test_message_moment_is_the_timestamp_of_the_message(tmp_path: Path) -> None:
    relpath = "observations/archived/moments.md"
    (tmp_path / "content" / "observations" / "archived").mkdir(parents=True)
    (tmp_path / "content" / relpath).write_text(
        transcript(["first words", "second words"]), encoding="utf-8"
    )
    entry = token_cache.load(tmp_path / "content", [relpath])[relpath]

    moment = entries.message_moment(entry, 2)
    assert moment is not None
    assert moment.isoformat() == "2026-10-01T09:02:00+00:00"
    assert entries.message_moment(entry, 99) is None


def test_file_and_chunk_units_carry_the_title_as_a_phrase(tmp_path: Path) -> None:
    relpath = "observations/pending/titled.md"
    (tmp_path / "content" / "observations" / "pending").mkdir(parents=True)
    (tmp_path / "content" / relpath).write_text(
        "---\ntitle: Alpha note\n---\n### user\n\nBeta words.\n", encoding="utf-8"
    )
    entry = token_cache.load(tmp_path / "content", [relpath])[relpath]

    unit = entries.file_unit(entry)
    assert unit.title == ("alpha", "note")
    assert unit.phrases == frozenset({"alpha note"})
    assert unit.headings == ()
    assert unit.body == ("beta", "word")
    assert entries.file_unit(entry) == reference_unit(
        corpus.read_document(tmp_path / "content", relpath)
    )


def test_a_chunk_unit_has_the_file_title_and_its_own_body(tmp_path: Path) -> None:
    relpath = "observations/archived/chunked.md"
    (tmp_path / "content" / "observations" / "archived").mkdir(parents=True)
    (tmp_path / "content" / relpath).write_text(transcript(["traefik renewal"]), encoding="utf-8")
    entry = token_cache.load(tmp_path / "content", [relpath])[relpath]

    found = entries.chunk_tokens(entry)[0]
    unit = entries.chunk_unit(entry, found)
    assert unit.body == found.body
    assert unit.title == entry.title
    assert unit.headings == () and unit.aliases == ()
    assert unit.phrases == entries.file_unit(entry).phrases


def test_a_bounded_chunking_never_spans_a_rejected_part(tmp_path: Path) -> None:
    relpath = "observations/archived/bounded.md"
    (tmp_path / "content" / "observations" / "archived").mkdir(parents=True)
    (tmp_path / "content" / relpath).write_text(
        transcript(["alpha", "beta", "gamma"]), encoding="utf-8"
    )
    entry = token_cache.load(tmp_path / "content", [relpath])[relpath]

    bounded = entries.chunk_tokens(entry, lambda moment: moment is None or moment.minute != 2)

    assert [(found.number, found.last) for found in bounded] == [(1, 1), (3, 3)]
