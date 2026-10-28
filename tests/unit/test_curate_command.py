"""Command helpers that must remain read-only."""

import contextlib
import hashlib
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from kb import archive, config, curation, dates, lock, remote, secrets
from kb.commands import curate
from kb.commands import sync as sync_command
from kb.context import Context
from kb.errors import KbError

RUN = "20261028T120000-a1b2c3d4"


def _make_repo(root: Path, observations: dict[str, str] | None = None) -> Path:
    """Create a small, clean Git content repository for direct command-helper tests."""
    pending = root / "observations" / "pending"
    pending.mkdir(parents=True)
    (root / "knowledge").mkdir()
    (root / "questions" / "open").mkdir(parents=True)
    (root / ".fixture").write_text("Synthetic content repository.\n", encoding="utf-8")
    for filename, text in (observations or {}).items():
        (pending / filename).write_text(text, encoding="utf-8")
    git_commands = [
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.name", "Test Author"],
        ["git", "config", "user.email", "author@example.invalid"],
        ["git", "add", "--all"],
        ["git", "commit", "-q", "-m", "Initialize fixture"],
    ]
    for command in git_commands:
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    return root


def _context(root: Path) -> Context:
    return Context(root, date(2026, 10, 26))


def _observation(title: str, created: str | None, body: str = "A small note.") -> str:
    created_field = f"created: {created}\n" if created is not None else ""
    return f"---\ntitle: {title}\n{created_field}---\n\n{body}\n"


def _commit_repo(root: Path, *paths: str) -> None:
    subprocess.run(["git", "add", "--", *paths], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "Update fixture", "--", *paths],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _new_process(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
    """Run the source package with isolated content and home paths."""
    home = root.parent / "home"
    home.mkdir(exist_ok=True)
    environment = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / "xdg"),
        "KB_CONTENT": str(root),
        "KB_TODAY": "2026-10-26",
        "KB_NOW": "2026-10-26T12:00:00Z",
        "KB_LOCK_WAIT": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.run(
        [sys.executable, "-m", "kb", *words],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )


def _completion_fixture(
    tmp_path: Path, filename: str = "item.md"
) -> tuple[Path, bytes, curation.Batch]:
    """Create a clean repository with one pending member and its manifest."""
    content = _observation("Completion fixture", "2026-10-20", "Evidence to preserve.").encode()
    root = _make_repo(tmp_path / "content", {filename: content.decode()})
    member = curation.make_member(filename, content)
    batch = curation.make_batch(RUN, datetime(2026, 10, 28, tzinfo=UTC), 100, [member])
    batches = root / "observations" / "batches"
    batches.mkdir()
    (batches / f"{RUN}.json").write_text(curation.render_batch(batch), encoding="utf-8")
    return root, content, batch


def _write_destination(root: Path) -> Path:
    """Write a destination with one numbered section."""
    destination = root / "knowledge" / "topic.md"
    destination.write_text(
        "---\ntitle: Topic\n---\n# Topic\n\n## 1. First section\n\nA curated fact.\n",
        encoding="utf-8",
    )
    return destination


