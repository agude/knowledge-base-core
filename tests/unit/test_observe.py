"""In-process tests of kb observe: its arguments, its write path, and its failures.

The end-to-end tests run the installed command. These tests run cli.main in this process,
so the coverage of the command and the lock comes from here.
"""

import io
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import cli
from kb.commands import observe

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


class FixedClock:
    """Stands in for datetime in the observe module, so that now() is always one UTC instant."""

    @staticmethod
    def now(tz: object = None) -> datetime:
        return datetime(2026, 10, 26, 12, 0, 5, tzinfo=UTC)


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
    monkeypatch.setattr(observe, "datetime", FixedClock)
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
        f'project: "{home}"\n'
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
    assert f'project: "{work.resolve()}"\n' in text


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
    monkeypatch.setattr(observe, "datetime", FixedClock)
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


def test_five_taken_names_are_a_failure(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(observe, "datetime", FixedClock)
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
