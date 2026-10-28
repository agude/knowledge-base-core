"""End-to-end checks of `kb setup --print`, which writes host text and changes nothing."""

import json

from .harness import Kb

WORKING = ("recall", "read", "map", "questions", "evidence", "observe", "gap")


def test_print_instructions_writes_the_block_with_the_content_policy(kb: Kb) -> None:
    result = kb("setup", "--print", "instructions")

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("<!-- kb:begin -->\n")
    assert result.stdout.endswith("<!-- kb:end -->\n")
    assert f"Content policy: @{kb.content.resolve().as_posix()}/AGENTS.md\n" in result.stdout


def test_print_instructions_resolves_a_symbolic_link_in_the_content_path(kb: Kb) -> None:
    link = kb.home / "content-link"
    link.symlink_to(kb.content, target_is_directory=True)

    result = kb("setup", "--print", "instructions", env={"KB_CONTENT": str(link)})

    assert result.returncode == 0, result.stderr
    assert f"Content policy: @{kb.content.resolve().as_posix()}/AGENTS.md\n" in result.stdout


def test_print_allow_claude_writes_the_seven_working_rules(kb: Kb) -> None:
    result = kb("setup", "--print", "allow-claude")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "permissions": {"allow": [f"Bash(kb {word} *)" for word in WORKING]}
    }


def test_print_allow_codex_writes_the_seven_working_rules(kb: Kb) -> None:
    result = kb("setup", "--print", "allow-codex")

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("prefix_rule(") == len(WORKING)
    assert result.stdout.endswith('decision = "allow")\n')


def test_print_needs_no_content_repository_and_creates_nothing(kb: Kb) -> None:
    missing = kb.home / "nowhere" / "content"

    result = kb("setup", "--print", "instructions", env={"KB_CONTENT": str(missing)})

    assert result.returncode == 0, result.stderr
    assert not missing.parent.exists()


def test_print_instructions_without_a_content_path_fails_with_the_setup_prefix(kb: Kb) -> None:
    result = kb("setup", "--print", "instructions", env={"KB_CONTENT": None})

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("setup: no content path;")


def test_print_with_another_option_is_a_usage_error(kb: Kb) -> None:
    result = kb("setup", "--print", "allow-codex", "--kb", "/bin/true")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Usage: kb setup")
