"""Claude session-start: context injection, buffer setup, and env exports."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result


def _start(kb: KB, session_id: str, **env: str | None) -> Result:
    return kb.run(
        "adapters/claude/session-start",
        stdin=json.dumps({"session_id": session_id}),
        env=env,
    )


def _check(kb: KB, golden: Golden, result: Result) -> None:
    """Pin output; the tooling repo's AGENTS.md, printed verbatim, is a placeholder."""
    out = kb.placeholder_instructions(result.out)
    golden.contract("result", f"exit {result.returncode}\n")
    golden.contract("context", kb.context_facts(result.out))
    golden.check("stdout", kb.norm(out).replace(kb.session_prefix, "<SESSION>-"))
    golden.check("stderr", kb.norm_err(result.err))


def _mode(path: Path) -> str:
    return f"{stat.S_IMODE(path.lstat().st_mode):o}"


@pytest.mark.bats("session_start.bats", "session-start outputs AGENTS.md content")
@pytest.mark.bats("session_start.bats", "session-start includes auto-generated topics heading")
def test_session_start_empty(kb: KB, golden: Golden) -> None:
    _check(kb, golden, _start(kb, kb.session_id(), KNOWLEDGE_OBSERVE="0"))


@pytest.mark.bats("session_start.bats", "session-start includes the topic map from toc")
@pytest.mark.bats("session_start.bats", "session-start includes live state")
def test_session_start_map_and_state(kb: KB, golden: Golden) -> None:
    kb.create_article("infra/networking.md", "# Networking\n\n## DNS\n\nContent.")
    kb.create_observation("20260412T000000-0000aaaa.md", "Obs", "Body")
    kb.create_question("q.md", "Why?")
    _check(kb, golden, _start(kb, kb.session_id(), KNOWLEDGE_OBSERVE="0"))


@pytest.mark.bats("session_start.bats", "session-start injection stays small as articles are added")
def test_session_start_stays_small(kb: KB) -> None:
    for index in range(1, 31):
        kb.create_article(
            f"area{index % 5}/topic{index}.md", f"# Topic {index}\n\n## Section\n\nContent."
        )
    few = _start(kb, kb.session_id(), KNOWLEDGE_OBSERVE="0")
    for index in range(31, 61):
        kb.create_article(
            f"area{index % 5}/topic{index}.md", f"# Topic {index}\n\n## Section\n\nContent."
        )
    many = _start(kb, kb.session_id(), KNOWLEDGE_OBSERVE="0")
    assert few.returncode == many.returncode == 0
    assert "knowledge/area0/" in few.out
    # 30 more articles in the same areas add no lines: the map is per area.
    assert len(many.out.splitlines()) == len(few.out.splitlines())
    assert len(few.out.splitlines()) < 100


@pytest.mark.bats("session_start.bats", "session-start includes content AGENTS.md when present")
def test_session_start_content_instructions(kb: KB, golden: Golden) -> None:
    (kb.layout.content / "AGENTS.md").write_text("# Project Rules\n", encoding="utf-8")
    _check(kb, golden, _start(kb, kb.session_id(), KNOWLEDGE_OBSERVE="0"))


def test_session_start_content_claude_md(kb: KB, golden: Golden) -> None:
    (kb.layout.content / "CLAUDE.md").write_text("# Legacy Rules\n", encoding="utf-8")
    _check(kb, golden, _start(kb, kb.session_id(), KNOWLEDGE_OBSERVE="0"))


@pytest.mark.bats("session_start.bats", "session-start still injects context when jq is missing")
def test_session_start_without_jq(no_jq: KB, golden: Golden) -> None:
    no_jq.create_article("infra/networking.md", "# Networking\n\n## DNS\n\nContent.")
    session_id = no_jq.session_id()
    # The context is printed either way. Bash's adapter needs jq to read the
    # session ID and skips capture without it; Python's needs no jq (A-043).
    _check(no_jq, golden, _start(no_jq, session_id))


