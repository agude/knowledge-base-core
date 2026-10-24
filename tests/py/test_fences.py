"""Fenced code blocks are not parsed for headings (toc and section)."""

from __future__ import annotations

import pytest

from kbtest import facts
from kbtest.golden import Golden
from kbtest.runner import KB, Result

FENCED = """# Shell Recipes

## Dangling symlinks

```bash
# All dangling symlinks in $HOME
find "$HOME" -xtype l

# Same, restricted to one repo
find "$HOME" -xtype l -lname "*repo*"
```

Trailing prose in the same section.

## Second Section

Content."""

TILDE = """# Tilde

## One

~~~
# not a heading
~~~

Body text.

## Two

More."""

NESTED = """# Nested

## One

````markdown
```
# still inside
```
````

## Two

Content."""

UNCLOSED = """# Unclosed

## One

```bash
# comment

## Two"""

INDENTED = """# Indented

## One

   ```bash
   # not a heading
   ```

## Two

Content."""

CLOSED_HASHES = """# H

## Closed With Hashes ##

body

### Also Closed ###

more"""


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    if result.script == "section":
        golden.contract("content", kb.norm(facts.section_body(result.out)))
    else:
        golden.contract("facts", kb.norm(facts.toc(result.out)))
    if result.returncode != 0:
        assert result.err.strip(), "a failing run must say why"
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.bats("fences.bats", "toc ignores comments inside fenced blocks")
def test_toc_ignores_fenced_comments(kb: KB, golden: Golden) -> None:
    kb.create_article("recipes.md", FENCED)
    _check(kb, golden, kb.run("toc", "--depth", "2"))


@pytest.mark.bats("fences.bats", "section returns the whole section past a fenced comment")
def test_section_past_fenced_comment(kb: KB, golden: Golden) -> None:
    kb.create_article("recipes.md", FENCED)
    result = kb.run("section", "--file", "knowledge/recipes.md", "--heading", "Dangling symlinks")
    _check(kb, golden, result)


@pytest.mark.bats("fences.bats", "fenced comments do not shift H2 numbering")
def test_fenced_comments_keep_numbering(kb: KB, golden: Golden) -> None:
    kb.create_article("recipes.md", FENCED)
    _check(kb, golden, kb.run("section", "--file", "knowledge/recipes.md", "--number", "2"))


@pytest.mark.bats("fences.bats", "tilde fences are honored")
def test_tilde_fences(kb: KB, golden: Golden) -> None:
    kb.create_article("tilde.md", TILDE)
    _check(kb, golden, kb.run("toc", "--depth", "2"))


@pytest.mark.bats("fences.bats", "a longer closing fence closes the block")
def test_longer_closing_fence(kb: KB, golden: Golden) -> None:
    kb.create_article("nested.md", NESTED)
    _check(kb, golden, kb.run("toc", "--depth", "2"))


@pytest.mark.bats("fences.bats", "an unclosed fence swallows the rest of the file")
def test_unclosed_fence(kb: KB, golden: Golden) -> None:
    kb.create_article("unclosed.md", UNCLOSED)
    _check(kb, golden, kb.run("toc", "--depth", "2"))


@pytest.mark.bats("fences.bats", "fence state resets between files")
def test_fence_state_resets(kb: KB, golden: Golden) -> None:
    kb.create_article("a.md", "# A\n\n## Open\n\n```bash\n# unterminated")
    kb.create_article("b.md", "# B\n\n## Visible\n\nContent.")
    _check(kb, golden, kb.run("toc", "--depth", "2"))


@pytest.mark.bats("fences.bats", "indented fences up to three spaces are honored")
def test_indented_fences(kb: KB, golden: Golden) -> None:
    kb.create_article("indented.md", INDENTED)
    _check(kb, golden, kb.run("toc", "--depth", "2"))


def test_four_space_indent_is_not_a_fence(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "code.md", "# Code\n\n## One\n\n    ```\n# heading after indented code\n\n## Two\n\nx"
    )
    _check(kb, golden, kb.run("toc", "--depth", "2"))


@pytest.mark.bats("fences.bats", "toc strips the closing hashes of an ATX heading")
def test_closing_hashes_stripped(kb: KB, golden: Golden) -> None:
    kb.create_article("h.md", CLOSED_HASHES)
    _check(kb, golden, kb.run("toc", "--depth", "3"))


@pytest.mark.bats("fences.bats", "section --exact matches the name toc printed")
def test_section_exact_after_closing_hashes(kb: KB, golden: Golden) -> None:
    kb.create_article("h.md", "# H\n\n## Closed With Hashes ##\n\nbody here")
    result = kb.run(
        "section", "--file", "knowledge/h.md", "--heading", "Closed With Hashes", "--exact"
    )
    _check(kb, golden, result)


@pytest.mark.bats("fences.bats", "a heading of only hashes does not become a heading name")
@pytest.mark.audit("A-017")
def test_hashes_only_heading(kb: KB, golden: Golden) -> None:
    # The bats original has no hashes-only line; this adds one.
    kb.create_article("h.md", "# H\n\n## ##\n\n## Real Section\n\nbody")
    _check(kb, golden, kb.run("toc", "--depth", "2"))
