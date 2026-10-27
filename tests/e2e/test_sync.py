"""End-to-end acceptance tests for `kb sync`.

Each test is marked xfail(strict=True) until Step 5 registers the command. The
tests use hand-written transcript fixtures and isolated content repositories.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from .harness import FIXTURE_TRANSCRIPTS, Kb, run_git

HOST = socket.gethostname().split(".", 1)[0]
SINCE = "2026-10-24T00:00:00Z"
SECRET = "fixture-only-secret-92841"
HOLD_FLOCK = (
    "import fcntl, os, sys\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('locked', flush=True)\n"
    "sys.stdin.read()\n"
)


def config(kb: Kb, harvest_since: str | None = SINCE) -> Path:
    """Write an isolated kb config with or without transcript harvesting enabled."""
    path = kb.config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'content = "{kb.content}"']
    if harvest_since is not None:
        lines.append(f"harvest_since = {harvest_since}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def install(kb: Kb, app: str, *relative_paths: str) -> list[Path]:
    """Copy selected hand-written fixtures into the isolated host stores."""
    destination_root = kb.claude_config_dir if app == "claude" else kb.codex_home
    copied: list[Path] = []
    for relative in relative_paths:
        source = FIXTURE_TRANSCRIPTS / app / relative
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        set_mtime(destination, "2026-10-25T00:00:00Z")
        copied.append(destination)
    return copied


def install_text(kb: Kb, app: str, relative: str, text: str) -> Path:
    """Write a generated transcript under the isolated host store."""
    root = kb.claude_config_dir if app == "claude" else kb.codex_home
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    set_mtime(path, "2026-10-25T00:00:00Z")
    return path


def set_mtime(path: Path, timestamp: str) -> None:
    """Set a fixture's mtime to a fixed UTC instant for readiness checks."""
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    os.utime(path, (value, value))


def pending(kb: Kb) -> list[Path]:
    """Return pending transcript observations in name order."""
    directory = kb.content / "observations" / "pending"
    if not directory.exists():
        return []
    return [
        path
        for path in sorted(directory.glob("*.md"))
        if field(path.read_text(encoding="utf-8"), "session") is not None
    ]


def observation_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def field(text: str, name: str) -> str | None:
    """Read one scalar from the transcript observation front matter."""
    prefix = f"{name}: "
    for line in text.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :]
            if len(value) >= 2 and value[0] == value[-1] == '"':
                return value[1:-1]
            return value
    return None


def observation_for(kb: Kb, session: str, part: int = 1) -> Path:
    """Find an observation by its transcript session and part fields."""
    matches = []
    for path in pending(kb):
        text = observation_text(path)
        if field(text, "session") == session and field(text, "part") == str(part):
            matches.append(path)
    assert len(matches) == 1, (session, part, [path.name for path in matches])
    return matches[0]


def remote_head(kb: Kb) -> str:
    assert kb.origin is not None
    return run_git(kb.origin, "rev-parse", "refs/heads/main").strip()


def clone_remote(kb: Kb, destination: Path) -> Path:
    assert kb.origin is not None
    run_git(destination.parent, "clone", "-q", str(kb.origin), str(destination))
    return destination


def append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def transcript_record(
    message_id: str | None,
    role: str,
    text: str,
    timestamp: str,
) -> str:
    """Build a small Claude JSONL record for generated edge-case transcripts."""
    identifier = f',"uuid":"{message_id}"' if message_id is not None else ""
    return (
        f'{{"type":"{role}"{identifier},"timestamp":"{timestamp}",'
        f'"message":{{"role":"{role}","content":"{text}"}}}}\n'
    )


def count_text(paths: list[Path], text: str) -> int:
    total = 0
    for path in paths:
        contents = observation_text(path)
        body = contents.split("\n---\n", 1)[1] if "\n---\n" in contents else contents
        total += body.count(text)
    return total


