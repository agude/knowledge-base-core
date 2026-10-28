"""End-to-end tests for compatibility with the old scripts in ~/Knowledge/scripts.

Skipped unless KB_OLD_TOOLING is set to a checkout of the old tooling. `just
test-compat` sets it. Each test copies the fixture into a temporary Git
repository, points the old scripts at it with KB_CONTENT_DIR, and leaves the
real content untouched.
"""

import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from .harness import Kb

OLD_TOOLING = os.environ.get("KB_OLD_TOOLING", "")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
WROTE_PREFIX = "Wrote: observations/pending/"
pytestmark = pytest.mark.skipif(not OLD_TOOLING, reason="KB_OLD_TOOLING is not set")


def old_script(name: str) -> Path:
    """The file `name` in the scripts directory of the checkout that KB_OLD_TOOLING names.

    Raises AssertionError when the checkout does not have it.
    """
    path = Path(OLD_TOOLING).expanduser() / "scripts" / name
    assert path.is_file(), f"KB_OLD_TOOLING has no scripts/{name}: {path}"
    return path


def run_old(
    kb: Kb,
    name: str,
    *args: str,
    env: Mapping[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an old script with the test's content repository as its content directory."""
    overrides = {"KB_CONTENT_DIR": str(kb.content), **(env or {})}
    return subprocess.run(
        [str(old_script(name)), *args],
        cwd=kb.home,
        env=kb.environment(overrides),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def written_name(result: subprocess.CompletedProcess[str]) -> str:
    """The file name from a successful run's Wrote line, whichever script printed it."""
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(WROTE_PREFIX), result.stdout
    assert result.stdout.endswith("\n"), result.stdout
    return result.stdout[len(WROTE_PREFIX) : -1]


def read_pending(kb: Kb, name: str) -> str:
    """The text of a file in observations/pending."""
    return (kb.content / "observations" / "pending" / name).read_text(encoding="utf-8")


def without_created_or_attribution(text: str) -> list[str]:
    """The lines that must match between the two scripts: all but created, project, and host."""
    return [
        line
        for line in text.splitlines(keepends=True)
        if not line.startswith(("created: ", "project: ", "host: "))
    ]


def old_field(kb: Kb, field: str, name: str) -> str:
    """The value that the old frontmatter_field prints for one field of a pending file."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1" && frontmatter_field "$2" "$3"',
            "bash",
            str(old_script("_lib.sh")),
            field,
            str(kb.content / "observations" / "pending" / name),
        ],
        cwd=kb.home,
        env=kb.environment({"KB_CONTENT_DIR": str(kb.content)}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.removesuffix("\n")


def old_question_field(kb: Kb, field: str, name: str) -> str:
    """Read a question field with the old tooling's YAML front-matter helper."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1" && frontmatter_field "$2" "$3"',
            "bash",
            str(old_script("_lib.sh")),
            field,
            str(kb.content / "questions" / "open" / name),
        ],
        cwd=kb.home,
        env=kb.environment({"KB_CONTENT_DIR": str(kb.content)}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.removesuffix("\n")


def test_kb_observe_writes_what_the_old_script_writes_plus_attribution(git_kb: Kb) -> None:
    title = 'Say "hi" \\ there'
    body = "Written by both scripts."
    old = run_old(git_kb, "observe", "--title", title, "--body", body)
    new = git_kb("observe", "--title", title, "--body", body)
    old_text = read_pending(git_kb, written_name(old))
    new_text = read_pending(git_kb, written_name(new))
    assert without_created_or_attribution(new_text) == without_created_or_attribution(old_text)
    assert "project: " not in old_text
    assert "host: " not in old_text
    assert "project: " in new_text
    assert "host: " in new_text
    assert git_kb.git("log", "--format=%s", "-2") == f"Observe: {title}\n" * 2


def test_old_frontmatter_field_reads_kb_files_as_it_reads_old_files(git_kb: Kb) -> None:
    old = written_name(run_old(git_kb, "observe", "--title", "Field check", "--body", "Read."))
    new = written_name(git_kb("observe", "--title", "Field check", "--body", "Read."))
    for field in ("title", "source"):
        assert old_field(git_kb, field, new) == old_field(git_kb, field, old)
    assert old_field(git_kb, "title", new) == "Field check"
    assert old_field(git_kb, "source", new) == "session"
    for name in (old, new):
        assert TIMESTAMP.fullmatch(old_field(git_kb, "created", name))


def test_old_stale_and_lint_accept_an_article_written_by_kb_verify(git_kb: Kb) -> None:
    article = git_kb.content / "knowledge" / "infra" / "nas.md"
    text = article.read_text(encoding="utf-8")
    article.write_text(
        text.replace('title: "NAS"\n', 'title: "NAS"\nupdated: 2026-10-20\n'), encoding="utf-8"
    )

    verified = git_kb("verify", "knowledge/infra/nas.md")
    assert verified.returncode == 0, verified.stderr

    linted = run_old(git_kb, "lint", "--path", "knowledge/infra/nas.md")
    assert linted.returncode == 0, linted.stderr
    assert "0 error(s)" in linted.stdout

    today_epoch = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp())
    stale = run_old(
        git_kb,
        "stale",
        "--path",
        "knowledge/infra",
        env={"FRESHNESS_TODAY_EPOCH": str(today_epoch)},
    )
    assert stale.returncode == 0, stale.stderr
    assert "knowledge/infra/nas.md" not in stale.stdout


def test_old_pending_lists_a_kb_observation_with_its_title(git_kb: Kb) -> None:
    name = written_name(git_kb("observe", "--title", "Listed title", "--body", "Listed body."))
    listing = run_old(git_kb, "pending")
    assert listing.returncode == 0, listing.stderr
    assert "Listed title" in listing.stdout
    assert f"[{name}]" in listing.stdout


def test_old_archive_moves_a_kb_observation_and_commits_it(git_kb: Kb) -> None:
    name = written_name(git_kb("observe", "--title", "Archived title", "--body", "Archived body."))
    archived = run_old(git_kb, "archive", name)
    assert archived.returncode == 0, archived.stderr
    assert archived.stdout == f"Archived: observations/pending/{name}\n"
    assert not (git_kb.content / "observations" / "pending" / name).exists()
    assert (git_kb.content / "observations" / "archived" / name).is_file()
    assert git_kb.git("log", "-1", "--format=%s") == "Archive: 1 observation(s)\n"
    assert git_kb.git("status", "--porcelain") == ""


def test_old_questions_and_resolve_accept_a_gap_with_quoted_unicode_fields(git_kb: Kb) -> None:
    title = 'Where is "München" \\ backup?'
    context = "knowledge/infra/nas.md"
    body = "The answer is not recorded."
    result = git_kb("gap", "--title", title, "--body", body, "--context", context)
    assert result.returncode == 0, result.stderr
    prefix = "Wrote: questions/open/"
    assert result.stdout.startswith(prefix), result.stdout
    name = result.stdout[len(prefix) :].removesuffix("\n")

    listing = run_old(git_kb, "questions")
    assert listing.returncode == 0, listing.stderr
    assert f"- {title} ({context})" in listing.stdout
    inspection = run_old(git_kb, "questions", "--file", name)
    assert inspection.returncode == 0, inspection.stderr
    assert body in inspection.stdout
    assert old_question_field(git_kb, "title", name) == title
    assert old_question_field(git_kb, "context", name) == context
    assert old_question_field(git_kb, "source", name) == "session"

    answer = "See the archived note: café backup remains unknown."
    resolved = run_old(git_kb, "resolve", "--file", name, "--answer", answer)
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == f"Resolved: questions/open/{name} -> questions/resolved/{name}\n"
    resolved_path = git_kb.content / "questions" / "resolved" / name
    resolved_text = resolved_path.read_text(encoding="utf-8")
    assert resolved_text.startswith(inspection.stdout.split("\n\n## Resolution", 1)[0])
    assert answer in resolved_text
    assert 'title: "Where is \\"München\\" \\\\ backup?"\n' in resolved_text
    assert f'context: "{context}"\n' in resolved_text
    assert 'project: "' in resolved_text
    assert 'host: "' in resolved_text
    assert git_kb.git("log", "-1", "--format=%s") == f"Resolve: {title}\n"
    assert not (git_kb.content / "questions" / "open" / name).exists()
    assert git_kb.git("status", "--porcelain") == ""


def test_kb_observe_waits_for_a_legacy_lock_until_the_old_script_releases_it(
    git_kb: Kb,
) -> None:
    holder = subprocess.Popen(
        [
            "bash",
            "-c",
            'source "$1" && acquire_lock && echo locked && { read -r _ || true; } && release_lock',
            "bash",
            str(old_script("_lib.sh")),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=git_kb.environment({"KB_CONTENT_DIR": str(git_kb.content)}),
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == "locked\n"
        observer = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kb",
                "observe",
                "--title",
                "After the lock",
                "--body",
                "Waited for the old lock.",
            ],
            cwd=git_kb.home,
            env=git_kb.environment({"KB_LOCK_WAIT": "10"}),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        time.sleep(1.5)
        assert observer.poll() is None, "kb observe finished while the old lock was held"
        holder.stdin.close()
        stdout, stderr = observer.communicate(timeout=30)
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert observer.returncode == 0, stderr
    assert stdout.startswith(WROTE_PREFIX)
    assert git_kb.git("log", "-1", "--format=%s") == "Observe: After the lock\n"
    assert not (git_kb.content / ".observe.lock").exists()