def test_start_snapshots_selection_and_reports_related_stale_knowledge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _observation("Special topic", "2026-01-01")
    skipped = _observation("Skipped note", "2026-01-02", "Short.")
    oversized = _observation("Large note", "not-a-date", "x" * 300)
    root = _make_repo(
        tmp_path / "content",
        {"first.md": first, "skip.md": skipped, "large.md": oversized},
    )
    article = root / "knowledge" / "topic.md"
    article.write_text(
        "---\ntitle: Special topic\nupdated: 2020-01-01\nverified: 2020-01-01\n"
        "ttl: 1\n---\n# Special topic\n\nExisting fact.\n",
        encoding="utf-8",
    )
    question = root / "questions" / "open" / "question.md"
    question.write_text("---\ntitle: Open question\ncontext: infra\n---\n\nQuestion.\n")
    _commit_repo(root, "knowledge/topic.md", "questions/open/question.md")
    monkeypatch.setattr(
        dates,
        "now",
        lambda _environment: datetime(2026, 10, 28, 12, tzinfo=UTC),
    )
    budget = len(first.encode("utf-8")) + 10
    assert len(skipped.encode("utf-8")) <= budget
    assert len(first.encode("utf-8")) + len(skipped.encode("utf-8")) > budget
    assert len(oversized.encode("utf-8")) > budget
    original_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout

    exit_code = curate._start(_context(root), root / ".git", budget, [], synchronize=False)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Selected: 1 observation(s)" in output
    assert "Skipped: 2 observation(s)" in output
    assert "Larger than budget: 1 observation(s)" in output
    assert "created date is invalid" in output
    assert "Open questions: 1" in output
    assert "Related stale articles: 1" in output
    manifest_paths = list((root / "observations" / "batches").glob("*.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert [member["filename"] for member in manifest["members"]] == ["first.md"]
    assert not list((root / ".git" / "kb-tmp").iterdir())
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    assert current_head == original_head


def test_start_with_no_fit_or_empty_queue_writes_no_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_repo(tmp_path / "no-fit", {"large.md": _observation("Large", None, "x" * 100)})

    assert curate._start(_context(root), root / ".git", 1, [], synchronize=False) == 1
    assert "No observations fit --max-bytes 1." in capsys.readouterr().out
    assert not (root / "observations" / "batches").exists()

    empty_root = _make_repo(tmp_path / "empty")
    assert curate._start(_context(empty_root), empty_root / ".git", 10, [], synchronize=False) == 1
    assert "No pending observations." in capsys.readouterr().out
    assert not (empty_root / "observations" / "batches").exists()


def test_dispatch_and_nested_command_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert curate.run([]) == 0
    assert (
        "Usage: kb curate {start,status,next,complete,defer,drop,finish} ..."
        in capsys.readouterr().out
    )
    assert curate.run(["--help"]) == 0
    assert curate.run(["start", "--help"]) == 0
    assert curate.run(["status", "--help"]) == 0
    assert curate.run(["next", "--help"]) == 0
    assert curate.run(["defer", "--help"]) == 0
    assert curate.run(["drop", "--help"]) == 0
    with pytest.raises(KbError, match="Usage: kb curate"):
        curate.run(["other"])
    with pytest.raises(KbError, match="Usage: kb curate start"):
        curate._start_command([])
    with pytest.raises(KbError, match="nonnegative ASCII"):
        curate._start_command(["--max-bytes", "-1"])
    with pytest.raises(KbError, match="Usage: kb curate start"):
        monkeypatch.setenv("KB_LOCK_WAIT", "invalid")
        curate._start_command(["--max-bytes", "1"])
    with pytest.raises(KbError, match="Usage: kb curate status"):
        curate._status_command([])
    with pytest.raises(KbError, match="Usage: kb curate next"):
        curate._next_command([])
    with pytest.raises(KbError, match="Usage: kb curate defer"):
        curate._defer_command([])
    with pytest.raises(KbError, match="Usage: kb curate drop"):
        curate._drop_command([])


def test_start_command_holds_the_shared_lock_and_wraps_runtime_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "content"
    root.mkdir()
    context = _context(root)
    git_directory = tmp_path / "git"
    git_directory.mkdir()
    observed: list[object] = []
    monkeypatch.setattr(curate, "load", lambda *_args: context)
    monkeypatch.setattr(lock, "git_dir_path", lambda *_args: git_directory)
    monkeypatch.setattr(lock, "default_backend", lambda *_args: object())
    monkeypatch.setattr(lock, "write_lock", lambda *_args: contextlib.nullcontext())

    def start(*values: object, synchronize: bool) -> int:
        observed.extend(values)
        observed.append(synchronize)
        return 7

    monkeypatch.setattr(curate, "_start", start)
    assert curate._start_command(["--max-bytes", "12", "first.md"]) == 7
    assert observed == [context, git_directory, 12, ["first.md"], True]
    observed.clear()
    assert curate._start_command(["--no-sync", "--max-bytes", "12"]) == 7
    assert observed == [context, git_directory, 12, [], False]

    def fail(*_values: object, **_keywords: object) -> int:
        raise KbError("unexpected failure")

    monkeypatch.setattr(curate, "_start", fail)
    with pytest.raises(KbError, match="curate: unexpected failure"):
        curate._start_command(["--max-bytes", "12"])


def test_status_command_prints_the_report_returned_by_its_read_only_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    context = _context(tmp_path)
    member = curation.make_member("item.md", b"input")
    batch = curation.make_batch(RUN, datetime(2026, 10, 28, tzinfo=UTC), 10, [member])
    monkeypatch.setattr(curate, "load", lambda *_args: context)
    monkeypatch.setattr(curate, "_read_batch", lambda *_args: batch)
    monkeypatch.setattr(curate, "_status", lambda *_args: ("Status output.\n", 1))

    assert curate._status_command([RUN]) == 1
    assert capsys.readouterr().out == "Status output.\n"


def test_start_report_bounds_skipped_oversized_and_stale_lists() -> None:
    inputs = tuple(
        curation.PendingInput(f"item-{index}.md", b"x" * (index + 1), None) for index in range(10)
    )
    selected = curation.Selection(inputs[:1], inputs[1:], inputs[1:], inputs[0].size)
    entries = tuple(curate.QueueEntry(item, None, ("created date is missing",)) for item in inputs)
    stale = tuple(
        curate.StaleArticle(f"knowledge/{index}.md", "stale, verified 2020-01-01")
        for index in range(9)
    )

    report = curate._start_report(RUN, 10, 10, selected, entries, 2, stale)

    assert "... 1 more skipped(s)" in report
    assert "... 1 more larger-than-budget(s)" in report
    assert "... 1 more stale article(s)" in report
    assert report.count("Metadata warning:") == 10


def test_status_does_not_write_call_git_lock_scan_secrets_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "content"
    pending_directory = root / "observations" / "pending"
    batches_directory = root / "observations" / "batches"
    pending_directory.mkdir(parents=True)
    batches_directory.mkdir(parents=True)
    source = pending_directory / "item.md"
    source.write_bytes(b"original input")
    member = curation.make_member(source.name, source.read_bytes())
    batch = curation.make_batch(
        "20261028T120000-a1b2c3d4", datetime(2026, 10, 28, 12, tzinfo=UTC), 100, [member]
    )
    manifest = batches_directory / f"{batch.id}.json"
    manifest.write_text(curation.render_batch(batch), encoding="utf-8")
    before = {path: path.stat().st_mtime_ns for path in (source, manifest)}

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("status attempted an external or writing operation")

    monkeypatch.setattr(curate, "run_process", unexpected)
    monkeypatch.setattr(lock, "write_lock", unexpected)
    monkeypatch.setattr(secrets, "findings", unexpected)
    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(urllib.request, "urlopen", unexpected)

    output, exit_code = curate._status(root, batch)

    assert exit_code == 0
    assert "States: pending=1" in output
    assert {path: path.stat().st_mtime_ns for path in before} == before
    assert sorted(path.name for path in batches_directory.iterdir()) == [manifest.name]


def test_next_is_read_only_and_does_not_call_git_lock_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    filename = "item.md"
    content = _observation("A focused synthetic title", "2026-10-20", "Full body context.")
    root = _make_repo(tmp_path / "content", {filename: content})
    article = root / "knowledge" / "context.md"
    article.write_text(
        "---\ntitle: A focused synthetic title\nverified: 2026-10-20\n---\n"
        "# A focused synthetic title\n\nA matching fact.\n",
        encoding="utf-8",
    )
    _commit_repo(root, "knowledge/context.md")
    context = _context(root)
    pending = root / "observations" / "pending" / filename
    member = curation.make_member(filename, pending.read_bytes())
    batch = curation.make_batch(RUN, datetime(2026, 10, 28, tzinfo=UTC), 100, [member])
    manifest = root / "observations" / "batches" / f"{RUN}.json"
    (manifest.parent).mkdir(parents=True, exist_ok=True)
    manifest.write_text(curation.render_batch(batch), encoding="utf-8")
    before = {path: path.stat().st_mtime_ns for path in (pending, article, manifest)}
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("next attempted an external or writing operation")

    monkeypatch.setattr(curate, "load", lambda *_args: context)
    monkeypatch.setattr(curate, "_read_batch", lambda *_args: batch)
    monkeypatch.setattr(curate, "run_process", unexpected)
    monkeypatch.setattr(lock, "write_lock", unexpected)
    monkeypatch.setattr(secrets, "findings", unexpected)
    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(urllib.request, "urlopen", unexpected)

    assert curate._next_command([RUN]) == 0
    output = capsys.readouterr().out

    assert "Full body context." in output
    assert {path: path.stat().st_mtime_ns for path in before} == before
    current_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    assert current_head == head
    assert not list((root / ".git" / "kb-tmp").glob("*"))


@pytest.mark.parametrize(
    "failure",
    [
        "before_intent",
        "after_intent",
        "before_archive",
        "after_archive",
        "before_remove",
        "after_remove",
        "before_complete",
        "after_complete",
        "interrupt_after_archive",
    ],
)
def test_complete_failure_stages_recover_in_a_new_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    filename = "recovery.md"
    content = _observation("Recoverable observation", "2026-10-20", "Preserve this evidence.")
    root = _make_repo(tmp_path / failure / "content", {filename: content})
    batches = root / "observations" / "batches"
    batches.mkdir()
    member = curation.make_member(
        filename, (root / "observations" / "pending" / filename).read_bytes()
    )
    batch = curation.make_batch(RUN, datetime(2026, 10, 28, tzinfo=UTC), 100, [member])
    manifest = batches / f"{RUN}.json"
    manifest.write_text(curation.render_batch(batch), encoding="utf-8")
    context = _context(root)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    replace_manifest = curate._replace_manifest
    publish_archive = curate._publish_archive
    remove_pending = curate._remove_pending
    replacement_count = 0

    def fail_manifest(git: Path, target: Path, updated: curation.Batch) -> None:
        nonlocal replacement_count
        replacement_count += 1
        target_stage = "intent" if replacement_count == 1 else "complete"
        if failure == f"before_{target_stage}":
            raise OSError(f"injected before {target_stage}")
        replace_manifest(git, target, updated)
        if failure == f"after_{target_stage}":
            raise OSError(f"injected after {target_stage}")

    def fail_publish(*values: object) -> None:
        if failure == "before_archive":
            raise OSError("injected before archive")
        publish_archive(*values)  # type: ignore[arg-type]
        if failure == "after_archive":
            raise OSError("injected after archive")
        if failure == "interrupt_after_archive":
            raise KeyboardInterrupt

    def fail_remove(*values: object) -> None:
        if failure == "before_remove":
            raise OSError("injected before remove")
        remove_pending(*values)  # type: ignore[arg-type]
        if failure == "after_remove":
            raise OSError("injected after remove")

    monkeypatch.setattr(curate, "_replace_manifest", fail_manifest)
    monkeypatch.setattr(curate, "_publish_archive", fail_publish)
    monkeypatch.setattr(curate, "_remove_pending", fail_remove)

    if failure == "interrupt_after_archive":
        with pytest.raises(KeyboardInterrupt):
            curate._complete(context, root / ".git", batch, filename, "ephemeral", [], "Temporary")
    else:
        with pytest.raises((KbError, OSError)):
            curate._complete(context, root / ".git", batch, filename, "ephemeral", [], "Temporary")

    state = curate._read_batch(root, RUN)
    persisted = state.members[0]
    archive_path = root / "observations" / "archived" / filename
    pending_path = root / "observations" / "pending" / filename
    assert not list((root / ".git" / "kb-tmp").glob("*"))
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout
        == head
    )
    assert (
        subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )

    if failure == "before_intent":
        assert persisted.status == "pending"
        assert pending_path.read_text(encoding="utf-8") == content
        assert not archive_path.exists()
        return

    status = _new_process(root, "curate", "status", RUN)
    assert status.returncode == 0, status.stderr
    if failure == "after_complete":
        assert persisted.status == "complete"
        assert "locally settled and unpublished" in status.stdout
        command = [
            "curate",
            "complete",
            RUN,
            filename,
            "--disposition",
            "ephemeral",
            "--reason",
            "Temporary",
        ]
    else:
        assert persisted.status == "archiving"
        recovery_line = next(
            line.strip() for line in status.stdout.splitlines() if "Run: kb curate complete" in line
        )
        command = shlex.split(recovery_line.removeprefix("Run: "))[1:]
    completed = _new_process(root, *command)
    assert completed.returncode == 0, completed.stderr
    assert f"observations/archived/{filename}" in completed.stdout
    assert not pending_path.exists()
    assert archive_path.is_file()
    assert curate._read_batch(root, RUN).members[0].status == "complete"
    assert not list((root / ".git" / "kb-tmp").glob("*"))


@pytest.mark.parametrize("supplied", ["reason", "destination"])
def test_complete_scans_supplied_text_and_cleans_secret_scan_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supplied: str,
) -> None:
    filename = "secret-input.md"
    content = _observation("Secret scan fixture", "2026-10-20")
    root = _make_repo(tmp_path / "content", {filename: content})
    batches = root / "observations" / "batches"
    batches.mkdir()
    member = curation.make_member(
        filename, (root / "observations" / "pending" / filename).read_bytes()
    )
    batch = curation.make_batch(RUN, datetime(2026, 10, 28, tzinfo=UTC), 1000, [member])
    manifest = batches / f"{RUN}.json"
    manifest.write_text(curation.render_batch(batch), encoding="utf-8")
    scan_directory = tmp_path / "secret-scan"
    scan_directory.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: scan_directory)
    secret = 'password = "hunter2hunter2"'
    destinations = [secret] if supplied == "destination" else []
    reason = secret if supplied == "reason" else "Temporary"

    with pytest.raises(KbError, match="possible secret") as refusal:
        curate._complete(
            _context(root),
            root / ".git",
            batch,
            filename,
            "ephemeral" if supplied == "reason" else "incorporated",
            destinations,
            reason if supplied == "reason" else None,
        )

    assert secret not in str(refusal.value)
    assert "Secret Keyword" in str(refusal.value)
    assert sorted(path.name for path in scan_directory.iterdir()) == []
    assert (root / "observations" / "pending" / filename).read_text(encoding="utf-8") == content
    assert manifest.read_text(encoding="utf-8") == curation.render_batch(batch)
    assert not (root / "observations" / "archived" / filename).exists()


