"""Tests for the command-line word parser."""

import pytest

from kb import args
from kb.args import Spec
from kb.errors import KbError

SPEC = Spec(
    usage="fake WORD... [--limit N] [--in PATH] [--sources]",
    summary="A fake command.",
    valued=frozenset({"--limit", "--in"}),
    switches=frozenset({"--sources"}),
)


def test_words_values_and_switches_are_separated() -> None:
    parsed = args.parse(SPEC, ["alpha", "--limit", "3", "beta", "--in=dir", "--sources"])
    assert parsed.words == ["alpha", "beta"]
    assert parsed.values == {"--limit": "3", "--in": "dir"}
    assert parsed.switches == {"--sources"}
    assert parsed.help is False


def test_double_dash_makes_the_rest_positional() -> None:
    parsed = args.parse(SPEC, ["--", "--limit", "--", "x"])
    assert parsed.words == ["--limit", "--", "x"]
    assert parsed.values == {}


def test_a_lone_dash_is_a_word() -> None:
    assert args.parse(SPEC, ["-"]).words == ["-"]


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_flag_stops_parsing_before_later_errors(flag: str) -> None:
    parsed = args.parse(SPEC, ["alpha", flag, "--bogus"])
    assert parsed.help is True


def test_a_value_may_look_like_a_flag() -> None:
    parsed = args.parse(SPEC, ["--in", "--help"])
    assert parsed.help is False
    assert parsed.values == {"--in": "--help"}


def test_the_last_value_wins() -> None:
    assert args.parse(SPEC, ["--limit", "1", "--limit", "2"]).values == {"--limit": "2"}


def test_a_valued_option_without_a_value_is_an_error() -> None:
    with pytest.raises(KbError, match=r"^Option --limit requires an argument$"):
        args.parse(SPEC, ["alpha", "--limit"])


def test_an_unknown_long_option_is_an_error() -> None:
    with pytest.raises(KbError, match=r"^Unknown option: --bogus$"):
        args.parse(SPEC, ["--bogus"])


def test_a_switch_with_a_value_is_unknown() -> None:
    with pytest.raises(KbError, match=r"^Unknown option: --sources$"):
        args.parse(SPEC, ["--sources=yes"])


def test_an_unknown_short_option_is_an_error() -> None:
    with pytest.raises(KbError, match=r"^Unknown option: -x$"):
        args.parse(SPEC, ["-x"])


def test_help_text_and_usage_error_name_the_command() -> None:
    assert SPEC.help_text() == (
        "Usage: kb fake WORD... [--limit N] [--in PATH] [--sources]\n\nA fake command.\n"
    )
    assert str(SPEC.usage_error()) == "Usage: kb fake WORD... [--limit N] [--in PATH] [--sources]"


@pytest.mark.parametrize(("text", "value"), [("1", 1), ("42", 42), ("007", 7)])
def test_positive_int_accepts_digits_above_zero(text: str, value: int) -> None:
    assert args.positive_int(text, "--limit") == value


@pytest.mark.parametrize("text", ["0", "-1", "+3", "x", "", "٣"])
def test_positive_int_rejects_everything_else(text: str) -> None:
    with pytest.raises(KbError, match=r"^Option --limit must be a positive integer$"):
        args.positive_int(text, "--limit")


def test_choice_int_accepts_a_listed_value() -> None:
    assert args.choice_int("2", "--depth", (1, 2, 3)) == 2


def test_choice_int_lists_three_choices() -> None:
    with pytest.raises(KbError, match=r"^Option --depth must be 1, 2, or 3$"):
        args.choice_int("4", "--depth", (1, 2, 3))


def test_choice_int_lists_two_choices() -> None:
    with pytest.raises(KbError, match=r"^Option --flag must be 1 or 2$"):
        args.choice_int("x", "--flag", (1, 2))


def test_choice_int_rejects_non_ascii_digits() -> None:
    with pytest.raises(KbError):
        args.choice_int("٢", "--depth", (1, 2, 3))