def claude_message(
    session: str,
    message_id: str,
    role: str,
    text: str,
    timestamp: str,
) -> str:
    """Build one Claude message record with the fixture's measured shape."""
    content = f'"{text}"' if role == "user" else f'[{{"type":"text","text":"{text}"}}]'
    return (
        f'{{"type":"{role}","uuid":"{message_id}","sessionId":"{session}",'
        '"cwd":"/fixture/claude-project",'
        f'"timestamp":"{timestamp}","message":{{"role":"{role}","content":{content}}}}}\n'
    )


def git_refs(kb: Kb) -> str:
    return run_git(kb.content, "for-each-ref", "--format=%(refname) %(objectname)")


def start_lock_process(kb: Kb, lock: str) -> subprocess.Popen[str]:
    """Hold the named cross-process lock until the caller closes stdin."""
    if lock == "kernel":
        path = kb.content / ".git" / "kb.lock"
        script = HOLD_FLOCK
    else:
        path = kb.content / ".observe.lock"
        script = (
            "import os, pathlib, sys\n"
            "path = pathlib.Path(sys.argv[1])\n"
            "path.mkdir()\n"
            "(path / 'pid').write_text(f'{os.getpid()}\\n')\n"
            "print('locked', flush=True)\n"
            "sys.stdin.read()\n"
        )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=kb.environment({}),
    )
    assert process.stdout is not None
    assert process.stdout.readline() == "locked\n"
    return process


def seed_session_observation(kb: Kb, session: str, host: str = HOST) -> Path:
    """Write an interrupted-run marker under the isolated content repository."""
    path = kb.content / "observations" / "pending" / f"20261026T110000-{session[:8]}.md"
    path.write_text(
        "---\n"
        'title: "Interrupted transcript"\n'
        "source: session-transcript\n"
        f'host: "{host}"\n'
        'app: "claude-code"\n'
        f'session: "{session}"\n'
        "part: 1\n"
        'first_message: "stale-first"\n'
        'last_message: "stale-last"\n'
        "started: 2026-10-25T08:00:00Z\n"
        "ended: 2026-10-25T08:01:00Z\n"
        "created: 2026-10-26T11:00:00Z\n"
        "---\n\nInterrupted content.\n",
        encoding="utf-8",
    )
    return path


def test_harvest_off_only_pulls_remote_changes(remote_git_kb: Kb, tmp_path: Path) -> None:
    config(remote_git_kb, harvest_since=None)
    remote_work = clone_remote(remote_git_kb, tmp_path / "remote-work")
    (remote_work / "knowledge" / "remote-change.md").write_text(
        "# Remote change\n\nPulled by sync.\n", encoding="utf-8"
    )
    run_git(remote_work, "add", "knowledge/remote-change.md")
    run_git(remote_work, "commit", "-q", "-m", "Add remote change")
    run_git(remote_work, "push", "-q", "origin", "main")
    before = remote_git_kb.git("rev-parse", "HEAD").strip()

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert pending(remote_git_kb) == []
    assert remote_git_kb.git("rev-parse", "HEAD").strip() != before
    assert remote_git_kb.git("show", "HEAD:knowledge/remote-change.md").startswith("# Remote")
    assert result.stderr == ""


def test_harvest_commits_all_ready_sessions_once_and_pushes(remote_git_kb: Kb) -> None:
    install(
        remote_git_kb,
        "claude",
        "projects/demo/main.jsonl",
        "projects/demo/heading.jsonl",
    )
    config(remote_git_kb)
    commits_before = int(remote_git_kb.git("rev-list", "--count", "HEAD"))

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert len(pending(remote_git_kb)) == 2
    assert remote_git_kb.git("log", "-1", "--format=%s") == "Observe: 2 session transcript(s)\n"
    assert int(remote_git_kb.git("rev-list", "--count", "HEAD")) == commits_before + 1
    assert remote_head(remote_git_kb) == remote_git_kb.git("rev-parse", "HEAD").strip()
    assert "Harvested: 2 session transcript(s)" in result.stdout
    assert "Pushed: 1 commit(s)" in result.stdout


