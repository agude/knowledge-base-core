"""Check that every bats test in a ported file maps to pytest or NOT_PORTED.md.

A ported pytest test carries @pytest.mark.bats("<file>.bats", "<test name>").
A bats test that is deliberately not ported has a row in NOT_PORTED.md:

    | `<file>.bats` | <test name> | <reason> |

bats_ported.txt lists the bats files whose port is complete, one per line.
Only listed files are checked.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

BATS_TEST = re.compile(r'^@test "([^"]*)" \{$', re.MULTILINE)
NOT_PORTED_ROW = re.compile(r"^\|\s*`([^`]+\.bats)`\s*\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*$")

Key = tuple[str, str]


@dataclass(frozen=True)
class Sources:
    bats_dir: Path
    ported_list: Path
    not_ported: Path
    test_dir: Path


def bats_tests(path: Path) -> list[str]:
    return BATS_TEST.findall(path.read_text(encoding="utf-8"))


def ported_files(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def not_ported_entries(path: Path) -> dict[Key, str]:
    entries: dict[Key, str] = {}
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        match = NOT_PORTED_ROW.match(line)
        if match:
            entries[(match.group(1), match.group(2))] = match.group(3)
    return entries


def _is_bats_marker(node: ast.expr) -> bool:
    # pytest.mark.bats(...)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "bats"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "mark"
    )


def marker_keys(test_dir: Path) -> dict[Key, list[str]]:
    """Map each (file, name) named by a bats marker to the tests that carry it."""
    found: dict[Key, list[str]] = {}
    for path in sorted(test_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if not _is_bats_marker(decorator):
                    continue
                args = decorator.args
                if len(args) != 2 or not all(
                    isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args
                ):
                    raise ValueError(
                        f"{path.name}:{node.lineno}: bats marker needs two string literals"
                    )
                key = (args[0].value, args[1].value)
                found.setdefault(key, []).append(f"{path.name}::{node.name}")
    return found


def problems(sources: Sources) -> list[str]:
    """Return every mapping violation; an empty list means the mapping holds."""
    result = []
    markers = marker_keys(sources.test_dir)
    excluded = not_ported_entries(sources.not_ported)
    listed = ported_files(sources.ported_list)
    known: set[Key] = set()

    for name in listed:
        path = sources.bats_dir / name
        if not path.exists():
            result.append(f"bats_ported.txt lists missing file {name}")
            continue
        for test in bats_tests(path):
            key = (name, test)
            known.add(key)
            if key not in markers and key not in excluded:
                result.append(f"{name}: @test {test!r} has no pytest test and no NOT_PORTED entry")
            if key in markers and key in excluded:
                result.append(f"{name}: @test {test!r} is both ported and listed as not ported")

    for key, reason in excluded.items():
        if not reason:
            result.append(f"NOT_PORTED entry for {key[0]}: {key[1]!r} has no reason")

    for key in list(markers) + list(excluded):
        file_name, test = key
        path = sources.bats_dir / file_name
        if not path.exists():
            result.append(f"{file_name} does not exist (named for {test!r})")
        elif key not in known and test not in bats_tests(path):
            result.append(f"{file_name} has no @test {test!r}")
    return sorted(set(result))