@pytest.mark.parametrize(
    ("disposition", "destinations", "reason"),
    [
        ("incorporated", ["knowledge/topic.md#1"], None),
        ("duplicate", ["knowledge/topic.md#1", "knowledge/topic.md#1"], None),
        ("ephemeral", [], "Temporary evidence"),
    ],
)
def test_complete_publishes_each_outcome_and_is_idempotent(
    tmp_path: Path,
    disposition: curation.Disposition,
    destinations: list[str],
    reason: str | None,
) -> None:
    root, original, batch = _completion_fixture(tmp_path)
    destination = _write_destination(root)
    git_directory = root / ".git"

    result = curate._complete(
        _context(root), git_directory, batch, "item.md", disposition, destinations, reason
    )

    archive_path = root / "observations" / "archived" / "item.md"
    archived = archive_path.read_bytes()
    member = curate._read_batch(root, RUN).members[0]
    assert result == "Archived: observations/pending/item.md -> observations/archived/item.md\n"
    assert not (root / "observations" / "pending" / "item.md").exists()
    assert member.status == "complete"
    assert member.disposition == disposition
    assert member.archive_sha256 == hashlib.sha256(archived).hexdigest()
    assert f"original_sha256: {member.original_sha256}".encode() in archived
    assert b"curation_batch: " + RUN.encode() in archived
    if disposition == "ephemeral":
        assert b'curation_reason: "Temporary evidence"' in archived
    else:
        assert member.destinations[0].locator == "knowledge/topic.md#1"
        assert member.destinations[0].heading == "1. First section"
        assert archived.count(b"destination:") == 1
        assert archived.count(b"destination_heading:") == 1
        assert b"knowledge/topic.md#1" in archived
    assert destination.read_text(encoding="utf-8").endswith("A curated fact.\n")
    assert not list((git_directory / "kb-tmp").glob("*"))

    assert (
        curate._complete(
            _context(root),
            git_directory,
            curate._read_batch(root, RUN),
            "item.md",
            disposition,
            destinations,
            reason,
        )
        == result
    )
    assert archive_path.read_bytes() == archived
    assert not list((git_directory / "kb-tmp").glob("*"))
    assert len(original) == member.original_bytes


