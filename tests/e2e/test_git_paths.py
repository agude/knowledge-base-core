"""End-to-end checks for content roots inside repositories and linked worktrees."""

from pathlib import Path

import pytest

from .harness import Kb, make_git_kb, make_linked_worktree_kb, make_subdirectory_kb


def _layout(tmp_path: Path, layout: str) -> Kb:
    kb = make_git_kb(tmp_path)
    if layout != "root":
        kb = make_subdirectory_kb(kb)
    if layout == "linked-worktree":
        kb = make_linked_worktree_kb(kb)
    return kb


@pytest.mark.parametrize("layout", ["root", "subdirectory", "linked-worktree"])
def test_observe_uses_the_content_root_for_git_writes(tmp_path: Path, layout: str) -> None:
    kb = _layout(tmp_path, layout)

    result = kb("observe", "--title", "Nested root", "--body", "Git paths stay content relative.")

    assert result.returncode == 0, result.stderr
    relative = result.stdout.removeprefix("Wrote: ").strip()
    assert (kb.content / relative).is_file()
    assert kb.git("status", "--porcelain", "--untracked-files=all") == ""


@pytest.mark.parametrize("layout", ["root", "subdirectory", "linked-worktree"])
def test_verify_uses_the_content_root_for_lock_and_publication(tmp_path: Path, layout: str) -> None:
    kb = _layout(tmp_path, layout)

    result = kb("verify", "knowledge/rules/ttl-missing.md", "--ttl", "domain")

    assert result.returncode == 0, result.stderr
    assert "verified: 2026-10-26" in (kb.content / "knowledge/rules/ttl-missing.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("layout", ["root", "subdirectory", "linked-worktree"])
def test_resolve_uses_the_content_root_for_lock_and_publication(
    tmp_path: Path, layout: str
) -> None:
    kb = _layout(tmp_path, layout)
    question = "questions/open/20261001T090000-bbbb2222.md"

    result = kb(
        "resolve",
        question,
        "--answer",
        "The NAS restart order is recorded.",
        "--destination",
        "knowledge/infra/nas.md#1",
    )

    assert result.returncode == 0, result.stderr
    assert not (kb.content / question).exists()
    assert (kb.content / question.replace("open", "resolved")).is_file()
