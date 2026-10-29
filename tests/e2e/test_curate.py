"""End-to-end tests for local curation batch selection, status, and next context."""

import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from .harness import HOLD_KERNEL_LOCK, TODAY, Kb, make_git_kb

RUN_RE = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")


def _run_id(result: CompletedProcess[str]) -> str:
    match = RUN_RE.search(result.stdout)
    assert match is not None, result.stdout
    return match.group(1)


def _pending(kb: Kb, filename: str) -> Path:
    return kb.content / "observations" / "pending" / filename


def _write_article(kb: Kb, relative: str, content: str) -> Path:
    path = kb.content / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _member(
    filename: str,
    content: bytes,
    *,
    status: str = "pending",
    disposition: str | None = None,
    destinations: list[dict[str, str | None]] | None = None,
    reason: str | None = None,
    archived: bytes | None = None,
) -> dict[str, object]:
    return {
        "filename": filename,
        "original_sha256": hashlib.sha256(content).hexdigest(),
        "original_bytes": len(content),
        "status": status,
        "disposition": disposition,
        "destinations": [] if destinations is None else destinations,
        "reason": reason,
        "archive_sha256": hashlib.sha256(archived).hexdigest() if archived is not None else None,
    }


def _write_batch(
    kb: Kb, run_id: str, members: list[dict[str, object]], max_bytes: int | None = None
) -> Path:
    directory = kb.content / "observations" / "batches"
    directory.mkdir(parents=True, exist_ok=True)
    selected_bytes = sum(_member_size(member) for member in members)
    manifest = {
        "schema_version": 1,
        "id": run_id,
        "created": "2026-10-26T12:00:00Z",
        "max_bytes": selected_bytes if max_bytes is None else max_bytes,
        "selected_bytes": selected_bytes,
        "members": members,
    }
    path = directory / f"{run_id}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _member_size(member: dict[str, object]) -> int:
    """The byte total in a manifest helper row."""
    value = member["original_bytes"]
    assert isinstance(value, int)
    return value


def _commit(kb: Kb, *paths: str) -> None:
    kb.git("add", "--", *paths)
    kb.git("commit", "-q", "-m", "Prepare curation fixture", "--", *paths)


def _failure(result: CompletedProcess[str], text: str) -> None:
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("curate:")
    assert text in result.stderr


def _interrupt_archive(kb: Kb, *arguments: str) -> CompletedProcess[str]:
    """Fail archive publication after the command has persisted its intent."""
    words = ["curate", "complete", *arguments]
    script = (
        "from kb import cli\n"
        "from kb.commands import curate\n"
        "def interrupt(*_args, **_kwargs):\n"
        "    raise OSError('injected interruption')\n"
        "curate._publish_archive = interrupt\n"
        f"raise SystemExit(cli.main({words!r}))\n"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=kb.home,
        env=kb.environment({}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def test_start_help_usage_and_budget_validation(git_kb: Kb) -> None:
    help_result = git_kb("curate", "start", "--help")
    assert help_result.returncode == 0
    assert help_result.stdout.startswith(
        "Usage: kb curate start [--no-sync] --max-bytes N [FILENAME...]\n\n"
    )
    assert git_kb("curate").stdout.startswith(
        "Usage: kb curate {start,status,next,complete,defer,drop,finish} ..."
    )

    missing = git_kb("curate", "start")
    assert missing.returncode == 1
    assert missing.stdout == ""
    assert missing.stderr == "Usage: kb curate start [--no-sync] --max-bytes N [FILENAME...]\n"
    for budget in ("-1", "1.5", chr(0x661)):
        invalid = git_kb("curate", "start", "--no-sync", "--max-bytes", budget)
        _failure(invalid, "nonnegative ASCII decimal integer")


def test_start_snapshots_date_ordered_inputs_and_stale_context(git_kb: Kb) -> None:
    names = [path.name for path in (git_kb.content / "observations/pending").glob("*.md")]
    contents = {name: _pending(git_kb, name).read_bytes() for name in names}
    head = git_kb.git("rev-parse", "HEAD")

    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "100000")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    run_id = _run_id(result)
    manifest_path = git_kb.content / "observations/batches" / f"{run_id}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [member["filename"] for member in manifest["members"]] == [
        "20261024T094659-8d6fecbe.md",
        "20261025T180000-1f2e3d4c.md",
    ]
    assert manifest["selected_bytes"] == sum(map(len, contents.values()))
    assert [member["original_sha256"] for member in manifest["members"]] == [
        hashlib.sha256(contents[name]).hexdigest() for name in manifest_member_names(manifest)
    ]
    assert result.stdout.startswith(
        f"Not synchronized: local batch\nCreated batch: {run_id}\nSelected: 2 observation(s)\n"
    )
    assert "Eligible pending observations: 2" in result.stdout
    assert "Open questions: " in result.stdout
    assert "Related stale articles: " in result.stdout
    assert git_kb.git("rev-parse", "HEAD") == head
    assert manifest_path.is_file()


def manifest_member_names(manifest: dict[str, object]) -> list[str]:
    """The ordered filenames stored in a parsed manifest."""
    members = manifest["members"]
    assert isinstance(members, list)
    return [str(member["filename"]) for member in members]


def test_explicit_selection_preserves_order_and_counts_utf8_bytes(git_kb: Kb) -> None:
    first = _pending(git_kb, "first café.md")
    second = _pending(git_kb, "second.md")
    first_text = '---\ntitle: "Café"\ncreated: 2026-10-20\n---\n\nRésumé.\n'
    second_text = "---\ntitle: Second\ncreated: 2026-10-21\n---\n\nText.\n"
    first.write_text(first_text, encoding="utf-8")
    second.write_text(second_text, encoding="utf-8")
    _commit(git_kb, "observations/pending/first café.md", "observations/pending/second.md")

    result = git_kb(
        "curate",
        "start",
        "--no-sync",
        "--max-bytes",
        str(len(first_text.encode()) + len(second_text.encode())),
        "second.md",
        "first café.md",
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (git_kb.content / "observations/batches" / f"{_run_id(result)}.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest_member_names(manifest) == ["second.md", "first café.md"]
    assert manifest["selected_bytes"] == len(first_text.encode()) + len(second_text.encode())


def test_selection_skips_nonfitting_items_then_uses_remaining_budget(git_kb: Kb) -> None:
    pending_dir = git_kb.content / "observations/pending"
    for filename, size in (("a-first.md", 500), ("b-skip.md", 700), ("c-fit.md", 100)):
        path = pending_dir / filename
        path.write_text(
            "---\ntitle: " + filename + "\ncreated: 2026-10-20\n---\n\n" + "x" * size,
            encoding="utf-8",
        )
    paths = [f"observations/pending/{name}" for name in ("a-first.md", "b-skip.md", "c-fit.md")]
    _commit(git_kb, *paths)

    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "700")

    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (git_kb.content / "observations/batches" / f"{_run_id(result)}.json").read_text(
            encoding="utf-8"
        )
    )
    names = manifest_member_names(manifest)
    assert names.index("a-first.md") < names.index("c-fit.md")
    assert "b-skip.md" not in names
    assert "Skipped: " in result.stdout


def test_zero_budget_creates_no_manifest(git_kb: Kb) -> None:
    before = set((git_kb.content / "observations/batches").glob("*.json"))

    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "0")

    assert result.returncode == 1
    assert result.stderr == ""
    assert "No observations fit --max-bytes 0." in result.stdout
    assert set((git_kb.content / "observations/batches").glob("*.json")) == before


