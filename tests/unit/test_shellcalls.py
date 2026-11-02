"""Tests for finding recorded kb calls in one shell command line."""

import pytest

from kb.shellcalls import invocations, sole_invocation


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


def test_a_quoted_operator_is_an_argument_not_an_operator() -> None:
    assert invocations('kb recall "|"')[0].arguments == ("|",)
    assert invocations("kb recall '&&' ';'")[0].arguments == ("&&", ";")


def test_a_quoted_newline_stays_in_its_argument() -> None:
    found = invocations('kb recall "a\nb"')
    assert [item.arguments for item in found] == [("a\nb",)]


def test_an_unquoted_newline_still_separates_commands() -> None:
    found = invocations("kb recall a\nkb read b")
    assert [(item.subcommand, item.arguments) for item in found] == [
        ("recall", ("a",)),
        ("read", ("b",)),
    ]


def test_a_separator_run_with_a_newline_still_separates_commands() -> None:
    found = invocations("kb recall a;\nkb read b\n\nkb read c")
    assert [item.subcommand for item in found] == ["recall", "read", "read"]


def test_adjacent_quoted_pieces_are_one_word() -> None:
    assert invocations("kb recall 'it''s'")[0].arguments == ("its",)


def test_a_backslash_escaped_blank_is_part_of_its_word() -> None:
    assert invocations("kb recall a\\ b")[0].arguments == ("a b",)


def test_a_word_that_does_not_unquote_gives_no_calls() -> None:
    assert invocations('kb recall "a"b"') == ()
    assert sole_invocation('kb recall "a"b"') is None


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        ("kb recall x 2>&1", ("x",)),
        ("FOO=1 kb recall x", ("x",)),
        ('kb recall "|"', ("|",)),
        ("kb recall x\n", ("x",)),
        ("kb recall x &", ("x",)),
    ],
)
def test_sole_invocation_accepts_one_simple_kb_call(
    command: str, arguments: tuple[str, ...]
) -> None:
    found = sole_invocation(command)
    assert found is not None
    assert found.subcommand == "recall"
    assert found.arguments == arguments


@pytest.mark.parametrize(
    "command",
    [
        "kb recall x | head",
        "cd y && kb recall x",
        "kb recall x; kb read y",
        "kb recall x\nkb read y",
        "echo kb recall x",
        "",
    ],
)
def test_sole_invocation_rejects_anything_else(command: str) -> None:
    assert sole_invocation(command) is None


def test_an_escaped_quote_stays_in_its_argument() -> None:
    found = invocations(r'kb observe --title t --body "say \"hi\" now"')
    assert found[0].arguments == ("--title", "t", "--body", 'say "hi" now')
    assert invocations(r"kb recall a\"b")[0].arguments == ('a"b',)


def test_an_escaped_blank_or_operator_stays_in_its_word() -> None:
    assert invocations(r"kb recall a\ b")[0].arguments == ("a b",)
    assert invocations(r"kb recall a\;b")[0].arguments == ("a;b",)


def test_a_backslash_inside_single_quotes_is_literal() -> None:
    assert invocations(r"kb recall 'a\'")[0].arguments == ("a\\",)


def test_a_backslash_inside_double_quotes_escapes_only_a_quote_or_a_backslash() -> None:
    assert invocations(r'kb recall "x\ y" "a\\" b')[0].arguments == ("x\\ y", "a\\", "b")


def test_a_backslash_before_a_newline_continues_the_line() -> None:
    found = invocations("kb recall x\\\nkb read y")
    assert [(item.subcommand, item.arguments) for item in found] == [
        ("recall", ("xkb", "read", "y"))
    ]


def test_an_escaped_quote_that_leaves_a_quote_open_gives_no_calls() -> None:
    assert invocations(r'kb recall "a\"; kb read b') == ()
