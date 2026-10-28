"""End-to-end tests for synchronized local batch start and its --no-sync form."""

import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from .harness import FIXTURE_TRANSCRIPTS, Kb, run_git

RUN_RE = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")
BATCHES = "observations/batches"
HARVEST_SINCE = "2026-10-24T00:00:00Z"


def _run_id(result: CompletedProcess[str]) -> str:
    match = RUN_RE.search(result.stdout)
    assert match is not None, result.stdout
    return match.group(1)


def _manifest(kb: Kb, run_id: str) -> dict[str, object]:
    path = kb.content / BATCHES / f"{run_id}.json"
    value: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return value


def _manifest_count(kb: Kb) -> int:
    directory = kb.content / BATCHES
    return len(list(directory.glob("*.json"))) if directory.exists() else 0


def _refused(result: CompletedProcess[str], text: str) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr.startswith("curate: no batch created; ")
    assert text in result.stderr


def _observation(title: str) -> str:
    return f"---\ntitle: {title}\ncreated: 2026-10-24\n---\n\n## 1. Evidence\n\n{title} evidence.\n"


def _clone(kb: Kb, name: str) -> Path:
    assert kb.origin is not None
    destination = kb.home / name
    run_git(kb.home, "clone", "-q", str(kb.origin), str(destination))
    return destination


def _push_from(clone: Path, relative: str, text: str, message: str) -> None:
    path = clone / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    run_git(clone, "add", "--", relative)
    run_git(clone, "commit", "-q", "-m", message)
    run_git(clone, "push", "-q", "origin", "main")


def _commit_local(kb: Kb, relative: str, text: str, message: str) -> None:
    path = kb.content / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    kb.git("add", "--", relative)
    kb.git("commit", "-q", "-m", message)


def _head(kb: Kb) -> str:
    return kb.git("rev-parse", "HEAD").strip()


def _origin_head(kb: Kb) -> str:
    assert kb.origin is not None
    return run_git(kb.origin, "rev-parse", "refs/heads/main").strip()


def _member_names(manifest: dict[str, object]) -> list[str]:
    members = manifest["members"]
    assert isinstance(members, list)
    return [str(member["filename"]) for member in members]


def test_synchronized_start_without_origin_creates_no_batch(git_kb: Kb) -> None:
    result = git_kb("curate", "start", "--max-bytes", "1000000")

    _refused(result, "sync: no origin remote")
    assert _manifest_count(git_kb) == 0


def test_synchronized_start_refuses_a_detached_head(remote_git_kb: Kb) -> None:
    run_git(remote_git_kb.content, "checkout", "-q", "--detach")

    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    _refused(result, "sync: current branch is detached")
    assert _manifest_count(remote_git_kb) == 0