def test_complete_resumes_when_expected_archive_is_already_published(
    tmp_path: Path,
) -> None:
    root, original, batch = _completion_fixture(tmp_path)
    member = batch.members[0]
    archived = archive.render(
        original.decode(), "ephemeral", member.original_sha256, RUN, (), "Temporary"
    ).encode()
    intent = curation.begin_archive(
        member, "ephemeral", (), "Temporary", hashlib.sha256(archived).hexdigest()
    )
    intent_batch = curation.replace_member(batch, intent)
    manifest = root / "observations" / "batches" / f"{RUN}.json"
    manifest.write_text(curation.render_batch(intent_batch), encoding="utf-8")
    archived_path = root / "observations" / "archived" / member.filename
    archived_path.parent.mkdir()
    archived_path.write_bytes(archived)

    result = curate._complete(
        _context(root), root / ".git", intent_batch, member.filename, "ephemeral", [], "Temporary"
    )

    assert result.startswith("Archived: observations/pending/")
    assert not (root / "observations" / "pending" / member.filename).exists()
    assert archived_path.read_bytes() == archived
    assert curate._read_batch(root, RUN).members[0].status == "complete"


@pytest.mark.parametrize(
    ("disposition", "destinations", "reason", "message"),
    [
        ("ephemeral", ["knowledge/topic.md#1"], "Temporary", "does not accept destinations"),
        ("ephemeral", [], None, "nonempty single-line --reason"),
        ("ephemeral", [], "two\nlines", "nonempty single-line --reason"),
        ("incorporated", ["knowledge/topic.md#1"], "extra", "only valid for an ephemeral"),
        ("incorporated", [], None, "needs at least one knowledge destination"),
        ("incorporated", ["knowledge/missing.md"], None, "no such destination"),
        ("incorporated", ["observations/pending/item.md"], None, "must resolve under knowledge/"),
        ("incorporated", ["knowledge/topic.md#9"], None, "has no section 9"),
        ("duplicate", ["knowledge/topic.md"], None, "must name numbered sections"),
        ("duplicate", ["knowledge/topic.md#title"], None, "must name numbered sections"),
    ],
)
def test_requested_destinations_rejects_invalid_outcome_inputs(
    tmp_path: Path,
    disposition: curation.Disposition,
    destinations: list[str],
    reason: str | None,
    message: str,
) -> None:
    root, _content, _batch = _completion_fixture(tmp_path)
    _write_destination(root)

    with pytest.raises(KbError, match=message):
        curate._requested_destinations(root, destinations, disposition, reason)