def test_observation_front_matter_covers_main_subagent_and_fork(remote_git_kb: Kb) -> None:
    install(
        remote_git_kb,
        "claude",
        "projects/demo/main.jsonl",
        "projects/demo/subagent-parent.jsonl",
        "projects/demo/subagent-parent/subagents/agent-helper.jsonl",
        "projects/demo/fork-origin.jsonl",
        "projects/demo/fork-child.jsonl",
    )
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    main = observation_text(observation_for(remote_git_kb, "main"))
    child = observation_text(observation_for(remote_git_kb, "agent-helper"))
    assert field(main, "app") == "claude-code"
    assert field(main, "project") == "/fixture/claude-project"
    assert field(main, "host") == HOST
    assert field(main, "first_message") == "main-user-1"
    assert field(main, "last_message") == "main-assistant-3"
    assert field(main, "part") == "1"
    assert field(child, "parent_session") == "subagent-parent"
    fork_observations = [
        observation_text(observation_for(remote_git_kb, session))
        for session in ("fork-origin", "fork-child")
    ]
    assert sum('forked_from: "' in text for text in fork_observations) == 1


def test_codex_main_and_subagent_use_measured_session_identity(remote_git_kb: Kb) -> None:
    install(
        remote_git_kb,
        "codex",
        "sessions/2026/10/25/rollout-codex-main.jsonl",
        "sessions/2026/10/25/rollout-codex-agent.jsonl",
    )
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    main = observation_text(observation_for(remote_git_kb, "codex-main"))
    agent = observation_text(observation_for(remote_git_kb, "codex-agent"))
    assert field(main, "app") == "codex"
    assert field(main, "project") == "/fixture/project"
    assert field(main, "first_message") == "codex-user-1"
    assert "Summarize this Codex fixture." in main
    assert "<environment_context>" not in main
    assert "fixture command" in main
    assert field(agent, "parent_session") == "codex-main"


