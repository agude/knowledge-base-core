"""In-process tests of kb observe: its arguments, its write path, and its failures.

The end-to-end tests run the installed command. These tests run cli.main in this process,
so the coverage of the command and the lock comes from here.
"""

import io
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import cli, lock, observation, secrets, write
from kb.commands import observe, sync
from kb.errors import KbError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"
USAGE = "Usage: kb observe --title TITLE --body TEXT\n"
WROTE = re.compile(r"Wrote: observations/pending/([0-9]{8}T[0-9]{6}-[0-9a-f]{8}\.md)\n")
REFUSAL = (
    "observe: refused: possible secret (Secret Keyword) at body line 2\n"
    "observe: remove or redact it, then run kb observe again\n"
)
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.invalid",
}
SECRET_BODY = 'Login notes.\npassword = "hunter2hunter2"\nDone.'
HOLD_KERNEL_LOCK = (
    "import os, sys\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
    "if sys.platform == 'win32':\n"
    " import msvcrt\n"
    " if os.fstat(fd).st_size == 0: os.write(fd, b'0')\n"
    " os.lseek(fd, 0, os.SEEK_SET)\n"
    " msvcrt.locking(fd, msvcrt.LK_LOCK, 1)\n"
    "else:\n"
    " import fcntl\n"
    " fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('locked', flush=True)\n"
    "sys.stdin.read()\n"
)


class ScannerInterrupted(BaseException):
    """A scanner interruption that must propagate after releasing the writer lock."""


def git(repo: Path, *args: str) -> str:
    """Run git in repo under the test identity and return its stdout."""
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def pending(content: Path) -> list[str]:
    """Every entry in observations/pending, dot-files included."""
    return sorted(entry.name for entry in (content / "observations" / "pending").iterdir())


def kb_tmp(content: Path) -> list[str]:
    """Every entry in <git dir>/kb-tmp, or none when the directory is absent."""
    directory = content / ".git" / "kb-tmp"
    return sorted(entry.name for entry in directory.iterdir()) if directory.is_dir() else []


def use_stdin(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    """Replace standard input with data."""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data), encoding="utf-8"))


def run_kb(capsys: pytest.CaptureFixture[str], *words: str) -> tuple[int, str, str]:
    """Run `kb observe WORDS` in process and return its status, stdout, and stderr."""
    status = cli.main(["observe", *words])
    captured = capsys.readouterr()
    return status, captured.out, captured.err


@pytest.fixture(autouse=True)
def isolated_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test away from the user's configuration and content repositories.

    Without this, a test that names no content repository reads the user's config file and
    writes to the content repository it names. The working directory is a plain directory,
    outside any git repository, so attribution does not depend on where pytest runs.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("KB_CONTENT", raising=False)
    monkeypatch.chdir(home)


