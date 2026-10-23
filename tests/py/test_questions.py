"""questions, ask, resolve: record, list, read, and resolve open questions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kbtest.golden import Golden
from kbtest.inspect import git_log, tree
from kbtest.runner import KB, Result


def _today(kb: KB) -> None:
    """resolve stamps the real UTC date into the resolution heading."""
    kb.normalizer.extra[datetime.now(UTC).strftime("%Y-%m-%d")] = "<TODAY>"


def _check(kb: KB, golden: Golden, result: Result, *, state: bool = True) -> None:
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    if state:
        golden.check("questions", kb.norm(tree(kb.layout.content / "questions")))
        golden.check("log", kb.norm(git_log(kb.layout.content, kb.git_env())))


def _only_question(kb: KB, area: str = "open") -> str:
    files = sorted((kb.layout.content / "questions" / area).glob("*.md"))
    assert len(files) == 1, files
    return kb.norm(files[0].read_text(encoding="utf-8"))


# questions


@pytest.mark.bats("questions.bats", "questions shows 'no open questions' when empty")
def test_questions_empty(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("questions"), state=False)


@pytest.mark.bats("questions.bats", "questions lists open questions")
def test_questions_lists(kb: KB, golden: Golden) -> None:
    kb.create_question("q2.md", "Second?", "knowledge/b.md")
    kb.create_question("q1.md", "Who owns deploys?")
    _check(kb, golden, kb.run("questions"), state=False)


@pytest.mark.bats("questions.bats", "questions --path filters by context")
@pytest.mark.audit("A-013")
def test_questions_path_filter(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Deploy question", "knowledge/deploys/canary.md")
    kb.create_question("q2.md", "Unrelated question")
    kb.create_question("q3.md", "Sibling prefix", "knowledge/deploys-old/x.md")
    _check(kb, golden, kb.run("questions", "--path", "knowledge/deploys"), state=False)


def test_questions_path_filter_no_match(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Deploy question", "knowledge/deploys/canary.md")
    _check(kb, golden, kb.run("questions", "--path", "knowledge/other"), state=False)


def test_questions_path_filter_resolves_bare_name(kb: KB, golden: Golden) -> None:
    kb.create_article("deploys/canary.md", "# Canary")
    kb.create_question("q1.md", "Deploy question", "knowledge/deploys/canary.md")
    _check(kb, golden, kb.run("questions", "--path", "canary.md"), state=False)


@pytest.mark.bats("questions.bats", "questions --file reads single question")
def test_questions_file(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("questions", "--file", "q1.md"), state=False)


def test_questions_file_resolved(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Done question")
    open_file = kb.layout.content / "questions" / "open" / "q1.md"
    open_file.rename(kb.layout.content / "questions" / "resolved" / "q1.md")
    _check(kb, golden, kb.run("questions", "--file", "q1.md"), state=False)


@pytest.mark.parametrize("name", ["missing.md", "../open/q1.md"], ids=["missing", "path"])
def test_questions_file_errors(kb: KB, golden: Golden, name: str) -> None:
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("questions", "--file", name), state=False)


def test_questions_full_and_all(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Open one", "knowledge/a.md")
    kb.create_question("q2.md", "Resolved one")
    q2 = kb.layout.content / "questions" / "open" / "q2.md"
    q2.rename(kb.layout.content / "questions" / "resolved" / "q2.md")
    golden.check("all", kb.norm(kb.run("questions", "--all").out))
    golden.check("full", kb.norm(kb.run("questions", "--full").out))
    golden.check("full-all", kb.norm(kb.run("questions", "--full", "--all").out))


def test_questions_unknown_option(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("questions", "--bogus"), state=False)


# ask


@pytest.mark.bats("questions.bats", "ask creates question file")
def test_ask_creates_question(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("ask", "--title", "New question?", "--no-commit"))
    golden.check("file", _only_question(kb))


@pytest.mark.bats("questions.bats", "ask includes --context in frontmatter")
def test_ask_context(kb: KB, golden: Golden) -> None:
    kb.create_article("topic.md", "# Topic")
    result = kb.run("ask", "--title", "About topic?", "--context", "topic.md", "--no-commit")
    _check(kb, golden, result)
    golden.check("file", _only_question(kb))


def test_ask_context_missing(kb: KB, golden: Golden) -> None:
    result = kb.run("ask", "--title", "About?", "--context", "missing.md", "--no-commit")
    _check(kb, golden, result)


@pytest.mark.bats("questions.bats", "ask includes --body")
def test_ask_body(kb: KB, golden: Golden) -> None:
    result = kb.run("ask", "--title", "Question?", "--body", "Extra context here", "--no-commit")
    _check(kb, golden, result)
    golden.check("file", _only_question(kb))


def test_ask_body_from_stdin(kb: KB, golden: Golden) -> None:
    result = kb.run(
        "ask", "--title", "Question?", "--body", "-", "--no-commit", stdin="Line one.\nLine two.\n"
    )
    _check(kb, golden, result)
    golden.check("file", _only_question(kb))


@pytest.mark.audit("A-014")
def test_ask_body_that_looks_like_an_echo_option(kb: KB, golden: Golden) -> None:
    result = kb.run("ask", "--title", "Question?", "--body", "-n", "--no-commit")
    _check(kb, golden, result)
    golden.check("file", _only_question(kb))


def test_ask_escapes_title(kb: KB, golden: Golden) -> None:
    title = 'Why "quoted" and back\\slash?'
    _check(kb, golden, kb.run("ask", "--title", title, "--source", "curator"))
    golden.check("file", _only_question(kb))


def test_ask_requires_title(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("ask", "--no-commit"))


def test_ask_commits(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("ask", "--title", "Committed?"))


# resolve


@pytest.mark.bats("questions.bats", "resolve moves question to resolved")
@pytest.mark.bats("questions.bats", "resolve appends resolution section")
def test_resolve_with_answer(kb: KB, golden: Golden) -> None:
    _today(kb)
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("resolve", "--file", "q1.md", "--answer", "Answered.", "--no-commit"))
    golden.check("file", _only_question(kb, "resolved"))


def test_resolve_without_answer(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("resolve", "--file", "q1.md", "--no-commit"))
    golden.check("file", _only_question(kb, "resolved"))


def test_resolve_answer_from_stdin_and_commit(kb: KB, golden: Golden) -> None:
    _today(kb)
    kb.create_question("q1.md", "Test question")
    kb.git("add", "-A")
    kb.git("commit", "-q", "-m", "Ask")
    result = kb.run("resolve", "--file", "q1.md", "--answer", "-", stdin="Long answer.\n")
    _check(kb, golden, result)
    golden.check("file", _only_question(kb, "resolved"))


@pytest.mark.bats("questions.bats", "resolve fails for nonexistent question")
def test_resolve_missing(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("resolve", "--file", "nonexistent.md", "--no-commit"))


@pytest.mark.parametrize("args", [[], ["--file", "../open/q1.md"]], ids=["no-file", "path"])
def test_resolve_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("resolve", *args, "--no-commit"))