def test_requested_destinations_canonicalizes_aliases_and_checks_containment(
    tmp_path: Path,
) -> None:
    root, _content, _batch = _completion_fixture(tmp_path)
    _write_destination(root)
    destinations = curate._requested_destinations(
        root,
        ["topic.md#1", "knowledge/topic.md#1"],
        "incorporated",
        None,
    )

    assert destinations == (curation.Destination("knowledge/topic.md#1", "1. First section"),)

    outside = tmp_path / "outside.md"
    outside.write_text("---\ntitle: Outside\n---\n# Outside\n", encoding="utf-8")
    escaped = root / "knowledge" / "escaped.md"
    escaped.symlink_to(outside)
    with pytest.raises(KbError, match="outside the content repository"):
        curate._requested_destinations(root, ["knowledge/escaped.md"], "incorporated", None)


def test_complete_rejects_missing_member_changed_input_and_preexisting_archive(
    tmp_path: Path,
) -> None:
    root, original, batch = _completion_fixture(tmp_path)
    with pytest.raises(KbError, match="not a batch member"):
        curate._complete(
            _context(root), root / ".git", batch, "other.md", "ephemeral", [], "reason"
        )

    pending = root / "observations" / "pending" / "item.md"
    pending.write_bytes(b"changed")
    with pytest.raises(KbError, match="input is changed or missing"):
        curate._complete(_context(root), root / ".git", batch, "item.md", "ephemeral", [], "reason")
    pending.write_bytes(original)

    archive_path = root / "observations" / "archived" / "item.md"
    archive_path.parent.mkdir()
    archive_path.write_bytes(b"existing archive")
    with pytest.raises(KbError, match="archive already exists"):
        curate._complete(_context(root), root / ".git", batch, "item.md", "ephemeral", [], "reason")


def test_archive_publication_never_replaces_a_file_created_after_precheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _original, _batch = _completion_fixture(tmp_path)
    archive_directory = root / "observations" / "archived"
    archive_directory.mkdir()
    archive_path = archive_directory / "item.md"
    real_link = os.link

    def create_competing_archive(source: Path, target: Path) -> None:
        target.write_bytes(b"concurrent archive")
        real_link(source, target)

    monkeypatch.setattr(os, "link", create_competing_archive)
    with pytest.raises(KbError, match="archive already exists"):
        curate._publish_archive(root, root / ".git", "item.md", b"expected archive", 0o600)

    assert archive_path.read_bytes() == b"concurrent archive"
    assert not list((root / ".git" / "kb-tmp").glob("*"))


