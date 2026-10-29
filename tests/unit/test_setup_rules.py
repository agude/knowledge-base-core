"""The canonical host text: the instruction block, the policy import, and the allow rules."""

import json
import re

import pytest

from kb import setup_rules
from kb.errors import KbError

WORKING = ("recall", "read", "map", "questions", "evidence", "observe", "gap")
BLOCK_CONTENT = "/data/content"


def test_the_block_has_both_markers_once_and_at_most_twelve_lines() -> None:
    block = setup_rules.instruction_block(BLOCK_CONTENT)
    lines = block.splitlines()

    assert lines[0] == setup_rules.BEGIN_MARKER
    assert lines[-1] == setup_rules.END_MARKER
    assert lines.count(setup_rules.BEGIN_MARKER) == 1
    assert lines.count(setup_rules.END_MARKER) == 1
    assert len(lines) <= setup_rules.MAX_BLOCK_LINES
    assert setup_rules.POLICY_PLACEHOLDER not in block


def test_the_block_names_only_the_working_commands_and_help() -> None:
    block = setup_rules.instruction_block(BLOCK_CONTENT)

    named = re.findall(r"`kb ([a-z-]+)", block)

    assert sorted(named) == sorted([*WORKING, "--help"])
    assert all(word not in named for word in ("lint", "sync", "curate", "verify", "resolve"))


def test_the_policy_line_is_an_import_of_the_content_policy() -> None:
    assert setup_rules.policy_import("/home/u/Knowledge/content") == (
        "@/home/u/Knowledge/content/AGENTS.md"
    )
    assert setup_rules.policy_import("/home/u/My Notes") == "@/home/u/My\\ Notes/AGENTS.md"
    assert (
        setup_rules.instruction_block(BLOCK_CONTENT).count(
            "Content policy: @/data/content/AGENTS.md"
        )
        == 1
    )


@pytest.mark.parametrize("content_root", ["/a\nb", "/a\rb", "/a\0b"])
def test_a_policy_path_with_a_line_break_or_nul_is_refused(content_root: str) -> None:
    with pytest.raises(KbError, match="line break or NUL"):
        setup_rules.policy_import(content_root)


def test_the_claude_fragment_allows_exactly_the_working_commands() -> None:
    fragment = json.loads(setup_rules.allow_claude())

    assert fragment == {"permissions": {"allow": [f"Bash(kb {word} *)" for word in WORKING]}}


def test_the_codex_rules_allow_exactly_the_working_commands() -> None:
    lines = setup_rules.allow_codex().splitlines()

    assert lines[0].startswith("# ")
    assert lines[1:] == [
        f'prefix_rule(pattern = ["kb", "{word}"], decision = "allow")' for word in WORKING
    ]


def test_no_rule_approves_a_curator_command_setup_or_the_bare_prefix() -> None:
    text = setup_rules.allow_claude() + setup_rules.allow_codex()

    for word in ("lint", "sync", "curate", "verify", "resolve", "setup"):
        assert f"kb {word}" not in text
    assert 'pattern = ["kb"]' not in text
    assert "Bash(kb *)" not in text
    assert "Bash(kb)" not in text
