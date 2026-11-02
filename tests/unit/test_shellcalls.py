"""Tests for finding recorded kb calls in one shell command line."""

import pytest

from kb.shellcalls import invocations


def test_a_plain_kb_call_is_found_with_its_arguments() -> None:
    found = invocations("kb recall nas restart order")
    assert [(item.subcommand, item.arguments) for item in found] == [
        ("recall", ("nas", "restart", "order"))
    ]


@pytest.mark.parametrize(
    "command",
    [
        "kb recall a; kb read b",
        "kb recall a && kb read b",
        "kb recall a || kb read b",
        "kb recall a | kb read b",
        "kb recall a & kb read b",
        "kb recall a\nkb read b",
    ],
)
def test_each_kb_call_in_a_joined_command_is_found(command: str) -> None:
    found = invocations(command)
    assert [item.subcommand for item in found] == ["recall", "read"]


def test_a_redirection_and_its_target_are_not_arguments() -> None:
    found = invocations("kb recall a b 2>&1 | head -60 >/dev/null")
    assert found == (invocations("kb recall a b")[0],)


def test_a_quoted_operator_stays_in_its_argument() -> None:
    found = invocations('kb gap --title t --body "a; b && c"')
    assert found[0].arguments == ("--title", "t", "--body", "a; b && c")


def test_an_assignment_before_kb_is_skipped() -> None:
    assert invocations("KB_CONTENT=/x kb evidence backup")[0].subcommand == "evidence"


def test_other_kb_subcommands_and_other_programs_are_ignored() -> None:
    assert invocations("kb sync --status; kb curate next; git status; echo kb recall") == ()


def test_a_path_to_kb_is_a_kb_call() -> None:
    assert invocations("/usr/bin/kb observe --title t --body b")[0].subcommand == "observe"


def test_unbalanced_quotes_give_no_calls() -> None:
    assert invocations('kb recall "unterminated') == ()


def test_an_empty_command_gives_no_calls() -> None:
    assert invocations("") == ()
