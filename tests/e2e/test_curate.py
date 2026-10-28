"""End-to-end tests for local curation batch selection, status, and next context."""

import hashlib
import json
import re
import shlex
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from .harness import Kb, make_git_kb

RUN_RE = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")
OLD_HEADER = "filename\toriginal_sha256\tstatus\tdisposition\tdestination\n"


def _run_id(result: CompletedProcess[str]) -> str:
    match = RUN_RE.search(result.stdout)
    assert match is not None, result.stdout
    return match.group(1)


def _pending(kb: Kb, filename: str) -> Path:
    return kb.content / "observations" / "pending" / filename


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


def test_start_help_usage_and_budget_validation(git_kb: Kb) -> None:
    help_result = git_kb("curate", "start", "--help")
    assert help_result.returncode == 0
    assert help_result.stdout.startswith("Usage: kb curate start --max-bytes N [FILENAME...]\n\n")
    assert git_kb("curate").stdout.startswith("Usage: kb curate {start,status,next} ...")

    missing = git_kb("curate", "start")
    assert missing.returncode == 1
    assert missing.stdout == ""
    assert missing.stderr == "Usage: kb curate start --max-bytes N [FILENAME...]\n"
    for budget in ("-1", "1.5", chr(0x661)):
        invalid = git_kb("curate", "start", "--max-bytes", budget)
        _failure(invalid, "nonnegative ASCII decimal integer")


def test_start_snapshots_date_ordered_inputs_and_stale_context(git_kb: Kb) -> None:
    names = [path.name for path in (git_kb.content / "observations/pending").glob("*.md")]
    contents = {name: _pending(git_kb, name).read_bytes() for name in names}
    head = git_kb.git("rev-parse", "HEAD")

    result = git_kb("curate", "start", "--max-bytes", "100000")

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
    assert result.stdout.startswith(f"Created batch: {run_id}\nSelected: 2 observation(s)\n")
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

    result = git_kb("curate", "start", "--max-bytes", "700")

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

    result = git_kb("curate", "start", "--max-bytes", "0")

    assert result.returncode == 1
    assert result.stderr == ""
    assert "No observations fit --max-bytes 0." in result.stdout
    assert set((git_kb.content / "observations/batches").glob("*.json")) == before


def test_larger_than_budget_report_gives_a_working_single_item_command(git_kb: Kb) -> None:
    result = git_kb("curate", "start", "--max-bytes", "10")

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
    suggested = git_kb(*command[1:])
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

    result = git_kb("curate", "start", "--max-bytes", "100")

    assert result.returncode == 1
    assert "Eligible pending observations: 0" in result.stdout
    assert "No pending observations." in result.stdout
    assert not list((git_kb.content / "observations/batches").glob("*.json"))


def test_start_requires_git_metadata(kb: Kb) -> None:
    no_git = kb("curate", "start", "--max-bytes", "10000")
    _failure(no_git, "Git directory")


def test_start_requires_a_clean_index_and_worktree(git_kb: Kb) -> None:
    staged = git_kb.content / "staged.txt"
    staged.write_text("staged\n", encoding="utf-8")
    git_kb.git("add", "--", "staged.txt")
    dirty_index = git_kb("curate", "start", "--max-bytes", "10000")
    _failure(dirty_index, "uncommitted changes")

    git_kb.git("reset", "-q", "--", "staged.txt")
    staged.unlink()
    untracked = git_kb.content / "untracked.txt"
    untracked.write_text("untracked\n", encoding="utf-8")
    dirty_worktree = git_kb("curate", "start", "--max-bytes", "10000")
    _failure(dirty_worktree, "uncommitted changes")


def test_start_ignores_its_legacy_lock_but_rejects_pending_old_batches(git_kb: Kb) -> None:
    result = git_kb("curate", "start", "--max-bytes", "10000")
    assert result.returncode == 0, result.stderr

    # Commit the new batch so the clean-tree gate passes and the active-batch gate is tested.
    run_id = _run_id(result)
    _commit(git_kb, f"observations/batches/{run_id}.json")
    blocked = git_kb("curate", "start", "--max-bytes", "10000")
    _failure(blocked, "pending or archiving work")


def test_start_rejects_malformed_new_manifests_and_allows_settled_batches(git_kb: Kb) -> None:
    directory = git_kb.content / "observations/batches"
    directory.mkdir(parents=True, exist_ok=True)
    malformed_id = "20261028T120000-a1b2c3d4"
    malformed = directory / f"{malformed_id}.json"
    malformed.write_text('{"schema_version": 1, "schema_version": 1}\n', encoding="utf-8")
    _commit(git_kb, f"observations/batches/{malformed.name}")

    refused = git_kb("curate", "start", "--max-bytes", "10000")
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

    allowed = git_kb("curate", "start", "--max-bytes", "10000")

    assert allowed.returncode == 0, allowed.stderr
    assert "Created batch:" in allowed.stdout


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (OLD_HEADER, None),
        (OLD_HEADER + "old.md\tabc\tcomplete\tprocessed\t\n", None),
        (OLD_HEADER + "old.md\tabc\tpending\t\t\n", "pending work"),
        ("broken header\n", "malformed old batch"),
        (OLD_HEADER + "short\trow\n", "malformed old batch"),
    ],
)
def test_old_tsv_batches_are_read_only_and_gate_only_pending_work(
    git_kb: Kb, contents: str, expected: str | None
) -> None:
    path = git_kb.content / "observations/batches" / "old.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    _commit(git_kb, "observations/batches/old.tsv")
    before = path.read_bytes()

    result = git_kb("curate", "start", "--max-bytes", "10000")

    if expected is None:
        assert result.returncode == 0, result.stderr
        assert path.read_bytes() == before
    else:
        _failure(result, expected)
        assert path.read_bytes() == before


def test_ignored_nested_markdown_is_not_eligible_or_reported(git_kb: Kb) -> None:
    nested = git_kb.content / "observations/pending/nested/ignored.md"
    nested.parent.mkdir()
    nested.write_text("---\ntitle: Nested\n---\n\nNested text.\n", encoding="utf-8")
    ignore = git_kb.content / ".gitignore"
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    ignore.write_text(existing + "observations/pending/nested/\n", encoding="utf-8")
    _commit(git_kb, ".gitignore")

    result = git_kb("curate", "start", "--max-bytes", "10000")

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

    result = git_kb("curate", "start", "--max-bytes", "10000")

    _failure(result, "symlink")
    assert not list((git_kb.content / "observations/batches").glob("*.json"))


def test_repository_and_filename_paths_with_spaces_are_safe(tmp_path: Path) -> None:
    git_kb = make_git_kb(tmp_path / "repository path with spaces")
    content = _pending(git_kb, "20261028T010000-a space.md")
    content.write_text("---\ntitle: A spaced path\ncreated: 2026-10-20\n---\n", encoding="utf-8")
    _commit(git_kb, "observations/pending/20261028T010000-a space.md")

    result = git_kb("curate", "start", "--max-bytes", str(len(content.read_bytes())), content.name)

    assert result.returncode == 0, result.stderr
    manifest = json.loads(
        (git_kb.content / "observations/batches" / f"{_run_id(result)}.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest_member_names(manifest) == [content.name]


def test_later_observe_and_gap_commits_do_not_change_the_selected_set(git_kb: Kb) -> None:
    started = git_kb("curate", "start", "--max-bytes", "100000")
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

    result = git_kb("curate", "start", "--max-bytes", "100000")

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
    assert not (kb.content / ".observe.lock").exists()


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
