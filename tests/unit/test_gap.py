"""In-process tests for kb gap's validation and protected write path."""

import io
import os
import re
import shutil
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import cli, lock, observation, secrets, write
from kb.commands import gap, sync

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"
USAGE = "Usage: kb gap --title TITLE --body TEXT --context PATH\n"
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.invalid",
}


class FixedClock:
    """A fixed instant for stable question filenames and metadata."""

    @staticmethod
    def now(tz: object = None) -> datetime:
        return datetime(2026, 10, 26, 12, 0, 5, tzinfo=UTC)


class FakeFcntl:
    """A no-contention POSIX lock backend for lock-release checks."""

    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def flock(self, fd: int, operation: int, /) -> None:
        pass


def git(root: Path, *words: str) -> str:
    """Run Git with the isolated test identity."""
    result = subprocess.run(
        ["git", *words],
        cwd=root,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(root), **GIT_ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def open_questions(root: Path) -> list[Path]:
    """The Markdown questions under questions/open."""
    directory = root / "questions" / "open"
    return sorted(directory.glob("*.md")) if directory.exists() else []


def run_gap(capsys: pytest.CaptureFixture[str], *words: str) -> tuple[int, str, str]:
    """Run the command in process and return status, stdout, and stderr."""
    status = cli.main(["gap", *words])
    captured = capsys.readouterr()
    return status, captured.out, captured.err


@pytest.fixture(autouse=True)
def isolated_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a private home, config root, and working directory for each command test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("KB_CONTENT", raising=False)
    monkeypatch.chdir(home)


@pytest.fixture
def content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Git content fixture and environment that names it."""
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", "Import the content fixture")
    monkeypatch.setenv("KB_CONTENT", str(root))
    monkeypatch.setenv("KB_LOCK_WAIT", "0")
    monkeypatch.setenv("KB_TODAY", "2026-10-26")
    return root


def test_help_and_top_level_registration(capsys: pytest.CaptureFixture[str]) -> None:
    status, out, err = run_gap(capsys, "--help")
    assert (status, err) == (0, "")
    assert out.startswith(USAGE)
    assert cli.main(["--help"]) == 0
    assert any(line.split()[:1] == ["gap"] for line in capsys.readouterr().out.splitlines())


@pytest.mark.parametrize(
    "words",
    [
        pytest.param(["--body", "Body", "--context", "infra"], id="missing-title"),
        pytest.param(["--title", "Title", "--context", "infra"], id="missing-body"),
        pytest.param(["--title", "Title", "--body", "Body"], id="missing-context"),
        pytest.param(
            ["stray", "--title", "Title", "--body", "Body", "--context", "infra"], id="stray-word"
        ),
        pytest.param(["--title", " ", "--body", "Body", "--context", "infra"], id="blank-title"),
        pytest.param(
            ["--title", "Title\nAgain", "--body", "Body", "--context", "infra"],
            id="multiline-title",
        ),
        pytest.param(
            ["--title", "Title", "--body", " \n\t ", "--context", "infra"], id="blank-body"
        ),
    ],
)
def test_usage_errors_do_not_write_questions(
    content: Path,
    capsys: pytest.CaptureFixture[str],
    words: list[str],
) -> None:
    before = open_questions(content)
    status, out, err = run_gap(capsys, *words)
    assert (status, out, err) == (1, "", USAGE)
    assert open_questions(content) == before
    assert git(content, "rev-list", "--count", "HEAD").strip() == "1"


def test_invalid_context_is_reported_and_changes_nothing(
    content: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = open_questions(content)
    for context, message in (
        (" ", "context must not be blank"),
        ("../outside", "context must not contain .. components"),
        ("/absolute", "context must be a relative path"),
        ("article.md#2", "context must not contain a fragment"),
        ("bad\x7fpath", "context must not contain control characters"),
    ):
        status, out, err = run_gap(
            capsys, "--title", "Title", "--body", "Body", "--context", context
        )
        assert (status, out) == (1, "")
        assert err == f"gap: {message}\n"
        assert open_questions(content) == before
    assert git(content, "status", "--porcelain") == ""
    monkeypatch.setenv("KB_LOCK_WAIT", "soon")
    status, out, err = run_gap(capsys, "--title", "Title", "--body", "Body", "--context", "infra")
    assert (status, out, err) == (1, "", USAGE)


def test_non_git_content_root_is_reported_with_the_gap_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "plain"
    shutil.copytree(FIXTURE, root)
    monkeypatch.setenv("KB_CONTENT", str(root))
    status, out, err = run_gap(capsys, "--title", "Title", "--body", "Body", "--context", "infra")
    assert (status, out) == (1, "")
    assert err == f"gap: the content repository is not a git repository: {root.resolve()}\n"


def test_missing_content_configuration_is_reported_with_the_gap_prefix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("KB_CONTENT", raising=False)
    status, out, err = run_gap(capsys, "--title", "Title", "--body", "Body", "--context", "infra")
    assert (status, out) == (1, "")
    assert err.startswith("gap: knowledge base: no content repository")


def test_os_error_from_the_scratch_directory_uses_the_gap_prefix(
    content: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scratch = content / ".git" / "kb-tmp"
    scratch.write_text("not a directory", encoding="utf-8")
    status, out, err = run_gap(capsys, "--title", "Title", "--body", "Body", "--context", "infra")
    assert (status, out) == (1, "")
    assert re.match(r"gap: \[(Errno|WinError) \d+\]", err)
    assert scratch.read_text(encoding="utf-8") == "not a directory"


def test_invalid_utf8_stdin_is_refused_before_content_changes(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = open_questions(content)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.TextIOWrapper(io.BytesIO(b"\xff\xfe"), encoding="utf-8"),
    )
    status, out, err = run_gap(capsys, "--title", "Title", "--body", "-", "--context", "infra")
    assert (status, out) == (1, "")
    assert err.startswith("gap: standard input is not UTF-8")
    assert open_questions(content) == before


def test_valid_utf8_stdin_is_kept_as_read(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.TextIOWrapper(io.BytesIO("First café line.\nSecond line.".encode()), encoding="utf-8"),
    )
    status, out, err = run_gap(
        capsys, "--title", "Stdin", "--body", "-", "--context", "future/area"
    )
    assert status == 0
    assert err == ""
    relative = out.removeprefix("Wrote: ").removesuffix("\n")
    text = (content / relative).read_text(encoding="utf-8")
    assert text.endswith("First café line.\nSecond line.\n")


def test_success_writes_exact_bytes_commits_one_path_and_reads_back(
    content: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(gap, "datetime", FixedClock)
    monkeypatch.setattr(socket, "gethostname", lambda: "test-host.local")
    title = 'Say "hi" \\ café'
    body = "The owner is not listed."
    status, out, err = run_gap(
        capsys, "--title", title, "--body", body, "--context", "./infra/./nas.md/"
    )
    assert (status, err) == (0, "")
    assert out.startswith("Wrote: questions/open/20261026T120005-")
    relative = out.removeprefix("Wrote: ").removesuffix("\n")
    assert relative.startswith("questions/open/")
    question = content / relative
    home = (tmp_path / "home").resolve()
    assert question.read_text(encoding="utf-8") == (
        "---\n"
        'title: "Say \\"hi\\" \\\\ café"\n'
        'context: "knowledge/infra/nas.md"\n'
        "source: session\n"
        f'project: "{observation.escape(str(home))}"\n'
        'host: "test-host"\n'
        "created: 2026-10-26T12:00:05Z\n"
        "---\n"
        "\n"
        f"{body}\n"
    )
    assert git(content, "log", "-1", "--format=%s") == f"Ask: {title}\n"
    assert git(content, "show", "--name-only", "--format=", "HEAD").split() == [relative]
    assert git(content, "status", "--porcelain") == ""
    assert list((content / ".git" / "kb-tmp").iterdir()) == []

    read_status = cli.main(["read", relative])
    read_output = capsys.readouterr().out
    assert read_status == 0
    assert body in read_output


def test_sync_recovery_at_lock_acquisition_does_not_remove_gap_scratch(
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

    status, out, err = run_gap(
        capsys,
        "--title",
        "Recovery boundary",
        "--body",
        "Keep scratch.",
        "--context",
        "infra",
    )

    assert (status, err) == (0, "")
    assert out.startswith("Wrote: questions/open/")
    assert list((content / ".git" / "kb-tmp").iterdir()) == []


def test_secrets_in_each_supplied_field_are_refused_without_publication(
    content: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = open_questions(content)
    cases = (
        ('password = "hunter2hunter2"', "safe body", "infra", "at title"),
        ("Safe title", "safe body", 'password = "hunter2hunter2"', "at context"),
        ("Safe title", 'password = "hunter2hunter2"', "infra", "at body line 1"),
    )
    for title, body, context, location in cases:
        status, out, err = run_gap(
            capsys,
            "--title",
            title,
            "--body",
            body,
            "--context",
            context,
        )
        assert (status, out) == (1, "")
        assert "gap: refused: possible secret (Secret Keyword) " + location in err
        assert "remove or redact it, then run kb gap again" in err
        assert "hunter2" not in err
        assert open_questions(content) == before
    assert git(content, "status", "--porcelain") == ""


def test_question_filename_collision_uses_a_new_random_suffix(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(gap, "datetime", FixedClock)
    first = content / "questions" / "open" / "20261026T120005-00000001.md"
    first.write_text("Existing collision.\n", encoding="utf-8")
    draws = iter(
        [b"\xaa\xaa\xaa\xaa", b"\xbb\xbb\xbb\xbb", b"\x00\x00\x00\x01", b"\x00\x00\x00\x02"]
    )
    monkeypatch.setattr(os, "urandom", lambda size: next(draws))
    status, out, err = run_gap(
        capsys, "--title", "Collision", "--body", "Use the next suffix.", "--context", "infra"
    )
    assert (status, err) == (0, "")
    assert out == "Wrote: questions/open/20261026T120005-00000002.md\n"
    assert first.read_text(encoding="utf-8") == "Existing collision.\n"
    assert (content / "questions" / "open" / "20261026T120005-00000002.md").is_file()
    assert git(content, "show", "--name-only", "--format=", "HEAD").split() == [
        "questions/open/20261026T120005-00000002.md"
    ]


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

    status, out, err = run_gap(
        capsys,
        "--title",
        "Scratch collision",
        "--body",
        "Keep it.",
        "--context",
        "infra",
    )

    assert (status, err) == (0, "")
    assert out.startswith("Wrote: questions/open/")
    assert collision.read_text(encoding="utf-8") == "Keep this file.\n"
    assert sorted(path.name for path in scratch.iterdir()) == [collision.name]


def test_failed_staging_removes_the_new_question_and_preserves_existing_questions(
    content: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = open_questions(content)
    index_lock = content / ".git" / "index.lock"
    index_lock.write_text("held", encoding="utf-8")
    status, out, err = run_gap(
        capsys, "--title", "Stage failure", "--body", "Do not publish.", "--context", "infra"
    )
    assert (status, out) == (1, "")
    assert err.startswith("gap: commit failed:")
    assert open_questions(content) == before
    assert list((content / ".git" / "kb-tmp").iterdir()) == []
    assert index_lock.read_text(encoding="utf-8") == "held"


@pytest.mark.parametrize("interrupted_command", ["add", "commit"])
def test_interruption_removes_only_the_new_question_and_releases_locks(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted_command: str,
) -> None:
    existing = content / "questions" / "open" / "existing.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("---\ntitle: Existing\n---\n\nKeep me.\n", encoding="utf-8")
    git(content, "add", "questions/open/existing.md")
    before = open_questions(content)
    original_git = write._git

    def interrupt_git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
        if words[0] == interrupted_command:
            if interrupted_command == "add":
                original_git(root, *words)
            raise KeyboardInterrupt
        return original_git(root, *words)

    monkeypatch.setattr(write, "_git", interrupt_git)
    with pytest.raises(KeyboardInterrupt):
        gap._record(content, "Interrupted", "knowledge/future", "Keep the old question.", 0)

    assert open_questions(content) == before
    assert git(content, "status", "--porcelain") == "A  questions/open/existing.md\n"
    assert list((content / ".git" / "kb-tmp").iterdir()) == []
    backend = lock.FlockBackend(FakeFcntl())
    fd = lock.acquire_kernel(content / ".git" / lock.KERNEL_LOCK, backend, 0)
    backend.unlock(fd)
    os.close(fd)


@pytest.mark.parametrize("failed_command", ["ls-files", "rm"])
def test_rollback_failure_is_reported_and_keeps_the_question_for_recovery(
    content: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed_command: str,
) -> None:
    before = set(open_questions(content))
    original_git = write._git

    def fail_git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
        if words[0] in ("commit", failed_command):
            return subprocess.CompletedProcess(["git", *words], 1, "", "index unavailable\n")
        return original_git(root, *words)

    monkeypatch.setattr(write, "_git", fail_git)
    status, out, err = run_gap(
        capsys,
        "--title",
        "Retain on cleanup failure",
        "--body",
        "Recover me.",
        "--context",
        "infra",
    )
    assert (status, out) == (1, "")
    assert err.startswith("gap: rollback failed for questions/open/")
    assert "inspect Git status before retrying" in err
    assert "index unavailable" in err
    published = set(open_questions(content)) - before
    assert len(published) == 1
    question = published.pop()
    assert question.read_text(encoding="utf-8").endswith("Recover me.\n")
    assert git(content, "diff", "--cached", "--name-only").splitlines() == [
        question.relative_to(content).as_posix()
    ]
    assert list((content / ".git" / "kb-tmp").iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")
@pytest.mark.parametrize("relative", ["questions", "questions/open"])
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
    if relative == "questions":
        external_open = external / "open"
        external_open.mkdir()
    else:
        external_open = external
    existing = external_open / "existing.md"
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

    status, out, err = run_gap(
        capsys,
        "--title",
        "Unsafe path",
        "--body",
        "Keep outside.",
        "--context",
        "infra",
    )

    assert (status, out) == (1, "")
    assert "content directory is a symlink" in err
    assert scan_calls == []
    assert sorted(path.relative_to(external) for path in external.rglob("*")) == names
    assert existing.read_text(encoding="utf-8") == "keep"
    assert git(content, "ls-files", "--stage") == index