def test_larger_than_budget_report_gives_a_working_single_item_command(git_kb: Kb) -> None:
    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "10")

    assert result.returncode == 1
    assert result.stderr == ""
    assert "Larger than budget:" in result.stdout
    line = next(
        line
        for line in result.stdout.splitlines()
        if "Larger than --max-bytes; select alone:" in line
    )
    command = shlex.split(line.strip().removeprefix("Larger than --max-bytes; select alone: "))
    assert command[:4] == ["kb", "curate", "start", "--max-bytes"]
    # The fixture has no origin, so the suggested synchronized command runs offline.
    suggested = git_kb(*command[1:], "--no-sync")
    assert suggested.returncode == 0, suggested.stderr
    assert "Selected: 1 observation(s)" in suggested.stdout


def test_empty_queue_fails_without_publishing(git_kb: Kb) -> None:
    for path in (git_kb.content / "observations/pending").glob("*.md"):
        path.unlink()
    _commit(
        git_kb,
        "observations/pending/20261024T094659-8d6fecbe.md",
        "observations/pending/20261025T180000-1f2e3d4c.md",
    )

    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "100")

    assert result.returncode == 1
    assert "Eligible pending observations: 0" in result.stdout
    assert "No pending observations." in result.stdout
    assert not list((git_kb.content / "observations/batches").glob("*.json"))


def test_start_requires_git_metadata(kb: Kb) -> None:
    no_git = kb("curate", "start", "--no-sync", "--max-bytes", "10000")
    _failure(no_git, "Git directory")


def test_start_requires_a_clean_index_and_worktree(git_kb: Kb) -> None:
    staged = git_kb.content / "staged.txt"
    staged.write_text("staged\n", encoding="utf-8")
    git_kb.git("add", "--", "staged.txt")
    dirty_index = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")
    _failure(dirty_index, "uncommitted changes")

    git_kb.git("reset", "-q", "--", "staged.txt")
    staged.unlink()
    untracked = git_kb.content / "untracked.txt"
    untracked.write_text("untracked\n", encoding="utf-8")
    dirty_worktree = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")
    _failure(dirty_worktree, "uncommitted changes")


def test_start_rejects_pending_batches(git_kb: Kb) -> None:
    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")
    assert result.returncode == 0, result.stderr

    # Commit the new batch so the clean-tree gate passes and the active-batch gate is tested.
    run_id = _run_id(result)
    _commit(git_kb, f"observations/batches/{run_id}.json")
    blocked = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")
    _failure(blocked, "pending or archiving work")


def test_start_rejects_malformed_new_manifests_and_allows_settled_batches(git_kb: Kb) -> None:
    directory = git_kb.content / "observations/batches"
    directory.mkdir(parents=True, exist_ok=True)
    malformed_id = "20261028T120000-a1b2c3d4"
    malformed = directory / f"{malformed_id}.json"
    malformed.write_text('{"schema_version": 1, "schema_version": 1}\n', encoding="utf-8")
    _commit(git_kb, f"observations/batches/{malformed.name}")

    refused = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")
    _failure(refused, "malformed batch manifest")

    malformed.unlink()
    content = _pending(git_kb, "settled-later.md")
    content.write_bytes(b"kept for another batch")
    settled_id = "20261028T120001-b1b2c3d4"
    settled = _write_batch(
        git_kb,
        settled_id,
        [_member(content.name, content.read_bytes(), status="deferred", reason="Later")],
    )
    _commit(git_kb, f"observations/batches/{malformed.name}")
    _commit(git_kb, f"observations/pending/{content.name}", f"observations/batches/{settled.name}")

    allowed = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")

    assert allowed.returncode == 0, allowed.stderr
    assert "Created batch:" in allowed.stdout


def test_ignored_nested_markdown_is_not_eligible_or_reported(git_kb: Kb) -> None:
    nested = git_kb.content / "observations/pending/nested/ignored.md"
    nested.parent.mkdir()
    nested.write_text("---\ntitle: Nested\n---\n\nNested text.\n", encoding="utf-8")
    ignore = git_kb.content / ".gitignore"
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    ignore.write_text(existing + "observations/pending/nested/\n", encoding="utf-8")
    _commit(git_kb, ".gitignore")

    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")

    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (git_kb.content / "observations/batches" / f"{_run_id(result)}.json").read_text(
            encoding="utf-8"
        )
    )
    assert "nested/ignored.md" not in manifest_member_names(manifest)
    assert "nested/ignored.md" not in result.stdout


def test_pending_symlink_is_refused(git_kb: Kb, tmp_path: Path) -> None:
    target = tmp_path / "outside.md"
    target.write_text("---\ntitle: Outside\n---\n", encoding="utf-8")
    link = _pending(git_kb, "linked.md")
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    _commit(git_kb, "observations/pending/linked.md")

    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "10000")

    _failure(result, "symlink")
    assert not list((git_kb.content / "observations/batches").glob("*.json"))