@pytest.fixture
def content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A content repository whose one commit is the fixture, and an environment that names it."""
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", "Import the content fixture")
    monkeypatch.setenv("KB_CONTENT", str(root))
    monkeypatch.setenv("KB_TODAY", "2026-10-26")
    monkeypatch.setenv("KB_LOCK_WAIT", "0")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path / "home")
    use_stdin(monkeypatch, b"")
    return root


def test_help_prints_the_usage_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    status, out, err = run_kb(capsys, "--help")
    assert status == 0
    assert out.startswith(USAGE)
    assert err == ""


def test_the_top_level_help_lists_observe(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    assert any(line.split()[:1] == ["observe"] for line in capsys.readouterr().out.splitlines())


@pytest.mark.parametrize(
    "words",
    [
        pytest.param(["--body", "Text."], id="missing-title"),
        pytest.param(["--title", "Title"], id="missing-body"),
        pytest.param(["--title", "   ", "--body", "Text."], id="blank-title"),
        pytest.param(["--title", "one\ntwo", "--body", "Text."], id="two-line-title"),
        pytest.param(["--title", "one\rtwo", "--body", "Text."], id="carriage-return-title"),
        pytest.param(["--title", "Title", "--body", ""], id="empty-body"),
        pytest.param(["--title", "Title", "--body", " \n\t "], id="blank-body"),
        pytest.param(["stray", "--title", "Title", "--body", "Text."], id="stray-word"),
    ],
)
def test_usage_errors_print_the_usage_line(
    content: Path, capsys: pytest.CaptureFixture[str], words: list[str]
) -> None:
    before = pending(content)
    status, out, err = run_kb(capsys, *words)
    assert (status, out, err) == (1, "", USAGE)
    assert pending(content) == before
    assert git(content, "rev-list", "--count", "HEAD").strip() == "1"


def test_an_unknown_option_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    status, out, err = run_kb(capsys, "--title", "T", "--body", "x", "--source", "chat")
    assert (status, out, err) == (1, "", "Unknown option: --source\n")


def test_an_invalid_lock_wait_is_a_usage_error(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = pending(content)
    monkeypatch.setenv("KB_LOCK_WAIT", "soon")
    status, out, err = run_kb(capsys, "--title", "T", "--body", "x")
    assert (status, out, err) == (1, "", USAGE)
    assert pending(content) == before


def test_a_body_from_stdin_is_kept_as_read(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_stdin(monkeypatch, b"First line.\nSecond line.\n")
    status, out, err = run_kb(capsys, "--title", "Stdin", "--body", "-")
    assert (status, err) == (0, "")
    name = WROTE.fullmatch(out)
    assert name is not None
    text = (content / "observations" / "pending" / name.group(1)).read_text(encoding="utf-8")
    assert text.endswith("First line.\nSecond line.\n\n")


def test_stdin_that_is_not_utf8_is_refused(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = pending(content)
    use_stdin(monkeypatch, b"\xff\xfe")
    status, out, err = run_kb(capsys, "--title", "Bytes", "--body", "-")
    assert (status, out) == (1, "")
    assert err.startswith("observe: standard input is not UTF-8")
    assert pending(content) == before


def test_a_content_root_outside_git_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    shutil.copytree(FIXTURE, plain)
    monkeypatch.setenv("KB_CONTENT", str(plain))
    status, out, err = run_kb(capsys, "--title", "T", "--body", "x")
    assert (status, out) == (1, "")
    assert err == f"observe: the content repository is not a git repository: {plain.resolve()}\n"


def test_a_missing_content_root_is_reported_with_the_observe_prefix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("KB_CONTENT", raising=False)
    status, out, err = run_kb(capsys, "--title", "T", "--body", "x")
    assert (status, out) == (1, "")
    assert err.startswith("observe: knowledge base: no content repository")


def test_success_writes_one_file_and_commits_it(
    content: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("KB_NOW", "2026-10-26T12:00:05Z")
    status, out, err = run_kb(capsys, "--title", "DNS caching", "--body", "Cached for an hour.")
    assert (status, err) == (0, "")
    name = WROTE.fullmatch(out)
    assert name is not None
    assert name.group(1).startswith("20261026T120005-")
    host = socket.gethostname().split(".")[0]
    home = (tmp_path / "home").resolve()
    text = (content / "observations" / "pending" / name.group(1)).read_text(encoding="utf-8")
    assert text == (
        "---\n"
        'title: "DNS caching"\n'
        "source: session\n"
        f'project: "{observation.escape(str(home))}"\n'
        f'host: "{host}"\n'
        "created: 2026-10-26T12:00:05Z\n"
        "---\n"
        "\n"
        "Cached for an hour.\n"
    )
    assert git(content, "log", "-1", "--format=%s") == "Observe: DNS caching\n"
    assert git(content, "show", "--name-only", "--format=", "HEAD").split() == [
        f"observations/pending/{name.group(1)}"
    ]
    assert git(content, "status", "--porcelain") == ""
    assert kb_tmp(content) == []


def test_sync_recovery_at_lock_acquisition_does_not_remove_observe_scratch(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_lock = lock.write_lock

    @contextmanager
    def recover_then_lock(git_directory: Path, wait: int, backend: lock.Backend) -> Iterator[None]:
        sync._recover(content, git_directory, observation.short_host(socket.gethostname()))
        with original_lock(git_directory, wait, backend):
            yield

    monkeypatch.setattr(lock, "write_lock", recover_then_lock)

    status, out, err = run_kb(capsys, "--title", "Recovery boundary", "--body", "Keep scratch.")

    assert (status, err) == (0, "")
    assert WROTE.fullmatch(out) is not None
    assert kb_tmp(content) == []


@pytest.mark.parametrize("failure", [RuntimeError("scanner failed"), ScannerInterrupted()])
def test_scanner_failure_cleans_scratch_and_releases_the_writer_lock(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    from detect_secrets.core import scan as detect_scan

    def broken(filename: str) -> Iterator[object]:
        raise failure

    monkeypatch.setattr(detect_scan, "scan_file", broken)

    with pytest.raises(type(failure)):
        observe._record(content, "Scanner failure", "Ordinary test text.", 0)

    assert kb_tmp(content) == []
    with lock.write_lock(content / ".git", 0, lock.default_backend(sys.platform)):
        pass


@pytest.mark.skipif(os.name == "nt", reason="POSIX umask behavior")
def test_record_scratch_file_is_owner_only_with_a_group_readable_umask(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_publish = write._publish
    modes: list[int] = []

    def inspect(root: Path, directory: str, temporary: Path, when: datetime, command: str) -> str:
        modes.append(stat.S_IMODE(temporary.stat().st_mode))
        return original_publish(root, directory, temporary, when, command)

    monkeypatch.setattr(write, "_publish", inspect)
    previous = os.umask(0o022)
    try:
        status, out, err = run_kb(capsys, "--title", "Private scratch", "--body", "Safe text.")
    finally:
        os.umask(previous)

    assert (status, err) == (0, "")
    assert WROTE.fullmatch(out) is not None
    assert modes == [0o600]


@pytest.mark.parametrize("occupied_kind", ["race", "dangling"])
def test_publish_observation_retries_without_replacing_an_occupied_target(
    content: Path, monkeypatch: pytest.MonkeyPatch, occupied_kind: str
) -> None:
    if occupied_kind == "dangling" and os.name == "nt":
        pytest.skip("symbolic links need privilege")
    pending_directory = content / "observations" / "pending"
    scratch = content / ".git" / "kb-tmp"
    scratch.mkdir(exist_ok=True)
    marker = scratch / "other-operation.tmp"
    marker.write_bytes(b"keep")
    temporary = scratch / "record.md"
    temporary.write_bytes(b"new observation")
    first = pending_directory / "race.md"
    second = pending_directory / "next.md"
    if occupied_kind == "dangling":
        first.symlink_to(pending_directory / "missing.md")
    else:
        original_exists = Path.exists
        inserted = False

        def create_competing_observation(path: Path) -> bool:
            nonlocal inserted
            exists = original_exists(path)
            if path == first and not exists and not inserted:
                first.write_bytes(b"concurrent observation")
                inserted = True
            return exists

        monkeypatch.setattr(Path, "exists", create_competing_observation)
    names = iter((first.name, second.name))
    monkeypatch.setattr(observation, "file_name", lambda _now, _suffix: next(names))

    name = write._publish(
        content,
        "observations/pending",
        temporary,
        datetime(2026, 10, 26, 12, 0, 5, tzinfo=UTC),
        "observe",
    )
    temporary.unlink(missing_ok=True)

    assert name == second.name
    assert second.read_bytes() == b"new observation"
    if occupied_kind == "dangling":
        assert first.is_symlink()
        assert not first.exists()
    else:
        assert first.read_bytes() == b"concurrent observation"
    assert sorted(path.name for path in scratch.iterdir()) == [marker.name]
    assert marker.read_bytes() == b"keep"


def test_project_is_the_top_of_the_repository_the_process_is_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: Path,
) -> None:
    work = tmp_path / "work"
    subdirectory = work / "src"
    subdirectory.mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    monkeypatch.chdir(subdirectory)
    status, out, err = run_kb(capsys, "--title", "Attribution", "--body", "In a repository.")
    assert (status, err) == (0, "")
    name = WROTE.fullmatch(out)
    assert name is not None
    text = (content / "observations" / "pending" / name.group(1)).read_text(encoding="utf-8")
    assert f'project: "{observation.escape(str(work.resolve()))}"\n' in text


def test_a_secret_is_refused_and_nothing_is_written(
    content: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = pending(content)
    status, out, err = run_kb(capsys, "--title", "Credentials", "--body", SECRET_BODY)
    assert (status, out, err) == (1, "", REFUSAL)
    assert pending(content) == before
    assert git(content, "rev-list", "--count", "HEAD").strip() == "1"
    assert kb_tmp(content) == []


def test_a_rejected_commit_is_reported_and_undone(
    content: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = content / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'hook rejected the commit' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    before = pending(content)
    status, out, err = run_kb(capsys, "--title", "Rejected", "--body", "Refused by the hook.")
    assert (status, out) == (1, "")
    assert err.startswith("observe: commit failed:")
    assert "hook rejected the commit" in err
    assert pending(content) == before
    assert git(content, "diff", "--cached", "--name-only") == ""
    assert kb_tmp(content) == []


@pytest.mark.parametrize("point", ["before_add", "after_add", "after_commit"])
def test_interrupted_single_path_commit_preserves_its_git_outcome(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    unrelated = content / "unrelated.md"
    unrelated.write_text("Keep unrelated staging.\n", encoding="utf-8")
    git(content, "add", "--", "unrelated.md")
    before_head = git(content, "rev-parse", "HEAD").strip()
    before_index = git(content, "write-tree").strip()
    before_status = git(content, "status", "--porcelain")
    before_pending = set(pending(content))
    original_git = write._git

    def interrupt_git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
        if point == "before_add" and words[0] == "add":
            raise KeyboardInterrupt
        result = original_git(root, *words)
        if point == "after_add" and words[0] == "add" and result.returncode == 0:
            raise KeyboardInterrupt
        if point == "after_commit" and words[0] == "commit" and result.returncode == 0:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(write, "_git", interrupt_git)

    with pytest.raises(KeyboardInterrupt):
        observe._record(content, "Interrupt boundary", "Preserve the outcome.", 0)

    after_head = git(content, "rev-parse", "HEAD").strip()
    assert git(content, "status", "--porcelain") == before_status
    assert git(content, "diff", "--cached", "--name-only").splitlines() == ["unrelated.md"]
    if point == "after_commit":
        assert after_head != before_head
        assert before_index != git(content, "write-tree").strip()
        committed_paths = git(content, "show", "--format=", "--name-only", "HEAD").splitlines()
        assert len(committed_paths) == 1
        committed_path = committed_paths[0]
        assert committed_path.startswith("observations/pending/")
        assert (content / committed_path).is_file()
        assert git(content, "show", f"HEAD:{committed_path}") == git(
            content, "show", f":{committed_path}"
        )
    else:
        assert after_head == before_head
        assert git(content, "write-tree").strip() == before_index
        assert set(pending(content)) == before_pending
    assert unrelated.read_text(encoding="utf-8") == "Keep unrelated staging.\n"
    assert kb_tmp(content) == []


def test_uninspectable_commit_outcome_preserves_the_file_and_reports_uncertainty(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unrelated = content / "unrelated.md"
    unrelated.write_text("Keep unrelated staging.\n", encoding="utf-8")
    git(content, "add", "--", "unrelated.md")
    before_pending = set(pending(content))
    original_git = write._git
    committed = False

    def interrupt_and_hide_head(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
        nonlocal committed
        if committed and words[:3] == ("rev-parse", "--verify", "HEAD"):
            return subprocess.CompletedProcess(["git", *words], 1, "", "inspection unavailable\n")
        result = original_git(root, *words)
        if words[0] == "commit" and result.returncode == 0:
            committed = True
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(write, "_git", interrupt_and_hide_head)

    with pytest.raises(KbError, match="commit outcome is uncertain"):
        observe._record(content, "Unknown outcome", "Preserve recoverable state.", 0)

    committed_paths = git(content, "show", "--format=", "--name-only", "HEAD").splitlines()
    assert len(committed_paths) == 1
    committed_path = committed_paths[0]
    assert committed_path.startswith("observations/pending/")
    assert (content / committed_path).is_file()
    assert set(pending(content)) == before_pending | {Path(committed_path).name}
    assert git(content, "status", "--porcelain") == "A  unrelated.md\n"
    assert git(content, "show", f"HEAD:{committed_path}") == git(
        content, "show", f":{committed_path}"
    )
    assert unrelated.read_text(encoding="utf-8") == "Keep unrelated staging.\n"
    assert kb_tmp(content) == []


def test_interrupted_commit_reconciles_a_nested_content_root(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = content / "nested-content"
    shutil.copytree(FIXTURE, nested)
    git(content, "add", "--", "nested-content")
    git(content, "commit", "-q", "-m", "Add nested content")
    original_git = write._git

    def interrupt_after_commit(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
        result = original_git(root, *words)
        if words[0] == "commit" and result.returncode == 0:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(write, "_git", interrupt_after_commit)

    with pytest.raises(KeyboardInterrupt):
        observe._record(nested, "Nested interruption", "Keep the committed file.", 0)

    committed_paths = git(content, "show", "--format=", "--name-only", "HEAD").splitlines()
    assert len(committed_paths) == 1
    committed_path = committed_paths[0]
    assert committed_path.startswith("nested-content/observations/pending/")
    assert (content / committed_path).is_file()
    assert git(content, "status", "--porcelain") == ""
    assert git(content, "show", f"HEAD:{committed_path}") == git(
        content, "show", f":{committed_path}"
    )


def test_a_failed_stage_is_reported_as_a_failed_commit(
    content: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (content / ".git" / "index.lock").write_text("", encoding="utf-8")
    before = pending(content)
    status, out, err = run_kb(capsys, "--title", "Locked index", "--body", "Index is busy.")
    assert (status, out) == (1, "")
    assert err.startswith("observe: commit failed:")
    assert pending(content) == before
    assert kb_tmp(content) == []


def test_a_kernel_lock_held_by_another_descriptor_is_reported_as_busy(
    content: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = pending(content)
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_KERNEL_LOCK, str(content / ".git" / "kb.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == "locked\n"
        status, out, err = run_kb(capsys, "--title", "Blocked", "--body", "Waits.")
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert (status, out, err) == (
        1,
        "",
        "observe: content repository is busy (waited 0s for the lock)\n",
    )
    assert pending(content) == before
    assert kb_tmp(content) == []


def test_a_taken_name_draws_a_new_suffix(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KB_NOW", "2026-10-26T12:00:05Z")
    (content / "observations" / "pending" / "20261026T120005-00000001.md").write_text(
        "taken\n", encoding="utf-8"
    )
    draws = iter(
        [b"\xaa\xaa\xaa\xaa", b"\xbb\xbb\xbb\xbb", b"\x00\x00\x00\x01", b"\x00\x00\x00\x02"]
    )
    monkeypatch.setattr(os, "urandom", lambda size: next(draws))
    status, out, err = run_kb(capsys, "--title", "Suffix", "--body", "Second draw wins.")
    assert (status, out, err) == (
        0,
        "Wrote: observations/pending/20261026T120005-00000002.md\n",
        "",
    )
    assert (content / "observations" / "pending" / "20261026T120005-00000001.md").read_text(
        encoding="utf-8"
    ) == "taken\n"
    assert kb_tmp(content) == []


def test_a_record_name_collision_preserves_the_existing_scratch_file(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratch = content / ".git" / "kb-tmp"
    scratch.mkdir()
    collision = scratch / "record-01020304.md"
    collision.write_text("Keep this file.\n", encoding="utf-8")
    draws = iter(
        [
            b"\xaa\xaa\xaa\xaa",
            b"\x01\x02\x03\x04",
            b"\x05\x06\x07\x08",
            b"\x00\x00\x00\x01",
        ]
    )
    monkeypatch.setattr(os, "urandom", lambda size: next(draws))

    status, out, err = run_kb(capsys, "--title", "Scratch collision", "--body", "Keep it.")

    assert (status, err) == (0, "")
    assert WROTE.fullmatch(out) is not None
    assert collision.read_text(encoding="utf-8") == "Keep this file.\n"
    assert sorted(path.name for path in scratch.iterdir()) == [collision.name]


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")
def test_observe_refuses_a_symlinked_scratch_directory(
    content: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    existing = external / "keep.md"
    existing.write_text("Keep this file.\n", encoding="utf-8")
    scratch = content / ".git" / "kb-tmp"
    scratch.symlink_to(external, target_is_directory=True)

    status, out, err = run_kb(capsys, "--title", "Unsafe scratch", "--body", "Do not write.")

    assert (status, out) == (1, "")
    assert err.startswith("observe: temporary directory is a symlink:")
    assert scratch.is_symlink()
    assert existing.read_text(encoding="utf-8") == "Keep this file.\n"
    assert sorted(path.name for path in external.iterdir()) == [existing.name]


def test_five_taken_names_are_a_failure(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KB_NOW", "2026-10-26T12:00:05Z")
    (content / "observations" / "pending" / "20261026T120005-00000001.md").write_text(
        "taken\n", encoding="utf-8"
    )
    monkeypatch.setattr(os, "urandom", lambda size: b"\x00\x00\x00\x01")
    status, out, err = run_kb(capsys, "--title", "Suffix", "--body", "Every draw is taken.")
    assert (status, out) == (1, "")
    assert err == "observe: no free file name in observations/pending\n"
    assert kb_tmp(content) == []


def test_an_operating_system_error_is_reported_with_the_observe_prefix(
    content: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(content / "observations" / "pending")
    (content / "observations" / "pending").write_text("not a directory\n", encoding="utf-8")
    status, out, err = run_kb(capsys, "--title", "Blocked dir", "--body", "Pending is a file.")
    assert (status, out) == (1, "")
    assert err.startswith("observe: ")
    assert kb_tmp(content) == []


def test_recall_does_not_import_detect_secrets(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in [name for name in sys.modules if name.startswith("detect_secrets")]:
        monkeypatch.delitem(sys.modules, name)
    assert cli.main(["recall", "nas", "restart", "order"]) == 0
    capsys.readouterr()
    assert not [name for name in sys.modules if name.startswith("detect_secrets")]


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")
@pytest.mark.parametrize("relative", ["observations", "observations/pending"])
@pytest.mark.parametrize("target_kind", ["internal", "external"])
def test_refuses_publication_through_a_symlinked_directory(
    content: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    relative: str,
    target_kind: str,
) -> None:
    external = content / "safe-area" if target_kind == "internal" else tmp_path / "external"
    external.mkdir()
    if relative == "observations":
        external_pending = external / "pending"
        external_pending.mkdir()
    else:
        external_pending = external
    existing = external_pending / "existing.md"
    existing.write_text("keep", encoding="utf-8")
    link = content / relative
    link.rename(tmp_path / "original-directory")
    try:
        link.symlink_to(external, target_is_directory=True)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    names = sorted(path.relative_to(external) for path in external.rglob("*"))
    index = git(content, "ls-files", "--stage")
    scan_calls: list[Path] = []

    def track_scan(directory: Path, _text: str) -> list[tuple[str, int]]:
        scan_calls.append(directory)
        return []

    monkeypatch.setattr(write, "_commit", lambda *_args: None)
    monkeypatch.setattr(secrets, "findings", track_scan)

    status, out, err = run_kb(capsys, "--title", "Unsafe path", "--body", "Keep outside.")

    assert (status, out) == (1, "")
    assert "content directory is a symlink" in err
    assert scan_calls == []
    assert sorted(path.relative_to(external) for path in external.rglob("*")) == names
    assert existing.read_text(encoding="utf-8") == "keep"
    assert git(content, "ls-files", "--stage") == index
