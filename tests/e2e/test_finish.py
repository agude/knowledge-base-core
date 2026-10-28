"""End-to-end tests for `kb curate finish`: validate, commit the publication set once, push."""

import os
import re
import subprocess
import sys
from pathlib import Path

from .harness import GIT_ISOLATION, Kb, run_git

RUN_RE = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")
COMMIT_RE = re.compile(r"Commit: ([0-9a-f]{40})\n")
ARTICLE = (
    "---\ntitle: Workflow evidence\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
    "# Workflow evidence\n\n## 1. Incorporated fact\n\nA durable workflow fact.\n\n"
    "## 2. Duplicate fact\n\nA repeated durable fact.\n"
)
QUESTION = "questions/open/20261001T090000-bbbb2222.md"
RESOLVED = "questions/resolved/20261001T090000-bbbb2222.md"


def _head(kb: Kb) -> str:
    return run_git(kb.content, "rev-parse", "HEAD").strip()


def _origin_head(kb: Kb) -> str:
    assert kb.origin is not None
    return run_git(kb.origin, "rev-parse", "refs/heads/main").strip()


def _commit_count(kb: Kb) -> int:
    return int(run_git(kb.content, "rev-list", "--count", "HEAD").strip())


def _clone(kb: Kb, name: str) -> Path:
    assert kb.origin is not None
    destination = kb.home / name
    run_git(kb.home, "clone", "-q", str(kb.origin), str(destination))
    return destination


def _push_from(clone: Path, relative: str, text: str) -> None:
    path = clone / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    run_git(clone, "add", "--", relative)
    run_git(clone, "commit", "-q", "-m", f"Change {relative}")
    run_git(clone, "push", "-q", "origin", "main")


def _settled_batch(kb: Kb) -> str:
    """A committed fixture with one batch that holds every outcome and resolves a question."""
    pending = kb.content / "observations" / "pending"
    names = ["incorporated.md", "duplicate.md", "ephemeral.md", "deferred.md", "dropped.md"]
    for name in names:
        (pending / name).write_text(
            f"---\ntitle: {name}\ncreated: 2026-10-24\n---\n\n## 1. Evidence\n\n"
            f"Evidence for {name}.\n",
            encoding="utf-8",
        )
    (kb.content / "knowledge/workflow.md").write_text(ARTICLE, encoding="utf-8")
    run_git(kb.content, "add", "--all")
    run_git(kb.content, "commit", "-q", "-m", "Prepare settled batch fixture")
    started = kb("curate", "start", "--no-sync", "--max-bytes", "100000", *names)
    assert started.returncode == 0, started.stderr
    run_id = RUN_RE.search(started.stdout)
    assert run_id is not None, started.stdout
    run = run_id.group(1)
    # Changed after selection, so the publication set includes the article.
    (kb.content / "knowledge/workflow.md").write_text(
        ARTICLE.replace("A durable workflow fact.", "A durable workflow fact, confirmed."),
        encoding="utf-8",
    )
    (pending / "dropped.md").unlink()
    steps = [
        ("complete", "incorporated.md", "--disposition", "incorporated", "knowledge/workflow.md"),
        ("complete", "duplicate.md", "--disposition", "duplicate", "knowledge/workflow.md#2"),
        (
            "complete",
            "ephemeral.md",
            "--disposition",
            "ephemeral",
            "--reason",
            "Session-only detail",
        ),
        ("defer", "deferred.md", "--reason", "Need owner input"),
        ("drop", "dropped.md", "--reason", "Input was removed externally"),
    ]
    for verb, *arguments in steps:
        result = kb("curate", verb, run, *arguments)
        assert result.returncode == 0, result.stderr
    resolved = kb(
        "resolve",
        QUESTION,
        "--answer",
        "The local workflow retains a reusable example.",
        "--destination",
        "knowledge/workflow.md#1",
    )
    assert resolved.returncode == 0, resolved.stderr
    return run


