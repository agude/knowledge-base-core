"""File lists are in code-point order under every locale (A-005).

The Bash scripts sort file lists with `sort -z` under the caller's locale,
so these names order differently under C (code-point order) and en_US
(punctuation and case ignored at the first level). The audit chose
code-point order of the file names everywhere.
"""

from __future__ import annotations

import subprocess

import pytest

from kbtest.marks import xfail_bash
from kbtest.runner import KB

NAMES = ("B", "_x", "a-c", "a", "ab")
LOCALES = (
    "C.UTF-8",
    pytest.param(
        "en_US.UTF-8", marks=xfail_bash("A-005: bash sorts file lists in the caller's collation")
    ),
)


def _available(locale: str) -> bool:
    result = subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False)
    wanted = locale.lower().replace("-", "")
    return wanted in {line.strip().lower().replace("-", "") for line in result.stdout.splitlines()}


def _order(text: str, words: list[str]) -> list[str]:
    positions = {word: text.find(word) for word in words}
    assert all(position >= 0 for position in positions.values()), positions
    return sorted(words, key=positions.__getitem__)


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("script", ["toc", "pending"])
def test_order_is_code_point(kb: KB, script: str, locale: str) -> None:
    if not _available(locale):
        pytest.skip(f"locale {locale} is not installed")
    for name in NAMES:
        if script == "toc":
            kb.create_article(f"{name}.md", f'---\ntitle: "Title {name}"\n---\n\n# Title {name}')
        else:
            kb.create_observation(f"{name}.md", f"Title {name}", "Body")
    result = kb.run(script, env={"LANG": locale, "LC_ALL": locale})
    assert result.returncode == 0, result.err
    expected = [f"Title {name}" for name in sorted(NAMES, key=lambda name: f"{name}.md")]
    assert _order(result.out, [f"Title {name}" for name in NAMES]) == expected
