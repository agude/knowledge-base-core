"""End-to-end checks of `kb setup`: the config key, the installed pre-commit hook, and refusals.

The installed hook is a POSIX shell script, so these tests run only where Git runs it. The
unit tests cover the same rules in process on every platform.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from .harness import HOLD_KERNEL_LOCK, TODAY, Kb, run_git

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the installed pre-commit hook is a POSIX shell script"
)
ARTICLE = (
    "---\ntitle: Backups\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
    "# Backups\n\n## 1. Schedule\n\nNightly.\n"
)
MARKER = "# Installed by kb setup. Do not edit; run kb setup again to update.\n"


def shim(kb: Kb) -> Path:
    """A kb executable that runs this interpreter's kb, at a path that an install would use."""
    path = kb.home / "bin" / "kb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m kb "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def hook_of(kb: Kb) -> Path:
    return kb.content / ".git" / "hooks" / "pre-commit"


def setup_for(
    kb: Kb, *extra: str, env: dict[str, str | None] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run setup for this content repository with the shim as kb."""
    return kb("setup", "--content", str(kb.content), "--kb", str(shim(kb)), *extra, env=env)


def commit(kb: Kb, message: str) -> subprocess.CompletedProcess[str]:
    """Commit the index through git, with the isolated environment, so the hook sees the clock.

    A path-limited commit would use a temporary index, which the hook treats as partial.
    """
    return subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=kb.content,
        env=kb.environment({}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def test_the_first_run_writes_the_config_and_the_hook_and_the_second_changes_nothing(
    git_kb: Kb,
) -> None:
    first = setup_for(git_kb)

    assert first.returncode == 0, first.stderr
    assert first.stdout == (
        f"Config: created {git_kb.config_file}\nHook: installed {hook_of(git_kb)}\n"
    )
    assert git_kb.config_file.read_text(encoding="utf-8") == (
        f'content = "{git_kb.content.as_posix()}"\n'
    )
    assert hook_of(git_kb).read_text(encoding="utf-8") == (
        f"#!/bin/sh\n{MARKER}exec '{shim(git_kb)}' hook pre-commit \"$@\"\n"
    )

    second = setup_for(git_kb)

    assert second.returncode == 0, second.stderr
    assert second.stdout == (
        f"Config: unchanged {git_kb.config_file}\nHook: unchanged {hook_of(git_kb)}\n"
    )


def test_a_foreign_hook_is_refused_and_left_alone_while_the_config_is_written(git_kb: Kb) -> None:
    foreign = "#!/bin/sh\necho mine\n"
    hook_of(git_kb).write_text(foreign, encoding="utf-8")

    result = setup_for(git_kb)

    assert result.returncode == 1
    assert result.stdout == (
        f"Config: created {git_kb.config_file}\nHook: refused {hook_of(git_kb)}\n"
    )
    assert f"setup: {hook_of(git_kb)} exists and kb did not install it" in result.stderr
    assert hook_of(git_kb).read_text(encoding="utf-8") == foreign


def test_an_old_tooling_link_is_refused_without_the_flag_and_replaced_with_it(
    git_kb: Kb,
) -> None:
    old = git_kb.home / "Knowledge" / "scripts" / "hooks" / "pre-commit"
    old.parent.mkdir(parents=True)
    old.write_text("#!/bin/sh\necho old\n", encoding="utf-8")
    old.chmod(0o755)
    hook_of(git_kb).symlink_to(old)

    refused = setup_for(git_kb)

    assert refused.returncode == 1
    assert "--replace-old-hook" in refused.stderr
    assert hook_of(git_kb).is_symlink()

    replaced = setup_for(git_kb, "--replace-old-hook")

    assert replaced.returncode == 0, replaced.stderr
    assert f"Hook: updated {hook_of(git_kb)}\n" in replaced.stdout
    assert not hook_of(git_kb).is_symlink()
    assert old.read_text(encoding="utf-8") == "#!/bin/sh\necho old\n"


def test_the_installed_hook_runs_on_a_real_commit_and_stamps_the_article(git_kb: Kb) -> None:
    assert setup_for(git_kb).returncode == 0
    article = git_kb.content / "knowledge" / "infra" / "backups.md"
    article.write_text(ARTICLE.replace("Nightly.", "Nightly and weekly."), encoding="utf-8")
    run_git(git_kb.content, "add", "--", "knowledge/infra/backups.md")

    result = commit(git_kb, "Describe the backup schedule")

    assert result.returncode == 0, result.stderr
    assert f"hook: stamped updated: {TODAY} on 1 article(s)" in result.stderr
    assert f"updated: {TODAY}\n" in run_git(
        git_kb.content, "show", "HEAD:knowledge/infra/backups.md"
    )


def test_a_configured_hooks_path_receives_the_hook(git_kb: Kb) -> None:
    run_git(git_kb.content, "config", "core.hooksPath", "custom-hooks")

    result = setup_for(git_kb)

    assert result.returncode == 0, result.stderr
    installed = git_kb.content / "custom-hooks" / "pre-commit"
    assert installed.read_text(encoding="utf-8").startswith("#!/bin/sh\n" + MARKER)
    assert not hook_of(git_kb).exists()


def test_a_held_write_lock_refuses_the_hook_while_the_config_is_written(git_kb: Kb) -> None:
    lock_file = git_kb.content / ".git" / "kb.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_KERNEL_LOCK, str(lock_file)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline() == "locked\n"

        result = setup_for(git_kb)

        assert result.returncode == 1
        assert result.stdout == (
            f"Config: created {git_kb.config_file}\nHook: refused {hook_of(git_kb)}\n"
        )
        assert "setup: content repository is busy" in result.stderr
        assert not hook_of(git_kb).exists()
    finally:
        if holder.stdin is not None:
            holder.stdin.close()
        holder.wait(timeout=10)


def test_a_kb_path_with_a_single_quote_is_refused_before_anything_is_installed(
    git_kb: Kb,
) -> None:
    result = git_kb("setup", "--content", str(git_kb.content), "--kb", "/nowhere/it's/kb")

    assert result.returncode == 1
    assert "Hook: refused -\n" in result.stdout
    assert "single quote" in result.stderr
    assert not hook_of(git_kb).exists()


def test_without_kb_on_path_the_hook_is_refused_and_the_config_is_written(git_kb: Kb) -> None:
    result = git_kb("setup", "--content", str(git_kb.content), env={"PATH": ""})

    assert result.returncode == 1
    assert result.stdout == f"Config: created {git_kb.config_file}\nHook: refused -\n"
    assert "setup: kb is not on PATH; pass --kb PATH" in result.stderr


def test_a_content_path_that_is_not_a_directory_refuses_both_resources(git_kb: Kb) -> None:
    missing = git_kb.home / "missing"

    result = git_kb("setup", "--content", str(missing), "--kb", str(shim(git_kb)))

    assert result.returncode == 1
    assert result.stdout == f"Config: refused {git_kb.config_file}\nHook: refused -\n"
    assert f"not a directory: {missing}" in result.stderr
    assert not git_kb.config_file.exists()


def test_setup_without_a_content_path_refuses_the_hook_and_keeps_the_config(git_kb: Kb) -> None:
    result = git_kb("setup", "--kb", str(shim(git_kb)), env={"KB_CONTENT": None})

    assert result.returncode == 1
    assert result.stdout == f"Config: unchanged {git_kb.config_file}\nHook: refused -\n"
    assert "no content repository" in result.stderr


def test_setup_without_options_installs_into_the_configured_repository(git_kb: Kb) -> None:
    git_kb.config_file.parent.mkdir(parents=True, exist_ok=True)
    git_kb.config_file.write_text(f'content = "{git_kb.content.as_posix()}"\n', encoding="utf-8")

    result = git_kb("setup", "--kb", str(shim(git_kb)), env={"KB_CONTENT": None})

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        f"Config: unchanged {git_kb.config_file}\nHook: installed {hook_of(git_kb)}\n"
    )
