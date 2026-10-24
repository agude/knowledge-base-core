"""sync: rebase the content repository onto its remote and push."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.inspect import tree
from kbtest.runner import KB, Result

REMOTE_OBSERVATION = "20260101T000000-0000ffff.md"


class Remote:
    """A bare origin for the content repository, and other machines that use it."""

    def __init__(self, kb: KB) -> None:
        self.kb = kb
        self.path = kb.layout.root / "remote.git"
        self.git("init", "-q", "--bare", "-b", "main", str(self.path), cwd=kb.layout.root)
        kb.git("remote", "add", "origin", str(self.path))
        kb.git("push", "-q", "-u", "origin", "main")

    def env(self, **extra: str) -> dict[str, str]:
        return {**self.kb.git_env(), **extra}

    def git(self, *args: str, cwd: Path, **extra: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=self.env(**extra),
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def other_machine_commits(
        self, name: str = REMOTE_OBSERVATION, text: str = "from another machine"
    ) -> None:
        other = self.kb.layout.root / "other"
        self.git("clone", "-q", str(self.path), str(other), cwd=self.kb.layout.root)
        target = other / "observations" / "pending" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        identity = {
            "GIT_AUTHOR_NAME": "Other",
            "GIT_COMMITTER_NAME": "Other",
            "GIT_AUTHOR_DATE": "2026-10-02T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-10-02T00:00:00Z",
        }
        self.git("add", "-A", cwd=other)
        self.git("commit", "-q", "-m", "Observe: from another machine", cwd=other, **identity)
        self.git("push", "-q", "origin", "HEAD", cwd=other)
        shutil.rmtree(other)

    def log(self) -> str:
        return self.git("log", "--format=%an %s", cwd=self.path)


@pytest.fixture
def remote(kb: KB) -> Remote:
    return Remote(kb)


def _check(
    kb: KB, golden: Golden, result: Result, remote: Remote, *, git_stderr: bool = False
) -> None:
    """git_stderr: stderr also carries git's own messages, which vary by git
    version; pin only sync's last line."""
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    if git_stderr:
        golden.check("stderr-last", kb.norm(result.err.splitlines()[-1] + "\n"))
    else:
        golden.check("stderr", kb.norm_err(result.err))
    golden.check("local-log", kb.git("log", "--format=%an %s"))
    golden.check("remote-log", remote.log())
    golden.check(
        "lock", "held\n" if (kb.layout.content / ".observe.lock").exists() else "released\n"
    )


def _observe(kb: KB, title: str = "Local") -> None:
    assert kb.run("observe", "--title", title, "--body", "Body").returncode == 0


@pytest.mark.bats("sync.bats", "sync reports being in sync")
def test_sync_in_sync(kb: KB, remote: Remote, golden: Golden) -> None:
    _check(kb, golden, kb.run("sync"), remote)


@pytest.mark.bats("sync.bats", "sync --status reports counts without changing anything")
def test_sync_status(kb: KB, remote: Remote, golden: Golden) -> None:
    remote.other_machine_commits()
    _observe(kb)
    _check(kb, golden, kb.run("sync", "--status"), remote)
    assert not (kb.layout.content / "observations" / "pending" / REMOTE_OBSERVATION).exists()


def test_sync_status_in_sync(kb: KB, remote: Remote, golden: Golden) -> None:
    _check(kb, golden, kb.run("sync", "--status"), remote)


@pytest.mark.bats("sync.bats", "sync pulls another machine's observations")
@pytest.mark.bats("sync.bats", "sync releases the lock")
def test_sync_pulls(kb: KB, remote: Remote, golden: Golden) -> None:
    remote.other_machine_commits()
    _check(kb, golden, kb.run("sync"), remote)
    assert (kb.layout.content / "observations" / "pending" / REMOTE_OBSERVATION).is_file()


@pytest.mark.bats("sync.bats", "sync pushes local observations")
def test_sync_pushes(kb: KB, remote: Remote, golden: Golden) -> None:
    _observe(kb)
    _check(kb, golden, kb.run("sync"), remote)


@pytest.mark.bats("sync.bats", "sync rebases local commits on top of remote ones")
def test_sync_rebases(kb: KB, remote: Remote, golden: Golden) -> None:
    _observe(kb)
    remote.other_machine_commits()
    _check(kb, golden, kb.run("sync"), remote)
    assert kb.git("log", "--merges", "--format=%s") == ""


@pytest.mark.bats("sync.bats", "sync refuses to run with uncommitted changes")
def test_sync_refuses_dirty_tree(kb: KB, remote: Remote, golden: Golden) -> None:
    (kb.layout.content / "knowledge" / "wip.md").write_text("half-written\n", encoding="utf-8")
    _check(kb, golden, kb.run("sync"), remote)


@pytest.mark.bats("sync.bats", "sync fails cleanly with no remote")
def test_sync_without_remote(kb: KB, remote: Remote, golden: Golden) -> None:
    kb.git("remote", "remove", "origin")
    _check(kb, golden, kb.run("sync"), remote)


