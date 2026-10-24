"""Static rules for kb/: platform calls stay in kb/platform.py (plan 3.7).

The source is parsed, never imported.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from kbtest import impl as implmod

pytestmark = pytest.mark.static

KB = implmod.REPO / "kb"
PLATFORM = KB / "platform.py"

# Calls that only kb/platform.py may make: (module or object, attribute).
RESERVED = {("os", "kill"), ("os", "getuid"), ("os", "chmod"), ("os", "symlink"), ("os", "umask")}
TEXT_METHODS_NEEDING_ENCODING = {"read_text", "write_text"}


def _sources() -> list[Path]:
    return sorted(p for p in KB.rglob("*.py") if "__pycache__" not in p.parts)


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _binary_mode(call: ast.Call, position: int) -> bool:
    mode = _keyword(call, "mode")
    if mode is None and len(call.args) > position:
        mode = call.args[position]
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
            if "syslog" in names:
                found.append(f"{node.lineno}: imports syslog")
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and (func.value.id, func.attr) in RESERVED
        ):
            found.append(f"{node.lineno}: calls {func.value.id}.{func.attr}")
        is_open = (isinstance(func, ast.Name) and func.id == "open") or (
            isinstance(func, ast.Attribute) and func.attr == "open"
        )
        position = 1 if isinstance(func, ast.Name) else 0
        if is_open and not _binary_mode(node, position):
            for keyword in ("encoding", "newline"):
                if _keyword(node, keyword) is None:
                    found.append(f"{node.lineno}: open() without {keyword}")
        if isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS_NEEDING_ENCODING:
            needed = ("encoding", "newline") if func.attr == "write_text" else ("encoding",)
            for keyword in needed:
                if _keyword(node, keyword) is None:
                    found.append(f"{node.lineno}: {func.attr}() without {keyword}")
    return found


def test_platform_calls_stay_in_platform_module() -> None:
    problems = [
        f"{path.relative_to(implmod.REPO)}:{v}"
        for path in _sources()
        if path != PLATFORM
        for v in violations(path)
    ]
    assert problems == []


def test_rules_catch_each_reserved_call(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\nimport syslog\nfrom pathlib import Path\n"
        "os.kill(1, 0)\nos.getuid()\nos.chmod('x', 0)\nos.symlink('a', 'b')\n"
        "open('x')\nopen('x', 'rb')\nPath('x').open(encoding='utf-8')\n"
        "Path('x').read_text()\nPath('x').write_text('t', encoding='utf-8')\n",
        encoding="utf-8",
    )
    assert violations(sample) == [
        "2: imports syslog",
        "4: calls os.kill",
        "5: calls os.getuid",
        "6: calls os.chmod",
        "7: calls os.symlink",
        "8: open() without encoding",
        "8: open() without newline",
        "10: open() without newline",
        "11: read_text() without encoding",
        "12: write_text() without newline",
    ]