def test_complete_rejects_conflicting_retries_and_preserves_recovery_commands(
    tmp_path: Path,
) -> None:
    root, original, batch = _completion_fixture(tmp_path / "completed")
    curate._complete(_context(root), root / ".git", batch, "item.md", "ephemeral", [], "Temporary")
    complete_batch = curate._read_batch(root, RUN)
    with pytest.raises(KbError, match="different outcome"):
        curate._complete(
            _context(root), root / ".git", complete_batch, "item.md", "ephemeral", [], "Other"
        )
    (root / "observations" / "pending" / "item.md").write_bytes(original)
    with pytest.raises(KbError, match="still has a pending copy"):
        curate._complete(
            _context(root),
            root / ".git",
            complete_batch,
            "item.md",
            "ephemeral",
            [],
            "Temporary",
        )

    root, original, batch = _completion_fixture(tmp_path / "archiving")
    member = batch.members[0]
    archived = archive.render(
        original.decode(), "ephemeral", member.original_sha256, RUN, (), "Temporary"
    ).encode()
    intent = curation.begin_archive(
        member, "ephemeral", (), "Temporary", hashlib.sha256(archived).hexdigest()
    )
    intent_batch = curation.replace_member(batch, intent)
    manifest = root / "observations" / "batches" / f"{RUN}.json"
    manifest.write_text(curation.render_batch(intent_batch), encoding="utf-8")
    with pytest.raises(KbError, match="resume with: kb curate complete"):
        curate._complete(
            _context(root), root / ".git", intent_batch, "item.md", "ephemeral", [], ""
        )
    _write_destination(root)
    with pytest.raises(KbError, match="differs from the stored archive intent"):
        curate._complete(
            _context(root),
            root / ".git",
            intent_batch,
            "item.md",
            "incorporated",
            ["knowledge/topic.md#1"],
            None,
        )
    archive_path = root / "observations" / "archived" / "item.md"
    archive_path.parent.mkdir()
    archive_path.write_bytes(b"conflicting archive")
    with pytest.raises(KbError, match="archive operation failed: curate: archive conflicts"):
        curate._complete(
            _context(root),
            root / ".git",
            intent_batch,
            "item.md",
            "ephemeral",
            [],
            "Temporary",
        )


def test_complete_archiving_intent_refuses_destination_heading_drift(tmp_path: Path) -> None:
    root, original, batch = _completion_fixture(tmp_path)
    destination = _write_destination(root)
    requested = curate._requested_destinations(root, ["knowledge/topic.md#1"], "incorporated", None)
    member = batch.members[0]
    archived = archive.render(
        original.decode(), "incorporated", member.original_sha256, RUN, requested, None
    ).encode()
    intent = curation.begin_archive(
        member, "incorporated", requested, None, hashlib.sha256(archived).hexdigest()
    )
    intent_batch = curation.replace_member(batch, intent)
    manifest = root / "observations" / "batches" / f"{RUN}.json"
    manifest.write_text(curation.render_batch(intent_batch), encoding="utf-8")
    destination.write_text(
        "---\ntitle: Topic\n---\n# Topic\n\n## 1. Renamed section\n\nA curated fact.\n",
        encoding="utf-8",
    )

    with pytest.raises(KbError, match="destination heading changed since the archive intent"):
        curate._complete(
            _context(root),
            root / ".git",
            intent_batch,
            "item.md",
            "incorporated",
            ["knowledge/topic.md#1"],
            None,
        )


def test_resume_archive_detects_heading_drift_and_completed_file_conflicts(tmp_path: Path) -> None:
    root, _original, batch = _completion_fixture(tmp_path)
    destination = _write_destination(root)
    destination_locator = curate._requested_destinations(
        root, ["knowledge/topic.md#1"], "incorporated", None
    )
    member = batch.members[0]
    source = (root / "observations" / "pending" / member.filename).read_text(encoding="utf-8")
    archived = archive.render(
        source, "incorporated", member.original_sha256, RUN, destination_locator, None
    ).encode()
    intent = curation.begin_archive(
        member,
        "incorporated",
        destination_locator,
        None,
        hashlib.sha256(archived).hexdigest(),
    )
    destination.write_text(
        "---\ntitle: Topic\n---\n# Topic\n\n## 1. Renamed section\n\nA curated fact.\n",
        encoding="utf-8",
    )
    with pytest.raises(KbError, match="destination heading changed"):
        curate._resume_archive(_context(root), root / ".git", batch, intent)

    destination.write_text(
        "---\ntitle: Topic\n---\n# Topic\n\n## 1. First section\n\nA curated fact.\n",
        encoding="utf-8",
    )
    completed = curation.finish_archive(intent)
    complete_batch = curation.replace_member(batch, completed)
    (root / "observations" / "pending" / member.filename).unlink()
    archive_path = root / "observations" / "archived" / member.filename
    archive_path.parent.mkdir()
    archive_path.write_bytes(b"changed archive")
    manifest = root / "observations" / "batches" / f"{RUN}.json"
    manifest.write_text(curation.render_batch(complete_batch), encoding="utf-8")
    with pytest.raises(KbError, match="archive is missing or changed"):
        curate._complete(
            _context(root),
            root / ".git",
            complete_batch,
            member.filename,
            "incorporated",
            ["knowledge/topic.md#1"],
            None,
        )


