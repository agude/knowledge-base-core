"""End-to-end tests for `kb observe`.

Each test is marked xfail(strict=True) until the command is registered, and
step 5 removes the markers. Each test checks stdout, stderr, the exit status,
the working tree, and the git log, and each fails only because observe does
not exist yet.
"""

import os
import re
import socket
import subprocess
import sys
import time

import pytest

from .harness import Kb, run_git

USAGE = "Usage: kb observe --title TITLE --body TEXT\n"
BUSY = "observe: content repository is busy (waited 1s for the lock)\n"
WROTE = re.compile(r"Wrote: observations/pending/([0-9]{8}T[0-9]{6}-[0-9a-f]{8}\.md)\n")
CREATED = re.compile(r"^created: (\S+)$", re.MULTILINE)
# Holds an exclusive flock on the file named by argv[1] until its stdin closes.
HOLD_FLOCK = (
    "import fcntl, os, sys\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('locked', flush=True)\n"
    "sys.stdin.read()\n"
)
USAGE_CASES = [
    pytest.param(["observe", "--body", "Text."], USAGE, id="missing-title"),
    pytest.param(["observe", "--title", "Title"], USAGE, id="missing-body"),
    pytest.param(["observe", "--title", "   ", "--body", "Text."], USAGE, id="empty-title"),
    pytest.param(["observe", "--title", "One\nTwo", "--body", "Text."], USAGE, id="two-line-title"),
    pytest.param(["observe", "--title", "Title", "--body", ""], USAGE, id="empty-body"),
    pytest.param(["observe", "--title", "Title", "--body", " \n\t "], USAGE, id="whitespace-body"),
    pytest.param(
        ["observe", "--title", "Title", "--body", "Text.", "--source", "chat"],
        "Unknown option: --source\n",
        id="unknown-option",
    ),
]


def escape(text: str) -> str:
    """Escape as section 2 does: each backslash doubles, then each double quote gets a backslash."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def expected_host() -> str:
    """The host attribution: the host name up to its first dot."""
    return socket.gethostname().split(".")[0]


def expected_observation(title: str, body: str, project: str, created: str) -> str:
    """The bytes that section 2 requires: front matter, a blank line, the body, one newline."""
    return (
        "---\n"
        f'title: "{escape(title)}"\n'
        "source: session\n"
        f'project: "{escape(project)}"\n'
        f'host: "{escape(expected_host())}"\n'
        f"created: {created}\n"
        "---\n"
        "\n"
        f"{body}\n"
    )


def pending_files(kb: Kb) -> list[str]:
    """Every entry in observations/pending, dot-files included."""
    return sorted(entry.name for entry in (kb.content / "observations" / "pending").iterdir())


def temp_files(kb: Kb) -> list[str]:
    """Every entry in <git dir>/kb-tmp. The directory is made on demand, so it may be absent."""
    directory = kb.content / ".git" / "kb-tmp"
    if not directory.is_dir():
        return []
    return sorted(entry.name for entry in directory.iterdir())


def written_name(result: subprocess.CompletedProcess[str]) -> str:
    """The file name that a successful run's Wrote line names."""
    match = WROTE.fullmatch(result.stdout)
    assert match is not None, result.stdout
    return match.group(1)


def assert_observation(
    kb: Kb, result: subprocess.CompletedProcess[str], title: str, body: str, project: str
) -> str:
    """Assert that the run wrote the section 2 file and committed only that file.

    Returns the file name.
    """
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    name = written_name(result)
    text = (kb.content / "observations" / "pending" / name).read_text(encoding="utf-8")
    created = CREATED.search(text)
    assert created is not None, text
    stamp = created.group(1).replace("-", "").replace(":", "").removesuffix("Z")
    assert name.split("-")[0] == stamp
    assert text == expected_observation(title, body, project, created.group(1))
    assert kb.git("log", "-1", "--format=%s") == f"Observe: {title}\n"
    assert kb.git("show", "--name-only", "--format=", "HEAD").split() == [
        f"observations/pending/{name}"
    ]
    assert kb.git("status", "--porcelain") == ""
    assert temp_files(kb) == []
    assert not (kb.content / ".observe.lock").exists()
    return name


