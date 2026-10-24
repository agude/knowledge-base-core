"""The content-repo pre-commit hook: stamp `updated:`, lint, and reject."""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB


def good_article(body: str) -> str:
    return (
        '---\ntitle: "Networking"\nupdated: 2020-01-01\nverified: 2026-08-08\n---\n\n'
        f"# Networking\n\n## DNS\n\n{body}"
    )


TWO_H1 = (
    '---\ntitle: "Bad"\nupdated: 2026-08-08\nverified: 2026-08-08\n---\n\n'
    "# One\n\n## Section\n\nContent.\n\n# Two\n\n## Other\n\nContent."
)

INBOUND = (
    '---\ntitle: "Inbound Link"\nupdated: 2020-01-01\nverified: 2026-08-08\n---\n\n'
    "# Inbound Link\n\n## Reference\n\nSee [the target](b.md)."
)


@dataclass(frozen=True)
class Commit:
    returncode: int
    stdout: str
    stderr: str


def _commit(kb: KB, *args: str) -> Commit:
    completed = subprocess.run(
        ["git", "commit", "-q", *args],
        cwd=kb.layout.content,
        env=kb.git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return Commit(completed.returncode, completed.stdout, completed.stderr)


def _check(kb: KB, golden: Golden, result: Commit) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.stdout))
    golden.check("stderr", kb.norm_err(result.stderr))
    golden.contract("log", kb.norm(kb.git("log", "--format=%s", "--name-status")))


def _committed(kb: KB, path: str) -> str:
    return kb.norm(kb.git("show", f"HEAD:{path}"))


@pytest.mark.bats("pre_commit.bats", "pre-commit stamps updated on a staged article")
@pytest.mark.bats("pre_commit.bats", "pre-commit leaves verified alone")
def test_stamps_updated(hooked: KB, golden: Golden) -> None:
    hooked.create_article("net.md", good_article("How DNS works."))
    hooked.git("add", "knowledge/net.md")
    _check(hooked, golden, _commit(hooked, "-m", "Add networking"))
    golden.contract("committed", _committed(hooked, "knowledge/net.md"))
    golden.contract(
        "worktree", hooked.norm((hooked.layout.content / "knowledge" / "net.md").read_text())
    )


@pytest.mark.bats("pre_commit.bats", "pre-commit rejects a lint error")
def test_rejects_lint_error(hooked: KB, golden: Golden) -> None:
    hooked.create_article("bad.md", TWO_H1)
    hooked.git("add", "knowledge/bad.md")
    _check(hooked, golden, _commit(hooked, "-m", "Add bad article"))


@pytest.mark.bats("pre_commit.bats", "pre-commit lets an oversized section through as a warning")
def test_oversized_section_warns(hooked: KB, golden: Golden) -> None:
    filler = "filler\n" * 60
    hooked.create_article(
        "long.md",
        f'---\ntitle: "Long"\nupdated: 2026-08-08\nverified: 2026-08-08\n---\n\n# Long\n\n## Big\n\n{filler}',
    )
    hooked.git("add", "knowledge/long.md")
    _check(hooked, golden, _commit(hooked, "-m", "Add long article"))


@pytest.mark.bats("pre_commit.bats", "pre-commit ignores commits with no staged articles")
@pytest.mark.null_ok("the contract is a silent exit 0 when no article is staged")
def test_ignores_commits_without_articles(hooked: KB, golden: Golden) -> None:
    hooked.create_observation("20260412T000000-0000aaaa.md", "Obs", "Body")
    hooked.git("add", "observations/pending/20260412T000000-0000aaaa.md")
    _check(hooked, golden, _commit(hooked, "-m", "Observe: Obs"))


@pytest.mark.bats("pre_commit.bats", "observe still commits with the hook installed")
def test_observe_with_hook(hooked: KB, golden: Golden) -> None:
    result = hooked.run("observe", "--title", "Test", "--body", "Body")
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stderr", hooked.norm_err(result.err))
    golden.contract("log", hooked.norm(hooked.git("log", "--format=%s", "--name-status")))


@pytest.mark.bats("pre_commit.bats", "pre-commit does not restamp an article already dated today")
def test_no_restamp_today(hooked: KB, golden: Golden) -> None:
    path = hooked.create_article("net.md", good_article("First."))
    hooked.git("add", "knowledge/net.md")
    _commit(hooked, "-m", "Add")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("Second edit.\n")
    hooked.git("add", "knowledge/net.md")
    _check(hooked, golden, _commit(hooked, "-m", "Edit"))


@pytest.mark.bats(
    "pre_commit.bats", "pre-commit skips stamping on a partial commit instead of losing it"
)
def test_partial_commit_skips_stamp(hooked: KB, golden: Golden) -> None:
    hooked.create_article("net.md", good_article("How DNS works."))
    hooked.git("add", "knowledge/net.md")
    _check(hooked, golden, _commit(hooked, "-m", "Add", "--", "knowledge/net.md"))
    golden.contract("committed", _committed(hooked, "knowledge/net.md"))