def test_repository_and_filename_paths_with_spaces_are_safe(tmp_path: Path) -> None:
    git_kb = make_git_kb(tmp_path / "repository path with spaces")
    content = _pending(git_kb, "20261028T010000-a space.md")
    content.write_text("---\ntitle: A spaced path\ncreated: 2026-10-20\n---\n", encoding="utf-8")
    _commit(git_kb, "observations/pending/20261028T010000-a space.md")

    result = git_kb(
        "curate", "start", "--no-sync", "--max-bytes", str(len(content.read_bytes())), content.name
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (git_kb.content / "observations/batches" / f"{_run_id(result)}.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest_member_names(manifest) == [content.name]


def test_later_observe_and_gap_commits_do_not_change_the_selected_set(git_kb: Kb) -> None:
    started = git_kb("curate", "start", "--no-sync", "--max-bytes", "100000")
    assert started.returncode == 0, started.stderr
    run_id = _run_id(started)
    manifest_path = git_kb.content / "observations/batches" / f"{run_id}.json"
    selected = manifest_member_names(json.loads(manifest_path.read_text(encoding="utf-8")))

    observed = git_kb("observe", "--title", "Arrived later", "--body", "A new observation.")
    assert observed.returncode == 0, observed.stderr
    gap = git_kb(
        "gap",
        "--title",
        "Later question",
        "--body",
        "A separate unanswered question.",
        "--context",
        "infra",
    )
    assert gap.returncode == 0, gap.stderr

    unchanged = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_member_names(unchanged) == selected
    assert observed.stdout.removeprefix("Wrote: ").strip().split("/")[-1] not in selected
    status = git_kb("curate", "status", run_id)
    assert status.returncode == 0, status.stderr
    assert "locally settled" not in status.stdout


def test_related_stale_article_report_is_deduplicated_and_bounded(git_kb: Kb) -> None:
    pending_dir = git_kb.content / "observations/pending"
    article_paths: list[str] = []
    for index in range(10):
        title = f"Curation spotlight token {index}"
        article = git_kb.content / f"knowledge/spotlight-{index}.md"
        article.write_text(
            f"---\ntitle: {title}\nupdated: 2020-01-01\nverified: 2020-01-01\nttl: 1\n---\n"
            f"# {title}\n\nA distinct maintenance fact.\n",
            encoding="utf-8",
        )
        filename = f"20261028T0000{index:02d}-a1b2c3d4.md"
        (pending_dir / filename).write_text(
            f"---\ntitle: {title}\ncreated: 2026-10-20\n---\n\nReview this fact.\n",
            encoding="utf-8",
        )
        article_paths.append(f"knowledge/spotlight-{index}.md")
    _commit(
        git_kb,
        *article_paths,
        *(f"observations/pending/{path.name}" for path in pending_dir.glob("20261028*.md")),
    )

    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "100000")

    assert result.returncode == 0, result.stderr
    assert "Related stale articles: 10" in result.stdout
    stale_block = result.stdout.split("Related stale knowledge:\n", 1)[1]
    stale_lines = [line for line in stale_block.splitlines() if line.startswith("  ")]
    assert sum("knowledge/spotlight-" in line for line in stale_lines) == 8
    assert any("2 more stale article(s)" in line for line in stale_lines)


def test_status_reports_all_states_recovery_and_unpublished_settlement(kb: Kb) -> None:
    filename = "20261024T094659-8d6fecbe.md"
    original = _pending(kb, filename).read_bytes()
    archive = original + b"archive\n"
    members = [
        _member(
            filename,
            original,
            status="archiving",
            disposition="ephemeral",
            reason="Session-only",
            archived=archive,
        ),
        _member("deferred.md", b"Deferred", status="deferred", reason="Need owner input"),
        _member("dropped.md", b"Dropped", status="dropped", reason="Input changed"),
    ]
    run_id = "20261028T120000-a1b2c3d4"
    _write_batch(kb, run_id, members)

    result = kb("curate", "status", run_id)

    assert result.returncode == 0, result.stderr
    assert "States: pending=0, archiving=1, complete=0, deferred=1, dropped=1" in result.stdout
    assert (
        "Run: kb curate complete "
        + run_id
        + f" {filename} --disposition ephemeral --reason Session-only"
    ) in result.stdout
    assert "Need owner input" in result.stdout
    assert "Input changed" in result.stdout
    assert "locally settled and unpublished" not in result.stdout


def test_status_reports_changed_and_missing_pending_inputs_with_drop_commands(kb: Kb) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    changed_name = "changed.md"
    missing_name = "missing item.md"
    changed = _pending(kb, changed_name)
    changed.write_bytes(b"before")
    members = [
        _member(changed_name, b"before"),
        _member(missing_name, b"gone"),
    ]
    _pending(kb, changed_name).write_bytes(b"after")
    _write_batch(kb, run_id, members)

    result = kb("curate", "status", run_id)

    assert result.returncode == 1
    assert f"Run: kb curate drop {run_id} changed.md --reason TEXT" in result.stdout
    assert f"Run: kb curate drop {run_id} 'missing item.md' --reason TEXT" in result.stdout


def test_status_checks_every_pending_member_beyond_the_display_limit(kb: Kb) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    members = []
    for index in range(10):
        filename = f"item-{index}.md"
        content = f"input-{index}".encode()
        if index < 9:
            _pending(kb, filename).write_bytes(content)
        else:
            _pending(kb, filename).write_bytes(b"changed")
        members.append(_member(filename, content))
    _write_batch(kb, run_id, members)

    result = kb("curate", "status", run_id)

    assert result.returncode == 1
    assert "... 2 more pending item(s)" in result.stdout
    assert f"Run: kb curate drop {run_id} item-9.md --reason TEXT" in result.stdout


def test_status_is_read_only_and_does_not_require_git_or_valid_lock_configuration(kb: Kb) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "20261024T094659-8d6fecbe.md"
    input_path = _pending(kb, filename)
    manifest = _write_batch(kb, run_id, [_member(filename, input_path.read_bytes())])
    manifest_mtime = manifest.stat().st_mtime_ns
    input_mtime = input_path.stat().st_mtime_ns

    result = kb("curate", "status", run_id, env={"KB_LOCK_WAIT": "invalid"})

    assert result.returncode == 0, result.stderr
    assert "States: pending=1" in result.stdout
    assert manifest.stat().st_mtime_ns == manifest_mtime
    assert input_path.stat().st_mtime_ns == input_mtime


def test_status_accepts_a_deferred_input_archived_by_a_later_batch(kb: Kb) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "historically-deferred.md"
    archived = kb.content / "observations/archived" / filename
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_bytes(b"archived by later batch")
    _write_batch(
        kb,
        run_id,
        [_member(filename, b"original", status="deferred", reason="Waited for context")],
    )

    result = kb("curate", "status", run_id)

    assert result.returncode == 0, result.stderr
    assert "locally settled and unpublished" in result.stdout
    assert "Waited for context" in result.stdout


def test_status_refuses_inconsistent_complete_archives(kb: Kb) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "complete.md"
    original = b"original"
    archived = b"different archive"
    archive_path = kb.content / "observations/archived" / filename
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archived)
    _write_batch(
        kb,
        run_id,
        [
            _member(
                filename,
                original,
                status="complete",
                disposition="ephemeral",
                reason="Temporary",
                archived=b"expected archive",
            )
        ],
    )

    result = kb("curate", "status", run_id)

    assert result.returncode == 1
    assert f"Inconsistent complete archive: observations/archived/{filename}" in result.stdout


def test_status_rejects_malformed_manifest_and_path_like_run_id(kb: Kb) -> None:
    malformed = kb.content / "observations/batches/20261028T120000-a1b2c3d4.json"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_text('{"schema_version": 1, "schema_version": 1}\n', encoding="utf-8")

    bad_json = kb("curate", "status", "20261028T120000-a1b2c3d4")
    _failure(bad_json, "malformed batch manifest")
    path_run = kb("curate", "status", "../20261028T120000-a1b2c3d4")
    _failure(path_run, "unsafe batch id")


def test_next_prints_full_observation_stable_context_and_three_section_limit(git_kb: Kb) -> None:
    filename = "full transcript note.md"
    observation = (
        '---\ntitle: "Curation context crimson"\n'
        "source: session-transcript\n"
        'session: "fixture-session"\n'
        "part: 1\n"
        'first_message: "message-1"\n'
        'last_message: "message-4"\n'
        "started: 2026-10-24T09:00:00Z\n"
        "ended: 2026-10-24T09:03:00Z\n"
        "created: 2026-10-24T09:03:00Z\n---\n\n"
        "## 1. user, 2026-10-24T09:00:00Z\n\n"
        "````text\nThe first user turn reported a restart problem.\n````\n\n"
        "## 2. assistant, 2026-10-24T09:01:00Z\n\n"
        "````text\nCheck the logs after the service restart.\n````\n\n"
        "## 3. user, 2026-10-24T09:02:00Z\n\n"
        "````text\nThe failure happened after the network came back.\n````\n\n"
        "## 4. assistant, 2026-10-24T09:03:00Z\n\n"
        "````sh\nrestart-services --after-network\n````\n"
    )
    pending = _pending(git_kb, filename)
    pending.write_text(observation, encoding="utf-8")
    for index in range(4):
        article = git_kb.content / f"knowledge/next-context-{index}.md"
        conflict = "conflict: unresolved\n" if index == 0 else ""
        article.write_text(
            "---\n"
            'title: "Curation context crimson"\n'
            "verified: 2020-01-01\n"
            "ttl: 1\n"
            f"{conflict}"
            "---\n\n"
            "# Curation context crimson\n\n"
            f"Context entry {index}.\n",
            encoding="utf-8",
        )
    manifest = _write_batch(
        git_kb, "20261028T120000-a1b2c3d4", [_member(filename, pending.read_bytes())]
    )
    pending_mtime = pending.stat().st_mtime_ns
    manifest_mtime = manifest.stat().st_mtime_ns
    original_head = git_kb.git("rev-parse", "HEAD")

    first = git_kb("curate", "next", "20261028T120000-a1b2c3d4")
    second = git_kb("curate", "next", "20261028T120000-a1b2c3d4")
    path_read = git_kb("read", f"observations/pending/{filename}")

    assert first.returncode == 0, first.stderr
    assert first.stderr == ""
    assert first.stdout == second.stdout
    assert f"Observation:\n{observation}" in first.stdout
    assert "The failure happened after the network came back." in first.stdout
    assert "restart-services --after-network" in first.stdout
    assert path_read.returncode == 0, path_read.stderr
    assert "The failure happened after the network came back." not in path_read.stdout
    assert "restart-services --after-network" not in path_read.stdout
    assert "Query: Curation context crimson" in first.stdout
    sections = first.stdout.split("Matching curated sections:\n", 1)[1].split(
        "Related open questions:", 1
    )[0]
    headers = [line for line in sections.splitlines() if line.startswith("knowledge/")]
    assert len(headers) == 3
    assert all("stale, verified 2020-01-01 (ttl 1)" in header for header in headers)
    assert any(", conflict |" in header for header in headers)
    assert "knowledge/next-context-3.md" not in sections
    assert pending.read_text(encoding="utf-8") == observation
    assert pending.stat().st_mtime_ns == pending_mtime
    assert manifest.stat().st_mtime_ns == manifest_mtime
    assert git_kb.git("rev-parse", "HEAD") == original_head