@pytest.mark.bats("session_start.bats", "session-start creates the session directory mode 700")
@pytest.mark.bats("session_start.bats", "session-start creates the buffer mode 600")
def test_session_start_creates_buffer(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    env_file = kb.layout.root / "claude.env"
    env_file.touch()
    result = _start(kb, session_id, CLAUDE_ENV_FILE=str(env_file))
    _check(kb, golden, result)
    buffer = kb.layout.sessions / f"session-{session_id}.jsonl"
    marker = kb.layout.sessions / f"session-{session_id}.initialized"
    golden.contract(
        "modes",
        f"dir {_mode(kb.layout.sessions)}\nbuffer {_mode(buffer)} size {buffer.stat().st_size}\n"
        + (f"marker {_mode(marker)}\n" if marker.exists() else "marker absent\n"),
    )
    golden.contract(
        "env",
        kb.norm(env_file.read_text(encoding="utf-8")).replace(kb.session_prefix, "<SESSION>-"),
    )


@pytest.mark.bats(
    "session_start.bats", "session-start tightens a pre-existing world-readable directory"
)
def test_session_start_tightens_directory(kb: KB) -> None:
    kb.layout.sessions.mkdir(parents=True)
    kb.layout.sessions.chmod(0o777)
    result = _start(kb, kb.session_id())
    assert result.returncode == 0
    assert _mode(kb.layout.sessions) == "700"


@pytest.mark.bats(
    "session_start.bats", "session-start still injects context when the session dir is unwritable"
)
def test_session_start_unwritable_session_dir(kb: KB, golden: Golden) -> None:
    blocked = kb.layout.root / "blocked"
    blocked.touch()
    env_file = kb.layout.root / "claude.env"
    env_file.touch()
    result = _start(kb, kb.session_id(), SESSION_DIR=str(blocked), CLAUDE_ENV_FILE=str(env_file))
    _check(kb, golden, result)
    golden.contract("env", kb.norm(env_file.read_text(encoding="utf-8")))


@pytest.mark.bats("session_start.bats", "session-start sets KNOWLEDGE_OBSERVE=1 by default")
@pytest.mark.bats("session_start.bats", "session-start respects KNOWLEDGE_OBSERVE=0")
@pytest.mark.parametrize("observe", [None, "1", "0"], ids=["unset", "enabled", "disabled"])
def test_session_start_env_file(kb: KB, golden: Golden, observe: str | None) -> None:
    env_file = kb.layout.root / "claude.env"
    env_file.touch()
    session_id = kb.session_id()
    result = _start(kb, session_id, KNOWLEDGE_OBSERVE=observe, CLAUDE_ENV_FILE=str(env_file))
    assert result.returncode == 0
    golden.contract(
        "env",
        kb.norm(env_file.read_text(encoding="utf-8")).replace(kb.session_prefix, "<SESSION>-"),
    )
    buffer = kb.layout.sessions / f"session-{session_id}.jsonl"
    golden.contract("buffer", "present\n" if buffer.exists() else "absent\n")


def test_session_start_without_session_id(kb: KB, golden: Golden) -> None:
    env_file = kb.layout.root / "claude.env"
    env_file.touch()
    result = kb.run(
        "adapters/claude/session-start", stdin="{}", env={"CLAUDE_ENV_FILE": str(env_file)}
    )
    assert result.returncode == 0
    # The adapter generates "<pid>-<epoch>" and creates that buffer.
    names = [p.name for p in kb.layout.sessions.iterdir()]
    assert len(names) == 1, names
    assert re.fullmatch(r"session-\d+-\d+\.jsonl", names[0]), names
    golden.contract(
        "env",
        re.sub(
            r"session-\d+-\d+",
            "session-<PID>-<EPOCH>",
            kb.norm(env_file.read_text(encoding="utf-8")),
        ),
    )


@pytest.mark.bats("session_start.bats", "session-start does not flush a symlinked orphan buffer")
def test_session_start_skips_symlinked_orphan(kb: KB) -> None:
    kb.layout.sessions.mkdir(mode=0o700, parents=True)
    secret = kb.layout.root / "secret.txt"
    secret.write_text('{"role":"user","message":"private"}\n', encoding="utf-8")
    link = kb.layout.sessions / f"session-{kb.session_id()}.jsonl"
    link.symlink_to(secret)
    two_hours_ago = time.time() - 7200
    os.utime(secret, (two_hours_ago, two_hours_ago))
    os.utime(link, (two_hours_ago, two_hours_ago), follow_symlinks=False)

    current = kb.session_id()
    result = _start(kb, current)

    assert result.returncode == 0
    assert (kb.layout.sessions / f"session-{current}.jsonl").is_file()
    pending = kb.layout.content / "observations" / "pending"
    assert not any("private" in p.read_text(encoding="utf-8") for p in pending.glob("*.md"))
    assert secret.read_text(encoding="utf-8") == '{"role":"user","message":"private"}\n'
    assert link.is_symlink()
