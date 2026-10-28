"""Markdown link syntax that affects local reference checks."""

import pytest

from kb import links


@pytest.mark.parametrize(
    ("line", "targets"),
    [
        ("[guide](guide(v2).md)", ["guide(v2).md"]),
        ("[guide](guide(one(two)).md)", ["guide(one(two)).md"]),
        (r"[guide](guide\(v2\).md)", ["guide(v2).md"]),
        ('[guide](<guide(v2).md> "Guide")', ["guide(v2).md"]),
        ("[guide](<guide v2.md>)", ["guide v2.md"]),
        ('[guide](guide.md "A title (v2)")', ["guide.md"]),
        ("[guide](guide.md 'A title')", ["guide.md"]),
        ("[guide](guide.md (A title))", ["guide.md"]),
        (r'[guide](guide.md "An escaped \"title\"")', ["guide.md"]),
        (r"\[escaped](missing.md) [real](guide.md)", ["guide.md"]),
        ("[a [nested] label](guide.md)", ["guide.md"]),
        ("[ordinary text [link](guide.md)]", ["guide.md"]),
        (r"[escaped \] label](guide.md)", ["guide.md"]),
        ("[first](one.md) and [second](two.md)", ["one.md", "two.md"]),
        ("![image](picture.png)", ["picture.png"]),
        ("[unclosed", []),
        ("[guide](unbalanced(one.md)", []),
        ("[guide](<unclosed.md)", []),
        ("[guide](<nested<angle>.md>)", []),
        ('[guide](guide.md "unclosed title)', []),
        ("[guide](guide.md trailing text)", []),
    ],
)
def test_inline_destinations(line: str, targets: list[str]) -> None:
    assert links.destinations([line]) == [(1, target) for target in targets]


def test_references_use_the_first_definition_and_normalize_label_whitespace() -> None:
    assert links.destinations(
        [
            "[full][ A   LABEL ] [collapsed][] [shortcut] [unknown]",
            "",
            "[a label]: first.md",
            "[A LABEL]: ignored.md",
            "[collapsed]: second.md 'Title'",
            "[shortcut]: <third.md>",
        ]
    ) == [(1, "first.md"), (1, "second.md"), (1, "third.md")]


def test_malformed_definitions_and_undefined_references_do_not_create_targets() -> None:
    assert links.destinations(["[unused][missing]", "[label]: <unclosed"]) == []
