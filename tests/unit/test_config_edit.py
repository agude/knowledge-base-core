"""The config edit: the content key is set, and no other byte or key changes."""

import tomllib

import pytest

from kb import setup_rules
from kb.errors import KbError

ROOT = "/home/agude/Knowledge/content"
HARVEST = "harvest_since = 2026-10-24T00:00:00Z"


@pytest.mark.parametrize("text", ["", "\n"])
def test_an_absent_or_empty_config_gains_only_the_content_line(text: str) -> None:
    edited = setup_rules.set_content(text, ROOT)

    assert edited.endswith(f'content = "{ROOT}"\n')
    assert tomllib.loads(edited) == {"content": ROOT}


def test_an_existing_content_line_is_replaced_and_the_rest_is_kept() -> None:
    text = f'# notes\ncontent = "/old"  # the vault\n{HARVEST}\n'

    edited = setup_rules.set_content(text, ROOT)

    assert edited == f'# notes\ncontent = "{ROOT}"\n{HARVEST}\n'


def test_a_content_line_is_inserted_before_the_first_table_when_absent() -> None:
    text = f"{HARVEST}\n[section]\nvalue = 1\n"

    edited = setup_rules.set_content(text, ROOT)

    assert edited == f'{HARVEST}\ncontent = "{ROOT}"\n[section]\nvalue = 1\n'


def test_a_content_key_inside_a_table_is_not_the_top_level_key() -> None:
    text = '[section]\ncontent = "/inside"\n'

    edited = setup_rules.set_content(text, ROOT)

    assert edited == f'content = "{ROOT}"\n[section]\ncontent = "/inside"\n'
    assert tomllib.loads(edited)["section"] == {"content": "/inside"}


def test_a_top_level_line_before_a_table_is_replaced_and_the_table_copy_is_kept() -> None:
    text = '[section]\ncontent = "/inside"\n'
    top_then_table = f'content = "/top"\n{text}'

    edited = setup_rules.set_content(top_then_table, ROOT)

    assert edited == f'content = "{ROOT}"\n{text}'


def test_a_missing_final_newline_is_completed_before_the_appended_line() -> None:
    edited = setup_rules.set_content(HARVEST, ROOT)

    assert edited == f'{HARVEST}\ncontent = "{ROOT}"\n'


def test_crlf_line_endings_are_kept_on_the_edited_and_inserted_lines() -> None:
    replaced = setup_rules.set_content(f'content = "/old"\r\n{HARVEST}\r\n', ROOT)
    inserted = setup_rules.set_content(f"{HARVEST}\r\n", ROOT)

    assert replaced == f'content = "{ROOT}"\r\n{HARVEST}\r\n'
    assert inserted == f'{HARVEST}\r\ncontent = "{ROOT}"\r\n'


def test_a_multi_line_content_string_is_refused() -> None:
    with pytest.raises(KbError, match="single-line basic string"):
        setup_rules.set_content('content = """\n/old\n"""\n', ROOT)


def test_a_literal_content_string_is_refused() -> None:
    with pytest.raises(KbError, match="single-line basic string"):
        setup_rules.set_content("content = '/old'\n", ROOT)


def test_a_non_string_content_key_is_refused() -> None:
    with pytest.raises(KbError, match="single-line basic string"):
        setup_rules.set_content("content = 3\n", ROOT)


def test_invalid_toml_is_refused() -> None:
    with pytest.raises(KbError, match="not valid TOML"):
        setup_rules.set_content("content = \n", ROOT)


def test_a_byte_order_mark_is_refused_because_the_reader_cannot_parse_it() -> None:
    with pytest.raises(KbError, match="byte order mark"):
        setup_rules.set_content("\ufeff", ROOT)


def test_a_windows_path_round_trips_through_its_escaped_value() -> None:
    windows = "C:\\Users\\alex\\Knowledge\\content"

    edited = setup_rules.set_content("", windows)

    assert tomllib.loads(edited)["content"] == windows


def test_quotes_and_backslashes_are_escaped_in_the_value() -> None:
    value = 'C:\\a "b"'

    assert setup_rules.toml_string(value) == '"C:\\\\a \\"b\\""'
    assert tomllib.loads(f"content = {setup_rules.toml_string(value)}\n")["content"] == value


@pytest.mark.parametrize("value", ["a\nb", "a\tb", "a\x7fb"])
def test_a_control_character_in_the_value_is_refused(value: str) -> None:
    with pytest.raises(KbError, match="control character"):
        setup_rules.toml_string(value)


def test_an_unchanged_content_line_produces_identical_text() -> None:
    text = f'content = "{ROOT}"\n{HARVEST}\n'

    assert setup_rules.set_content(text, ROOT) == text