def test_inbound_reference_resolver_ignores_external_paths_and_reports_local_paths(
    tmp_path: Path,
) -> None:
    root, _original, _batch = _completion_fixture(tmp_path)
    _write_destination(root)
    inbound = root / "knowledge" / "inbound.md"
    inbound.write_text(
        "---\ntitle: Inbound\n---\n\n[external](https://example.invalid/a.md)\n"
        "[pending](../observations/pending/item.md#1)\n",
        encoding="utf-8",
    )

    with pytest.raises(KbError, match="references still target the pending observation"):
        curate._refuse_inbound_pending_references(root, "item.md")

    inbound.write_text(
        "---\ntitle: Inbound\n---\n\n[external](https://example.invalid/a.md)\n"
        "[absolute](/observations/pending/item.md)\n[drive](C:\\observations\\pending\\item.md)\n",
        encoding="utf-8",
    )
    curate._refuse_inbound_pending_references(root, "item.md")


def test_transition_member_defers_unchanged_input_and_allows_identical_retries(
    tmp_path: Path,
) -> None:
    root, original, batch = _completion_fixture(tmp_path)

    result = curate._transition_member(
        _context(root), root / ".git", batch, "item.md", "Need owner input", "deferred"
    )

    manifest = curate._read_batch(root, RUN)
    assert result == f"Deferred: item.md in batch {RUN}\n"
    assert manifest.members[0].status == "deferred"
    assert manifest.members[0].reason == "Need owner input"
    assert (root / "observations" / "pending" / "item.md").read_bytes() == original
    assert curation.is_settled(manifest)
    assert (
        curate._transition_member(
            _context(root), root / ".git", manifest, "item.md", "Need owner input", "deferred"
        )
        == result
    )
    with pytest.raises(KbError, match="already deferred with a different reason"):
        curate._transition_member(
            _context(root), root / ".git", manifest, "item.md", "Different reason", "deferred"
        )


@pytest.mark.parametrize("disk_state", ["changed", "missing"])
def test_transition_member_drops_changed_or_missing_input_without_modifying_it(
    tmp_path: Path, disk_state: str
) -> None:
    root, _original, batch = _completion_fixture(tmp_path)
    pending = root / "observations" / "pending" / "item.md"
    if disk_state == "changed":
        pending.write_bytes(b"newer bytes from another writer")
        expected = pending.read_bytes()
    else:
        pending.unlink()
        expected = None

    result = curate._transition_member(
        _context(root),
        root / ".git",
        batch,
        "item.md",
        "Input changed outside the batch",
        "dropped",
    )

    member = curate._read_batch(root, RUN).members[0]
    assert result == f"Dropped: item.md in batch {RUN}\n"
    assert member.status == "dropped"
    assert member.reason == "Input changed outside the batch"
    assert curation.is_settled(curate._read_batch(root, RUN))
    if expected is None:
        assert not pending.exists()
    else:
        assert pending.read_bytes() == expected
    with pytest.raises(KbError, match="already dropped with a different reason"):
        curate._transition_member(
            _context(root),
            root / ".git",
            curate._read_batch(root, RUN),
            "item.md",
            "Different reason",
            "dropped",
        )


def test_transition_member_refuses_the_wrong_file_state_and_scans_reasons(
    tmp_path: Path,
) -> None:
    root, _original, batch = _completion_fixture(tmp_path)
    with pytest.raises(KbError, match="input is unchanged; use defer"):
        curate._transition_member(
            _context(root), root / ".git", batch, "item.md", "Reason", "dropped"
        )
    (root / "observations" / "pending" / "item.md").write_bytes(b"changed")
    with pytest.raises(KbError, match="input is changed or missing; use drop"):
        curate._transition_member(
            _context(root), root / ".git", batch, "item.md", "Reason", "deferred"
        )
    for reason in ("", "two\nlines"):
        with pytest.raises(KbError, match="reason must be nonempty and single-line"):
            curate._transition_member(
                _context(root), root / ".git", batch, "item.md", reason, "dropped"
            )
    with pytest.raises(KbError, match="not a batch member"):
        curate._transition_member(
            _context(root), root / ".git", batch, "missing.md", "Reason", "dropped"
        )


