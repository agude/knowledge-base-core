"""In-process tests for `kb curate finish`: refusals, commit failures, and publication outcomes.

The subprocess tests in tests/e2e/test_finish.py show the observable contract. These tests
run the same code in process, so every branch counts toward coverage, and they force the
Git failures that a healthy repository never produces.
"""

import os
import re
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from kb import curation, lock, remote, secrets
from kb.commands import curate
from kb.errors import KbError

NOW = "2026-10-26T12:00:00Z"
RUN_RE = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Finish Test",
    "GIT_AUTHOR_EMAIL": "finish@example.invalid",
    "GIT_COMMITTER_NAME": "Finish Test",
    "GIT_COMMITTER_EMAIL": "finish@example.invalid",
}
ARTICLE = (
    "---\ntitle: Workflow\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
    "# Workflow\n\n## 1. Fact\n\nA durable fact.\n"
)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


@pytest.fixture
def make_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Create a content repository, optionally with a bare origin, and point kb at it."""
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("KB_NOW", NOW)
    monkeypatch.setenv("KB_TODAY", "2026-10-26")

    def make(*, origin: bool = True) -> Path:
        root = tmp_path / "content"
        (root / "knowledge").mkdir(parents=True)
        (root / "observations" / "pending").mkdir(parents=True)
        (root / "questions" / "open").mkdir(parents=True)
        (root / "knowledge" / "workflow.md").write_text(ARTICLE, encoding="utf-8")
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "--all")
        git(root, "commit", "-q", "-m", "Seed")
        if origin:
            bare = tmp_path / "origin.git"
            git(tmp_path, "init", "--bare", "-q", "-b", "main", str(bare))
            git(root, "remote", "add", "origin", str(bare))
            git(root, "push", "-q", "--set-upstream", "origin", "main")
        monkeypatch.setenv("KB_CONTENT", str(root))
        return root

    return make


def _run(capsys: pytest.CaptureFixture[str], *words: str) -> tuple[int, str, str]:
    """Run the curate command in process, as the CLI would report it."""
    arguments = list(words[1:] if words[:1] == ("curate",) else words)
    try:
        code = curate.run(arguments)
        error = ""
    except KbError as failure:
        code, error = 1, f"{failure}\n"
    captured = capsys.readouterr()
    return code, captured.out, captured.err + error


def _observe(root: Path, name: str) -> None:
    (root / "observations" / "pending" / name).write_text(
        f"---\ntitle: {name}\ncreated: 2026-10-24\n---\n\nEvidence.\n", encoding="utf-8"
    )
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", f"Add {name}")


def _start(capsys: pytest.CaptureFixture[str], *names: str) -> str:
    code, out, err = _run(capsys, "curate", "start", "--no-sync", "--max-bytes", "100000", *names)
    assert code == 0, err
    match = RUN_RE.search(out)
    assert match is not None, out
    return match.group(1)


def _settled(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """A committed fixture with one settled batch: one ephemeral member."""
    _observe(root, "one.md")
    run = _start(capsys, "one.md")
    code, _, err = _run(
        capsys, "curate", "complete", run, "one.md", "--disposition", "ephemeral", "--reason", "x"
    )
    assert code == 0, err
    return run


def _patch_git(monkeypatch: pytest.MonkeyPatch, **overrides: CompletedProcess[str]) -> None:
    """Replace the result of any Git call whose words include a key, and run the rest."""
    real = curate._git_quiet

    def fake(root: Path, *words: str) -> CompletedProcess[str]:
        for word, result in overrides.items():
            if word in words:
                return result
        return real(root, *words)

    monkeypatch.setattr(curate, "_git_quiet", fake)


def _completed(code: int, stderr: str = "") -> CompletedProcess[str]:
    return CompletedProcess(["git"], code, "", stderr)


def test_finish_refuses_an_archive_interrupted_before_completion(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    member = curation.begin_archive(
        curation.Member("one.md", "a" * 64, 3), "ephemeral", [], "Stopped", "b" * 64
    )
    batch = curation.make_batch(
        "20261026T120000-a1b2c3d4", datetime(2026, 10, 26, 12, tzinfo=UTC), 100, [member]
    )
    manifest = root / "observations" / "batches" / f"{batch.id}.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(curation.render_batch(batch), encoding="utf-8")

    code, _, err = _run(capsys, "curate", "finish", batch.id)

    assert code == 1
    assert "archive is interrupted for one.md; resume: kb curate complete" in err


def test_finish_refuses_a_batch_with_pending_work(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    _observe(root, "open.md")
    run = _start(capsys, "open.md")

    code, _, err = _run(capsys, "curate", "finish", run)

    assert code == 1
    assert f"batch has pending work; run: kb curate status {run}" in err


@pytest.mark.parametrize(
    ("origin", "detach", "message"),
    [
        (True, True, "HEAD is detached"),
        (False, False, "no origin remote; use --no-push to commit locally"),
    ],
)
def test_finish_refuses_before_writing_when_the_branch_or_origin_is_unusable(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    origin: bool,
    detach: bool,
    message: str,
) -> None:
    root = make_content(origin=origin)
    run = _settled(root, capsys)
    if detach:
        git(root, "checkout", "-q", "--detach")
    head = git(root, "rev-parse", "HEAD")

    code, _, err = _run(capsys, "curate", "finish", run)

    assert code == 1
    assert message in err
    assert git(root, "rev-parse", "HEAD") == head


def test_finish_refuses_staged_changes_and_unrelated_paths_with_a_count(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    (root / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(root, "add", "--", "staged.txt")

    code, _, err = _run(capsys, "curate", "finish", run)

    assert code == 1
    assert "the index has staged changes: staged.txt" in err
    git(root, "rm", "-q", "--cached", "--", "staged.txt")
    (root / "staged.txt").unlink()
    for number in range(9):
        (root / f"loose-{number}.txt").write_text("loose\n", encoding="utf-8")

    code, _, err = _run(capsys, "curate", "finish", run)

    assert code == 1
    assert "loose-0.txt, loose-1.txt" in err
    assert "loose-7.txt, and 1 more" in err


def test_a_blocking_finding_refuses_publication_and_writes_nothing(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    (root / "knowledge" / "workflow.md").write_text(ARTICLE + "\n# Second\n", encoding="utf-8")
    head = git(root, "rev-parse", "HEAD")

    code, _, err = _run(capsys, "curate", "finish", run)

    assert code == 1
    assert "validation refused publication; nothing was written" in err
    assert "  knowledge/workflow.md:" in err
    assert git(root, "rev-parse", "HEAD") == head
    assert git(root, "diff", "--cached", "--name-only") == ""


def test_preexisting_findings_are_printed_before_the_commit(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    (root / "knowledge" / "old.md").write_text(
        "---\ntitle: Old\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n# A\n# B\n",
        encoding="utf-8",
    )
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", "Add a preexisting problem")
    run = _settled(root, capsys)

    code, out, err = _run(capsys, "curate", "finish", run, "--no-push")

    assert code == 0, err
    assert "Preexisting (not blocking): 1\n  knowledge/old.md:" in out


def test_a_rejecting_hook_is_reported_and_its_staging_is_undone(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'hook: refused in process' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    code, _, err = _run(capsys, "curate", "finish", run, "--no-push")

    assert code == 1
    assert "commit failed" in err
    assert "hook: refused in process" in err
    assert git(root, "diff", "--cached", "--name-only") == ""


def test_a_failed_unstage_after_a_rejected_commit_is_reported(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho refused >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    _patch_git(monkeypatch, reset=_completed(1, "index locked"))

    code, _, err = _run(capsys, "curate", "finish", run, "--no-push")

    assert code == 1
    assert "cannot unstage the publication set; inspect Git status: index locked" in err


def test_a_failed_stage_is_unstaged_and_reported(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    _patch_git(monkeypatch, add=_completed(1, "fatal: disk full"))

    code, _, err = _run(capsys, "curate", "finish", run, "--no-push")

    assert code == 1
    assert "cannot stage the publication set: fatal: disk full" in err
    assert git(root, "diff", "--cached", "--name-only") == ""


def test_a_staged_set_that_differs_from_the_publication_set_is_refused(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    _patch_git(monkeypatch, add=_completed(0))

    code, _, err = _run(capsys, "curate", "finish", run, "--no-push")

    assert code == 1
    assert "staged set differs from the publication set" in err
    assert "nothing committed" in err
    assert git(root, "diff", "--cached", "--name-only") == ""


def test_a_secret_match_in_the_message_is_an_internal_error(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    monkeypatch.setattr(secrets, "findings", lambda *_args: [("Fake", 1)])

    code, _, err = _run(capsys, "curate", "finish", run, "--no-push")

    assert code == 1
    assert "matched a secret check (Fake); internal error" in err


def test_publication_reports_each_remote_failure_and_keeps_the_commit(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    outcomes = [
        (
            remote.Result(errors=("sync: rebase onto origin/main failed; local commits kept",)),
            "Resolve the conflict, then run: kb sync",
        ),
        (
            remote.Result(errors=("sync: push origin/main failed: refused",)),
            "Resolve the cause, then run: kb sync",
        ),
        (
            remote.Result(skipped_dirty=("loose.txt",)),
            "uncommitted changes: loose.txt",
        ),
    ]
    for outcome, expected in outcomes:
        monkeypatch.setattr(remote, "synchronize", lambda *_args, value=outcome, **_kw: value)
        code, _, err = _run(capsys, "curate", "finish", run)
        assert code == 1
        assert "Committed locally; not published" in err
        assert expected in err


def test_publication_reports_a_commit_that_origin_already_has(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    code, _, err = _run(capsys, "curate", "finish", run, "--no-push")
    assert code == 0, err
    commit = git(root, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(
        remote, "synchronize", lambda *_args, **_kw: remote.Result(already_in_sync=True)
    )

    code, out, err = _run(capsys, "curate", "finish", run)

    assert code == 0, err
    assert out == f"Already published: {commit}\n"


def test_no_push_then_publish_then_no_push_again_follows_the_remote_state(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    code, out, _ = _run(capsys, "curate", "finish", run, "--no-push")
    assert code == 0
    commit = git(root, "rev-parse", "HEAD").strip()
    assert out.endswith("Committed locally; not published\n")

    code, out, _ = _run(capsys, "curate", "finish", run, "--no-push")
    assert code == 0
    assert out == f"Commit: {commit}\nCommitted locally; not published\n"

    code, out, err = _run(capsys, "curate", "finish", run)
    assert code == 0, err
    assert out == "Published: origin/main\n"

    code, out, _ = _run(capsys, "curate", "finish", run, "--no-push")
    assert code == 0
    assert out == f"Already published: {commit}\n"

    code, out, _ = _run(capsys, "curate", "status", run)
    assert code == 0
    assert f"Batch is published as {commit}." in out


def test_status_reports_a_committed_batch_that_is_not_published(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    assert _run(capsys, "curate", "finish", run, "--no-push")[0] == 0
    commit = git(root, "rev-parse", "HEAD").strip()

    code, out, _ = _run(capsys, "curate", "status", run)

    assert code == 0
    assert f"Committed locally; not published: {commit}. Run: kb curate finish {run}" in out


def test_usage_wait_and_wrapped_failures_are_reported(
    make_content: Callable[..., Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = make_content()
    run = _settled(root, capsys)

    assert _run(capsys, "curate", "finish")[2] == "Usage: kb curate finish RUN [--no-push]\n"
    code, out, _ = _run(capsys, "curate", "finish", "--help")
    assert code == 0 and out.startswith("Usage: kb curate finish RUN [--no-push]\n")
    monkeypatch.setenv("KB_LOCK_WAIT", "soon")
    assert _run(capsys, "curate", "finish", run)[2].startswith("Usage: kb curate finish")
    monkeypatch.delenv("KB_LOCK_WAIT")

    def busy(*_args: object) -> object:
        raise lock.LockBusy(2)

    @contextmanager
    def nothing(*_args: object) -> Iterator[None]:
        yield

    monkeypatch.setattr(lock, "write_lock", busy)
    assert (
        "content repository is busy (waited 2s for the lock)"
        in _run(capsys, "curate", "finish", run)[2]
    )
    monkeypatch.setattr(lock, "write_lock", nothing)
    for raised, expected in [
        (curation.StateError("bad manifest"), "curate: bad manifest"),
        (OSError("disk gone"), "curate: disk gone"),
        (KbError("plain failure"), "curate: plain failure"),
        (KbError("curate: already prefixed"), "curate: already prefixed"),
    ]:

        def failing(*_args: object, error: BaseException = raised, **_kwargs: object) -> int:
            raise error

        monkeypatch.setattr(curate, "_finish", failing)
        assert _run(capsys, "curate", "finish", run)[2] == f"{expected}\n"


def test_committed_batch_is_found_in_full_history_when_its_base_is_not_an_ancestor(
    make_content: Callable[..., Path], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_content()
    run = _settled(root, capsys)
    assert _run(capsys, "curate", "finish", run, "--no-push")[0] == 0
    commit = git(root, "rev-parse", "HEAD").strip()
    batch = curation.load_batch(
        (root / "observations" / "batches" / f"{run}.json").read_text(encoding="utf-8")
    )
    unrelated = curation.make_batch(
        batch.id,
        datetime(2026, 10, 26, 12, tzinfo=UTC),
        100,
        batch.members,
        base_commit="a" * 40,
    )

    assert curate._committed_batch(root, unrelated) == commit
    assert curate._committed_batch(root.parent, unrelated) is None


def test_git_queries_report_absence_outside_a_repository(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="curate: cannot inspect Git status"):
        curate._git_output(tmp_path, "status", message="cannot inspect Git status")
    assert curate._branch(tmp_path) is None
    assert curate._has_origin(tmp_path) is False
    assert curate._is_ancestor(tmp_path, "a" * 40, "b" * 40) is False


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("??", "A"),
        (" D", "D"),
        ("D ", "D"),
        (" T", "T"),
        ("MM", "M"),
        (" M", "M"),
        ("A ", "A"),
    ],
)
def test_worktree_codes_map_to_git_status_letters(code: str, status: str) -> None:
    assert curate._change_status(code) == status
