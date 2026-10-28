"""End-to-end checks of `kb setup --init`: the layout, the hook, the initial commit, and origin.

The installed hook is a POSIX shell script, so these tests run only where Git runs it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from .harness import Kb, run_git

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the installed pre-commit hook is a POSIX shell script"
)
LAYOUT = (
    "knowledge",
    "sources",
    "observations/pending",
    "observations/archived",
    "observations/batches",
    "questions/open",
    "questions/resolved",
)


def shim(kb: Kb) -> Path:
    """A kb executable that runs this interpreter's kb, at a path that an install would use."""
    path = kb.home / "bin" / "kb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m kb "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def without_content_override(kb: Kb) -> dict[str, str | None]:
    """The environment that makes kb read the configured content, not the fixture."""
    return {"KB_CONTENT": None}


def test_init_creates_the_layout_the_hook_the_config_and_one_commit_on_main(kb: Kb) -> None:
    target = kb.home / "new-content"

    result = kb("setup", "--init", str(target), "--kb", str(shim(kb)))

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        f"Init: created {target}\n"
        f"Config: created {kb.config_file}\n"
        f"Hook: installed {target / '.git' / 'hooks' / 'pre-commit'}\n"
    )
    for relative in LAYOUT:
        assert (target / relative / ".gitkeep").read_bytes() == b""
    assert (target / ".gitattributes").read_bytes() == b"* text=auto eol=lf\n"
    assert "rules for agents" in (target / "AGENTS.md").read_text(encoding="utf-8")
    assert run_git(target, "rev-parse", "--abbrev-ref", "HEAD") == "main\n"
    assert run_git(target, "log", "--format=%s") == "Initialize knowledge base content\n"
    assert kb.config_file.read_text(encoding="utf-8") == f'content = "{target.as_posix()}"\n'


def test_the_installed_hook_refuses_an_invalid_article_after_init(kb: Kb) -> None:
    target = kb.home / "new-content"
    assert kb("setup", "--init", str(target), "--kb", str(shim(kb))).returncode == 0
    (target / "knowledge" / "broken.md").write_text("no front matter\n", encoding="utf-8")
    run_git(target, "add", "--", "knowledge/broken.md")

    result = subprocess.run(
        ["git", "commit", "-q", "-m", "Add a broken article"],
        cwd=target,
        env=kb.environment({}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )

    assert result.returncode != 0
    assert "hook:" in result.stderr


def test_a_non_empty_path_is_refused_and_nothing_is_written(kb: Kb) -> None:
    target = kb.home / "occupied"
    target.mkdir()
    (target / "notes.txt").write_text("mine\n", encoding="utf-8")

    result = kb("setup", "--init", str(target), "--kb", str(shim(kb)))

    assert result.returncode == 1
    assert result.stdout == (
        f"Init: refused {target}\nConfig: refused {kb.config_file}\nHook: refused -\n"
    )
    assert f"setup: {target} exists and is not an empty directory" in result.stderr
    assert (target / "notes.txt").read_text(encoding="utf-8") == "mine\n"
    assert not (target / ".git").exists()
    assert not kb.config_file.exists()


def test_without_kb_on_path_init_creates_nothing(kb: Kb) -> None:
    target = kb.home / "never-made"

    result = kb("setup", "--init", str(target), env={"PATH": ""})

    assert result.returncode == 1
    assert result.stdout == (
        f"Init: refused {target}\nConfig: refused {kb.config_file}\nHook: refused -\n"
    )
    assert "kb is not on PATH" in result.stderr
    assert not target.exists()


def test_init_with_a_bare_origin_pushes_and_the_commands_work_on_the_new_repository(
    kb: Kb,
) -> None:
    target = kb.home / "new-content"
    origin = kb.home / "origin.git"
    run_git(kb.home, "init", "--bare", "-q", "-b", "main", str(origin))

    result = kb("setup", "--init", str(target), "--origin", str(origin), "--kb", str(shim(kb)))

    assert result.returncode == 0, result.stderr
    assert run_git(origin, "rev-parse", "refs/heads/main") == run_git(target, "rev-parse", "HEAD")
    new = without_content_override(kb)
    observed = kb(
        "observe",
        "--title",
        "Build tool choice",
        "--body",
        "The project builds with uv.",
        env=new,
    )
    assert observed.returncode == 0, observed.stderr
    recalled = kb("recall", "uv", env=new)
    assert recalled.returncode == 0, recalled.stderr
    mapped = kb("map", env=new)
    assert mapped.returncode == 0, mapped.stderr
    linted = kb("lint", env=new)
    assert linted.returncode == 0, linted.stderr
    synced = kb("sync", env=new)
    assert synced.returncode == 0, synced.stderr
    assert run_git(origin, "rev-parse", "refs/heads/main") == run_git(target, "rev-parse", "HEAD")


def test_a_push_failure_keeps_the_local_repository_and_names_the_recovery(kb: Kb) -> None:
    target = kb.home / "new-content"
    missing_origin = kb.home / "missing.git"

    result = kb(
        "setup", "--init", str(target), "--origin", str(missing_origin), "--kb", str(shim(kb))
    )

    assert result.returncode == 1
    assert result.stdout.startswith(f"Init: created {target}\n")
    assert f"Config: created {kb.config_file}\n" in result.stdout
    assert "setup: git push failed:" in result.stderr
    assert "setup: the local repository is kept. After fixing origin, run: kb sync" in result.stderr
    assert run_git(target, "log", "--format=%s") == "Initialize knowledge base content\n"


def test_origin_without_init_and_init_with_content_are_usage_errors(kb: Kb) -> None:
    origin_alone = kb("setup", "--origin", "/tmp/x.git")
    both = kb("setup", "--init", str(kb.home / "a"), "--content", str(kb.home))

    assert origin_alone.returncode == 1
    assert origin_alone.stderr.startswith("Usage: kb setup")
    assert both.returncode == 1
    assert both.stderr.startswith("Usage: kb setup")
    assert not (kb.home / "a").exists()


def test_gap_and_curate_start_work_on_the_new_repository(kb: Kb) -> None:
    target = kb.home / "new-content"
    origin = kb.home / "origin.git"
    run_git(kb.home, "init", "--bare", "-q", "-b", "main", str(origin))
    created = kb("setup", "--init", str(target), "--origin", str(origin), "--kb", str(shim(kb)))
    assert created.returncode == 0, created.stderr
    new = without_content_override(kb)

    gapped = kb(
        "gap",
        "--title",
        "Backup window",
        "--body",
        "Which window applies?",
        "--context",
        "knowledge",
        env=new,
    )
    assert gapped.returncode == 0, gapped.stderr
    observed = kb(
        "observe", "--title", "Build tool", "--body", "The project builds with uv.", env=new
    )
    assert observed.returncode == 0, observed.stderr
    started = kb("curate", "start", "--no-sync", "--max-bytes", "100000", env=new)
    assert started.returncode == 0, started.stderr
