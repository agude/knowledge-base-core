"""Multi-turn capture through the Claude adapters: prompt, stop, end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.inspect import git_log
from kbtest.runner import KB, Result


class Session:
    """Drive the Claude session adapters for one session ID."""

    def __init__(self, kb: KB) -> None:
        self.kb = kb
        self.id = kb.session_id()
        self.file = kb.layout.sessions / f"session-{self.id}.jsonl"

    def start_buffer(self) -> None:
        """Create the buffer as session-start would, without the marker."""
        self.kb.layout.sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.file.touch(mode=0o600)

    def _hook(self, adapter: str, payload: dict[str, str], env: dict[str, str | None]) -> Result:
        return self.kb.run(
            f"adapters/claude/{adapter}",
            stdin=json.dumps({"session_id": self.id, **payload}),
            env=env,
        )

    def prompt(self, text: str, **env: str | None) -> Result:
        return self._hook("session-prompt", {"prompt": text}, {"KNOWLEDGE_OBSERVE": "1", **env})

    def stop(self, text: str, **env: str | None) -> Result:
        return self._hook(
            "session-stop", {"last_assistant_message": text}, {"KNOWLEDGE_OBSERVE": "1", **env}
        )

    def end(self, **env: str | None) -> Result:
        return self._hook("session-end", {"reason": "user_quit"}, {"KNOWLEDGE_OBSERVE": "1", **env})

    def buffer(self) -> str:
        if not self.file.exists():
            return "absent\n"
        return self.kb.norm(self.file.read_text(encoding="utf-8"))


def _pending(kb: KB) -> list[Path]:
    return sorted((kb.layout.content / "observations" / "pending").glob("*.md"))


def _observations(kb: KB) -> str:
    parts = [f"## {p.name}\n{p.read_text(encoding='utf-8')}" for p in _pending(kb)]
    return kb.norm("".join(parts) if parts else "none\n")


def _results(kb: KB, *results: Result) -> str:
    lines = [f"{r.script}: exit {r.returncode} stdout={r.out!r} stderr={r.err!r}" for r in results]
    return kb.norm("\n".join(lines) + "\n")


@pytest.fixture
def session(kb: KB) -> Session:
    return Session(kb)


@pytest.mark.bats("session_flow.bats", "session file persists after session-stop")
def test_buffer_persists_after_stop(session: Session, golden: Golden) -> None:
    session.start_buffer()
    results = [session.prompt("Hello"), session.stop("Hi there")]
    golden.check("results", _results(session.kb, *results))
    golden.contract("buffer", session.buffer())


@pytest.mark.bats("session_flow.bats", "session file accumulates messages across turns")
def test_buffer_accumulates(session: Session, golden: Golden) -> None:
    session.start_buffer()
    session.prompt("First question")
    session.stop("First answer")
    session.prompt("Second question")
    session.stop("Second answer")
    golden.contract("buffer", session.buffer())


@pytest.mark.bats("session_flow.bats", "multi-turn session creates observation with all messages")
@pytest.mark.bats("session_flow.bats", "session-end cleans up session file after flushing")
def test_session_end_flushes(session: Session, golden: Golden) -> None:
    session.start_buffer()
    session.prompt("What is 2+2?")
    session.stop("4")
    session.prompt("And 3+3?")
    session.stop("6")
    result = session.end()
    golden.check("results", _results(session.kb, result))
    golden.contract("buffer", session.buffer())
    golden.contract("observations", _observations(session.kb))
    golden.contract(
        "log", session.kb.norm(git_log(session.kb.layout.content, session.kb.git_env()))
    )


@pytest.mark.bats("session_flow.bats", "session-end drops a one-exchange transcript")
def test_session_end_drops_one_exchange(session: Session, golden: Golden) -> None:
    session.start_buffer()
    session.prompt("What is 2+2?")
    session.stop("4")
    result = session.end()
    golden.check("results", _results(session.kb, result))
    golden.contract("buffer", session.buffer())
    golden.contract("observations", _observations(session.kb))
    # How the drop is logged is not a contract (A-004).
    golden.check("syslog", session.kb.norm(_read(session.kb.layout.syslog)))


@pytest.mark.bats("session_flow.bats", "KNOWLEDGE_MIN_MESSAGES=0 keeps a one-exchange transcript")
def test_min_messages_zero(session: Session, golden: Golden) -> None:
    session.start_buffer()
    session.prompt("What is 2+2?")
    session.stop("4")
    session.end(KNOWLEDGE_MIN_MESSAGES="0")
    golden.contract("observations", _observations(session.kb))


@pytest.mark.bats("session_flow.bats", "session-end keeps a transcript at the threshold")
def test_session_end_at_threshold(session: Session, golden: Golden) -> None:
    session.start_buffer()
    session.prompt("First")
    session.stop("Answer")
    session.prompt("Second")
    session.end()
    golden.contract("observations", _observations(session.kb))


@pytest.mark.bats("session_flow.bats", "session-stop recreates a swept buffer")
def test_stop_recreates_buffer(session: Session, golden: Golden) -> None:
    result = session.stop("Response")
    golden.check("results", _results(session.kb, result))
    golden.contract("buffer", session.buffer())


@pytest.mark.bats("session_flow.bats", "session-prompt recreates a swept buffer")
def test_prompt_recreates_buffer(session: Session, golden: Golden) -> None:
    result = session.prompt("Hello")
    golden.check("results", _results(session.kb, result))
    golden.contract("buffer", session.buffer())


@pytest.mark.bats(
    "session_flow.bats", "capture continues after the orphan sweep removes the buffer"
)
def test_capture_continues_after_sweep(session: Session, golden: Golden) -> None:
    session.start_buffer()
    session.prompt("Before the sweep")
    session.stop("First answer")
    session.file.unlink()
    session.prompt("After the sweep")
    session.stop("Second answer")
    golden.contract("buffer", session.buffer())


@pytest.mark.bats("session_flow.bats", "capture stays off when session-start never ran")
@pytest.mark.null_ok("the contract is a silent exit 0 that creates no buffer")
def test_capture_off_without_start(session: Session) -> None:
    result = session.prompt("Hi", KNOWLEDGE_OBSERVE=None)
    assert (result.returncode, result.out, result.err) == (0, "", "")
    assert not session.file.exists()


@pytest.mark.bats("session_flow.bats", "capture stays off when KNOWLEDGE_OBSERVE=0")
@pytest.mark.null_ok("the contract is a silent exit 0 that creates no buffer")
def test_capture_off_when_disabled(session: Session) -> None:
    session.start_buffer()
    results = [
        session.prompt("Hi", KNOWLEDGE_OBSERVE="0"),
        session.stop("Hello", KNOWLEDGE_OBSERVE="0"),
        session.end(KNOWLEDGE_OBSERVE="0"),
    ]
    for result in results:
        assert (result.returncode, result.out, result.err) == (0, "", "")
    assert session.file.read_text(encoding="utf-8") == ""
    assert _pending(session.kb) == []


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else "none\n"
