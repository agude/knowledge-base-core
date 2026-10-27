"""End-to-end tests for compatibility with the old scripts in ~/Knowledge/scripts.

Skipped unless KB_OLD_TOOLING is set to a checkout of the old tooling. `just
test-compat` sets it. Each test copies the fixture into a temporary git
repository, points the old scripts at it with KB_CONTENT_DIR, and never touches
the real content.

Each test is marked xfail(strict=True) until the command is registered, and
step 5 removes the markers.
"""

import os
import re
import subprocess
import sys
import time
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


def run_old(kb: Kb, name: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run an old script with the test's content repository as its content directory."""
    return subprocess.run(
        [str(old_script(name)), *args],
        cwd=kb.home,
        env=kb.environment({"KB_CONTENT_DIR": str(kb.content)}),
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


@pytest.mark.xfail(strict=True, reason="kb observe is not implemented yet")
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


@pytest.mark.xfail(strict=True, reason="kb observe is not implemented yet")
def test_old_frontmatter_field_reads_kb_files_as_it_reads_old_files(git_kb: Kb) -> None:
    old = written_name(run_old(git_kb, "observe", "--title", "Field check", "--body", "Read."))
    new = written_name(git_kb("observe", "--title", "Field check", "--body", "Read."))
    for field in ("title", "source"):
        assert old_field(git_kb, field, new) == old_field(git_kb, field, old)
    assert old_field(git_kb, "title", new) == "Field check"
    assert old_field(git_kb, "source", new) == "session"
    for name in (old, new):
        assert TIMESTAMP.fullmatch(old_field(git_kb, "created", name))


@pytest.mark.xfail(strict=True, reason="kb observe is not implemented yet")
def test_old_pending_lists_a_kb_observation_with_its_title(git_kb: Kb) -> None:
    name = written_name(git_kb("observe", "--title", "Listed title", "--body", "Listed body."))
    listing = run_old(git_kb, "pending")
    assert listing.returncode == 0, listing.stderr
    assert "Listed title" in listing.stdout
    assert f"[{name}]" in listing.stdout


@pytest.mark.xfail(strict=True, reason="kb observe is not implemented yet")
def test_old_archive_moves_a_kb_observation_and_commits_it(git_kb: Kb) -> None:
    name = written_name(git_kb("observe", "--title", "Archived title", "--body", "Archived body."))
    archived = run_old(git_kb, "archive", name)
    assert archived.returncode == 0, archived.stderr
    assert archived.stdout == f"Archived: observations/pending/{name}\n"
    assert not (git_kb.content / "observations" / "pending" / name).exists()
    assert (git_kb.content / "observations" / "archived" / name).is_file()
    assert git_kb.git("log", "-1", "--format=%s") == "Archive: 1 observation(s)\n"
    assert git_kb.git("status", "--porcelain") == ""


@pytest.mark.xfail(strict=True, reason="kb observe is not implemented yet")
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
