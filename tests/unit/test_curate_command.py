"""Command helpers that must remain read-only."""

import contextlib
import json
import socket
import subprocess
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from kb import curation, dates, lock, secrets
from kb.commands import curate
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

    exit_code = curate._start(_context(root), root / ".git", budget, [])
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

    assert curate._start(_context(root), root / ".git", 1, []) == 1
    assert "No observations fit --max-bytes 1." in capsys.readouterr().out
    assert not (root / "observations" / "batches").exists()

    empty_root = _make_repo(tmp_path / "empty")
    assert curate._start(_context(empty_root), empty_root / ".git", 10, []) == 1
    assert "No pending observations." in capsys.readouterr().out
    assert not (empty_root / "observations" / "batches").exists()


def test_dispatch_and_nested_command_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert curate.run([]) == 0
    assert "Usage: kb curate {start,status,next} ..." in capsys.readouterr().out
    assert curate.run(["--help"]) == 0
    assert curate.run(["start", "--help"]) == 0
    assert curate.run(["status", "--help"]) == 0
    assert curate.run(["next", "--help"]) == 0
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

    def start(*values: object) -> int:
        observed.extend(values)
        return 7

    monkeypatch.setattr(curate, "_start", start)
    assert curate._start_command(["--max-bytes", "12", "first.md"]) == 7
    assert observed == [context, git_directory, 12, ["first.md"]]

    def fail(*_values: object) -> int:
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