def _changed_paths(kb: Kb, commit: str) -> set[str]:
    output = run_git(kb.content, "show", "--name-only", "--no-renames", "--format=", commit)
    return {line for line in output.splitlines() if line}


def test_finish_commits_the_publication_set_once_and_publishes_it(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    before = _head(kb)
    count = _commit_count(kb)

    result = kb("curate", "finish", run)

    assert result.returncode == 0, result.stderr
    commit = COMMIT_RE.search(result.stdout)
    assert commit is not None, result.stdout
    assert commit.group(1) == _head(kb)
    assert "Published: origin/main\n" in result.stdout
    assert _origin_head(kb) == _head(kb)
    assert _commit_count(kb) == count + 1
    assert run_git(kb.content, "rev-parse", "HEAD^").strip() == before
    assert _changed_paths(kb, "HEAD") == {
        "knowledge/workflow.md",
        f"observations/batches/{run}.json",
        "observations/archived/incorporated.md",
        "observations/archived/duplicate.md",
        "observations/archived/ephemeral.md",
        "observations/pending/incorporated.md",
        "observations/pending/duplicate.md",
        "observations/pending/ephemeral.md",
        "observations/pending/dropped.md",
        QUESTION,
        RESOLVED,
    }
    status = kb("curate", "status", run)
    assert status.returncode == 0, status.stderr
    assert f"Batch is published as {_head(kb)}." in status.stdout


def test_the_commit_message_renders_every_outcome_and_the_resolved_question(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)

    assert kb("curate", "finish", run).returncode == 0
    message = run_git(kb.content, "log", "-1", "--format=%B")

    assert message.startswith(
        f"Curate {run}: 1 incorporated, 1 duplicate, 1 ephemeral, 1 deferred, 1 dropped\n"
    )
    assert "Articles changed:\n- knowledge/workflow.md (modified)\n" in message
    assert "- incorporated.md: incorporated -> knowledge/workflow.md" in message
    assert "- duplicate.md: duplicate -> knowledge/workflow.md#2" in message
    assert "- ephemeral.md: ephemeral (Session-only detail)\n" in message
    assert "- deferred.md: deferred (Need owner input)\n" in message
    assert "- dropped.md: dropped (Input was removed externally)\n" in message
    assert f"Questions resolved:\n- {RESOLVED}\n" in message


def test_a_renamed_article_is_named_as_a_rename_in_the_commit_message(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    extra = ARTICLE.replace("Workflow evidence", "Extra evidence")
    (kb.content / "knowledge/extra.md").write_text(extra, encoding="utf-8")
    run_git(kb.content, "add", "--", "knowledge/extra.md")
    run_git(kb.content, "commit", "-q", "-m", "Add extra article", "--", "knowledge/extra.md")
    (kb.content / "knowledge/extra.md").rename(kb.content / "knowledge/moved.md")

    result = kb("curate", "finish", run)

    assert result.returncode == 0, result.stderr
    message = run_git(kb.content, "log", "-1", "--format=%B")
    assert "- knowledge/moved.md (renamed from knowledge/extra.md)\n" in message
    assert "knowledge/extra.md (deleted)" not in message


def test_repeating_finish_after_publication_reports_it_and_makes_no_commit(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    assert kb("curate", "finish", run).returncode == 0
    commit = _head(kb)
    count = _commit_count(kb)

    repeated = kb("curate", "finish", run)

    assert repeated.returncode == 0, repeated.stderr
    assert repeated.stdout == f"Already published: {commit}\n"
    assert _commit_count(kb) == count


def test_a_batch_with_only_deferred_members_commits_just_its_manifest(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    name = "deferred-only.md"
    (kb.content / "observations" / "pending" / name).write_text(
        "---\ntitle: Deferred\ncreated: 2026-10-24\n---\n\nA note.\n", encoding="utf-8"
    )
    run_git(kb.content, "add", "--all")
    run_git(kb.content, "commit", "-q", "-m", "Add deferred-only input")
    started = kb("curate", "start", "--no-sync", "--max-bytes", "100000", name)
    run = RUN_RE.search(started.stdout)
    assert run is not None, started.stdout
    assert kb("curate", "defer", run.group(1), name, "--reason", "Wait").returncode == 0

    result = kb("curate", "finish", run.group(1))

    assert result.returncode == 0, result.stderr
    assert _changed_paths(kb, "HEAD") == {f"observations/batches/{run.group(1)}.json"}


def test_an_invalid_article_refuses_publication_and_writes_nothing(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    (kb.content / "knowledge/workflow.md").write_text(ARTICLE + "\n# Second\n", encoding="utf-8")
    head = _head(kb)
    status = kb.git("status", "--porcelain")

    result = kb("curate", "finish", run)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "validation refused publication; nothing was written" in result.stderr
    assert "second H1" in result.stderr
    assert _head(kb) == head
    assert kb.git("diff", "--cached", "--name-only") == ""
    assert kb.git("status", "--porcelain") == status


def test_a_pending_arrival_outside_the_batch_refuses_publication(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    (kb.content / "observations/pending/new-arrival.md").write_text(
        "---\ntitle: New\ncreated: 2026-10-28\n---\n\nOutside the batch.\n", encoding="utf-8"
    )
    head = _head(kb)

    result = kb("curate", "finish", run)

    assert result.returncode == 1
    assert (
        "curate: uncommitted changes outside the batch: observations/pending/new-arrival.md"
        in result.stderr
    )
    assert _head(kb) == head


def test_dirty_paths_are_listed_up_to_eight_then_counted(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    for number in range(10):
        path = kb.content / "scratch" / f"note-{number:02d}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("scratch\n", encoding="utf-8")

    result = kb("curate", "finish", run)

    assert result.returncode == 1
    assert "scratch/note-00.txt, scratch/note-01.txt" in result.stderr
    assert "scratch/note-07.txt, and 2 more" in result.stderr


def test_staged_changes_refuse_finish_and_stay_staged(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    (kb.content / "scratch.txt").write_text("staged\n", encoding="utf-8")
    run_git(kb.content, "add", "--", "scratch.txt")

    result = kb("curate", "finish", run)

    assert result.returncode == 1
    assert "the index has staged changes: scratch.txt" in result.stderr
    assert run_git(kb.content, "diff", "--cached", "--name-only").strip() == "scratch.txt"


def test_an_unsettled_batch_is_refused(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    name = "open.md"
    (kb.content / "observations" / "pending" / name).write_text(
        "---\ntitle: Open\ncreated: 2026-10-24\n---\n\nA note.\n", encoding="utf-8"
    )
    run_git(kb.content, "add", "--all")
    run_git(kb.content, "commit", "-q", "-m", "Add open input")
    started = kb("curate", "start", "--no-sync", "--max-bytes", "100000", name)
    run = RUN_RE.search(started.stdout)
    assert run is not None, started.stdout

    result = kb("curate", "finish", run.group(1))

    assert result.returncode == 1
    assert f"batch has pending work; run: kb curate status {run.group(1)}" in result.stderr


def test_an_interrupted_archive_refuses_finish_and_names_the_completion(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    name = "interrupted.md"
    (kb.content / "observations" / "pending" / name).write_text(
        "---\ntitle: Interrupted\ncreated: 2026-10-24\n---\n\nA note.\n", encoding="utf-8"
    )
    run_git(kb.content, "add", "--all")
    run_git(kb.content, "commit", "-q", "-m", "Add interrupted input")
    started = kb("curate", "start", "--no-sync", "--max-bytes", "100000", name)
    run = RUN_RE.search(started.stdout)
    assert run is not None, started.stdout
    script = (
        "from kb import cli\n"
        "from kb.commands import curate\n"
        "def interrupt(*_args, **_kwargs):\n"
        "    raise OSError('injected interruption')\n"
        "curate._publish_archive = interrupt\n"
        f"raise SystemExit(cli.main({['curate', 'complete', run.group(1), name, '--disposition', 'ephemeral', '--reason', 'Stopped']!r}))\n"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=kb.home,
        env=kb.environment({}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )

    result = kb("curate", "finish", run.group(1))

    assert result.returncode == 1
    assert "archive is interrupted for interrupted.md; resume: kb curate complete" in result.stderr


def test_a_detached_head_and_a_missing_origin_refuse_before_writing(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    run_git(kb.content, "checkout", "-q", "--detach")
    head = _head(kb)

    detached = kb("curate", "finish", run)

    assert detached.returncode == 1
    assert "HEAD is detached" in detached.stderr
    assert _head(kb) == head


def test_finish_without_origin_requires_no_push(git_kb: Kb) -> None:
    run = _settled_batch(git_kb)
    head = _head(git_kb)

    refused = git_kb("curate", "finish", run)

    assert refused.returncode == 1
    assert "no origin remote; use --no-push to commit locally" in refused.stderr
    assert _head(git_kb) == head

    local = git_kb("curate", "finish", run, "--no-push")

    assert local.returncode == 0, local.stderr
    assert "Committed locally; not published\n" in local.stdout
    assert _head(git_kb) != head


def test_a_rejecting_commit_hook_leaves_the_worktree_and_index_intact(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    hook = kb.content / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'hook: refused by test' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    head = _head(kb)
    worktree = (kb.content / "knowledge/workflow.md").read_bytes()
    manifest = kb.content / "observations" / "batches" / f"{run}.json"
    manifest_bytes = manifest.read_bytes()

    result = kb("curate", "finish", run)

    assert result.returncode == 1
    assert "hook: refused by test" in result.stderr
    assert "commit failed" in result.stderr
    assert _head(kb) == head
    assert kb.git("diff", "--cached", "--name-only") == ""
    assert (kb.content / "knowledge/workflow.md").read_bytes() == worktree
    assert manifest.read_bytes() == manifest_bytes


def test_a_behind_origin_is_rebased_then_published(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    writer = _clone(kb, "writer")
    _push_from(writer, "knowledge/infra/nas.md", "# NAS\n\nRemote change.\n")

    result = kb("curate", "finish", run)

    assert result.returncode == 0, result.stderr
    assert "Published: origin/main\n" in result.stdout
    assert _origin_head(kb) == _head(kb)
    assert kb("curate", "finish", run).stdout == f"Already published: {_head(kb)}\n"


def test_a_rebase_conflict_keeps_the_commit_and_resumes_after_resolution(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    writer = _clone(kb, "writer")
    _push_from(writer, "knowledge/workflow.md", ARTICLE.replace("A durable", "Remote"))

    result = kb("curate", "finish", run)

    assert result.returncode == 1
    assert "sync: rebase onto origin/main failed; local commits kept" in result.stderr
    assert (
        "Committed locally; not published. Resolve the conflict, then run: kb sync" in result.stderr
    )
    commit = _head(kb)
    count = _commit_count(kb)
    assert kb("curate", "finish", run).returncode == 1
    assert _commit_count(kb) == count
    assert _head(kb) == commit

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(kb.home),
        "GIT_EDITOR": "true",
        **GIT_ISOLATION,
    }
    rebase = subprocess.run(
        ["git", "rebase", "origin/main"],
        cwd=kb.content,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rebase.returncode != 0
    (kb.content / "knowledge/workflow.md").write_text(ARTICLE, encoding="utf-8")
    run_git(kb.content, "add", "--", "knowledge/workflow.md")
    resumed = subprocess.run(
        ["git", "rebase", "--continue"],
        cwd=kb.content,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr

    finished = kb("curate", "finish", run)

    assert finished.returncode == 0, finished.stderr
    assert "Published: origin/main\n" in finished.stdout
    assert _origin_head(kb) == _head(kb)
    # The rebase adds the writer's commit to local history; finish adds no commit.
    assert _commit_count(kb) == count + 1
    subjects = run_git(kb.content, "log", "--format=%s").splitlines()
    assert sum(subject.startswith("Curate ") for subject in subjects) == 1


def test_a_rejected_push_keeps_the_commit_and_resumes_without_another(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    assert kb.origin is not None
    run = _settled_batch(kb)
    reject = kb.origin / "hooks" / "pre-receive"
    reject.write_text("#!/bin/sh\necho refused >&2\nexit 1\n", encoding="utf-8")
    reject.chmod(0o755)

    failed = kb("curate", "finish", run)

    assert failed.returncode == 1
    assert "sync: push origin/main failed" in failed.stderr
    assert "Committed locally; not published. Resolve the cause, then run: kb sync" in failed.stderr
    commit = _head(kb)
    count = _commit_count(kb)
    reject.unlink()

    resumed = kb("curate", "finish", run)

    assert resumed.returncode == 0, resumed.stderr
    assert "Published: origin/main\n" in resumed.stdout
    assert _origin_head(kb) == commit
    assert _commit_count(kb) == count


def test_no_push_commits_locally_and_a_later_finish_publishes_it(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    origin_before = _origin_head(kb)

    local = kb("curate", "finish", run, "--no-push")

    assert local.returncode == 0, local.stderr
    assert "Committed locally; not published\n" in local.stdout
    assert _origin_head(kb) == origin_before
    commit = _head(kb)
    count = _commit_count(kb)
    again = kb("curate", "finish", run, "--no-push")
    assert again.returncode == 0, again.stderr
    assert "Committed locally; not published\n" in again.stdout
    assert _commit_count(kb) == count

    published = kb("curate", "finish", run)

    assert published.returncode == 0, published.stderr
    assert "Published: origin/main\n" in published.stdout
    assert _origin_head(kb) == commit
    assert _commit_count(kb) == count


def test_an_interruption_between_commit_and_push_is_reported_and_resumed(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    script = (
        "from kb import cli\n"
        "from kb import remote\n"
        "def stop(*_args, **_kwargs):\n"
        "    raise SystemExit(3)\n"
        "remote.synchronize = stop\n"
        f"raise SystemExit(cli.main({['curate', 'finish', run]!r}))\n"
    )
    interrupted = subprocess.run(
        [sys.executable, "-c", script],
        cwd=kb.home,
        env=kb.environment({}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert interrupted.returncode == 3, interrupted.stderr
    commit = _head(kb)
    assert _origin_head(kb) != commit

    status = kb("curate", "status", run)

    assert status.returncode == 0, status.stderr
    assert (
        f"Committed locally; not published: {commit}. Run: kb curate finish {run}" in status.stdout
    )

    resumed = kb("curate", "finish", run)

    assert resumed.returncode == 0, resumed.stderr
    assert "Published: origin/main\n" in resumed.stdout
    assert _origin_head(kb) == commit


def test_status_of_a_finished_batch_reports_its_publication(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    run = _settled_batch(kb)
    assert kb("curate", "finish", run).returncode == 0

    status = kb("curate", "status", run)

    assert status.returncode == 0, status.stderr
    assert f"Batch is published as {_head(kb)}." in status.stdout


def test_finish_refuses_an_unknown_batch_and_takes_usage_errors(remote_git_kb: Kb) -> None:
    missing = remote_git_kb("curate", "finish", "20261028T120000-deadbeef")
    assert missing.returncode == 1
    assert "batch not found: 20261028T120000-deadbeef" in missing.stderr
    usage = remote_git_kb("curate", "finish")
    assert usage.returncode == 1
    assert usage.stderr == "Usage: kb curate finish RUN [--no-push]\n"
