"""Output order under the C and en_US collations (A-005).

The scripts sort file lists with `sort -z` under the caller's locale. These
names order differently under C (byte order) and en_US (punctuation and
case ignored at the first level).
"""

from __future__ import annotations

import subprocess

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB

NAMES = ("B", "_x", "a-c", "a", "ab")
LOCALES = ("C.UTF-8", "en_US.UTF-8")


def _available(locale: str) -> bool:
    result = subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False)
    wanted = locale.lower().replace("-", "")
    return wanted in {line.strip().lower().replace("-", "") for line in result.stdout.splitlines()}


def _order(text: str, words: list[str]) -> list[str]:
    positions = {word: text.find(word) for word in words}
    assert all(position >= 0 for position in positions.values()), positions
    return sorted(words, key=positions.__getitem__)


@pytest.mark.audit("A-005")
@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("script", ["toc", "pending"])
def test_order_follows_collation(kb: KB, golden: Golden, script: str, locale: str) -> None:
    if not _available(locale):
        pytest.skip(f"locale {locale} is not installed")
    for name in NAMES:
        if script == "toc":
            kb.create_article(f"{name}.md", f'---\ntitle: "Title {name}"\n---\n\n# Title {name}')
        else:
            kb.create_observation(f"{name}.md", f"Title {name}", "Body")
    result = kb.run(script, env={"LANG": locale, "LC_ALL": locale})
    assert result.returncode == 0, result.err
    order = _order(result.out, [f"Title {name}" for name in NAMES])
    golden.check("order", "".join(f"{title}\n" for title in order))
