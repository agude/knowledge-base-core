"""Content-reading commands against unusual input.

Each case builds one kind of awkward content and runs every reading
command. Contract: the exit code and the facts the command reports.
Reference: the full output.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable

import pytest

from kbtest import facts
from kbtest.golden import Golden
from kbtest.runner import KB, Result

ARTICLE = '---\ntitle: "{title}"\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n\n# {title}\n\n## Section\n\n{body}\n'


def _empty(kb: KB) -> None:
    for sub in ("knowledge", "observations", "questions", "sources"):
        shutil.rmtree(kb.layout.content / sub)


def _missing_dirs(kb: KB) -> None:
    shutil.rmtree(kb.layout.content / "observations")
    shutil.rmtree(kb.layout.content / "questions")
    kb.create_article("a.md", ARTICLE.format(title="A", body="needle"))


def _malformed(kb: KB) -> None:
    kb.create_article("open-front.md", '---\ntitle: "Unclosed\n# Heading\n\n## Section\n\nneedle')
    kb.create_article("no-front.md", "# Bare\n\n## Section\n\nneedle")
    (kb.layout.content / "observations" / "pending" / "20261001T000000-0000aaaa.md").write_text(
        "title: missing delimiters\nneedle\n", encoding="utf-8"
    )
    (kb.layout.content / "questions" / "open" / "q.md").write_text(
        "---\ntitle: \n---\n", encoding="utf-8"
    )


def _crlf(kb: KB) -> None:
    text = ARTICLE.format(title="Windows", body="needle line").replace("\n", "\r\n")
    (kb.layout.content / "knowledge" / "crlf.md").write_bytes(text.encode())


def _non_ascii(kb: KB) -> None:
    kb.create_article("résumé.md", ARTICLE.format(title="Résumé 日本", body="needle café 雪"))


def _no_trailing_newline(kb: KB) -> None:
    (kb.layout.content / "knowledge" / "tail.md").write_text(
        ARTICLE.format(title="Tail", body="needle").rstrip("\n"), encoding="utf-8"
    )


def _spaces(kb: KB) -> None:
    kb.create_article("with space/a file.md", ARTICLE.format(title="Spaced", body="needle"))


def _symlinks(kb: KB) -> None:
    kb.create_article("real.md", ARTICLE.format(title="Real", body="needle"))
    knowledge = kb.layout.content / "knowledge"
    (knowledge / "alias.md").symlink_to("real.md")
    (knowledge / "dangling.md").symlink_to("missing.md")


def _unreadable(kb: KB) -> None:
    kb.create_article("ok.md", ARTICLE.format(title="Readable", body="needle"))
    locked = kb.create_article("locked.md", ARTICLE.format(title="Locked", body="needle"))
    locked.chmod(0)


CASES: dict[str, Callable[[KB], None]] = {
    "empty": _empty,
    "missing-dirs": _missing_dirs,
    "malformed-front-matter": _malformed,
    "crlf": _crlf,
    "non-ascii": _non_ascii,
    "no-trailing-newline": _no_trailing_newline,
    "spaces": _spaces,
    "symlinks": _symlinks,
    "unreadable": _unreadable,
}

SUMMARY = re.compile(r"(\d+) file\(s\): (\d+) error\(s\), (\d+) warning\(s\)")


def _search_facts(kb: KB, result: Result) -> str:
    try:
        data = json.loads(result.out)
    except ValueError:
        return "not json\n"
    return "".join(f"{r['path']} | {r['locator']['section']}\n" for r in data["results"])


def _first_article(kb: KB) -> str:
    knowledge = kb.layout.content / "knowledge"
    if not knowledge.is_dir():
        return "knowledge/none.md"
    for path in sorted(knowledge.rglob("*.md")):
        if path.is_file() and os.access(path, os.R_OK):
            return path.relative_to(kb.layout.content).as_posix()
    return "knowledge/none.md"


COMMANDS: dict[str, tuple[Callable[[KB], list[str]], Callable[[KB, Result], str]]] = {
    "search": (lambda kb: ["--json", "needle"], _search_facts),
    "section": (
        lambda kb: ["--json", "--file", _first_article(kb), "--number", "1"],
        lambda kb, r: (json.loads(r.out).get("content", "") if r.returncode == 0 else "") + "\n",
    ),
    "toc": (lambda kb: [], lambda kb, r: facts.toc(r.out)),
    "stale": (lambda kb: [], lambda kb, r: facts.stale(r.out)),
    "pending": (lambda kb: [], lambda kb, r: "\n".join(facts.pending(r.out)) + "\n"),
    "status": (lambda kb: [], lambda kb, r: facts.status(r.out)),
    "context": (lambda kb: [], lambda kb, r: facts.status(r.out)),
    "questions": (
        lambda kb: [],
        lambda kb, r: "".join(f"{t} | {c}\n" for t, c in facts.questions(r.out)),
    ),
    "lint": (
        lambda kb: [],
        lambda kb, r: (m.group(0) if (m := SUMMARY.search(r.out + r.err)) else "none") + "\n",
    ),
    "session-context": (lambda kb: [], lambda kb, r: kb.context_facts(r.out)),
}


@pytest.mark.audit("A-035")
@pytest.mark.audit("A-036")
@pytest.mark.parametrize("command", sorted(COMMANDS))
@pytest.mark.parametrize("case", sorted(CASES))
def test_edge(kb: KB, golden: Golden, case: str, command: str) -> None:
    if case == "unreadable" and os.geteuid() == 0:
        pytest.skip("root reads files regardless of mode")
    CASES[case](kb)
    arguments, extract = COMMANDS[command]
    try:
        result = kb.run(command, *arguments(kb))
    finally:
        for path in (
            (kb.layout.content / "knowledge").rglob("*")
            if (kb.layout.content / "knowledge").is_dir()
            else []
        ):
            if not path.is_symlink():
                path.chmod(0o755 if path.is_dir() else 0o644)
    golden.contract("result", f"exit {result.returncode}\n")
    # An empty report and silence are different results.
    reported = f"stdout {'present' if result.out.strip() else 'empty'}\n"
    golden.contract("facts", kb.norm(reported + extract(kb, result)))
    if result.returncode != 0:
        assert (result.err + result.out).strip(), "a failing run must say why"
    golden.check("stdout", kb.norm(kb.placeholder_instructions(result.out)))
    golden.check("stderr", kb.norm_err(result.err))
