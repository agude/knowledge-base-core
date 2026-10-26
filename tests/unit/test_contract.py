"""Tests of the plan's rules that hold across commands: locators, parsing, and the package."""

import ast
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

from kb import cli, model
from kb.commands import map as map_command
from kb.commands import recall
from kb.context import Context
from kb.model import Document

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "kb"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"
TODAY = "2026-10-26"


@pytest.fixture
def content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Context:
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    monkeypatch.setenv("KB_CONTENT", str(root))
    monkeypatch.setenv("KB_TODAY", TODAY)
    return Context(root=root.resolve(), today=date(2026, 10, 26))


def read_back(capsys: pytest.CaptureFixture[str], locator: str) -> tuple[int, str]:
    status = cli.main(["read", locator])
    captured = capsys.readouterr()
    return status, captured.err


def test_every_locator_that_recall_and_map_print_is_read_back(
    content: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    printed: list[str] = []
    for words in (["nas", "restart", "order"], ["dns", "resolver"], ["backup", "retention"]):
        for line in recall.answer(content, words, 5, None).splitlines():
            locator = line.split(" | ")[0].strip()
            if locator.startswith(("knowledge/", "sources/")) and "#" in locator:
                printed.append(locator)
    for line in map_command.article_lines(
        [
            model.parse(path, (content.root / path).read_text(encoding="utf-8"))
            for path in sorted(
                str(p.relative_to(content.root)) for p in (content.root / "knowledge").rglob("*.md")
            )
        ],
        3,
    ):
        printed.append(line.split(" | ")[0].strip())
    assert len(printed) > 20
    for locator in printed:
        status, err = read_back(capsys, locator)
        assert status == 0, (locator, err)


def test_only_the_model_parses_front_matter_or_headings_in_the_package() -> None:
    markers = ("kb-section", "---", "#{")
    for module in PACKAGE.glob("*.py"):
        if module.name == "model.py":
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for marker in markers:
                    assert marker not in node.value, f"{module.name} mentions {marker!r}"


def test_the_package_imports_only_the_standard_library_and_itself() -> None:
    allowed = set(sys.stdlib_module_names) | {"kb"}
    for module in PACKAGE.rglob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] in allowed, f"{module.name} imports {name}"


def test_each_file_is_parsed_once_per_answer(
    content: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = model.parse
    for words in (["nas", "restart", "order"], ["quantum", "zebra"]):
        counts: dict[str, int] = {}

        def counting(path: str, text: str, counts: dict[str, int] = counts) -> Document:
            counts[path] = counts.get(path, 0) + 1
            return original(path, text)

        monkeypatch.setattr(model, "parse", counting)
        recall.answer(content, words, 3, None)
        assert counts
        assert max(counts.values()) == 1


def test_default_limit_prints_three_sections_then_five_also_relevant(tmp_path: Path) -> None:
    root = tmp_path / "content"
    (root / "knowledge").mkdir(parents=True)
    sections = "".join(
        f"## Topic {number}\n\nAlpha beta note {number}.\n\n" for number in range(1, 11)
    )
    (root / "knowledge" / "many.md").write_text(
        f"---\ntitle: Many\n---\n\n# Many\n\n{sections}", encoding="utf-8"
    )
    context = Context(root=root.resolve(), today=date(2026, 10, 26))
    text = recall.answer(context, ["alpha", "beta"], 3, None)
    assert text.count("\n## Topic ") == 3
    also = text.split("Also relevant:\n")[1].split("\n")
    assert [line for line in also if line.startswith("  knowledge/many.md#")] == [
        f"  knowledge/many.md#{number} | Topic {number}" for number in range(4, 9)
    ]


def test_uncurated_and_evidence_lists_stop_at_five(tmp_path: Path) -> None:
    root = tmp_path / "content"
    (root / "knowledge").mkdir(parents=True)
    (root / "knowledge" / "one.md").write_text(
        "---\ntitle: One\n---\n\n## Gamma\n\nAlpha beta.\n", encoding="utf-8"
    )
    pending = root / "observations" / "pending"
    pending.mkdir(parents=True)
    for number in range(1, 9):
        (pending / f"20261001T00000{number}-aaaaaaa{number}.md").write_text(
            f"---\ntitle: Note {number}\nsource: session\ncreated: 2026-10-0{number}T00:00:00Z\n---\n\nAlpha beta {number}.\n",
            encoding="utf-8",
        )
    context = Context(root=root.resolve(), today=date(2026, 10, 26))
    text = recall.answer(context, ["alpha", "beta"], 3, None)
    assert text.count("  observations/pending/") == 5
    evidence_root = tmp_path / "evidence"
    (evidence_root / "observations" / "archived").mkdir(parents=True)
    for number in range(1, 9):
        (
            evidence_root
            / "observations"
            / "archived"
            / f"20261001T00000{number}-bbbbbbb{number}.md"
        ).write_text(
            f"---\ntitle: Old {number}\nsource: session\ncreated: 2026-09-0{number}T00:00:00Z\n---\n\nAlpha beta {number}.\n",
            encoding="utf-8",
        )
    empty = Context(root=evidence_root.resolve(), today=date(2026, 10, 26))
    text = recall.answer(empty, ["alpha", "beta"], 3, None)
    assert text.count("  observations/archived/") == 5


def test_recall_and_map_leave_the_content_repository_unchanged(
    content: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib

    def digest() -> dict[str, str]:
        return {
            str(path.relative_to(content.root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(content.root.rglob("*"))
            if path.is_file()
        }

    before = digest()
    cli.main(["recall", "nas", "restart", "order"])
    cli.main(["read", "knowledge/infra/nas.md#1"])
    cli.main(["map", "--depth", "3"])
    capsys.readouterr()
    assert digest() == before
