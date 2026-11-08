"""The test double for kb.git answers matched calls and runs the rest for real."""

import subprocess
from pathlib import Path

import pytest

from kb import git

from . import git_fakes


def make_repo(root: Path) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    return root


def test_a_matched_call_returns_the_configured_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    fake = git_fakes.install(monkeypatch)
    fake.on(("rev-parse",), git_fakes.completed(3, "out\n", "err\n"))

    text = git.run(root, "rev-parse", "HEAD")
    raw = git.run_bytes(root, "rev-parse", "HEAD")

    assert (text.returncode, text.stdout, text.stderr) == (3, "out\n", "err\n")
    assert (raw.returncode, raw.stdout, raw.stderr) == (3, b"out\n", b"err\n")


def test_an_unmatched_call_runs_real_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_repo(tmp_path / "repo")
    fake = git_fakes.install(monkeypatch)
    fake.on(("commit",), git_fakes.completed(1))

    result = git.run(root, "rev-parse", "--is-inside-work-tree")

    assert result.returncode == 0
    assert result.stdout == "true\n"


def test_times_answers_only_the_first_matching_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    fake = git_fakes.install(monkeypatch)
    fake.on(("rev-parse",), git_fakes.completed(7), times=1)

    first = git.run(root, "rev-parse", "--is-inside-work-tree")
    second = git.run(root, "rev-parse", "--is-inside-work-tree")

    assert first.returncode == 7
    assert second.returncode == 0


def test_an_exception_result_is_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_repo(tmp_path / "repo")
    fake = git_fakes.install(monkeypatch)
    fake.on(("status",), KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        git.run_bytes(root, "status")


def test_calls_records_matched_and_unmatched_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    fake = git_fakes.install(monkeypatch)
    fake.on(("commit",), git_fakes.completed(1))

    git.run(root, "commit", "-q", read_only=True)
    git.run_bytes(root, "status", "--porcelain")

    assert fake.calls == [("commit", "-q"), ("status", "--porcelain")]
    assert fake.keywords == [{"read_only": True}, {}]


def test_a_responder_can_alter_a_real_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    fake = git_fakes.install(monkeypatch)

    def failing_status(root: Path, words: tuple[str, ...]) -> git_fakes.Result | None:
        if words[:1] != ("status",):
            return None
        real = fake.real_run(root, *words)
        return git_fakes.completed(1, real.stdout, "reported failure\n")

    fake.responders.append(failing_status)

    result = git.run(root, "status", "--porcelain")

    assert (result.returncode, result.stderr) == (1, "reported failure\n")
