"""Tests for the curation view of transcript observations."""

from datetime import UTC, datetime, timedelta

from kb import curation_view, transcript_observation
from kb.transcripts import App, Message, Role, Session

START = datetime(2026, 10, 25, 8, tzinfo=UTC)
LOCATOR = "observations/pending/view.md"


def observation(*messages: tuple[Role, str, tuple[str, ...]], app: App = "claude-code") -> str:
    retained = tuple(
        Message(f"m{index}", START + timedelta(minutes=index), role, text, commands)
        for index, (role, text, commands) in enumerate(messages, start=1)
    )
    session = Session(app, "session", "/work", None, None, retained, None, True)
    return transcript_observation.render(session, retained, 1, "host", START + timedelta(days=1))


def body(view: str) -> str:
    return view.split("\n---\n", 1)[1]


def test_a_transcript_without_commands_is_unchanged() -> None:
    text = observation(("user", "Hey, let's do some bash.", ()), ("assistant", "OK", ()))

    assert curation_view.render(text, LOCATOR) == text


def test_other_observations_are_unchanged() -> None:
    for text in (
        "---\ntitle: Note\nsource: observe\n---\n\n## 1. user, x\n\n~~~~sh\nls\n~~~~\n",
        "No front matter.\n",
        "---\nsource: session-transcript\nunclosed\n",
        "---\nsource: session-transcript\n---\n\nNo messages.\n",
    ):
        assert curation_view.render(text, LOCATOR) == text


def test_a_messages_commands_become_one_stub_after_its_text() -> None:
    text = observation(
        ("user", "Hey, let's do some bash.", ()),
        ("assistant", "OK", ("ls .", "rm -r ./tmp", "cp a b")),
        ("user", "Very good.", ()),
    )

    view = curation_view.render(text, LOCATOR)

    assert body(view) == (
        "\n## 1. user, 2026-10-25T08:01:00Z\n\n~~~~text\nHey, let's do some bash.\n~~~~\n\n"
        "## 2. assistant, 2026-10-25T08:02:00Z\n\n~~~~text\nOK\n~~~~\n\n"
        "[3 command(s) in message 2, 21 bytes: ls, rm, cp. "
        f"Read with: kb read {LOCATOR}#2]\n\n"
        "## 3. user, 2026-10-25T08:03:00Z\n\n~~~~text\nVery good.\n~~~~\n"
    )


def test_a_run_of_command_messages_becomes_one_stub() -> None:
    text = observation(
        ("user", "Look around.", ()),
        ("assistant", "", ("rg x",)),
        ("assistant", "", ("rg y | wc -l",)),
        ("assistant", "", ("FOO=1 /usr/bin/sed -n 1p f",)),
        ("assistant", "", ("rg z",)),
        ("assistant", "Done.", ()),
    )

    view = curation_view.render(text, LOCATOR)

    assert (
        "[4 command(s) in messages 2-5, 46 bytes: rg x3, wc, sed. "
        f"Read with: kb read {LOCATOR}#N, N 2-5]\n\n## 6. assistant"
    ) in view
    assert "~~~~sh" not in view


def test_a_stub_names_at_most_five_programs_and_rounds_kilobytes_up() -> None:
    commands = tuple(f"tool{index} {'x' * 300}" for index in range(7))
    text = observation(("assistant", "", commands))

    view = curation_view.render(text, LOCATOR)

    assert "[7 command(s) in message 1, 3 KB: tool0, tool1, tool2, tool3, tool4, 2 more." in view


def test_codex_scripts_name_their_literal_commands_patches_or_js() -> None:
    script = 'const r = await tools.exec_command({cmd:"git status && rg TODO"});\ntext(r.output);'
    patch = 'const p = "*** Begin Patch\\n*** End Patch";\nawait tools.apply_patch(p);'
    dynamic = "const r = await tools.exec_command({cmd:`ls ${dir}`});"
    text = observation(("assistant", "", (script, patch, dynamic, "just check")), app="codex")

    view = curation_view.render(text, LOCATOR)

    assert ": git, rg, patch, js, just." in view


def test_a_message_with_other_content_is_kept_verbatim() -> None:
    text = observation(("assistant", "", ("ls",)), ("user", "Next.", ()))
    edited = text.replace("## 2. user", "Stray line.\n\n## 2. user")

    view = curation_view.render(edited, LOCATOR)

    assert "~~~~sh\nls\n~~~~\n\nStray line.\n\n## 2. user" in view