def test_next_supports_query_override_and_no_match_output(git_kb: Kb) -> None:
    filename = "unrelated.md"
    content = b"---\ntitle: A random observation\n---\n\nA separate note.\n"
    _pending(git_kb, filename).write_bytes(content)
    _write_batch(git_kb, "20261028T120000-a1b2c3d4", [_member(filename, content)])

    default = git_kb("curate", "next", "20261028T120000-a1b2c3d4")
    overridden = git_kb(
        "curate", "next", "20261028T120000-a1b2c3d4", "--query", "NAS restart order"
    )
    unmatched = git_kb("curate", "next", "20261028T120000-a1b2c3d4", "--query", "quantum zebra")

    assert default.returncode == 0, default.stderr
    assert 'No curated sections match "A random observation".' in default.stdout
    assert overridden.returncode == 0, overridden.stderr
    assert "Query: NAS restart order" in overridden.stdout
    assert "knowledge/infra/nas.md#1 | Restart order" in overridden.stdout
    assert unmatched.returncode == 0, unmatched.stderr
    assert 'No curated sections match "quantum zebra".' in unmatched.stdout
    assert "No related open questions." in unmatched.stdout


def test_next_open_question_rows_match_recall_exactly(git_kb: Kb) -> None:
    filename = "question-context.md"
    content = b"---\ntitle: disk owner listed\n---\n\nCheck this open question.\n"
    _pending(git_kb, filename).write_bytes(content)
    _write_batch(git_kb, "20261028T120000-a1b2c3d4", [_member(filename, content)])

    next_result = git_kb("curate", "next", "20261028T120000-a1b2c3d4")
    recall_result = git_kb("recall", "disk owner listed")

    assert next_result.returncode == 0, next_result.stderr
    assert recall_result.returncode == 0, recall_result.stderr
    expected = [
        line for line in recall_result.stdout.splitlines() if line.startswith("  questions/open/")
    ]
    section = next_result.stdout.split("Related open questions:\n", 1)[1].split("Read with:", 1)[0]
    actual = [line for line in section.splitlines() if line.startswith("  questions/open/")]
    assert expected
    assert actual == expected


def test_next_refuses_interrupted_archive_until_the_stored_completion_is_repeated(kb: Kb) -> None:
    filename = "interrupted.md"
    original = b"Original input.\n"
    pending = _pending(kb, filename)
    pending.write_bytes(original)
    _write_batch(
        kb,
        "20261028T120000-a1b2c3d4",
        [
            _member(
                filename,
                original,
                status="archiving",
                disposition="ephemeral",
                reason="Session-only",
                archived=original + b"\n---\n",
            )
        ],
    )

    result = kb("curate", "next", "20261028T120000-a1b2c3d4")

    assert result.returncode == 1
    assert "finish it before presenting more work" in result.stdout
    assert (
        "Run: kb curate complete 20261028T120000-a1b2c3d4 interrupted.md "
        "--disposition ephemeral --reason Session-only"
    ) in result.stdout


@pytest.mark.parametrize("change", ["changed", "missing"])
def test_next_refuses_changed_or_missing_input_with_drop_command(kb: Kb, change: str) -> None:
    filename = "changed input.md"
    original = b"Original input.\n"
    pending = _pending(kb, filename)
    pending.write_bytes(original)
    _write_batch(kb, "20261028T120000-a1b2c3d4", [_member(filename, original)])
    if change == "changed":
        pending.write_bytes(b"Modified input.\n")
    else:
        pending.unlink()

    result = kb("curate", "next", "20261028T120000-a1b2c3d4")

    assert result.returncode == 1
    assert f"Pending input is missing or changed: observations/pending/{filename}" in result.stdout
    assert (
        "kb curate drop 20261028T120000-a1b2c3d4 'changed input.md' --reason TEXT" in result.stdout
    )


def test_next_reports_locally_settled_batch(kb: Kb) -> None:
    _write_batch(
        kb,
        "20261028T120000-a1b2c3d4",
        [_member("deferred.md", b"Deferred input", status="deferred", reason="Need context")],
    )

    result = kb("curate", "next", "20261028T120000-a1b2c3d4")

    assert result.returncode == 0
    assert result.stdout == "No pending members; batch is locally settled and unpublished.\n"


def test_next_help_and_usage(kb: Kb) -> None:
    help_result = kb("curate", "next", "--help")
    assert help_result.returncode == 0
    assert help_result.stdout.startswith("Usage: kb curate next RUN [--query TEXT]\n\n")
    missing = kb("curate", "next")
    assert missing.returncode == 1
    assert missing.stderr == "Usage: kb curate next RUN [--query TEXT]\n"


