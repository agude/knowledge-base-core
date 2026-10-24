"""install - Wire hooks and skills into the system.

Creates symlinks for the shared skills and content-repo hook.
Idempotent — safe to re-run after updates.

Usage:
  install

Environment:
  KNOWLEDGE_BASE   Tooling checkout used by host adapters (optional when
                   running this script directly).
  KB_CONTENT_DIR   Content repository that receives the git hook; defaults
                   to <tooling checkout>/content.

Locations:
  Skills:     ~/.agents/skills/<name>  (shared agent location)
  Git hooks:  <content>/.git/hooks/pre-commit
"""

from __future__ import annotations

import compileall
import os
import sys
from pathlib import Path

from kb import cli, platform
from kb.content import ROOT, content_dir

LEGACY = (
    ("SessionStart", "session-start"),
    ("UserPromptSubmit", "session-prompt"),
    ("Stop", "session-stop"),
    ("SessionEnd", "session-end"),
    ("PreToolUse", "pretool-allow"),
)


def _relink(link: Path, target: Path | str) -> None:
    """ln -sfn: replace whatever is at link with a symlink to target."""
    if link.is_symlink() or link.is_file():
        link.unlink()
    platform.symlink(target, link)


def install(executables: Path, content: Path) -> None:
    home = Path(os.environ.get("HOME", "~")).expanduser()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    legacy_dir = config / "coat-tree" / "hooks.d"
    knowledge_base = os.environ.get("KNOWLEDGE_BASE")
    legacy_scripts = Path(knowledge_base) / "scripts" if knowledge_base else executables

    # Hooks once linked straight to lifecycle scripts; point them at the adapters.
    migrated = 0
    for event, name in LEGACY:
        link = legacy_dir / event / "010.knowledge"
        if not link.is_symlink():
            continue
        target = str(link.readlink())
        if target not in (str(executables / name), str(legacy_scripts / name)):
            continue
        adapter = executables / "adapters" / "claude" / name
        try:
            if adapter.is_file():
                _relink(link, adapter)
            else:
                link.unlink()
            migrated += 1
        except OSError:
            print(f"  warning: cannot migrate legacy hook {link}", file=sys.stderr)
    if migrated:
        print(f"Migrated {migrated} legacy Claude hook(s).")

    skills_dirs = [home / ".agents" / "skills"]
    removed = 0
    for skills_dir in skills_dirs:
        for link in sorted(skills_dir.glob("*"), key=bytes) if skills_dir.is_dir() else []:
            if link.is_symlink() and str(link.readlink()).startswith(f"{ROOT}/"):
                link.unlink(missing_ok=True)
                removed += 1
    if removed:
        print(f"Removed {removed} prior skill symlink(s).")

    print("Installing skills...")
    for skills_dir in skills_dirs:
        try:
            skills_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            print(f"  warning: cannot write skills at {skills_dir}", file=sys.stderr)
            continue
        for skill in sorted((p for p in (ROOT / "skills").glob("*") if p.is_dir()), key=bytes):
            try:
                _relink(skills_dir / skill.name, skill)  # No trailing slash (audit A-007).
                print(f"  {skills_dir / skill.name}")
            except OSError:
                print(f"  warning: cannot install {skills_dir / skill.name}", file=sys.stderr)

    if (content / ".git").is_dir():
        print("Installing content repo git hooks...")
        hooks = content / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        _relink(hooks / "pre-commit", executables / "hooks" / "pre-commit")
        print("  pre-commit")

    # The preamble tries this interpreter first, so hooks start one process,
    # and compiled bytecode spares the first hook run the compile (plan 3.2).
    record = ROOT / ".python-interpreter"
    interpreter = f"{os.path.realpath(sys.executable)}\n"  # Not a link that may go away.
    if not record.is_file() or platform.read_text(record) != interpreter:
        platform.write_text(record, interpreter)
    compileall.compile_dir(str(ROOT / "kb"), quiet=1)
    print("Done.")

    if not knowledge_base:
        print(
            f'\nNote: KNOWLEDGE_BASE is not set in your shell.\n  Add to your shell config:\n    export KNOWLEDGE_BASE="{ROOT}"'
        )


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    cli.parse(argv, __doc__)
    install(Path(sys.argv[0]).resolve().parent, content_dir())
    return 0
