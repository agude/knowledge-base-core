"""init: create a content repository and wire it up through install."""

from __future__ import annotations

from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.inspect import git, git_log, tree
from kbtest.marks import xfail_bash
from kbtest.runner import KB

WRONG_REPO = xfail_bash("A-008: bash installs the hook into KB_CONTENT_DIR, not --path")


def _state(kb: KB, target: Path) -> str:
    """Tree, commits, local identity, and pre-commit hook of a new repository."""
    env = kb.git_env()
    config = git(target, "config", "--local", "--list", env=env)
    identity = "".join(line + "\n" for line in config.splitlines() if line.startswith("user."))
    hook = target / ".git" / "hooks" / "pre-commit"
    return kb.norm(
        "## tree\n"
        + tree(target)
        + "## log\n"
        + git_log(target, env)
        + "## identity\n"
        + identity
        + "## pre-commit\n"
        + (f"{hook.readlink()}\n" if hook.is_symlink() else "absent\n"),
        repos=(target,),
    )


@pytest.mark.bats("init.bats", "init creates all content directories")
@pytest.mark.bats("init.bats", "init initializes a git repo")
@pytest.mark.bats("init.bats", "init creates .gitkeep files")
@WRONG_REPO
def test_init_with_path(kb: KB, golden: Golden) -> None:
    target = kb.layout.root / "target"
    result = kb.run("init", "--path", str(target))
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out, repos=(target,)))
    golden.check("stderr", kb.norm_err(result.err, repos=(target,)))
    golden.contract("state", _state(kb, target))
    # The configured content repository is not the one being created.
    assert not (kb.layout.content / ".git" / "hooks" / "pre-commit").exists()


@WRONG_REPO
@pytest.mark.bats("init.bats", "init is safe to run twice")
def test_init_twice(kb: KB, golden: Golden) -> None:
    target = kb.layout.root / "target"
    kb.run("init", "--path", str(target))
    result = kb.run("init", "--path", str(target))
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out, repos=(target,)))
    golden.contract("state", _state(kb, target))


@pytest.mark.bats("init.bats", "init uses CONTENT_DIR when no --path given")
def test_init_defaults_to_content_dir(kb: KB, golden: Golden) -> None:
    target = kb.layout.root / "fresh"
    result = kb.run("init", env={"KB_CONTENT_DIR": str(target)})
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out, repos=(target,)))
    golden.contract("state", _state(kb, target))


def test_init_relative_path(kb: KB, golden: Golden) -> None:
    result = kb.run("init", "--path", "relative")
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out))
    golden.contract("tree", tree(kb.layout.root / "relative"))


@WRONG_REPO
def test_init_existing_partial_directory(kb: KB, golden: Golden) -> None:
    target = kb.layout.root / "partial"
    (target / "knowledge").mkdir(parents=True)
    (target / "knowledge" / "keep.md").write_text("# Keep\n", encoding="utf-8")
    result = kb.run("init", "--path", str(target))
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out, repos=(target,)))
    golden.contract("state", _state(kb, target))


def test_init_path_requires_argument(kb: KB, golden: Golden) -> None:
    result = kb.run("init", "--path")
    assert result.returncode != 0
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