@pytest.mark.bats(
    "pre_commit.bats", "pre-commit rejects a target rename with an unchanged inbound link"
)
@pytest.mark.bats(
    "pre_commit.bats", "pre-commit rejects a target deletion with an unchanged inbound link"
)
@pytest.mark.parametrize("change", ["rename", "delete"])
def test_rejects_broken_inbound_link(hooked: KB, golden: Golden, change: str) -> None:
    target = hooked.create_article("b.md", good_article("Target content."))
    hooked.create_article("a.md", INBOUND)
    hooked.git("add", "-A", "knowledge")
    hooked.git("commit", "-q", "--no-verify", "-m", "Add linked articles")
    if change == "rename":
        target.rename(target.with_name("c.md"))
    else:
        target.unlink()
    hooked.git("add", "-A", "knowledge")
    _check(hooked, golden, _commit(hooked, "-m", f"{change} target"))


@pytest.mark.bats(
    "pre_commit.bats", "pre-commit does not rewrite body lines in a file with no frontmatter"
)
def test_no_front_matter_body_untouched(hooked: KB, golden: Golden) -> None:
    body = "# Title\n\nRelease checklist\n---\n\nupdated: $(git describe)\n"
    path = hooked.layout.content / "knowledge" / "nofm.md"
    path.write_text(body, encoding="utf-8")
    hooked.git("add", "knowledge/nofm.md")
    _check(hooked, golden, _commit(hooked, "-m", "Add"))
    assert path.read_text(encoding="utf-8") == body


@pytest.mark.bats("pre_commit.bats", "pre-commit leaves the tree untouched when lint rejects")
def test_rejection_leaves_tree_untouched(hooked: KB, golden: Golden) -> None:
    good = hooked.create_article(
        "good.md",
        '---\ntitle: "Good"\nupdated: 2020-01-01\nverified: 2026-08-08\n---\n\n'
        "# Good\n\n## Section\n\nContent.",
    )
    hooked.create_article(
        "bad.md",
        '---\ntitle: "Bad"\nupdated: 2020-01-01\nverified: 2026-08-08\n---\n\n'
        "# One\n\n## S\n\nContent.\n\n# Two",
    )
    before = good.read_text(encoding="utf-8")
    hooked.git("add", "knowledge/")
    _check(hooked, golden, _commit(hooked, "-m", "Add"))
    assert good.read_text(encoding="utf-8") == before


@pytest.mark.bats("pre_commit.bats", "pre-commit stamps an article with a non-ASCII filename")
def test_stamps_non_ascii_name(hooked: KB, golden: Golden) -> None:
    hooked.create_article(
        "café.md",
        '---\ntitle: "Cafe"\nupdated: 2020-01-01\nverified: 2026-08-08\n---\n\n'
        "# Cafe\n\n## Section\n\nContent.",
    )
    hooked.git("add", "-A", "knowledge/")
    _check(hooked, golden, _commit(hooked, "-m", "Add"))
    golden.contract("committed", _committed(hooked, "knowledge/café.md"))


@pytest.mark.bats("pre_commit.bats", "pre-commit lints an article with a non-ASCII filename")
def test_lints_non_ascii_name(hooked: KB, golden: Golden) -> None:
    hooked.create_article(
        "café.md",
        '---\ntitle: "Cafe"\nupdated: 2026-08-08\nverified: 2026-08-08\n---\n\n'
        "# One\n\n## S\n\nContent.\n\n# Two",
    )
    hooked.git("add", "-A", "knowledge/")
    _check(hooked, golden, _commit(hooked, "-m", "Add"))


@pytest.mark.bats("pre_commit.bats", "pre-commit preserves file mode")
@pytest.mark.parametrize("mode", [0o644, 0o600, 0o755])
def test_preserves_mode(hooked: KB, mode: int) -> None:
    path = hooked.create_article("net.md", good_article("Content."))
    path.chmod(mode)
    hooked.git("add", "knowledge/net.md")
    assert _commit(hooked, "-m", "Add").returncode == 0
    assert "updated: 2020-01-01" not in path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == mode


@pytest.mark.bats(
    "pre_commit.bats", "pre-commit does not turn a symlinked article into a regular file"
)
def test_symlinked_article_stays_a_link(hooked: KB, golden: Golden) -> None:
    real = hooked.layout.content / "real.md"
    real.write_text(good_article("Content.") + "\n", encoding="utf-8")
    link = hooked.layout.content / "knowledge" / "link.md"
    link.symlink_to("../real.md")
    hooked.git("add", "-A")
    _check(hooked, golden, _commit(hooked, "-m", "Add"))
    assert link.is_symlink()
    golden.contract("real", hooked.norm(real.read_text(encoding="utf-8")))


def test_alternate_index_commit(hooked: KB, golden: Golden) -> None:
    hooked.create_article("net.md", good_article("Content."))
    index = hooked.layout.root / "alt-index"
    env = {**hooked.git_env(), "GIT_INDEX_FILE": str(index)}
    subprocess.run(["git", "read-tree", "HEAD"], cwd=hooked.layout.content, env=env, check=True)
    subprocess.run(
        ["git", "add", "knowledge/net.md"], cwd=hooked.layout.content, env=env, check=True
    )
    completed = subprocess.run(
        ["git", "commit", "-q", "-m", "Alternate"],
        cwd=hooked.layout.content,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    _check(hooked, golden, Commit(completed.returncode, completed.stdout, completed.stderr))
    golden.contract("committed", _committed(hooked, "knowledge/net.md"))