def test_complete_archives_each_outcome_with_canonical_destinations_without_committing(
    git_kb: Kb,
) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    incorporated_name = "incorporated.md"
    duplicate_name = "duplicate.md"
    ephemeral_name = "ephemeral.md"
    contents = {
        incorporated_name: (
            b"---\ntitle: Network and services handoff\ncreated: 2026-10-24\n---\n\n"
            b"## 1. user, 2026-10-24T09:00:00Z\n\nNetwork access details.\n\n"
            b"## 2. assistant, 2026-10-24T09:01:00Z\n\nService restart order.\n"
        ),
        duplicate_name: b"---\ntitle: Duplicate detail\n---\n\nAlready known.\n",
        ephemeral_name: b"---\ntitle: Temporary detail\n---\n\nNo durable fact.\n",
    }
    for filename, content in contents.items():
        _pending(git_kb, filename).write_bytes(content)

    network_article = _write_article(
        git_kb,
        "knowledge/curation/network.md",
        "---\n"
        "title: Network setup\n"
        "updated: 2026-10-20\n"
        "verified: 2026-10-20\n"
        "ttl: domain\n"
        "sources:\n"
        f"  - observations/archived/{incorporated_name}#1\n"
        "---\n\n"
        "# Network setup\n\n"
        "## Access\n"
        f"<!-- kb-section: verified=2026-10-20; ttl=domain; sources=observations/archived/{incorporated_name}#1 -->\n\n"
        "Use the documented network route.\n",
    )
    services_article = _write_article(
        git_kb,
        "knowledge/curation/services.md",
        "---\n"
        "title: Service restart\n"
        "updated: 2026-10-21\n"
        "verified: 2026-10-21\n"
        "ttl: domain\n"
        "sources:\n"
        f"  - observations/archived/{incorporated_name}#2\n"
        "---\n\n"
        "# Service restart\n\n"
        "## Order\n\n"
        "Restart in dependency order.\n",
    )
    article_bytes = {path: path.read_bytes() for path in (network_article, services_article)}
    _write_batch(
        git_kb,
        run_id,
        [_member(filename, content) for filename, content in contents.items()],
    )
    original_head = git_kb.git("rev-parse", "HEAD")
    original_index = git_kb.git("diff", "--cached", "--name-only")

    incorporated = git_kb(
        "curate",
        "complete",
        run_id,
        incorporated_name,
        "--disposition",
        "incorporated",
        "knowledge/curation/network.md#01",
        "knowledge/curation/network.md#1",
        "knowledge/curation/services.md#1",
    )
    duplicate = git_kb(
        "curate",
        "complete",
        run_id,
        duplicate_name,
        "--disposition",
        "duplicate",
        "knowledge/curation/network.md#1",
    )
    ephemeral = git_kb(
        "curate",
        "complete",
        run_id,
        ephemeral_name,
        "--disposition",
        "ephemeral",
        "--reason",
        "No durable details",
    )

    assert incorporated.returncode == 0, incorporated.stderr
    assert incorporated.stdout == (
        f"Archived: observations/pending/{incorporated_name} -> "
        f"observations/archived/{incorporated_name}\n"
    )
    assert duplicate.returncode == 0, duplicate.stderr
    assert f"observations/archived/{duplicate_name}" in duplicate.stdout
    assert ephemeral.returncode == 0, ephemeral.stderr
    assert f"observations/archived/{ephemeral_name}" in ephemeral.stdout
    state = json.loads(
        (git_kb.content / "observations/batches" / f"{run_id}.json").read_text(encoding="utf-8")
    )
    members = {member["filename"]: member for member in state["members"]}
    assert members[incorporated_name]["status"] == "complete"
    assert members[incorporated_name]["destinations"] == [
        {"locator": "knowledge/curation/network.md#1", "heading": "Access"},
        {"locator": "knowledge/curation/services.md#1", "heading": "Order"},
    ]
    assert members[duplicate_name]["disposition"] == "duplicate"
    assert members[ephemeral_name]["disposition"] == "ephemeral"
    archived = git_kb.content / "observations" / "archived"
    incorporated_text = (archived / incorporated_name).read_text(encoding="utf-8")
    assert "\ndisposition:" not in incorporated_text
    assert "\ndestination" not in incorporated_text
    assert (
        f"original_sha256: {hashlib.sha256(contents[incorporated_name]).hexdigest()}"
        in incorporated_text
    )
    assert f"curation_batch: {run_id}" in incorporated_text
    assert "\ndestination" not in (archived / duplicate_name).read_text(encoding="utf-8")
    ephemeral_text = (archived / ephemeral_name).read_text(encoding="utf-8")
    assert "\ndisposition:" not in ephemeral_text
    assert 'curation_reason: "No durable details"' in ephemeral_text
    assert all(path.read_bytes() == content for path, content in article_bytes.items())
    linted = git_kb("lint", "knowledge/curation/network.md", "knowledge/curation/services.md")
    assert linted.returncode == 0, linted.stdout + linted.stderr
    assert git_kb.git("rev-parse", "HEAD") == original_head
    assert git_kb.git("diff", "--cached", "--name-only") == original_index

    archived_path = archived / incorporated_name
    manifest_path = git_kb.content / "observations/batches" / f"{run_id}.json"
    archive_mtime = archived_path.stat().st_mtime_ns
    manifest_mtime = manifest_path.stat().st_mtime_ns
    repeated = git_kb(
        "curate",
        "complete",
        run_id,
        incorporated_name,
        "--disposition",
        "incorporated",
        "knowledge/curation/network.md#1",
        "knowledge/curation/services.md#1",
    )
    assert repeated.returncode == 0, repeated.stderr
    assert archived_path.stat().st_mtime_ns == archive_mtime
    assert manifest_path.stat().st_mtime_ns == manifest_mtime
    different = git_kb(
        "curate",
        "complete",
        run_id,
        incorporated_name,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary instead",
    )
    _failure(different, "member is complete with a different outcome")


def test_complete_rejects_missing_ambiguous_and_unsectioned_duplicate_destinations(
    git_kb: Kb,
) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "destination-check.md"
    content = b"---\ntitle: Destination check\n---\n\nText.\n"
    _pending(git_kb, filename).write_bytes(content)
    _write_batch(git_kb, run_id, [_member(filename, content)])
    _write_article(
        git_kb, "knowledge/left/shared.md", "---\ntitle: Shared\n---\n# Shared\n## One\n"
    )
    _write_article(
        git_kb, "knowledge/right/shared.md", "---\ntitle: Shared\n---\n# Shared\n## One\n"
    )

    missing = git_kb(
        "curate",
        "complete",
        run_id,
        filename,
        "--disposition",
        "incorporated",
        "knowledge/missing.md#1",
    )
    ambiguous = git_kb(
        "curate", "complete", run_id, filename, "--disposition", "incorporated", "shared.md#1"
    )
    unsectioned = git_kb(
        "curate",
        "complete",
        run_id,
        filename,
        "--disposition",
        "duplicate",
        "knowledge/left/shared.md",
    )

    _failure(missing, "no such destination")
    _failure(ambiguous, "matches 2 files")
    _failure(unsectioned, "duplicate destinations must name numbered sections")
    assert _pending(git_kb, filename).read_bytes() == content
    assert not (git_kb.content / "observations/archived" / filename).exists()
    assert (
        json.loads((git_kb.content / "observations/batches" / f"{run_id}.json").read_text())[
            "members"
        ][0]["status"]
        == "pending"
    )


def test_complete_rejects_nonmembers_changed_inputs_and_existing_archives(git_kb: Kb) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "complete-check.md"
    content = b"---\ntitle: Complete check\n---\n\nOriginal.\n"
    pending = _pending(git_kb, filename)
    pending.write_bytes(content)
    _write_batch(git_kb, run_id, [_member(filename, content)])

    nonmember = git_kb(
        "curate",
        "complete",
        run_id,
        "other.md",
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
    )
    _failure(nonmember, "not a batch member")

    pending.write_bytes(b"Changed bytes.\n")
    changed = git_kb(
        "curate",
        "complete",
        run_id,
        filename,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
    )
    _failure(changed, "input is changed or missing")
    assert pending.read_bytes() == b"Changed bytes.\n"
    assert (
        json.loads((git_kb.content / "observations/batches" / f"{run_id}.json").read_text())[
            "members"
        ][0]["status"]
        == "pending"
    )

    pending.write_bytes(content)
    archive_path = git_kb.content / "observations" / "archived" / filename
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(b"Existing archive must survive.\n")
    conflict = git_kb(
        "curate",
        "complete",
        run_id,
        filename,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
    )
    _failure(conflict, "archive already exists")
    assert archive_path.read_bytes() == b"Existing archive must survive.\n"
    assert pending.read_bytes() == content


def test_complete_requires_git_metadata_for_the_shared_writer_lock(kb: Kb) -> None:
    filename = "no-git.md"
    content = b"---\ntitle: No Git metadata\n---\n\nEvidence.\n"
    pending = _pending(kb, filename)
    pending.write_bytes(content)
    manifest = _write_batch(kb, "20261028T120000-a1b2c3d4", [_member(filename, content)])
    before = manifest.read_bytes()

    result = kb(
        "curate",
        "complete",
        "20261028T120000-a1b2c3d4",
        filename,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
    )

    _failure(result, "cannot locate the Git directory")
    assert pending.read_bytes() == content
    assert manifest.read_bytes() == before
    assert not (kb.content / "observations/archived" / filename).exists()