def test_transition_commands_run_under_shared_lock_and_handle_usage_and_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    keep = _observation("Keep for later", "2026-10-20")
    changed = _observation("Changed elsewhere", "2026-10-21")
    root = _make_repo(tmp_path / "content", {"keep.md": keep, "changed.md": changed})
    members = [
        curation.make_member("keep.md", (root / "observations/pending/keep.md").read_bytes()),
        curation.make_member("changed.md", (root / "observations/pending/changed.md").read_bytes()),
    ]
    batch = curation.make_batch(RUN, datetime(2026, 10, 28, tzinfo=UTC), 1000, members)
    batches = root / "observations" / "batches"
    batches.mkdir()
    (batches / f"{RUN}.json").write_text(curation.render_batch(batch), encoding="utf-8")
    context = _context(root)
    git_directory = root / ".git"
    monkeypatch.setattr(curate, "load", lambda *_args: context)
    monkeypatch.setattr(lock, "git_dir_path", lambda *_args: git_directory)
    monkeypatch.setattr(lock, "default_backend", lambda *_args: object())
    monkeypatch.setattr(lock, "write_lock", lambda *_args: contextlib.nullcontext())
    monkeypatch.setenv("KB_LOCK_WAIT", "1")

    assert curate._defer_command([RUN, "keep.md", "--reason", "Need more evidence"]) == 0
    assert capsys.readouterr().out == f"Deferred: keep.md in batch {RUN}\n"
    changed_path = root / "observations" / "pending" / "changed.md"
    changed_path.write_text("modified by another writer", encoding="utf-8")
    assert curate._drop_command([RUN, "changed.md", "--reason", "Input changed"]) == 0
    assert capsys.readouterr().out == f"Dropped: changed.md in batch {RUN}\n"
    assert changed_path.read_text(encoding="utf-8") == "modified by another writer"

    monkeypatch.setenv("KB_LOCK_WAIT", "bad")
    with pytest.raises(KbError, match="Usage: kb curate drop"):
        curate._drop_command([RUN, "changed.md", "--reason", "Input changed"])
    monkeypatch.setenv("KB_LOCK_WAIT", "1")

    def busy(*_args: object) -> None:
        raise lock.LockBusy(1)

    monkeypatch.setattr(lock, "write_lock", busy)
    with pytest.raises(KbError, match="content repository is busy"):
        curate._drop_command([RUN, "changed.md", "--reason", "Input changed"])


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (remote.Result(pulled=2, pushed=3), "Pulled: 2 commit(s)\nPushed: 3 commit(s)\n"),
        (remote.Result(already_in_sync=True), "Already in sync.\n"),
    ],
)
def test_synchronize_prints_the_remote_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: remote.Result,
    expected: str,
) -> None:
    monkeypatch.setattr(config, "read_harvest_since", lambda _configuration: None)
    monkeypatch.setattr(sync_command, "recover_and_harvest", lambda *_args: ((), ()))
    monkeypatch.setattr(remote, "synchronize", lambda *_args, **_kwargs: outcome)

    curate._synchronize(tmp_path, tmp_path / ".git")

    assert capsys.readouterr().out == expected


def test_synchronize_writes_harvest_warnings_and_errors_before_the_remote_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(config, "read_harvest_since", lambda _configuration: None)
    monkeypatch.setattr(
        sync_command,
        "recover_and_harvest",
        lambda *_args: (("rewritten transcript",), ("sync: skipped session one: reason",)),
    )
    monkeypatch.setattr(
        remote, "synchronize", lambda *_args, **_kwargs: remote.Result(already_in_sync=True)
    )

    curate._synchronize(tmp_path, tmp_path / ".git")

    captured = capsys.readouterr()
    assert captured.err == (
        "sync: warning: rewritten transcript\nsync: skipped session one: reason\n"
    )
    assert captured.out == "Already in sync.\n"


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (
            remote.Result(skipped_dirty=("a.md", "b.md")),
            "curate: no batch created; uncommitted changes: a.md, b.md",
        ),
        (
            remote.Result(errors=("sync: no origin remote", "sync: second")),
            "curate: no batch created; sync: no origin remote; sync: second",
        ),
    ],
)
def test_synchronize_refuses_before_any_batch_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: remote.Result,
    message: str,
) -> None:
    monkeypatch.setattr(config, "read_harvest_since", lambda _configuration: None)
    monkeypatch.setattr(sync_command, "recover_and_harvest", lambda *_args: ((), ()))
    monkeypatch.setattr(remote, "synchronize", lambda *_args, **_kwargs: outcome)

    with pytest.raises(KbError) as refused:
        curate._synchronize(tmp_path, tmp_path / ".git")

    assert str(refused.value) == message


def test_head_commit_refuses_a_repository_without_commits(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)

    with pytest.raises(KbError, match="curate: cannot read HEAD"):
        curate._head_commit(tmp_path)


def test_synchronized_start_takes_the_writer_lock_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _make_repo(
        tmp_path / "content",
        {"20261024T094659-8d6fecbe.md": _observation("Lock once", "2026-10-24")},
    )
    monkeypatch.setenv("KB_CONTENT", str(root))
    monkeypatch.setenv("KB_NOW", "2026-10-28T12:00:00Z")
    monkeypatch.setenv("KB_TODAY", "2026-10-28")
    taken: list[Path] = []
    real_write_lock = lock.write_lock

    @contextlib.contextmanager
    def counting(git: Path, content: Path, wait: int, backend: lock.Backend) -> Iterator[None]:
        taken.append(git)
        with real_write_lock(git, content, wait, backend):
            yield

    monkeypatch.setattr(lock, "write_lock", counting)
    monkeypatch.setattr(config, "read_harvest_since", lambda _configuration: None)
    monkeypatch.setattr(sync_command, "recover_and_harvest", lambda *_args: ((), ()))
    monkeypatch.setattr(
        remote, "synchronize", lambda *_args, **_kwargs: remote.Result(already_in_sync=True)
    )

    assert curate.run(["start", "--max-bytes", "100000"]) == 0
    assert len(taken) == 1