@pytest.mark.bats("sync.bats", "sync reports fetch failure instead of using cached state")
@pytest.mark.bats("sync.bats", "sync --status reports fetch failure instead of using cached state")
@pytest.mark.parametrize("args", [[], ["--status"]], ids=["sync", "status"])
def test_sync_fetch_failure(kb: KB, remote: Remote, golden: Golden, args: list[str]) -> None:
    kb.git("remote", "set-url", "origin", str(remote.path / "unavailable"))
    _check(kb, golden, kb.run("sync", *args), remote, git_stderr=True)


@pytest.mark.bats("sync.bats", "sync rejects unavailable remote tracking information")
def test_sync_missing_tracking_ref(kb: KB, remote: Remote, golden: Golden) -> None:
    kb.git("config", "--unset-all", "remote.origin.fetch")
    kb.git("update-ref", "-d", "refs/remotes/origin/main")
    _check(kb, golden, kb.run("sync", "--status"), remote)


@pytest.mark.bats("sync.bats", "sync rechecks for observations written during fetch")
def test_sync_rechecks_after_fetch(kb: KB, remote: Remote, golden: Golden) -> None:
    started = kb.layout.root / "fetch-started"
    release = kb.layout.root / "fetch-release"
    real_git = (kb.layout.bin / "git").resolve()
    (kb.layout.bin / "git").unlink()
    # A git that pauses inside fetch, so a writer can publish mid-sync.
    wrapper = kb.layout.bin / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = fetch ]; then\n'
        f"  : > '{started}'\n"
        "  i=0\n"
        f"  while [ ! -f '{release}' ] && [ $i -lt 200 ]; do i=$((i+1)); sleep 0.05; done\n"
        "fi\n"
        f"exec '{real_git}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    tree_obj = kb.resolve_impl(kb.default_impl)
    process = subprocess.Popen(
        [str(tree_obj.executable("sync"))],
        env=kb.env(tree_obj),
        cwd=kb.layout.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists(), "sync never reached fetch"
        written = kb.run(
            "observe", "--no-commit", "--title", "Concurrent", "--body", "Written during sync"
        )
        assert written.returncode == 0
        release.touch()
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    golden.check("result", f"exit {process.returncode}\n")
    golden.check("stdout", kb.norm(stdout.decode()))
    golden.check("stderr", kb.norm_err(stderr.decode()))
    golden.check("pending", kb.norm(tree(kb.layout.content / "observations" / "pending")))


@pytest.mark.bats("sync.bats", "sync leaves rebase conflicts for resolution")
def test_sync_leaves_conflicts(kb: KB, remote: Remote, golden: Golden) -> None:
    conflict = kb.layout.content / "knowledge" / "conflict.md"
    conflict.write_text("base\n", encoding="utf-8")
    kb.git("add", "knowledge/conflict.md")
    kb.git("commit", "-qm", "Add conflict fixture")
    kb.git("push", "-q", "origin", "main")
    conflict.write_text("local\n", encoding="utf-8")
    kb.git("commit", "-qam", "Local conflict")

    other = kb.layout.root / "other"
    remote.git("clone", "-q", str(remote.path), str(other), cwd=kb.layout.root)
    (other / "knowledge" / "conflict.md").write_text("remote\n", encoding="utf-8")
    remote.git("commit", "-qam", "Remote conflict", cwd=other, GIT_AUTHOR_NAME="Other")
    remote.git("push", "-q", "origin", "HEAD", cwd=other)

    result = kb.run("sync")
    golden.check("result", f"exit {result.returncode}\n")
    # Between sync's own lines, git prints merge and rebase text whose
    # wording varies by git version; pin only sync's lines.
    golden.check("stdout-first", kb.norm(result.out.splitlines()[0] + "\n"))
    golden.check("stderr-last", kb.norm(result.err.splitlines()[-1] + "\n"))
    git_dir = kb.layout.content / ".git"
    assert (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir()
    assert not (kb.layout.content / ".observe.lock").exists()


@pytest.mark.bats("sync.bats", "sync --no-push pulls only")
def test_sync_no_push(kb: KB, remote: Remote, golden: Golden) -> None:
    _observe(kb)
    remote.other_machine_commits()
    _check(kb, golden, kb.run("sync", "--no-push"), remote)


@pytest.mark.bats("sync.bats", "sync rejects an unknown option")
def test_sync_unknown_option(kb: KB, remote: Remote, golden: Golden) -> None:
    _check(kb, golden, kb.run("sync", "--bogus"), remote)


def test_sync_outside_git_repository(kb: KB, golden: Golden) -> None:
    plain = kb.layout.root / "plain"
    plain.mkdir()
    result = kb.run("sync", env={"KB_CONTENT_DIR": str(plain)})
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stderr", kb.norm_err(result.err))