def test_recovery_detects_a_destination_heading_shift(git_kb: Kb) -> None:
    filename = "shifted-destination.md"
    original = b"---\ntitle: Shifted destination\n---\n\nEvidence.\n"
    pending = _pending(git_kb, filename)
    pending.write_bytes(original)
    article = _write_article(
        git_kb,
        "knowledge/shifted.md",
        "---\ntitle: Shifted\n---\n# Shifted\n## Replacement heading\n",
    )
    _write_batch(
        git_kb,
        "20261028T120000-a1b2c3d4",
        [
            _member(
                filename,
                original,
                status="archiving",
                disposition="incorporated",
                destinations=[{"locator": "knowledge/shifted.md#1", "heading": "Original heading"}],
                archived=b"Expected archive bytes.",
            )
        ],
    )

    result = git_kb(
        "curate",
        "complete",
        "20261028T120000-a1b2c3d4",
        filename,
        "--disposition",
        "incorporated",
        "knowledge/shifted.md#1",
    )

    assert result.returncode == 1
    assert "destination heading changed since the archive intent" in result.stderr
    assert article.is_file()
    assert pending.read_bytes() == original
    assert not (git_kb.content / "observations/archived" / filename).exists()


@pytest.mark.parametrize(
    "existing_field",
    [
        "original_sha256: " + "a" * 64 + "\n",
        "curation_batch: 20261028T120000-a1b2c3d4\n",
        'curation_reason: "Old note"\n',
    ],
)
def test_complete_rejects_preexisting_archive_metadata(git_kb: Kb, existing_field: str) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "unsafe-metadata.md"
    content = f"---\ntitle: Unsafe\n{existing_field}---\n\nEvidence.\n".encode()
    _pending(git_kb, filename).write_bytes(content)
    _write_batch(git_kb, run_id, [_member(filename, content)])

    result = git_kb(
        "curate",
        "complete",
        run_id,
        filename,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
    )

    _failure(result, "archive fields already exist")
    assert _pending(git_kb, filename).read_bytes() == content
    assert (
        json.loads((git_kb.content / "observations/batches" / f"{run_id}.json").read_text())[
            "members"
        ][0]["status"]
        == "pending"
    )


@pytest.mark.parametrize(
    ("kind", "reference"),
    [
        ("front matter source", "sources:\n  - observations/pending/referenced.md#1\n"),
        (
            "section source",
            "# Inbound\n\n## Claim\n<!-- kb-section: sources=observations/pending/referenced.md#1 -->\n\nFact.\n",
        ),
        (
            "inline link",
            "# Inbound\n\n[the pending note](../observations/pending/referenced.md#1)\n",
        ),
        (
            "reference link",
            "# Inbound\n\n[the pending note][pending]\n\n[pending]: ../observations/pending/referenced.md#1\n",
        ),
    ],
)
def test_complete_rejects_every_inbound_pending_reference(
    git_kb: Kb, kind: str, reference: str
) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "referenced.md"
    content = b"---\ntitle: Referenced\n---\n\nEvidence.\n"
    _pending(git_kb, filename).write_bytes(content)
    _write_batch(git_kb, run_id, [_member(filename, content)])
    if kind == "front matter source":
        article_text = (
            "---\ntitle: Inbound reference\nupdated: 2026-10-20\n"
            "verified: 2026-10-20\nttl: domain\n" + reference + "---\n\n"
        )
    else:
        article_text = (
            "---\ntitle: Inbound reference\nupdated: 2026-10-20\n"
            "verified: 2026-10-20\nttl: domain\n---\n\n" + reference
        )
    source = _write_article(git_kb, "knowledge/inbound.md", article_text)

    result = git_kb(
        "curate",
        "complete",
        run_id,
        filename,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
    )

    _failure(result, "references still target the pending observation")
    assert "knowledge/inbound.md" in result.stderr
    assert source.read_text(encoding="utf-8") == article_text
    assert _pending(git_kb, filename).read_bytes() == content
    assert not (git_kb.content / "observations/archived" / filename).exists()
    assert (
        json.loads((git_kb.content / "observations/batches" / f"{run_id}.json").read_text())[
            "members"
        ][0]["status"]
        == "pending"
    )


def test_complete_checks_inbound_references_under_sources(git_kb: Kb) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    filename = "source-referenced.md"
    content = b"---\ntitle: Source referenced\n---\n\nEvidence.\n"
    _pending(git_kb, filename).write_bytes(content)
    _write_batch(git_kb, run_id, [_member(filename, content)])
    source = _write_article(
        git_kb,
        "sources/inbound.md",
        "---\ntitle: Imported document\nsources:\n"
        f"  - observations/pending/{filename}#1\n---\n\nImported text.\n",
    )

    result = git_kb(
        "curate",
        "complete",
        run_id,
        filename,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
    )

    _failure(result, "references still target the pending observation")
    assert "sources/inbound.md" in result.stderr
    assert source.is_file()
    assert _pending(git_kb, filename).read_bytes() == content
    assert not (git_kb.content / "observations/archived" / filename).exists()


def _archiving_fixture(kb: Kb, filename: str) -> tuple[bytes, bytes, Path]:
    """Write an archiving intent with the exact expected ephemeral archive bytes."""
    original = b"---\ntitle: Recovery fixture\n---\n\nEvidence to retain.\n"
    original_hash = hashlib.sha256(original).hexdigest()
    archived = (
        "---\ntitle: Recovery fixture\n"
        f"original_sha256: {original_hash}\n"
        f"curation_batch: 20261028T120000-a1b2c3d4\n"
        'curation_reason: "Temporary note"\n'
        "---\n\nEvidence to retain.\n"
    ).encode()
    pending = _pending(kb, filename)
    pending.write_bytes(original)
    member = _member(
        filename,
        original,
        status="archiving",
        disposition="ephemeral",
        reason="Temporary note",
        archived=archived,
    )
    _write_batch(kb, "20261028T120000-a1b2c3d4", [member])
    return original, archived, pending


@pytest.mark.parametrize(
    ("disk_state", "expected_error"),
    [
        ("changed pending", "pending copy changed"),
        ("conflicting archive", "archive conflicts with the stored intent"),
        ("neither copy", "both copies are missing"),
    ],
)
def test_recovery_refuses_changed_or_conflicting_copies(
    git_kb: Kb, disk_state: str, expected_error: str
) -> None:
    filename = "recovery-case.md"
    original, expected_archive, pending = _archiving_fixture(git_kb, filename)
    archive_path = git_kb.content / "observations" / "archived" / filename
    if disk_state == "changed pending":
        pending.write_bytes(b"Changed evidence.\n")
    elif disk_state == "conflicting archive":
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(b"Unexpected archive bytes.\n")
    else:
        pending.unlink()

    status = git_kb("curate", "status", "20261028T120000-a1b2c3d4")
    assert status.returncode == 0, status.stderr
    line = next(
        line.strip() for line in status.stdout.splitlines() if "Run: kb curate complete" in line
    )
    command = shlex.split(line.removeprefix("Run: "))
    result = git_kb(*command[1:])

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected_error in result.stderr
    assert (
        json.loads(
            (git_kb.content / "observations/batches" / "20261028T120000-a1b2c3d4.json").read_text(
                encoding="utf-8"
            )
        )["members"][0]["status"]
        == "archiving"
    )
    if disk_state == "changed pending":
        assert pending.read_bytes() == b"Changed evidence.\n"
        assert not archive_path.exists()
    elif disk_state == "conflicting archive":
        assert pending.read_bytes() == original
        assert archive_path.read_bytes() == b"Unexpected archive bytes.\n"
    else:
        assert not pending.exists()
        assert not archive_path.exists()
    assert expected_archive


def test_complete_refuses_a_different_outcome_from_the_stored_intent(git_kb: Kb) -> None:
    filename = "intent.md"
    original, _archived, pending = _archiving_fixture(git_kb, filename)

    result = git_kb(
        "curate",
        "complete",
        "20261028T120000-a1b2c3d4",
        filename,
        "--disposition",
        "incorporated",
        "knowledge/infra/nas.md#1",
    )

    assert result.returncode == 1
    assert "requested outcome differs from the stored archive intent" in result.stderr
    assert "resume with: kb curate complete 20261028T120000-a1b2c3d4 intent.md" in result.stderr
    assert pending.read_bytes() == original
    assert not (git_kb.content / "observations/archived" / filename).exists()