def test_read_second_message_keeps_heading_and_tilde_fence_as_text(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/heading.jsonl")
    config(remote_git_kb)
    result = remote_git_kb("sync")
    assert result.returncode == 0, result.stderr
    path = observation_for(remote_git_kb, "heading")

    read = remote_git_kb("read", f"observations/pending/{path.name}#2")

    assert read.returncode == 0, read.stderr
    assert "## Heading inside a message" in read.stdout
    assert "~~~~sh" in read.stdout
    assert "#3 |" not in read.stdout


def test_tool_results_thinking_and_system_reminders_are_removed(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl", "projects/demo/filtered.jsonl")
    config(remote_git_kb)
    result = remote_git_kb("sync")
    assert result.returncode == 0, result.stderr
    text = "\n".join(observation_text(path) for path in pending(remote_git_kb))

    assert "Fixture tool output must not be retained." not in text
    assert "Private reasoning must not be retained." not in text
    assert "Do not retain this reasoning." not in text
    assert "Drop this injected span." not in text
    assert "<system-reminder>" not in text
    assert "Keep this request." in text
    assert "Keep this ending." in text


def test_secret_is_redacted_and_never_enters_the_repository_or_output(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/secret.jsonl")
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    text = observation_text(observation_for(remote_git_kb, "secret"))
    assert "[redacted: Secret Keyword]" in text
    assert SECRET not in text
    assert 'title: "Session transcript (2 messages)"' in text
    assert SECRET not in result.stdout + result.stderr
    assert run_git(remote_git_kb.content, "log", "--all", "--format=%H", f"-S{SECRET}") == ""
    path = observation_for(remote_git_kb, "secret")
    read = remote_git_kb("read", f"observations/pending/{path.name}#1")
    assert read.returncode == 0, read.stderr
    assert "[redacted: Secret Keyword]" in read.stdout


def test_second_run_is_empty_and_appended_messages_become_part_two(remote_git_kb: Kb) -> None:
    (transcript,) = install(remote_git_kb, "claude", "projects/demo/resumed.jsonl")
    config(remote_git_kb)
    first = remote_git_kb("sync")
    assert first.returncode == 0, first.stderr
    first_count = len(pending(remote_git_kb))

    second = remote_git_kb("sync")
    assert second.returncode == 0, second.stderr
    assert len(pending(remote_git_kb)) == first_count

    append_text(
        transcript,
        transcript_record("resumed-user-3", "user", "A third day.", "2026-10-26T08:00:00Z"),
    )
    set_mtime(transcript, "2026-10-26T08:00:00Z")
    third = remote_git_kb("sync")

    assert third.returncode == 0, third.stderr
    part_one = observation_text(observation_for(remote_git_kb, "resumed", 1))
    part_two = observation_text(observation_for(remote_git_kb, "resumed", 2))
    assert field(part_one, "last_message") == "resumed-assistant-2"
    assert field(part_two, "first_message") == "resumed-user-3"


def test_recent_message_is_waiting_for_idle_time(remote_git_kb: Kb) -> None:
    (transcript,) = install(remote_git_kb, "claude", "projects/demo/filtered.jsonl")
    append_text(
        transcript,
        transcript_record("recent-answer", "assistant", "Still active.", "2026-10-26T11:30:00Z"),
    )
    set_mtime(transcript, "2026-10-26T11:30:00Z")
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert pending(remote_git_kb) == []


def test_harvest_since_excludes_older_messages(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/resumed.jsonl")
    config(remote_git_kb, "2026-10-25T00:00:00Z")

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    text = observation_text(observation_for(remote_git_kb, "resumed"))
    assert field(text, "first_message") == "resumed-user-2"
    assert "Start the resumed fixture." not in text


def test_first_run_harvests_only_the_oldest_fifty_ready_sessions(remote_git_kb: Kb) -> None:
    root = remote_git_kb.claude_config_dir / "projects" / "generated"
    root.mkdir(parents=True)
    start = datetime.fromisoformat("2026-10-25T00:00:00+00:00")
    for number in range(60):
        session = f"session-{number:03d}"
        when = start.replace(minute=number).isoformat().replace("+00:00", "Z")
        (root / f"{session}.jsonl").write_text(
            transcript_record(f"{session}-user", "user", f"Message {number}.", when),
            encoding="utf-8",
        )
        set_mtime(root / f"{session}.jsonl", "2026-10-25T00:00:00Z")
    config(remote_git_kb, "2026-10-01T00:00:00Z")

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert len(pending(remote_git_kb)) == 50
    assert observation_for(remote_git_kb, "session-000").exists()
    assert observation_for(remote_git_kb, "session-049").exists()
    assert not any(
        field(observation_text(path), "session") == "session-050" for path in pending(remote_git_kb)
    )


def test_reclone_reconstructs_harvest_state_from_committed_observations(
    remote_git_kb: Kb, tmp_path: Path
) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl")
    config(remote_git_kb)
    first = remote_git_kb("sync")
    assert first.returncode == 0, first.stderr
    cloned_content = clone_remote(remote_git_kb, tmp_path / "fresh-clone")
    cloned_kb = replace(remote_git_kb, content=cloned_content)
    config(cloned_kb)

    second = cloned_kb("sync")

    assert second.returncode == 0, second.stderr
    assert len(pending(cloned_kb)) == 1
    assert "Harvested: 0 session transcript(s)" in second.stdout
    assert cloned_kb.git("rev-parse", "HEAD").strip() == remote_head(cloned_kb)


def test_no_push_keeps_harvest_commit_local(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl")
    config(remote_git_kb)
    before = remote_head(remote_git_kb)

    result = remote_git_kb("sync", "--no-push")

    assert result.returncode == 0, result.stderr
    assert remote_git_kb.git("rev-parse", "HEAD").strip() != before
    assert remote_head(remote_git_kb) == before
    assert "Pushed:" not in result.stdout


def test_dry_run_leaves_repository_state_and_temporary_directory_unchanged(
    remote_git_kb: Kb,
) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl")
    config(remote_git_kb)
    before_status = remote_git_kb.git("status", "--porcelain", "--untracked-files=all")
    before_head = remote_git_kb.git("rev-parse", "HEAD")
    before_refs = git_refs(remote_git_kb)
    git_dir = Path(remote_git_kb.git("rev-parse", "--git-common-dir").strip())
    if not git_dir.is_absolute():
        git_dir = (remote_git_kb.content / git_dir).resolve()
    temporary = git_dir / "kb-tmp"
    assert not temporary.exists()

    result = remote_git_kb("sync", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "claude-code main part 1:" in result.stdout
    assert remote_git_kb.git("status", "--porcelain", "--untracked-files=all") == before_status
    assert remote_git_kb.git("rev-parse", "HEAD") == before_head
    assert git_refs(remote_git_kb) == before_refs
    assert not temporary.exists()
    assert pending(remote_git_kb) == []


def test_status_fetches_without_moving_branch_or_working_tree(
    remote_git_kb: Kb, tmp_path: Path
) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl", "projects/demo/filtered.jsonl")
    config(remote_git_kb)
    remote_work = clone_remote(remote_git_kb, tmp_path / "remote-work")
    remote_file = remote_work / "knowledge" / "remote-status.md"
    remote_file.write_text("# Remote status\n", encoding="utf-8")
    run_git(remote_work, "add", "knowledge/remote-status.md")
    run_git(remote_work, "commit", "-q", "-m", "Add remote status file")
    run_git(remote_work, "push", "-q", "origin", "main")
    before_head = remote_git_kb.git("rev-parse", "HEAD")
    before_refs = git_refs(remote_git_kb)
    before_status = remote_git_kb.git("status", "--porcelain", "--untracked-files=all")

    result = remote_git_kb("sync", "--status")

    assert result.returncode == 0, result.stderr
    assert remote_git_kb.git("rev-parse", "HEAD") == before_head
    assert remote_git_kb.git("status", "--porcelain", "--untracked-files=all") == before_status
    before_ref_map = dict(line.split(" ", 1) for line in before_refs.splitlines())
    after_refs = git_refs(remote_git_kb)
    after_ref_map = dict(line.split(" ", 1) for line in after_refs.splitlines())
    assert set(after_ref_map) == set(before_ref_map)
    changed_refs = {name for name in after_ref_map if after_ref_map[name] != before_ref_map[name]}
    assert changed_refs == {"refs/remotes/origin/main"}
    assert pending(remote_git_kb) == []
    assert "ready" in result.stdout.lower()
    assert "waiting" in result.stdout.lower()


def test_rebase_conflict_is_aborted_and_keeps_local_commit(
    remote_git_kb: Kb, tmp_path: Path
) -> None:
    tracked = remote_git_kb.content / "knowledge" / "infra" / "nas.md"
    append_text(tracked, "\nLocal conflicting edit.\n")
    run_git(remote_git_kb.content, "add", "knowledge/infra/nas.md")
    run_git(remote_git_kb.content, "commit", "-q", "-m", "Make local conflicting edit")
    local_head = remote_git_kb.git("rev-parse", "HEAD").strip()
    before_status = remote_git_kb.git("status", "--porcelain", "--untracked-files=all")
    remote_work = clone_remote(remote_git_kb, tmp_path / "remote-work")
    remote_file = remote_work / "knowledge" / "infra" / "nas.md"
    append_text(remote_file, "\nRemote conflicting edit.\n")
    run_git(remote_work, "add", "knowledge/infra/nas.md")
    run_git(remote_work, "commit", "-q", "-m", "Make remote conflicting edit")
    run_git(remote_work, "push", "-q", "origin", "main")

    result = remote_git_kb("sync")

    assert result.returncode == 1
    assert "sync: rebase onto origin/main failed; local commits kept" in result.stderr
    assert remote_git_kb.git("rev-parse", "HEAD").strip() == local_head
    assert remote_git_kb.git("status", "--porcelain", "--untracked-files=all") == before_status
    assert not (remote_git_kb.content / ".git" / "rebase-merge").exists()
    assert not (remote_git_kb.content / ".git" / "rebase-apply").exists()


def test_dirty_worktree_keeps_harvest_commit_and_skips_pull_and_push(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl")
    config(remote_git_kb)
    dirty = remote_git_kb.content / "unrelated-local-file.txt"
    dirty.write_text("Keep this local change.\n", encoding="utf-8")
    before_remote = remote_head(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert len(pending(remote_git_kb)) == 1
    assert dirty.read_text(encoding="utf-8") == "Keep this local change.\n"
    assert remote_head(remote_git_kb) == before_remote
    assert "sync: uncommitted changes" in result.stderr
    assert "Pulled:" not in result.stdout
    assert "Pushed:" not in result.stdout


def test_original_harvested_first_owns_fork_prefix_in_one_run(remote_git_kb: Kb) -> None:
    shared = claude_message(
        "a-original", "shared-opening", "user", "One shared opening.", "2026-10-25T09:00:00Z"
    )
    install_text(
        remote_git_kb,
        "claude",
        "projects/demo/a-original.jsonl",
        shared
        + claude_message(
            "a-original", "original-answer", "assistant", "Original answer.", "2026-10-25T09:01:00Z"
        ),
    )
    install_text(
        remote_git_kb,
        "claude",
        "projects/demo/z-fork.jsonl",
        shared.replace('"a-original"', '"z-fork"', 1)
        + claude_message(
            "z-fork", "fork-answer", "assistant", "Fork answer.", "2026-10-25T09:02:00Z"
        ),
    )
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    original = observation_text(observation_for(remote_git_kb, "a-original"))
    fork = observation_text(observation_for(remote_git_kb, "z-fork"))
    assert count_text(pending(remote_git_kb), "One shared opening.") == 1
    assert "One shared opening." in original
    assert "One shared opening." not in fork
    assert field(fork, "forked_from") == "a-original"


def test_fork_harvested_before_original_owns_prefix_across_runs(remote_git_kb: Kb) -> None:
    shared = claude_message(
        "z-fork", "shared-opening", "user", "One shared opening.", "2026-10-25T09:00:00Z"
    )
    install_text(
        remote_git_kb,
        "claude",
        "projects/demo/z-fork.jsonl",
        shared
        + claude_message(
            "z-fork", "fork-answer", "assistant", "Fork answer.", "2026-10-25T09:02:00Z"
        ),
    )
    config(remote_git_kb)
    first = remote_git_kb("sync")
    assert first.returncode == 0, first.stderr
    install_text(
        remote_git_kb,
        "claude",
        "projects/demo/a-original.jsonl",
        shared.replace('"z-fork"', '"a-original"', 1)
        + claude_message(
            "a-original", "original-answer", "assistant", "Original answer.", "2026-10-25T09:01:00Z"
        ),
    )

    second = remote_git_kb("sync")

    assert second.returncode == 0, second.stderr
    original = observation_text(observation_for(remote_git_kb, "a-original"))
    assert count_text(pending(remote_git_kb), "One shared opening.") == 1
    assert "Original answer." in original
    assert field(original, "forked_from") == "z-fork"


def test_two_forks_share_each_prefix_message_exactly_once(remote_git_kb: Kb) -> None:
    shared = claude_message(
        "a-fork", "shared-opening", "user", "One shared opening.", "2026-10-25T09:00:00Z"
    )
    for session in ("a-fork", "b-fork"):
        install_text(
            remote_git_kb,
            "claude",
            f"projects/demo/{session}.jsonl",
            shared.replace('"a-fork"', f'"{session}"', 1)
            + claude_message(
                session,
                f"{session}-answer",
                "assistant",
                f"Answer from {session}.",
                "2026-10-25T09:02:00Z",
            ),
        )
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    first = observation_text(observation_for(remote_git_kb, "a-fork"))
    second = observation_text(observation_for(remote_git_kb, "b-fork"))
    assert count_text(pending(remote_git_kb), "One shared opening.") == 1
    assert field(first, "forked_from") is None
    assert field(second, "forked_from") == "a-fork"


def test_fork_keeps_shared_prefix_when_original_file_is_missing(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/fork-child.jsonl")
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    fork = observation_text(observation_for(remote_git_kb, "fork-child"))
    assert "Shared opening message." in fork
    assert field(fork, "forked_from") is None


@pytest.mark.parametrize("lock", ["kernel", "legacy"])
@pytest.mark.parametrize("mode", ["sync", "status"])
def test_held_write_lock_times_out(lock: str, mode: str, remote_git_kb: Kb) -> None:
    config(remote_git_kb, harvest_since=None)
    process = start_lock_process(remote_git_kb, lock)
    try:
        args = ("sync",) if mode == "sync" else ("sync", "--status")
        result = remote_git_kb(*args, env={"KB_LOCK_WAIT": "1"})
    finally:
        assert process.stdin is not None
        process.stdin.close()
        process.wait(timeout=10)

    assert result.returncode == 1
    assert "sync:" in result.stderr
    assert "lock" in result.stderr.lower()


def test_incomplete_final_line_makes_the_session_not_ready(remote_git_kb: Kb) -> None:
    path = install(remote_git_kb, "claude", "projects/demo/main.jsonl")[0]
    append_text(path, '{"type":"user","uuid":"unfinished"')
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert pending(remote_git_kb) == []


def test_malformed_interior_line_is_skipped_and_counted(remote_git_kb: Kb) -> None:
    valid = claude_message("malformed", "first", "user", "Keep first.", "2026-10-25T08:00:00Z")
    valid += '{"type":broken json}\n'
    valid += claude_message(
        "malformed", "second", "assistant", "Keep second.", "2026-10-25T08:01:00Z"
    )
    install_text(remote_git_kb, "claude", "projects/demo/malformed.jsonl", valid)
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    text = observation_text(observation_for(remote_git_kb, "malformed"))
    assert "Keep first." in text
    assert "Keep second." in text
    assert "1 malformed" in result.stdout.lower()


def test_missing_id_gets_a_stable_synthetic_id(remote_git_kb: Kb) -> None:
    record = (
        '{"type":"user","sessionId":"synthetic","timestamp":"2026-10-25T08:00:00Z",'
        '"message":{"role":"user","content":"Stable fixture text."}}\n'
    )
    install_text(remote_git_kb, "claude", "projects/demo/synthetic.jsonl", record)
    config(remote_git_kb)
    first = remote_git_kb("sync")
    assert first.returncode == 0, first.stderr
    first_observation = observation_text(observation_for(remote_git_kb, "synthetic"))
    synthetic_id = field(first_observation, "first_message")
    assert synthetic_id is not None
    assert len(synthetic_id) == 16
    assert all(character in "0123456789abcdef" for character in synthetic_id)

    second = remote_git_kb("sync")

    assert second.returncode == 0, second.stderr
    assert len(pending(remote_git_kb)) == 1
    assert (
        field(observation_text(observation_for(remote_git_kb, "synthetic")), "first_message")
        == synthetic_id
    )


def test_duplicate_message_id_keeps_first_occurrence(remote_git_kb: Kb) -> None:
    records = claude_message(
        "duplicate", "same-id", "user", "Keep the first copy.", "2026-10-25T08:00:00Z"
    )
    records += claude_message(
        "duplicate", "same-id", "assistant", "Drop the later duplicate.", "2026-10-25T08:01:00Z"
    )
    install_text(remote_git_kb, "claude", "projects/demo/duplicate.jsonl", records)
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    text = observation_text(observation_for(remote_git_kb, "duplicate"))
    assert "Keep the first copy." in text
    assert "Drop the later duplicate." not in text
    assert "1 duplicate" in result.stdout.lower()


def test_missing_transcript_roots_are_empty_stores(remote_git_kb: Kb) -> None:
    shutil.rmtree(remote_git_kb.claude_config_dir)
    shutil.rmtree(remote_git_kb.codex_home)
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert pending(remote_git_kb) == []
    assert "Harvested: 0 session transcript(s)" in result.stdout


def test_rewritten_transcript_continues_after_saved_end_and_warns(remote_git_kb: Kb) -> None:
    transcript = install(remote_git_kb, "claude", "projects/demo/resumed.jsonl")[0]
    config(remote_git_kb)
    first = remote_git_kb("sync")
    assert first.returncode == 0, first.stderr
    transcript.write_text(
        claude_message(
            "resumed", "rewritten-message", "user", "After the saved end.", "2026-10-25T09:00:00Z"
        ),
        encoding="utf-8",
    )
    set_mtime(transcript, "2026-10-25T09:00:00Z")

    second = remote_git_kb("sync")

    assert second.returncode == 0, second.stderr
    text = observation_text(observation_for(remote_git_kb, "resumed", 2))
    assert "After the saved end." in text
    assert "warning" in second.stderr.lower()
    assert "resumed" in second.stderr


def test_recent_unkept_record_prevents_harvesting_old_messages(remote_git_kb: Kb) -> None:
    transcript = install(remote_git_kb, "claude", "projects/demo/main.jsonl")[0]
    append_text(
        transcript,
        '{"type":"user","uuid":"recent-tool-result","timestamp":"2026-10-26T11:30:00Z",'
        '"message":{"role":"user","content":[{"type":"tool_result",'
        '"content":"Recent tool result."}]}}\n',
    )
    set_mtime(transcript, "2026-10-25T00:00:00Z")
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert pending(remote_git_kb) == []


def test_empty_transcript_stores_harvest_nothing(remote_git_kb: Kb) -> None:
    config(remote_git_kb)

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert pending(remote_git_kb) == []
    assert "Harvested: 0 session transcript(s)" in result.stdout


@pytest.mark.parametrize("staged", [False, True])
def test_recovery_removes_this_hosts_uncommitted_transcript_observation(
    staged: bool, remote_git_kb: Kb
) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl")
    config(remote_git_kb)
    interrupted = seed_session_observation(remote_git_kb, "main")
    if staged:
        run_git(remote_git_kb.content, "add", str(interrupted.relative_to(remote_git_kb.content)))

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert not interrupted.exists()
    assert len(pending(remote_git_kb)) == 1
    assert "Summarize the fixture." in observation_text(observation_for(remote_git_kb, "main"))
    assert "Interrupted content." not in "\n".join(
        observation_text(path) for path in pending(remote_git_kb)
    )
    assert remote_git_kb.git("status", "--porcelain", "--untracked-files=all") == ""


def test_failed_observation_commit_cleans_up_and_next_run_recovers(remote_git_kb: Kb) -> None:
    install(remote_git_kb, "claude", "projects/demo/main.jsonl")
    config(remote_git_kb)
    interrupted = seed_session_observation(remote_git_kb, "main")
    hook = remote_git_kb.content / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    failed = remote_git_kb("sync")

    assert failed.returncode == 1
    assert not interrupted.exists()
    assert pending(remote_git_kb) == []
    assert remote_git_kb.git("status", "--porcelain", "--untracked-files=all") == ""
    hook.unlink()
    recovered = remote_git_kb("sync")

    assert recovered.returncode == 0, recovered.stderr
    assert len(pending(remote_git_kb)) == 1
    assert remote_git_kb.git("log", "-1", "--format=%s") == "Observe: 1 session transcript(s)\n"


def test_recovery_leaves_another_hosts_observation_untracked(remote_git_kb: Kb) -> None:
    config(remote_git_kb, harvest_since=None)
    other_host = seed_session_observation(remote_git_kb, "other-session", "other-host")

    result = remote_git_kb("sync")

    assert result.returncode == 0, result.stderr
    assert other_host.exists()
    assert "Interrupted content." in observation_text(other_host)
    assert "sync: uncommitted changes" in result.stderr