def test_success_writes_one_file_and_commits_only_that_file(git_kb: Kb) -> None:
    before = pending_files(git_kb)
    commits = int(git_kb.git("rev-list", "--count", "HEAD"))
    result = git_kb(
        "observe", "--title", "DNS caching", "--body", "Resolver caches answers for an hour."
    )
    name = assert_observation(
        git_kb,
        result,
        "DNS caching",
        "Resolver caches answers for an hour.",
        str(git_kb.home.resolve()),
    )
    assert pending_files(git_kb) == sorted([*before, name])
    assert int(git_kb.git("rev-list", "--count", "HEAD")) == commits + 1


@pytest.mark.parametrize(
    "stdin",
    [
        pytest.param("First line.\nSecond line.", id="without-final-newline"),
        pytest.param("First line.\nSecond line.\n", id="with-final-newline"),
    ],
)
def test_body_from_stdin_is_kept_as_read(git_kb: Kb, stdin: str) -> None:
    result = git_kb("observe", "--title", "Stdin body", "--body", "-", stdin=stdin)
    assert_observation(git_kb, result, "Stdin body", stdin, str(git_kb.home.resolve()))


def test_quote_and_backslash_in_the_title_are_escaped(git_kb: Kb) -> None:
    title = 'Say "hi" \\ there'
    result = git_kb("observe", "--title", title, "--body", "Plain text.")
    assert_observation(git_kb, result, title, "Plain text.", str(git_kb.home.resolve()))


def test_project_is_the_top_of_the_git_repository_the_command_runs_in(git_kb: Kb) -> None:
    work = git_kb.home.parent / "work"
    subdirectory = work / "src" / "tool"
    subdirectory.mkdir(parents=True)
    run_git(work, "init", "-q", "-b", "main")
    result = git_kb(
        "observe", "--title", "Attribution", "--body", "Run from a subdirectory.", cwd=subdirectory
    )
    assert_observation(
        git_kb, result, "Attribution", "Run from a subdirectory.", str(work.resolve())
    )


def test_project_is_the_working_directory_outside_any_git_repository(git_kb: Kb) -> None:
    result = git_kb("observe", "--title", "Attribution", "--body", "Run from home.")
    assert_observation(git_kb, result, "Attribution", "Run from home.", str(git_kb.home.resolve()))


@pytest.mark.parametrize(("words", "stderr"), USAGE_CASES)
def test_usage_errors_exit_one_and_change_nothing(
    git_kb: Kb, words: list[str], stderr: str
) -> None:
    head = git_kb.git("rev-parse", "HEAD")
    before = pending_files(git_kb)
    result = git_kb(*words)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == stderr
    assert pending_files(git_kb) == before
    assert git_kb.git("rev-parse", "HEAD") == head
    assert git_kb.git("status", "--porcelain") == ""
    assert temp_files(git_kb) == []
    assert not (git_kb.content / ".observe.lock").exists()


def test_secret_in_the_body_is_refused_and_nothing_is_written(git_kb: Kb) -> None:
    head = git_kb.git("rev-parse", "HEAD")
    before = pending_files(git_kb)
    body = 'Login notes.\npassword = "hunter2hunter2"\nDone.'
    result = git_kb("observe", "--title", "Credentials", "--body", body)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "observe: refused: possible secret (Secret Keyword) at body line 2\n"
        "observe: remove or redact it, then run kb observe again\n"
    )
    assert "hunter2" not in result.stderr
    assert pending_files(git_kb) == before
    assert git_kb.git("rev-parse", "HEAD") == head
    assert git_kb.git("status", "--porcelain") == ""
    assert temp_files(git_kb) == []
    assert not (git_kb.content / ".observe.lock").exists()


