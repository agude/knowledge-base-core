"""Claude pretool-allow: approve only single simple calls to our own scripts.

The hook is a security boundary: a false approval runs an arbitrary
command without a prompt. A rejection is silence, so every rejection test
also checks that a known-good command is approved; otherwise a hook that
never approves anything would pass.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB

HOOK = "adapters/claude/pretool-allow"


def _scripts(kb: KB) -> Path:
    return kb.resolve_impl(kb.default_impl).scripts_dir


def _decide(kb: KB, command: str) -> tuple[int, str, str]:
    result = kb.run(HOOK, stdin=json.dumps({"tool_input": {"command": command}}))
    return result.returncode, result.out, result.err


def _approved(kb: KB, command: str) -> bool:
    code, out, err = _decide(kb, command)
    assert code == 0, (code, err)
    if not out:
        return False
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "allow", decision
    return True


@pytest.mark.bats("pretool_allow.bats", "approves a bare script invocation")
def test_approves_bare_invocation(kb: KB, golden: Golden) -> None:
    code, out, err = _decide(kb, f"{_scripts(kb)}/status")
    golden.contract("decision", f"exit {code}\nstdout={out!r}\nstderr={err!r}\n")


@pytest.mark.bats("pretool_allow.bats", "approves a script with quoted arguments")
@pytest.mark.bats(
    "pretool_allow.bats", "approves an argument containing operator characters inside quotes"
)
@pytest.mark.parametrize(
    "arguments",
    [
        '--title "NAS restart order" --body "Traefik first"',
        "--title 'A' --body 'run make check && make test; then ship'",
        "--title 'a | b > c < d (e) `f` $(g)' --body x",
        '--title "escaped \\" quote" --body x',
    ],
    ids=["double", "single-operators", "single-substitutions", "escaped-quote"],
)
def test_approves_quoted_arguments(kb: KB, arguments: str) -> None:
    assert _approved(kb, f"{_scripts(kb)}/observe {arguments}")


REJECTED = {
    "semicolon": "{s}/status; echo pwned",
    "and": "{s}/status && curl http://evil",
    "pipe": "{s}/status | sh",
    "substitution": "{s}/observe --title $(curl http://evil) --body x",
    "substitution-in-double": '{s}/observe --title "$(curl http://evil)" --body x',
    "backtick": "{s}/status `id`",
    "backtick-in-double": '{s}/status "`id`"',
    "redirect-out": "{s}/status > /home/user/.bashrc",
    "redirect-in": "{s}/status < /etc/passwd",
    "background": "{s}/status & echo done",
    "newline": "{s}/status\necho pwned",
    "subshell": "({s}/status)",
    "unterminated-single": "{s}/observe --title 'unclosed",
    "unterminated-double": '{s}/observe --title "unclosed',
    "not-ours": "/bin/echo hello",
    "escape-out": "{s}/../scripts/../../bin/sh",
    "nonexistent": "{s}/no-such-script --flag",
    "relative": "status",
}


@pytest.mark.bats("pretool_allow.bats", "rejects a command chained with a semicolon")
@pytest.mark.bats("pretool_allow.bats", "rejects a command chained with &&")
@pytest.mark.bats("pretool_allow.bats", "rejects a pipeline")
@pytest.mark.bats("pretool_allow.bats", "rejects command substitution in an argument")
@pytest.mark.bats("pretool_allow.bats", "rejects command substitution inside double quotes")
@pytest.mark.bats("pretool_allow.bats", "rejects backtick substitution")
@pytest.mark.bats("pretool_allow.bats", "rejects redirection")
@pytest.mark.bats("pretool_allow.bats", "rejects a background ampersand")
@pytest.mark.bats("pretool_allow.bats", "rejects a newline-separated second command")
@pytest.mark.bats("pretool_allow.bats", "rejects an unterminated quote")
@pytest.mark.bats("pretool_allow.bats", "rejects a command that is not one of our scripts")
@pytest.mark.bats("pretool_allow.bats", "rejects a path that resolves out of the scripts directory")
@pytest.mark.bats("pretool_allow.bats", "rejects a nonexistent script in the scripts directory")
@pytest.mark.parametrize("case", sorted(REJECTED))
def test_rejects(kb: KB, case: str) -> None:
    scripts = _scripts(kb)
    assert _approved(kb, f"{scripts}/status"), "control: a bare invocation must be approved"
    assert not _approved(kb, REJECTED[case].format(s=scripts))


@pytest.mark.bats("pretool_allow.bats", "ignores input with no command")
@pytest.mark.parametrize("payload", ["{}", '{"tool_input":{}}', "not json", ""])
def test_ignores_input_without_command(kb: KB, payload: str) -> None:
    scripts = _scripts(kb)
    assert _approved(kb, f"{scripts}/status"), "control: a bare invocation must be approved"
    result = kb.run(HOOK, stdin=payload)
    assert (result.returncode, result.out) == (0, "")


def test_approves_through_a_symlinked_hook(kb: KB) -> None:
    """Hosts install the hook as a symlink; it must still find its scripts."""
    tree = kb.resolve_impl(kb.default_impl)
    link_dir = kb.layout.root / "hooks"
    link_dir.mkdir()
    (link_dir / "010.knowledge").symlink_to(tree.executable(HOOK))
    payload = json.dumps({"tool_input": {"command": f"{tree.scripts_dir}/status"}})
    completed = subprocess.run(
        [str(link_dir / "010.knowledge")],
        input=payload,
        capture_output=True,
        text=True,
        env=kb.env(tree),
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"


# What an approved command can do: the scripts themselves refuse paths
# outside the knowledge base.


@pytest.mark.bats(
    "pretool_allow.bats", "an approved section command cannot read outside the content dir"
)
def test_section_cannot_read_outside(kb: KB, golden: Golden) -> None:
    outside = kb.layout.root / "outside.md"
    outside.write_text("# Secret\n\ntop secret\n", encoding="utf-8")
    command = f"{_scripts(kb)}/section --file {outside} --heading Secret"
    assert _approved(kb, command)
    result = kb.run("section", "--file", str(outside), "--heading", "Secret")
    assert result.returncode != 0
    assert "top secret" not in result.out + result.err
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.bats(
    "pretool_allow.bats", "an approved section command cannot read an absolute system path"
)
def test_section_cannot_read_system_path(kb: KB, golden: Golden) -> None:
    result = kb.run("section", "--file", "/etc/passwd", "--heading", "root")
    assert result.returncode != 0
    assert "root:" not in result.out
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.bats("pretool_allow.bats", "an approved toc command cannot walk the filesystem")
@pytest.mark.bats("pretool_allow.bats", "an approved toc --dirs cannot list an arbitrary tree")
@pytest.mark.parametrize("args", [["--path", "/etc"], ["--dirs", "--path", "/etc"]])
def test_toc_cannot_walk_outside(kb: KB, golden: Golden, args: list[str]) -> None:
    result = kb.run("toc", *args)
    assert result.returncode != 0
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.bats(
    "pretool_allow.bats", "an approved resolve command cannot append to a file outside"
)
def test_resolve_cannot_append_outside(kb: KB, golden: Golden) -> None:
    victim = kb.layout.root / "victim.txt"
    victim.write_text("original\n", encoding="utf-8")
    result = kb.run("resolve", "--file", "../../victim.txt", "--answer", "injected")
    assert result.returncode != 0
    assert victim.read_text(encoding="utf-8") == "original\n"
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.bats(
    "pretool_allow.bats", "an approved archive command cannot move a file from outside"
)
def test_archive_cannot_move_outside(kb: KB, golden: Golden) -> None:
    victim = kb.layout.content / "observations" / "victim.md"
    victim.write_text("mine\n", encoding="utf-8")
    result = kb.run("archive", "../victim.md")
    assert result.returncode != 0
    assert victim.is_file()
    golden.check("stderr", kb.norm_err(result.err))
