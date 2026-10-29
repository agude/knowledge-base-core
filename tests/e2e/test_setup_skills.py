"""`kb setup` installs managed skills without replacing foreign targets."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kb import __version__

from .harness import Kb, skill_lines, skill_paths

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the installed Git hook is a shell script"
)


def kb_executable(kb: Kb) -> Path:
    """Create a runner shim at the path setup records in the Git hook."""
    path = kb.home / "bin" / "kb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m kb "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def setup(kb: Kb, *options: str) -> subprocess.CompletedProcess[str]:
    """Run setup with the fixture content repository and the local kb shim."""
    return kb(
        "setup",
        "--content",
        str(kb.content),
        "--kb",
        str(kb_executable(kb)),
        *options,
    )


def test_setup_installs_both_skills_for_both_hosts_then_reports_unchanged(git_kb: Kb) -> None:
    first = setup(git_kb)

    assert first.returncode == 0, first.stderr
    assert first.stdout == (
        f"Config: created {git_kb.config_file}\n"
        f"Hook: installed {git_kb.content / '.git' / 'hooks' / 'pre-commit'}\n"
        f"{skill_lines(git_kb, 'installed')}"
    )
    for path in skill_paths(git_kb):
        assert (path / ".kb-managed").read_text(encoding="utf-8") == f"{__version__}\n"
        assert (path / "SKILL.md").is_file()

    second = git_kb("setup", "--kb", str(kb_executable(git_kb)))

    assert second.returncode == 0, second.stderr
    assert second.stdout.endswith(skill_lines(git_kb, "unchanged"))


def test_a_refused_foreign_skill_does_not_stop_config_or_hook_setup(git_kb: Kb) -> None:
    foreign = git_kb.home / ".agents" / "skills" / "curate"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("user-owned skill\n", encoding="utf-8")
    original = (foreign / "SKILL.md").read_bytes()

    result = setup(git_kb)

    assert result.returncode == 1
    assert f"Config: created {git_kb.config_file}" in result.stdout
    assert f"Hook: installed {git_kb.content / '.git' / 'hooks' / 'pre-commit'}" in result.stdout
    assert f"Skill: refused {foreign}" in result.stdout
    assert "kb did not install it" in result.stderr
    assert git_kb.config_file.is_file()
    assert (git_kb.content / ".git" / "hooks" / "pre-commit").is_file()
    assert (foreign / "SKILL.md").read_bytes() == original


def test_a_symbolic_link_skill_is_refused_and_its_target_is_kept(git_kb: Kb) -> None:
    installed = setup(git_kb)
    assert installed.returncode == 0, installed.stderr
    path = git_kb.home / ".claude" / "skills" / "curate"
    shutil.rmtree(path)
    target = git_kb.home / "elsewhere" / "curate"
    target.mkdir(parents=True)
    (target / "README.md").write_bytes(b"other skill bytes\n")
    target_digest = hashlib.sha256((target / "README.md").read_bytes()).hexdigest()
    path.symlink_to(target)

    refused = git_kb("setup", "--kb", str(kb_executable(git_kb)))

    assert refused.returncode == 1
    assert f"Skill: refused {path}" in refused.stdout
    assert path.is_symlink()
    assert hashlib.sha256((target / "README.md").read_bytes()).hexdigest() == target_digest


def test_doctor_reports_missing_different_old_and_foreign_skills(git_kb: Kb) -> None:
    installed = setup(git_kb)
    assert installed.returncode == 0, installed.stderr

    def skills_line() -> str:
        result = git_kb("doctor")
        return next(line for line in result.stdout.splitlines() if " skills: " in line)

    assert skills_line() == "PASS skills: both skills match the package for Claude Code and Codex"

    claude = git_kb.home / ".claude" / "skills" / "knowledge-base"
    (claude / "SKILL.md").write_text("different\n", encoding="utf-8")
    assert "Claude Code knowledge-base differs from the package" in skills_line()

    codex = git_kb.home / ".agents" / "skills" / "knowledge-base"
    shutil.rmtree(codex)
    assert "Codex knowledge-base is missing" in skills_line()

    shutil.rmtree(claude)
    claude.symlink_to(git_kb.home / "elsewhere")
    assert "Claude Code knowledge-base is unmanaged" in skills_line()

    claude.unlink()
    claude.mkdir()
    (claude / "SKILL.md").write_text("user-owned\n", encoding="utf-8")
    result = git_kb("doctor")
    lines = result.stdout.splitlines()
    assert any("Claude Code knowledge-base is unmanaged" in line for line in lines)
    index = next(i for i, line in enumerate(lines) if line.startswith("WARN skills:"))
    assert lines[index + 1] == "  fix: move unmanaged skill paths aside, then run kb setup"


def test_doctor_does_not_change_installed_skill_files(git_kb: Kb) -> None:
    installed = setup(git_kb)
    assert installed.returncode == 0, installed.stderr
    before = {
        str(path.relative_to(git_kb.home)): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in (git_kb.home / ".claude" / "skills", git_kb.home / ".agents" / "skills")
        for path in directory.rglob("*")
        if path.is_file()
    }

    git_kb("doctor")

    after = {
        str(path.relative_to(git_kb.home)): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in (git_kb.home / ".claude" / "skills", git_kb.home / ".agents" / "skills")
        for path in directory.rglob("*")
        if path.is_file()
    }
    assert after == before
