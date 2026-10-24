"""The session API: session-context, session-init, session-file, session-append,
and session-flush, called directly as the adapters call them."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.inspect import git as inspect_git
from kbtest.marks import xfail_bash
from kbtest.runner import KB, Result

TWO_HOURS = 7200


def _check(kb: KB, golden: Golden, result: Result, name: str = "") -> None:
    prefix = f"{name}-" if name else ""
    golden.contract(f"{prefix}result", f"exit {result.returncode}\n")
    golden.check(f"{prefix}stdout", kb.norm(result.out).replace(kb.session_prefix, "<SESSION>-"))
    golden.check(
        f"{prefix}stderr", kb.norm_err(result.err).replace(kb.session_prefix, "<SESSION>-")
    )


def _sessions(kb: KB) -> Path:
    kb.layout.sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
    return kb.layout.sessions


def _buffer(kb: KB, name: str = "buffer.jsonl", lines: list[dict[str, str]] | None = None) -> Path:
    path = _sessions(kb) / name
    path.write_text("".join(json.dumps(line) + "\n" for line in lines or []), encoding="utf-8")
    path.chmod(0o600)
    return path


def _transcript(n: int) -> list[dict[str, str]]:
    roles = ["user", "assistant"]
    return [{"role": roles[i % 2], "message": f"{'QA'[i % 2]}{i // 2 + 1}"} for i in range(n)]


def _pending(kb: KB) -> list[Path]:
    return sorted((kb.layout.content / "observations" / "pending").glob("*.md"))


def _mode(path: Path) -> str:
    return f"{path.stat().st_mode & 0o777:o}"


def _age(path: Path, seconds: int) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def _commit_count(kb: KB) -> int:
    return len(kb.commits())


def _append(kb: KB, path: Path, role: str, message: bytes) -> Result:
    return kb.run(
        "session-append", "--file", str(path), "--role", role, "--message", "-", stdin=message
    )


# session-context


@pytest.mark.bats("session_core.bats", "session-context outputs non-empty text")
@pytest.mark.bats("session_core.bats", "session-context includes topic areas heading")
@pytest.mark.bats("session_core.bats", "session-context includes state line")
@pytest.mark.bats("session_core.bats", "session-context includes articles from knowledge/")
@pytest.mark.bats("session_core.bats", "session-context includes pending observation count")
def test_session_context(kb: KB, golden: Golden) -> None:
    kb.create_article("infra/networking.md", "# Networking\n\n## DNS\n\nContent.")
    kb.create_observation("20260412T000000-0000aaaa.md", "Obs", "Body")
    result = kb.run("session-context")
    golden.contract("result", f"exit {result.returncode}\n")
    golden.contract("context", kb.context_facts(result.out))
    golden.check("stdout", kb.norm(kb.placeholder_instructions(result.out)))
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.bats("session_core.bats", "session-context includes content AGENTS.md when present")
def test_session_context_content_instructions(kb: KB, golden: Golden) -> None:
    (kb.layout.content / "AGENTS.md").write_text("# Project Rules\n", encoding="utf-8")
    result = kb.run("session-context")
    golden.contract("context", kb.context_facts(result.out))
    golden.check("stdout", kb.norm(kb.placeholder_instructions(result.out)))


# session-init and session-file


@pytest.mark.bats("session_core.bats", "session-init creates buffer file and prints path")
@pytest.mark.bats("session_core.bats", "session-init buffer has mode 600")
@pytest.mark.bats("session_core.bats", "session-init creates session dir with mode 700")
@pytest.mark.bats("session_core.bats", "session-init is idempotent")
def test_session_init(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    first = kb.run("session-init", "--session-id", session_id)
    second = kb.run("session-init", "--session-id", session_id)
    _check(kb, golden, first)
    assert second.out == first.out
    path = Path(first.out.strip())
    golden.contract(
        "modes",
        f"dir {_mode(kb.layout.sessions)}\nbuffer {_mode(path)} size {path.stat().st_size}\n",
    )
    golden.contract(
        "files",
        "\n".join(sorted(p.name.replace(session_id, "<ID>") for p in kb.layout.sessions.iterdir()))
        + "\n",
    )


@pytest.mark.bats(
    "session_core.bats", "session-init can persist initialization after a buffer sweep"
)
def test_persisted_initialization(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    path = Path(
        kb.run("session-init", "--session-id", session_id, "--persist-initialization").out.strip()
    )
    marker = kb.layout.sessions / f"session-{session_id}.initialized"
    golden.contract("marker", f"mode {_mode(marker)}\ncontent {marker.read_bytes()!r}\n")
    path.unlink()
    result = kb.run(
        "session-append",
        "--session-id",
        session_id,
        "--role",
        "user",
        "--message",
        "Recovered",
        env={"KNOWLEDGE_OBSERVE": None},
    )
    _check(kb, golden, result)
    golden.contract("buffer", kb.norm(path.read_text(encoding="utf-8")))


@pytest.mark.bats(
    "session_core.bats", "session-init initializes the session before sweeping orphans"
)
def test_init_before_sweep(kb: KB) -> None:
    current = kb.session_id()
    orphan = _buffer(kb, f"session-{kb.session_id()}.jsonl", _transcript(3))
    _age(orphan, TWO_HOURS)
    tree = kb.resolve_impl(kb.default_impl)
    with kb.hold_lock():
        process = subprocess.Popen(
            [
                str(kb.executable("session-init")),
                "--session-id",
                current,
                "--persist-initialization",
            ],
            env=kb.env(tree, {"KNOWLEDGE_LOCK_WAIT": "60"}),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            assert process.stdout is not None
            first_line = process.stdout.readline().decode()
            # The orphan flush is now blocked on the held lock.
            assert first_line.strip() == str(kb.layout.sessions / f"session-{current}.jsonl")
            assert (kb.layout.sessions / f"session-{current}.jsonl").is_file()
            assert (kb.layout.sessions / f"session-{current}.initialized").is_file()
            assert orphan.is_file(), "the sweep must not have finished"
        finally:
            process.kill()
            process.wait()


@pytest.mark.bats(
    "session_core.bats", "session-init prints only the buffer path when the sweep commits"
)
def test_init_sweep_output(kb: KB, golden: Golden) -> None:
    orphan = _buffer(kb, f"session-{kb.session_id()}.jsonl", _transcript(3))
    _age(orphan, TWO_HOURS)
    result = kb.run("session-init", "--session-id", kb.session_id())
    _check(kb, golden, result)
    assert not orphan.exists()
    golden.contract("log", kb.git("log", "-1", "--format=%s"))


def test_init_sweep_leaves_recent_and_symlinked_buffers(kb: KB, golden: Golden) -> None:
    recent = _buffer(kb, f"session-{kb.session_id()}.jsonl", _transcript(3))
    _age(recent, 60)
    target = kb.layout.root / "elsewhere.jsonl"
    target.write_text(json.dumps({"role": "user", "message": "private"}) + "\n", encoding="utf-8")
    link = _sessions(kb) / f"session-{kb.session_id()}.jsonl"
    link.symlink_to(target)
    _age(target, TWO_HOURS)
    os.utime(link, (time.time() - TWO_HOURS,) * 2, follow_symlinks=False)
    current = kb.session_id()
    result = kb.run("session-init", "--session-id", current)
    assert result.returncode == 0
    assert (kb.layout.sessions / f"session-{current}.jsonl").is_file()
    assert recent.is_file()
    assert link.is_symlink()
    assert _pending(kb) == []


@pytest.mark.bats(
    "session_core.bats", "session-flush clears persisted initialization after normal completion"
)
def test_flush_clears_marker(kb: KB) -> None:
    session_id = kb.session_id()
    path = Path(
        kb.run("session-init", "--session-id", session_id, "--persist-initialization").out.strip()
    )
    path.write_text("".join(json.dumps(m) + "\n" for m in _transcript(2)), encoding="utf-8")
    result = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"})
    assert result.returncode == 0
    assert not (kb.layout.sessions / f"session-{session_id}.initialized").exists()
    assert len(_pending(kb)) == 1


@pytest.mark.bats("session_core.bats", "session-init with no --session-id fails")
@pytest.mark.bats("session_core.bats", "session-init rejects a path traversal session ID")
@pytest.mark.parametrize(
    "args",
    [[], ["--session-id", "../escape"], ["--session-id", ""], ["--session-id", "a/b"], ["--bogus"]],
    ids=["missing", "traversal", "empty", "slash", "unknown"],
)
def test_init_rejects_bad_ids(kb: KB, golden: Golden, args: list[str]) -> None:
    _check(kb, golden, kb.run("session-init", *args))
    assert not kb.layout.root.joinpath("escape").exists()


@pytest.mark.bats("session_core.bats", "session-file resolves a session without creating it")
@pytest.mark.bats("session_core.bats", "session-file --create creates a private buffer")
@pytest.mark.parametrize("create", [False, True], ids=["resolve", "create"])
def test_session_file(kb: KB, golden: Golden, create: bool) -> None:
    session_id = kb.session_id()
    result = kb.run("session-file", "--session-id", session_id, *(["--create"] if create else []))
    _check(kb, golden, result)
    path = Path(result.out.strip())
    golden.contract("file", f"mode {_mode(path)}\n" if path.exists() else "absent\n")


@pytest.mark.parametrize("args", [[], ["--session-id", "../x"], ["--bogus"]])
def test_session_file_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    _check(kb, golden, kb.run("session-file", *args))


@pytest.mark.bats(
    "session_core.bats", "session-init tightens a pre-existing world-readable directory"
)
def test_init_tightens_directory(kb: KB) -> None:
    kb.layout.sessions.mkdir(parents=True)
    kb.layout.sessions.chmod(0o777)
    assert kb.run("session-init", "--session-id", kb.session_id()).returncode == 0
    assert _mode(kb.layout.sessions) == "700"


# session-append


@pytest.mark.bats("session_core.bats", "session-append adds a user message")
@pytest.mark.bats("session_core.bats", "session-append adds an assistant message")
@pytest.mark.bats("session_core.bats", "session-append accumulates multiple messages")
def test_append_messages(kb: KB, golden: Golden) -> None:
    path = _buffer(kb)
    results = [
        kb.run("session-append", "--file", str(path), "--role", role, "--message", text)
        for role, text in [("user", "Hello world"), ("assistant", "Hi there"), ("user", "Q2")]
    ]
    for result in results:
        assert (result.returncode, result.out, result.err) == (0, "", "")
    golden.contract("buffer", kb.norm(path.read_text(encoding="utf-8")))


@pytest.mark.bats(
    "session_core.bats", "session-append resolves a session ID through the shared API"
)
def test_append_by_session_id(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    kb.run("session-init", "--session-id", session_id)
    result = kb.run(
        "session-append",
        "--session-id",
        session_id,
        "--role",
        "user",
        "--message",
        "Resolved message",
    )
    assert result.returncode == 0
    golden.contract(
        "buffer",
        kb.norm((kb.layout.sessions / f"session-{session_id}.jsonl").read_text(encoding="utf-8")),
    )


@pytest.mark.bats("session_core.bats", "session-append to nonexistent file exits 0 (no-op)")
@pytest.mark.null_ok("the contract is a silent exit 0 that writes nothing")
def test_append_to_missing_file(kb: KB) -> None:
    missing = kb.layout.root / "missing" / "buffer.jsonl"
    result = kb.run("session-append", "--file", str(missing), "--role", "user", "--message", "Hi")
    assert (result.returncode, result.out, result.err) == (0, "", "")
    assert not missing.parent.exists()


@pytest.mark.bats(
    "session_core.bats", "session-append reports buffer creation failure when capture is enabled"
)
def test_append_creation_failure(kb: KB, golden: Golden) -> None:
    blocked = kb.layout.root / "blocked"
    blocked.write_text("retain this file\n", encoding="utf-8")
    result = kb.run(
        "session-append",
        "--session-id",
        kb.session_id(),
        "--role",
        "user",
        "--message",
        "durable evidence",
        env={"KNOWLEDGE_OBSERVE": "1", "SESSION_DIR": str(blocked)},
    )
    _check(kb, golden, result)
    assert blocked.read_text(encoding="utf-8") == "retain this file\n"


@pytest.mark.bats(
    "session_core.bats", "session-append skips an uninitialized session without creating a buffer"
)
@pytest.mark.null_ok("the contract is a silent exit 0 that creates no buffer")
def test_append_uninitialized_session(kb: KB) -> None:
    session_id = kb.session_id()
    result = kb.run(
        "session-append",
        "--session-id",
        session_id,
        "--role",
        "user",
        "--message",
        "uncaptured",
        env={"KNOWLEDGE_OBSERVE": None, "KNOWLEDGE_SESSION_FILE": None},
    )
    assert (result.returncode, result.out, result.err) == (0, "", "")
    assert not (kb.layout.sessions / f"session-{session_id}.jsonl").exists()


@pytest.mark.bats("session_core.bats", "session-append with missing --role fails")
@pytest.mark.bats("session_core.bats", "session-append with invalid role fails")
@pytest.mark.bats("session_core.bats", "session-append rejects repeated message options")
@pytest.mark.bats(
    "session_core.bats", "session-append rejects mixed stdin and argument message options"
)
@pytest.mark.parametrize(
    "args",
    [
        ["--message", "Hi"],
        ["--role", "system", "--message", "Hi"],
        ["--role", "user", "--message", "first", "--message", "second"],
        ["--role", "user", "--message", "-", "--message", "argument"],
        ["--role", "user", "--message", "Hi", "--session-id", "x"],
    ],
    ids=["no-role", "bad-role", "repeated", "mixed", "file-and-id"],
)
def test_append_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    path = _buffer(kb)
    _check(kb, golden, kb.run("session-append", "--file", str(path), *args, stdin="stdin"))
    assert path.read_bytes() == b""


@pytest.mark.parametrize(
    "args", [[], ["--role", "user", "--message", "Hi"]], ids=["nothing", "no-target"]
)
def test_append_requires_target(kb: KB, golden: Golden, args: list[str]) -> None:
    _check(kb, golden, kb.run("session-append", *args))


@pytest.mark.bats("session_core.bats", "session-append with missing --message is a no-op")
@pytest.mark.bats("session_core.bats", "session-append skips empty messages")
@pytest.mark.null_ok("an empty or missing message is a silent exit 0 that writes nothing")
@pytest.mark.parametrize(
    "args", [[], ["--message", ""], ["--message", "-"]], ids=["missing", "empty", "empty-stdin"]
)
def test_append_empty_message(kb: KB, args: list[str]) -> None:
    path = _buffer(kb)
    result = kb.run("session-append", "--file", str(path), "--role", "user", *args, stdin="")
    assert (result.returncode, result.out, result.err) == (0, "", "")
    assert path.read_bytes() == b""


@pytest.mark.bats("session_core.bats", "session-append reads a large multiline message from stdin")
@pytest.mark.parametrize("configuration", ["jq", "no-jq"])
def test_append_large_stdin(kb: KB, without_tools, configuration: str) -> None:
    if configuration == "no-jq":
        without_tools("jq")
    path = _buffer(kb)
    message = b"x" * 160000 + b"\n\n\n"
    assert _append(kb, path, "user", message).returncode == 0
    assert json.loads(path.read_bytes())["message"].encode() == message


@pytest.mark.bats(
    "session_core.bats", "session-append fallback escapes control characters without jq"
)
@pytest.mark.bats(
    "session_core.bats",
    "session-append fallback preserves Unicode and trailing newlines without jq",
)
@pytest.mark.parametrize(
    "message",
    ['line 1\nline 2\t"\\\x01', "café\n雪\n\n"],
    ids=["controls", "unicode-newlines"],
)
def test_append_without_jq(no_jq: KB, golden: Golden, message: str) -> None:
    path = _buffer(no_jq)
    result = no_jq.run(
        "session-append", "--file", str(path), "--role", "user", "--message", message
    )
    assert result.returncode == 0
    golden.contract("buffer", no_jq.norm(path.read_text(encoding="utf-8")))
    assert json.loads(path.read_bytes())["message"] == message


@pytest.mark.bats(
    "session_core.bats", "session-append returns failure when the buffer cannot be written"
)
def test_append_unwritable_buffer(kb: KB, golden: Golden) -> None:
    path = _buffer(kb)
    path.chmod(0o400)
    try:
        result = kb.run(
            "session-append", "--file", str(path), "--role", "user", "--message", "blocked"
        )
    finally:
        path.chmod(0o600)
    _check(kb, golden, result)
    assert path.read_bytes() == b""


# session-flush


@pytest.mark.bats("session_core.bats", "session-flush with >=3 messages creates observation")
@pytest.mark.bats("session_core.bats", "session-flush with <3 messages drops the file")
@pytest.mark.bats("session_core.bats", "session-flush with empty file removes it")
@pytest.mark.parametrize("count", [0, 2, 3, 4])
def test_flush_threshold(kb: KB, golden: Golden, count: int) -> None:
    path = _buffer(kb, lines=_transcript(count))
    result = kb.run("session-flush", str(path))
    _check(kb, golden, result)
    assert not path.exists()
    golden.contract(
        "observations",
        kb.norm("".join(f"## {p.name}\n{p.read_text()}" for p in _pending(kb)) or "none\n"),
    )
    # How the drop is logged is not a contract (A-004).
    golden.check("syslog", kb.layout.syslog.read_text() if kb.layout.syslog.exists() else "none\n")


@pytest.mark.parametrize("value", ["0", "5", "x"])
def test_flush_min_messages(kb: KB, golden: Golden, value: str) -> None:
    path = _buffer(kb, lines=_transcript(4))
    result = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": value})
    _check(kb, golden, result)
    golden.contract(
        "state",
        f"buffer {'kept' if path.exists() else 'removed'}\nobservations {len(_pending(kb))}\n",
    )


@pytest.mark.bats("session_core.bats", "session-flush with nonexistent file exits 0")
@pytest.mark.null_ok("the contract is a silent exit 0 for a missing buffer")
def test_flush_missing_file(kb: KB) -> None:
    result = kb.run("session-flush", str(kb.layout.root / "missing.jsonl"))
    assert (result.returncode, result.out, result.err) == (0, "", "")
    assert _pending(kb) == []


@xfail_bash("A-032: bash's session-flush exits 0 silently without a buffer argument")
def test_flush_without_argument(kb: KB, golden: Golden) -> None:
    result = kb.run("session-flush")
    assert result.err.strip(), "a usage error says why"
    _check(kb, golden, result)


@pytest.mark.bats("session_core.bats", "session-flush runs without KB_CONTENT_DIR")
@pytest.mark.bats("session_core.bats", "session-flush commits through the default content path")
def test_flush_default_content_path(kb: KB, golden: Golden) -> None:
    """Hooks run without KB_CONTENT_DIR; the default is <tooling root>/content."""
    kb.executable("session-flush")  # Skips until it is ported.
    tree = kb.resolve_impl(kb.default_impl)
    checkout = kb.layout.root / "checkout"
    shutil.copytree(
        tree.scripts_dir,
        checkout / tree.scripts_dir.name,
        symlinks=True,
        ignore=shutil.ignore_patterns("node_modules"),
    )
    for extra in ("kb", "pyproject.toml"):
        source = tree.kb_root / extra
        if source.is_dir():
            shutil.copytree(source, checkout / extra)
        elif source.is_file():
            shutil.copy(source, checkout / extra)
    shutil.move(str(kb.layout.content), checkout / "content")
    content = checkout / "content"
    path = _buffer(kb, lines=_transcript(3))
    flush = checkout / tree.scripts_dir.name / "session-flush"
    env = kb.env(tree, {"KB_CONTENT_DIR": None, "KNOWLEDGE_BASE": str(checkout)})
    completed = subprocess.run(
        [str(flush), str(path)], env=env, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert not path.exists()

    def git(*args: str) -> str:
        return inspect_git(content, *args, env=kb.git_env())

    golden.contract("log", git("log", "-1", "--format=%s"))
    golden.contract("status", git("status", "--porcelain"))
    assert len(git("ls-files", "observations/pending/*.md").split()) == 1


@pytest.mark.bats(
    "session_core.bats", "session-flush returns failure and keeps the buffer when observe fails"
)
def test_flush_observe_failure(kb: KB, golden: Golden) -> None:
    path = _buffer(kb, lines=_transcript(3))
    pending = kb.layout.content / "observations" / "pending"
    pending.chmod(0o555)
    try:
        failed = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"})
    finally:
        pending.chmod(0o755)
    _check(kb, golden, failed, "failed")
    assert path.is_file()
    retried = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"})
    assert retried.returncode == 0
    assert not path.exists()


def _rich_buffer(kb: KB) -> tuple[Path, bytes]:
    path = _buffer(kb)
    for role, text in [
        ("user", b"question line 1\nquestion line 2\n\n"),
        ("assistant", b"answer line 1\nanswer line 2\n\n"),
        ("user", b"follow-up\n\n"),
    ]:
        assert _append(kb, path, role, text).returncode == 0
    return path, path.read_bytes()


def _expected_body(buffer: bytes) -> str:
    records = [json.loads(line) for line in buffer.splitlines()]
    # Each record: a role heading, a blank line, the message, three newlines.
    return "\n" + "".join(f"### {r['role']}\n\n{r['message']}\n\n\n" for r in records) + "\n"


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("---\n", 2)[2]


@pytest.mark.bats(
    "session_core.bats", "session-flush retains evidence when the observation body copy fails"
)
def test_flush_keeps_buffer_when_observation_cannot_be_written(kb: KB) -> None:
    """A failed observation write keeps the buffer as evidence.

    The bats original stubs `cat` inside the Bash writer; an unwritable
    pending directory fails the same write without reaching into Bash.
    """
    if os.geteuid() == 0:
        pytest.skip("root writes regardless of mode")
    path, original = _rich_buffer(kb)
    pending = kb.layout.content / "observations" / "pending"
    pending.chmod(0o555)
    try:
        result = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"})
    finally:
        pending.chmod(0o755)
    assert result.returncode != 0 and result.err.strip()
    assert path.read_bytes() == original
    assert _pending(kb) == []
    assert kb.git("status", "--porcelain") == ""


@pytest.mark.bats("session_core.bats", "session-flush keeps the buffer when jq is unavailable")
def test_flush_without_jq(kb: KB, without_tools) -> None:
    """Without jq the buffer is never lost (A-043).

    Bash needs jq to parse the buffer, so it fails and keeps the buffer
    unchanged; Python needs no jq and flushes it. Either outcome is allowed.
    """
    path, original = _rich_buffer(kb)
    without_tools("jq")
    result = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"})
    if result.returncode == 0:
        assert not path.exists()
        (observation,) = _pending(kb)
        assert _body(observation) == _expected_body(original)
    else:
        assert result.err.strip(), "a failing flush says why"
        assert path.read_bytes() == original
        assert _pending(kb) == []
    assert list(kb.layout.tmp.iterdir()) == []


def test_flush_after_jq_returns(kb: KB) -> None:
    path, original = _rich_buffer(kb)
    assert kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"}).returncode == 0
    assert not path.exists()
    (observation,) = _pending(kb)
    assert _body(observation) == _expected_body(original)


@pytest.mark.bats(
    "session_core.bats", "session-flush retains the buffer when observe commit is rejected"
)
def test_flush_rejected_commit(kb: KB, golden: Golden) -> None:
    hook = kb.layout.content / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o700)
    path = _buffer(kb, lines=_transcript(3))
    rejected = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"})
    _check(kb, golden, rejected, "rejected")
    assert path.is_file()
    assert len(_pending(kb)) == 1
    hook.unlink()
    assert kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"}).returncode == 0
    assert not path.exists()
    assert len(_pending(kb)) == 2


# Bash prints these when a child it waits on dies by a signal; they are not
# session-flush's output.
SHELL_JOB_MESSAGES = {"Hangup", "Terminated", "Interrupt", "Killed"}


def _without_job_messages(text: str) -> str:
    return "".join(
        line for line in text.splitlines(keepends=True) if line.strip() not in SHELL_JOB_MESSAGES
    )


def _blocked_flush(kb: KB, path: Path, lock_wait: str) -> subprocess.Popen[bytes]:
    tree = kb.resolve_impl(kb.default_impl)
    process = subprocess.Popen(
        [str(kb.executable("session-flush")), str(path)],
        env=kb.env(tree, {"KNOWLEDGE_MIN_MESSAGES": "0", "KNOWLEDGE_LOCK_WAIT": lock_wait}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    time.sleep(1)
    return process


@pytest.mark.bats(
    "session_core.bats", "session-flush keeps the buffer when interrupted during parsing"
)
@pytest.mark.parametrize(
    "signum", [signal.SIGHUP, signal.SIGINT, signal.SIGTERM], ids=["HUP", "INT", "TERM"]
)
def test_flush_interrupted_while_blocked(kb: KB, golden: Golden, signum: int) -> None:
    """A signal to the hook's process group, as a terminal or host sends it."""
    path, original = _rich_buffer(kb)
    with kb.hold_lock():
        process = _blocked_flush(kb, path, "60")
        os.killpg(process.pid, signum)
        stdout, stderr = process.communicate(timeout=30)
        assert (kb.layout.content / ".observe.lock" / "pid").is_file(), "the held lock must survive"
    golden.contract("result", f"exit {process.returncode}\n")
    golden.check("stdout", kb.norm(stdout.decode()))
    golden.check("stderr", kb.norm_err(_without_job_messages(stderr.decode())))
    assert path.read_bytes() == original
    assert _pending(kb) == []
    assert list(kb.layout.tmp.iterdir()) == []