def test_complete_help_usage_invalid_wait_and_reason_validation(git_kb: Kb) -> None:
    help_result = git_kb("curate", "complete", "--help")
    assert help_result.returncode == 0
    assert help_result.stdout.startswith(
        "Usage: kb curate complete RUN FILENAME --disposition DISPOSITION [--reason TEXT] [LOCATOR...]\n\n"
    )
    missing = git_kb("curate", "complete")
    assert missing.returncode == 1
    assert missing.stderr == (
        "Usage: kb curate complete RUN FILENAME --disposition DISPOSITION [--reason TEXT] [LOCATOR...]\n"
    )
    filename = "invalid-reason.md"
    content = b"---\ntitle: Invalid reason\n---\n\nEvidence.\n"
    _pending(git_kb, filename).write_bytes(content)
    _write_batch(git_kb, "20261028T120000-a1b2c3d4", [_member(filename, content)])
    invalid_wait = git_kb(
        "curate",
        "complete",
        "20261028T120000-a1b2c3d4",
        filename,
        "--disposition",
        "ephemeral",
        "--reason",
        "Temporary",
        env={"KB_LOCK_WAIT": "soon"},
    )
    assert invalid_wait.returncode == 1
    assert invalid_wait.stderr == missing.stderr
    for reason in ("", "Two\nlines"):
        invalid_reason = git_kb(
            "curate",
            "complete",
            "20261028T120000-a1b2c3d4",
            filename,
            "--disposition",
            "ephemeral",
            "--reason",
            reason,
        )
        assert invalid_reason.returncode == 1
        assert "nonempty single-line --reason" in invalid_reason.stderr


def test_kernel_lock_blocks_completion_before_publishing(git_kb: Kb) -> None:
    filename = "locked.md"
    content = b"---\ntitle: Locked\n---\n\nEvidence.\n"
    pending = _pending(git_kb, filename)
    pending.write_bytes(content)
    manifest = _write_batch(git_kb, "20261028T120000-a1b2c3d4", [_member(filename, content)])
    before_manifest = manifest.read_bytes()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_KERNEL_LOCK, str(git_kb.content / ".git" / "kb.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == "locked\n"
        result = git_kb(
            "curate",
            "complete",
            "20261028T120000-a1b2c3d4",
            filename,
            "--disposition",
            "ephemeral",
            "--reason",
            "Temporary",
        )
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)

    assert result.returncode == 1
    assert result.stderr == "curate: content repository is busy (waited 1s for the lock)\n"
    assert pending.read_bytes() == content
    assert manifest.read_bytes() == before_manifest
    assert not (git_kb.content / "observations/archived" / filename).exists()
    assert not list((git_kb.content / ".git" / "kb-tmp").glob("*"))


def test_defer_and_drop_preserve_files_require_reasons_and_allow_identical_retries(
    git_kb: Kb,
) -> None:
    run_id = "20261028T120000-a1b2c3d4"
    contents = {
        "defer.md": b"unchanged observation\n",
        "changed.md": b"original observation\n",
        "missing.md": b"observation removed by another writer\n",
        "unchanged.md": b"do not drop this observation\n",
    }
    for filename, content in contents.items():
        _pending(git_kb, filename).write_bytes(content)
    manifest = _write_batch(
        git_kb,
        run_id,
        [_member(filename, content) for filename, content in contents.items()],
    )
    changed = _pending(git_kb, "changed.md")
    changed.write_bytes(b"updated by another writer\n")
    _pending(git_kb, "missing.md").unlink()

    deferred = git_kb("curate", "defer", run_id, "defer.md", "--reason", "Need owner input")
    assert deferred.returncode == 0, deferred.stderr
    assert deferred.stdout == f"Deferred: defer.md in batch {run_id}\n"
    assert _pending(git_kb, "defer.md").read_bytes() == contents["defer.md"]
    repeated = git_kb("curate", "defer", run_id, "defer.md", "--reason", "Need owner input")
    assert repeated.returncode == 0, repeated.stderr
    different = git_kb("curate", "defer", run_id, "defer.md", "--reason", "Changed reason")
    _failure(different, "already deferred with a different reason")

    for filename in ("changed.md", "missing.md"):
        dropped = git_kb(
            "curate", "drop", run_id, filename, "--reason", "Input changed outside this batch"
        )
        assert dropped.returncode == 0, dropped.stderr
        assert dropped.stdout == f"Dropped: {filename} in batch {run_id}\n"
        repeated_drop = git_kb(
            "curate", "drop", run_id, filename, "--reason", "Input changed outside this batch"
        )
        assert repeated_drop.returncode == 0, repeated_drop.stderr
    assert changed.read_bytes() == b"updated by another writer\n"
    assert not _pending(git_kb, "missing.md").exists()
    unchanged_drop = git_kb(
        "curate", "drop", run_id, "unchanged.md", "--reason", "No longer needed"
    )
    _failure(unchanged_drop, "input is unchanged; use defer")

    for command, filename in (("defer", "unchanged.md"), ("drop", "unchanged.md")):
        missing_reason = git_kb("curate", command, run_id, filename)
        assert missing_reason.returncode == 1
        assert missing_reason.stderr == f"Usage: kb curate {command} RUN FILENAME --reason TEXT\n"
        invalid_wait = git_kb(
            "curate",
            command,
            run_id,
            filename,
            "--reason",
            "A reason",
            env={"KB_LOCK_WAIT": "invalid"},
        )
        assert invalid_wait.returncode == 1
        assert invalid_wait.stderr == missing_reason.stderr

    secret = 'password = "hunter2hunter2"'
    refused = git_kb("curate", "defer", run_id, "unchanged.md", "--reason", secret)
    _failure(refused, "possible secret in --reason")
    assert secret not in refused.stderr
    assert _pending(git_kb, "unchanged.md").read_bytes() == contents["unchanged.md"]
    state = json.loads(manifest.read_text(encoding="utf-8"))
    assert {member["filename"]: member["status"] for member in state["members"]} == {
        "defer.md": "deferred",
        "changed.md": "dropped",
        "missing.md": "dropped",
        "unchanged.md": "pending",
    }