def test_staged_work_is_not_swept_into_the_commit(git_kb: Kb) -> None:
    (git_kb.content / "knowledge" / "unrelated.md").write_text(
        "# Unrelated\n\nStaged, not committed.\n", encoding="utf-8"
    )
    git_kb.git("add", "knowledge/unrelated.md")
    result = git_kb("observe", "--title", "Staged", "--body", "Committed alone.")
    assert result.returncode == 0
    assert result.stderr == ""
    name = written_name(result)
    assert git_kb.git("show", "--name-only", "--format=", "HEAD").split() == [
        f"observations/pending/{name}"
    ]
    assert git_kb.git("diff", "--cached", "--name-only").split() == ["knowledge/unrelated.md"]


def test_commit_failure_leaves_the_repository_as_it_was(git_kb: Kb) -> None:
    hook = git_kb.content / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'hook rejected the commit' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    head = git_kb.git("rev-parse", "HEAD")
    before = pending_files(git_kb)
    result = git_kb("observe", "--title", "Rejected", "--body", "The hook refuses this.")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("observe: commit failed:")
    assert "hook rejected the commit" in result.stderr
    assert pending_files(git_kb) == before
    assert git_kb.git("rev-parse", "HEAD") == head
    assert git_kb.git("diff", "--cached", "--name-only") == ""
    assert git_kb.git("status", "--porcelain") == ""
    assert temp_files(git_kb) == []
    assert not (git_kb.content / ".observe.lock").exists()


def test_kernel_lock_held_by_another_process_blocks_the_write(git_kb: Kb) -> None:
    head = git_kb.git("rev-parse", "HEAD")
    before = pending_files(git_kb)
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_FLOCK, str(git_kb.content / ".git" / "kb.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == "locked\n"
        started = time.monotonic()
        result = git_kb("observe", "--title", "Blocked", "--body", "Waits for the lock.")
        elapsed = time.monotonic() - started
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == BUSY
    assert 0.9 <= elapsed < 10
    assert pending_files(git_kb) == before
    assert git_kb.git("rev-parse", "HEAD") == head
    assert temp_files(git_kb) == []
    assert not (git_kb.content / ".observe.lock").exists()


def test_legacy_lock_held_by_a_live_process_blocks_the_write_and_is_left_alone(
    git_kb: Kb,
) -> None:
    head = git_kb.git("rev-parse", "HEAD")
    before = pending_files(git_kb)
    lock = git_kb.content / ".observe.lock"
    lock.mkdir()
    (lock / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    result = git_kb("observe", "--title", "Blocked", "--body", "The old script holds the lock.")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == BUSY
    assert pending_files(git_kb) == before
    assert git_kb.git("rev-parse", "HEAD") == head
    assert temp_files(git_kb) == []
    assert sorted(entry.name for entry in lock.iterdir()) == ["pid"]
    assert (lock / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"


def test_legacy_lock_left_by_a_dead_process_is_removed_and_the_write_succeeds(
    git_kb: Kb,
) -> None:
    exited = subprocess.Popen([sys.executable, "-c", "pass"])
    exited.wait(timeout=30)
    lock = git_kb.content / ".observe.lock"
    lock.mkdir()
    (lock / "pid").write_text(f"{exited.pid}\n", encoding="utf-8")
    result = git_kb("observe", "--title", "After a crash", "--body", "The old lock was stale.")
    assert_observation(
        git_kb, result, "After a crash", "The old lock was stale.", str(git_kb.home.resolve())
    )


def test_help_lists_observe_and_observe_help_exits_zero(kb: Kb) -> None:
    lines = kb("--help").stdout.splitlines()
    assert any(line.split()[:1] == ["observe"] for line in lines)
    result = kb("observe", "--help")
    assert result.returncode == 0
    assert result.stdout.startswith(USAGE)