def test_flush_signal_to_process_only(kb: KB, golden: Golden) -> None:
    """A signal to session-flush alone, not its group, still keeps the buffer.

    Bash acts on it only after the blocked child gives up (A-031); when it
    takes effect is not part of the contract.
    """
    path, original = _rich_buffer(kb)
    with kb.hold_lock():
        process = _blocked_flush(kb, path, "3")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=30)
    golden.contract("result", f"exit {process.returncode}\n")
    golden.check("stdout", kb.norm(stdout.decode()))
    golden.check("stderr", kb.norm_err(_without_job_messages(stderr.decode())))
    assert path.read_bytes() == original
    assert _pending(kb) == []


@pytest.mark.bats(
    "session_core.bats", "session-flush keeps the buffer when observation commit is interrupted"
)
def test_flush_interrupted_during_commit(kb: KB) -> None:
    path, original = _rich_buffer(kb)
    hook = kb.layout.content / ".git" / "hooks" / "pre-commit"
    hook_pid = kb.layout.root / "hook.pid"
    hook.write_text(
        f"#!/bin/sh\necho $$ > '{hook_pid}'\nwhile :; do sleep 1; done\n", encoding="utf-8"
    )
    hook.chmod(0o700)
    tree = kb.resolve_impl(kb.default_impl)
    process = subprocess.Popen(
        [str(kb.executable("session-flush")), str(path)],
        env=kb.env(tree, {"KNOWLEDGE_MIN_MESSAGES": "0"}),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not hook_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert hook_pid.exists(), "the commit never reached the hook"
        process.terminate()
        os.kill(int(hook_pid.read_text().strip()), signal.SIGTERM)
        process.wait(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert process.returncode != 0
    assert path.read_bytes() == original
    assert len(_pending(kb)) == 1
    assert _commit_count(kb) == 1
    hook.unlink()
    assert kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"}).returncode == 0
    assert not path.exists()
    observations = _pending(kb)
    assert len(observations) == 2
    assert _commit_count(kb) == 2
    for observation in observations:
        assert _body(observation) == _expected_body(original)


@pytest.mark.bats(
    "session_core.bats", "session-flush streams a large transcript and preserves its source"
)
def test_flush_large_transcript(kb: KB) -> None:
    path = _buffer(kb)
    message = b"large-evidence-" * 160000 + b"\n\n\n"
    assert _append(kb, path, "user", message).returncode == 0
    assert kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": "0"}).returncode == 0
    assert not path.exists()
    (observation,) = _pending(kb)
    body = _body(observation).encode()
    prefix = b"\n### user\n\n"
    assert body[len(prefix) : len(prefix) + len(message)] == message


@pytest.mark.bats("session_core.bats", "session-flush keeps malformed JSONL for recovery")
@pytest.mark.bats(
    "session_core.bats",
    "session-flush validates malformed JSON before applying the message threshold",
)
@pytest.mark.parametrize("min_messages", ["0", None], ids=["no-threshold", "default-threshold"])
def test_flush_malformed_buffer(kb: KB, golden: Golden, min_messages: str | None) -> None:
    path = _buffer(kb)
    path.write_text('{"role":"user","message":"valid"}\nnot json\n', encoding="utf-8")
    result = kb.run("session-flush", str(path), env={"KNOWLEDGE_MIN_MESSAGES": min_messages})
    _check(kb, golden, result)
    assert path.read_text(encoding="utf-8") == '{"role":"user","message":"valid"}\nnot json\n'
    assert _pending(kb) == []


def test_flush_preserve_initialization(kb: KB, golden: Golden) -> None:
    """The orphan sweep flushes with --preserve-initialization: the marker stays."""
    session_id = kb.session_id()
    path = Path(
        kb.run("session-init", "--session-id", session_id, "--persist-initialization").out.strip()
    )
    path.write_text("".join(json.dumps(m) + "\n" for m in _transcript(3)), encoding="utf-8")
    result = kb.run("session-flush", "--preserve-initialization", str(path))
    _check(kb, golden, result)
    assert not path.exists()
    assert (kb.layout.sessions / f"session-{session_id}.initialized").is_file()
    assert len(_pending(kb)) == 1