def test_full_local_curation_workflow_and_historical_defer(git_kb: Kb) -> None:
    filenames = [
        "incorporated.md",
        "duplicate.md",
        "ephemeral.md",
        "deferred.md",
        "dropped.md",
        "interrupted.md",
    ]
    observations = {
        filename: (
            f"---\ntitle: Workflow evidence {filename.removesuffix('.md')}\n"
            f"created: 2026-10-2{index}\n---\n\n## 1. Evidence\n\nEvidence for {filename}.\n"
        ).encode()
        for index, filename in enumerate(filenames, start=1)
    }
    for filename, content in observations.items():
        _pending(git_kb, filename).write_bytes(content)
    article = _write_article(
        git_kb,
        "knowledge/workflow.md",
        "---\ntitle: Workflow evidence\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        "ttl: domain\n---\n# Workflow evidence\n\n## 1. Incorporated fact\n\n"
        "A durable workflow fact.\n\n## 2. Duplicate fact\n\nA repeated durable fact.\n",
    )
    _commit(
        git_kb,
        "knowledge/workflow.md",
        *(f"observations/pending/{filename}" for filename in filenames),
    )
    start = git_kb(
        "curate",
        "start",
        "--no-sync",
        "--max-bytes",
        str(sum(map(len, observations.values()))),
        *filenames,
    )
    assert start.returncode == 0, start.stderr
    run_id = _run_id(start)
    first_manifest = git_kb.content / "observations" / "batches" / f"{run_id}.json"
    first_state = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert [member["filename"] for member in first_state["members"]] == filenames

    new_arrival = b"---\ntitle: New arrival\ncreated: 2026-10-28\n---\n\nOutside the batch.\n"
    _pending(git_kb, "new-arrival.md").write_bytes(new_arrival)
    article.write_text(
        "---\ntitle: Workflow evidence\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        "ttl: domain\nsources:\n"
        "  - observations/archived/incorporated.md#1\n"
        "  - observations/archived/duplicate.md#1\n"
        "  - observations/archived/interrupted.md#1\n"
        "---\n# Workflow evidence\n\n## 1. Incorporated fact\n\n"
        "A durable workflow fact.\n\n## 2. Duplicate fact\n\nA repeated durable fact.\n",
        encoding="utf-8",
    )
    article_before_completion = article.read_bytes()
    verify_before_archive = git_kb("verify", "knowledge/workflow.md")
    assert verify_before_archive.returncode == 1
    assert verify_before_archive.stdout == ""
    assert verify_before_archive.stderr.startswith("verify:")
    assert "proposed result has lint errors" in verify_before_archive.stderr
    assert article.read_bytes() == article_before_completion

    incorporated = git_kb(
        "curate",
        "complete",
        run_id,
        "incorporated.md",
        "--disposition",
        "incorporated",
        "knowledge/workflow.md",
    )
    assert incorporated.returncode == 0, incorporated.stderr
    duplicate = git_kb(
        "curate",
        "complete",
        run_id,
        "duplicate.md",
        "--disposition",
        "duplicate",
        "knowledge/workflow.md#1",
    )
    assert duplicate.returncode == 0, duplicate.stderr
    ephemeral = git_kb(
        "curate",
        "complete",
        run_id,
        "ephemeral.md",
        "--disposition",
        "ephemeral",
        "--reason",
        "Session-only detail",
    )
    assert ephemeral.returncode == 0, ephemeral.stderr
    deferred = git_kb("curate", "defer", run_id, "deferred.md", "--reason", "Need owner input")
    assert deferred.returncode == 0, deferred.stderr
    _pending(git_kb, "dropped.md").unlink()
    dropped = git_kb(
        "curate", "drop", run_id, "dropped.md", "--reason", "Input was removed externally"
    )
    assert dropped.returncode == 0, dropped.stderr

    interrupted = _interrupt_archive(
        git_kb,
        run_id,
        "interrupted.md",
        "--disposition",
        "ephemeral",
        "--reason",
        "Resume after interruption",
    )
    _failure(interrupted, "archive operation failed")
    assert "resume with: kb curate complete" in interrupted.stderr
    status = git_kb("curate", "status", run_id)
    assert status.returncode == 0, status.stderr
    recovery_line = next(
        line.strip()
        for line in status.stdout.splitlines()
        if line.lstrip().startswith("Run: kb curate complete")
    )
    recovery_command = shlex.split(recovery_line.removeprefix("Run: "))
    recovered = git_kb(*recovery_command[1:])
    assert recovered.returncode == 0, recovered.stderr
    assert _pending(git_kb, "interrupted.md").exists() is False
    assert (git_kb.content / "observations/archived/interrupted.md").is_file()
    assert article.read_bytes() == article_before_completion

    settled = git_kb("curate", "status", run_id)
    assert settled.returncode == 0, settled.stderr
    assert "States: pending=0, archiving=0, complete=4, deferred=1, dropped=1" in settled.stdout
    assert "locally settled and unpublished" in settled.stdout
    next_work = git_kb("curate", "next", run_id)
    assert next_work.returncode == 0, next_work.stderr
    assert next_work.stdout == "No pending members; batch is locally settled and unpublished.\n"
    for filename in ("incorporated.md", "duplicate.md", "ephemeral.md", "interrupted.md"):
        assert not _pending(git_kb, filename).exists()
    assert _pending(git_kb, "deferred.md").read_bytes() == observations["deferred.md"]
    assert not _pending(git_kb, "dropped.md").exists()
    assert _pending(git_kb, "new-arrival.md").read_bytes() == new_arrival

    lint = git_kb("lint", "knowledge/workflow.md", "--require-ttl")
    assert lint.returncode == 0, lint.stdout + lint.stderr
    for name in ("incorporated", "duplicate", "ephemeral", "interrupted"):
        archived_read = git_kb("read", f"observations/archived/{name}.md#1")
        assert archived_read.returncode == 0, archived_read.stderr
        assert f"Evidence for {name}.md." in archived_read.stdout
    cited_sources = [
        line.removeprefix("  - ")
        for line in article.read_text(encoding="utf-8").splitlines()
        if line.startswith("  - observations/archived/")
    ]
    assert len(cited_sources) == 3
    for source in cited_sources:
        cited = git_kb("read", source)
        assert cited.returncode == 0, cited.stderr
        assert "Evidence for " in cited.stdout
    manifest_before_verify = first_manifest.read_bytes()
    verify = git_kb("verify", "knowledge/workflow.md")
    assert verify.returncode == 0, verify.stderr
    verified_text = article.read_text(encoding="utf-8")
    assert f"verified: {TODAY}\n" in verified_text
    assert "ttl: domain\n" in verified_text
    assert "updated: 2026-10-20\n" in verified_text
    lint_verified = git_kb("lint", "knowledge/workflow.md", "--require-ttl")
    assert lint_verified.returncode == 0, lint_verified.stdout + lint_verified.stderr
    resolve = git_kb(
        "resolve",
        "questions/open/20261001T090000-bbbb2222.md",
        "--answer",
        "The local workflow retains a reusable example.",
        "--destination",
        "knowledge/workflow.md#1",
    )
    assert resolve.returncode == 0, resolve.stderr
    assert not (git_kb.content / "questions/open/20261001T090000-bbbb2222.md").exists()
    assert (git_kb.content / "questions/resolved/20261001T090000-bbbb2222.md").is_file()
    assert first_manifest.read_bytes() == manifest_before_verify
    recall = git_kb("recall", "workflow evidence")
    assert recall.returncode == 0, recall.stderr
    assert "knowledge/workflow.md" in recall.stdout
    assert "observations/pending/incorporated.md" not in recall.stdout
    assert "observations/pending/duplicate.md" not in recall.stdout
    assert "observations/pending/ephemeral.md" not in recall.stdout
    assert "observations/archived/" not in recall.stdout

    git_kb.git("add", "--all")
    git_kb.git("commit", "-q", "-m", "Settle synthetic local curation batch")
    later = git_kb(
        "curate",
        "start",
        "--no-sync",
        "--max-bytes",
        str(len(observations["deferred.md"])),
        "deferred.md",
    )
    assert later.returncode == 0, later.stderr
    later_run = _run_id(later)
    later_manifest = json.loads(
        (git_kb.content / "observations" / "batches" / f"{later_run}.json").read_text(
            encoding="utf-8"
        )
    )
    assert [member["filename"] for member in later_manifest["members"]] == ["deferred.md"]
    later_complete = git_kb(
        "curate",
        "complete",
        later_run,
        "deferred.md",
        "--disposition",
        "ephemeral",
        "--reason",
        "Processed in a later batch",
    )
    assert later_complete.returncode == 0, later_complete.stderr
    old_state = json.loads(first_manifest.read_text(encoding="utf-8"))
    old_deferred = next(
        member for member in old_state["members"] if member["filename"] == "deferred.md"
    )
    assert old_deferred["status"] == "deferred"
    assert old_deferred["reason"] == "Need owner input"
    old_status = git_kb("curate", "status", run_id)
    assert old_status.returncode == 0, old_status.stderr
    assert "Committed locally; not published:" in old_status.stdout
    assert _pending(git_kb, "new-arrival.md").read_bytes() == new_arrival
