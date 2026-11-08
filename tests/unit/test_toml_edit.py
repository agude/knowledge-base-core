"""Finding the first TOML table header and inserting one top-level line before it."""

import pytest

from kb import toml_edit

BOM = "﻿"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param('content = "/c"\nn = 1\n', 2, id="no-tables"),
        pytest.param("[t]\na = 1\n", 0, id="table-at-line-0"),
        pytest.param(f"{BOM}[t]\na = 1\n", 0, id="bom-before-table"),
        pytest.param("x = [\n  [1, 2],\n]\n[t]\na = 1\n", 3, id="nested-array"),
        pytest.param('s = """\n[not a table]\n"""\n[t]\n', 3, id="multi-line-string"),
        pytest.param("n = 1\n[[x]]\na = 1\n", 1, id="array-of-tables"),
    ],
)
def test_first_table_line_finds_only_top_level_headers(text: str, expected: int) -> None:
    assert toml_edit.first_table_line(text.splitlines(keepends=True)) == expected


@pytest.mark.parametrize(
    ("text", "index", "expected"),
    [
        pytest.param("a = 1\n[t]\n", 1, "a = 1\nk = 2\n[t]\n", id="lf"),
        pytest.param("a = 1\r\n[t]\r\n", 1, "a = 1\r\nk = 2\r\n[t]\r\n", id="crlf"),
        pytest.param("a = 1", 1, "a = 1\nk = 2\n", id="missing-final-newline"),
        pytest.param(f"{BOM}[t]\n", 0, f"{BOM}k = 2\n[t]\n", id="bom-at-line-0"),
    ],
)
def test_insert_line_matches_the_file(text: str, index: int, expected: str) -> None:
    lines = text.splitlines(keepends=True)

    assert toml_edit.insert_line(text, lines, index, "k = 2") == expected
