"""Select the implementation under test.

KB_IMPL names the implementation: bash, python, null0, or null1. The name is
the identity used by markers. KB_SCRIPTS_DIR may override where the
executables live, but never the identity.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BASH_SCRIPTS = REPO / "scripts"
PYTHON_SCRIPTS = REPO / "python"
FROZEN_TAG = "bash-frozen"

IMPLEMENTATIONS = ("bash", "python", "null0", "null1")

# Files under scripts/ that are not executables in the interface surface.
_NOT_EXECUTABLES = {"_lib.sh", "portability-lint"}
_SKIPPED_DIRS = {"pi", "node_modules"}


@dataclass(frozen=True)
class Impl:
    """One implementation tree.

    name: identity (bash, python, null0, null1).
    scripts_dir: directory that holds the executables, laid out like scripts/.
    kb_root: value for KNOWLEDGE_BASE, the parent of scripts_dir.
    """

    name: str
    scripts_dir: Path
    kb_root: Path

    def executable(self, script: str) -> Path:
        return self.scripts_dir / script

    def has(self, script: str) -> bool:
        path = self.executable(script)
        return path.is_file() and os.access(path, os.X_OK)


def selected_name() -> str:
    name = os.environ.get("KB_IMPL", "bash")
    if name not in IMPLEMENTATIONS:
        raise ValueError(f"KB_IMPL must be one of {', '.join(IMPLEMENTATIONS)}; got {name!r}")
    return name


def interface_executables(scripts_dir: Path = BASH_SCRIPTS) -> list[str]:
    """Return executable paths relative to scripts_dir, such as adapters/claude/session-start."""
    found = []
    for path in sorted(scripts_dir.rglob("*")):
        rel = path.relative_to(scripts_dir)
        if any(part in _SKIPPED_DIRS for part in rel.parts):
            continue
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        if rel.name in _NOT_EXECUTABLES or rel.suffix in {".sh", ".jq", ".ts", ".json"}:
            continue
        found.append(rel.as_posix())
    return found


def frozen_tag_exists() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{FROZEN_TAG}"],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def add_frozen_worktree(dest: Path) -> Path:
    """Check out the bash-frozen tag into dest and return its scripts directory."""
    subprocess.run(
        ["git", "worktree", "add", "--detach", "--quiet", str(dest), FROZEN_TAG],
        cwd=REPO,
        check=True,
    )
    return dest / "scripts"


def remove_worktree(dest: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(dest)],
        cwd=REPO,
        check=False,
        capture_output=True,
    )


def build_null_tree(dest: Path, exit_code: int) -> Path:
    """Create executables that exit with exit_code and print nothing."""
    scripts_dir = dest / "scripts"
    for rel in interface_executables():
        path = scripts_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
        path.chmod(0o755)
    return scripts_dir


def describe_scripts() -> str:
    """Where the selected implementation's executables come from, for the report header."""
    name = selected_name()
    override = os.environ.get("KB_SCRIPTS_DIR")
    if override:
        return str(Path(override).resolve())
    if name == "bash" and frozen_tag_exists():
        sha = subprocess.run(
            ["git", "rev-parse", "--short", f"{FROZEN_TAG}^{{commit}}"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return (
            f"tag {FROZEN_TAG} ({sha}), a worktree per worker at <basetemp>/**/impls*/{FROZEN_TAG}"
        )
    if name == "bash":
        return str(BASH_SCRIPTS)
    if name == "python":
        return f"a copy of {PYTHON_SCRIPTS} per worker at <basetemp>/**/impls*/python-tree"
    return "generated null tree"


# What a Python tree needs at run time: the package, its executables, the
# root markers, the instructions session-context prints, the skills
# install links, and the Pi adapter files doctor checks.
PYTHON_TREE = (
    "kb",
    "python",
    "skills",
    "pyproject.toml",
    "AGENTS.md",
    "CLAUDE.md",
    "scripts/adapters/pi",
)


def copy_python_tree(dest: Path) -> Path:
    """Copy the Python implementation into dest and return its executables directory.

    Tests run from a copy, as bash runs from a worktree of its tag, so that
    install writing .python-interpreter or compiled bytecode never touches
    the working tree, and one run's interpreter cannot leak into the next.
    """
    if not dest.exists():
        for name in PYTHON_TREE:
            source = REPO / name
            if source.is_dir():
                shutil.copytree(
                    source,
                    dest / name,
                    symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "node_modules"),
                )
            elif source.is_file():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest / name)
    return dest / "python"


def resolve(name: str, scratch: Path) -> Impl:
    """Resolve an implementation name to a tree, creating it under scratch if needed."""
    override = os.environ.get("KB_SCRIPTS_DIR")
    if override and name == selected_name():
        scripts_dir = Path(override).resolve()
    elif name == "bash":
        if frozen_tag_exists():
            scripts_dir = add_frozen_worktree(scratch / "bash-frozen")
        else:
            scripts_dir = BASH_SCRIPTS
    elif name == "python":
        scripts_dir = copy_python_tree(scratch / "python-tree")
    elif name in {"null0", "null1"}:
        scripts_dir = build_null_tree(scratch / name, int(name[-1]))
    else:
        raise ValueError(f"unknown implementation {name!r}")
    return Impl(name=name, scripts_dir=scripts_dir, kb_root=scripts_dir.parent)