def test_synchronized_start_refuses_when_origin_cannot_be_fetched(
    remote_git_kb: Kb, tmp_path: Path
) -> None:
    run_git(remote_git_kb.content, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    _refused(result, "sync: fetch origin/main failed")
    assert _manifest_count(remote_git_kb) == 0


def test_synchronized_start_refuses_a_rebase_conflict_and_keeps_local_commits(
    remote_git_kb: Kb,
) -> None:
    writer = _clone(remote_git_kb, "writer")
    _push_from(writer, "knowledge/infra/backups.md", "# Backups\n\nRemote claim.\n", "Remote claim")
    _commit_local(remote_git_kb, "knowledge/infra/backups.md", "# Backups\n\nLocal.\n", "Local")
    kept = _head(remote_git_kb)

    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    _refused(result, "sync: rebase onto origin/main failed; local commits kept")
    assert _head(remote_git_kb) == kept
    assert remote_git_kb.git("status", "--porcelain") == ""
    assert _manifest_count(remote_git_kb) == 0


@pytest.mark.skipif(sys.platform == "win32", reason="the rejecting hook is a POSIX script")
def test_synchronized_start_refuses_a_rejected_push_and_keeps_the_commit(
    remote_git_kb: Kb,
) -> None:
    assert remote_git_kb.origin is not None
    reject = remote_git_kb.origin / "hooks" / "pre-receive"
    reject.write_text("#!/bin/sh\necho refused >&2\nexit 1\n", encoding="utf-8")
    reject.chmod(0o755)
    _commit_local(remote_git_kb, "knowledge/infra/backups.md", "# Backups\n\nLocal.\n", "Local")
    before = _origin_head(remote_git_kb)

    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    _refused(result, "sync: push origin/main failed")
    assert "refused" in result.stderr
    assert _origin_head(remote_git_kb) == before
    assert _head(remote_git_kb) != before
    assert _manifest_count(remote_git_kb) == 0


def test_synchronized_start_pushes_local_commits_and_records_its_base(remote_git_kb: Kb) -> None:
    _commit_local(remote_git_kb, "knowledge/infra/backups.md", "# Backups\n\nLocal.\n", "Local")

    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    assert result.returncode == 0, result.stderr
    assert "Pushed: 1 commit(s)" in result.stdout
    assert "Pulled:" not in result.stdout
    assert _origin_head(remote_git_kb) == _head(remote_git_kb)
    manifest = _manifest(remote_git_kb, _run_id(result))
    assert manifest["schema_version"] == 2
    assert manifest["synchronized"] is True
    assert manifest["base_commit"] == _head(remote_git_kb)

    status = remote_git_kb("curate", "status", _run_id(result))
    assert status.returncode == 0, status.stderr
    assert "Synchronized: yes" in status.stdout
    assert f"Base commit: {_head(remote_git_kb)}" in status.stdout


def test_synchronized_start_pulls_then_pushes_diverged_history(remote_git_kb: Kb) -> None:
    writer = _clone(remote_git_kb, "writer")
    _push_from(writer, "knowledge/infra/nas.md", "# NAS\n\nRemote change.\n", "Remote change")
    _commit_local(remote_git_kb, "knowledge/infra/backups.md", "# Backups\n\nLocal.\n", "Local")

    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    assert result.returncode == 0, result.stderr
    assert "Pulled: 1 commit(s)" in result.stdout
    assert "Pushed: 1 commit(s)" in result.stdout
    assert _origin_head(remote_git_kb) == _head(remote_git_kb)


def test_synchronized_start_selects_observations_pulled_from_origin(remote_git_kb: Kb) -> None:
    writer = _clone(remote_git_kb, "writer")
    _push_from(
        writer,
        "observations/pending/remote-arrival.md",
        _observation("Remote arrival"),
        "Observe: remote arrival",
    )

    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    assert result.returncode == 0, result.stderr
    assert "Pulled: 1 commit(s)" in result.stdout
    assert "remote-arrival.md" in _member_names(_manifest(remote_git_kb, _run_id(result)))


def test_synchronized_start_reports_when_already_in_sync(remote_git_kb: Kb) -> None:
    result = remote_git_kb("curate", "start", "--max-bytes", "1000000")

    assert result.returncode == 0, result.stderr
    assert "Already in sync." in result.stdout
    assert "Pulled:" not in result.stdout
    assert "Pushed:" not in result.stdout


def test_synchronized_start_harvests_transcripts_before_selecting(remote_git_kb: Kb) -> None:
    kb = remote_git_kb
    kb.config_file.parent.mkdir(parents=True, exist_ok=True)
    kb.config_file.write_text(
        f'content = "{kb.content.as_posix()}"\nharvest_since = {HARVEST_SINCE}\n',
        encoding="utf-8",
    )
    source = FIXTURE_TRANSCRIPTS / "claude" / "projects" / "demo" / "main.jsonl"
    destination = kb.claude_config_dir / "projects" / "demo" / "main.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    ready = datetime.fromisoformat("2026-10-25T00:00:00+00:00").timestamp()
    os.utime(destination, (ready, ready))
    pending = kb.content / "observations" / "pending"
    before = {path.name for path in pending.glob("*.md")}

    result = kb("curate", "start", "--max-bytes", "1000000")

    assert result.returncode == 0, result.stderr
    assert "Harvested: 1 session transcript(s)" in result.stdout
    harvested = [
        name for name in _member_names(_manifest(kb, _run_id(result))) if name not in before
    ]
    assert len(harvested) == 1
    assert (pending / harvested[0]).is_file()


def test_no_sync_creates_a_local_batch_without_origin(git_kb: Kb) -> None:
    result = git_kb("curate", "start", "--no-sync", "--max-bytes", "1000000")

    assert result.returncode == 0, result.stderr
    assert "Not synchronized: local batch" in result.stdout
    manifest = _manifest(git_kb, _run_id(result))
    assert manifest["schema_version"] == 2
    assert manifest["synchronized"] is False
    assert manifest["base_commit"] == _head(git_kb)

    status = git_kb("curate", "status", _run_id(result))
    assert status.returncode == 0, status.stderr
    assert "Synchronized: no" in status.stdout
    assert f"Base commit: {_head(git_kb)}" in status.stdout


def test_version_one_manifests_load_as_unsynchronized_local_batches(git_kb: Kb) -> None:
    name = "20261024T094659-8d6fecbe.md"
    content = (git_kb.content / "observations/pending" / name).read_bytes()
    run_id = "20261028T120000-a1b2c3d4"
    manifest = {
        "schema_version": 1,
        "id": run_id,
        "created": "2026-10-28T12:00:00Z",
        "max_bytes": len(content),
        "selected_bytes": len(content),
        "members": [
            {
                "filename": name,
                "original_sha256": hashlib.sha256(content).hexdigest(),
                "original_bytes": len(content),
                "status": "pending",
                "disposition": None,
                "destinations": [],
                "reason": None,
                "archive_sha256": None,
            }
        ],
    }
    path = git_kb.content / BATCHES / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    status = git_kb("curate", "status", run_id)
    assert status.returncode == 0, status.stderr
    assert "Synchronized: no" in status.stdout
    assert "Base commit: none" in status.stdout

    next_work = git_kb("curate", "next", run_id)
    assert next_work.returncode == 0, next_work.stderr
    assert name in next_work.stdout
    assert path.read_text(encoding="utf-8") == json.dumps(manifest, indent=2) + "\n"
