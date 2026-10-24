"""questions, ask, resolve: record, list, read, and resolve open questions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kbtest import facts
from kbtest.golden import Golden
from kbtest.inspect import git_log, tree
from kbtest.marks import xfail_bash
from kbtest.runner import KB, Result


def _today(kb: KB) -> None:
    """resolve stamps the real UTC date into the resolution heading."""
    kb.normalizer.extra[datetime.now(UTC).strftime("%Y-%m-%d")] = "<TODAY>"


def _check(kb: KB, golden: Golden, result: Result, *, state: bool = True) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    if state:
        golden.contract("questions", kb.norm(tree(kb.layout.content / "questions")))
        golden.contract("log", kb.norm(git_log(kb.layout.content, kb.git_env())))


def _only_question(kb: KB, area: str = "open") -> str:
    files = sorted((kb.layout.content / "questions" / area).glob("*.md"))
    assert len(files) == 1, files
    return kb.norm(files[0].read_text(encoding="utf-8"))


# questions


def _question_text(kb: KB, area: str, name: str) -> str:
    return (kb.layout.content / "questions" / area / name).read_text(encoding="utf-8")


@pytest.mark.bats("questions.bats", "questions shows 'no open questions' when empty")
def test_questions_empty(kb: KB, golden: Golden) -> None:
    result = kb.run("questions")
    assert result.returncode == 0
    assert facts.questions(result.out) == []
    assert result.out.strip(), "an empty list is reported"
    _check(kb, golden, result, state=False)


@pytest.mark.bats("questions.bats", "questions lists open questions")
def test_questions_lists(kb: KB, golden: Golden) -> None:
    kb.create_question("q2.md", "Second?", "knowledge/b.md")
    kb.create_question("q1.md", "Who owns deploys?")
    result = kb.run("questions")
    assert facts.questions(result.out) == [("Who owns deploys?", ""), ("Second?", "knowledge/b.md")]
    _check(kb, golden, result, state=False)


@pytest.mark.bats("questions.bats", "questions --path filters by context")
@xfail_bash("A-013: bash matches a string prefix, so knowledge/deploys-old matches")
def test_questions_path_filter(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Deploy question", "knowledge/deploys/canary.md")
    kb.create_question("q2.md", "Unrelated question")
    kb.create_question("q3.md", "Sibling prefix", "knowledge/deploys-old/x.md")
    result = kb.run("questions", "--path", "knowledge/deploys")
    titles = [title for title, _ in facts.questions(result.out)]
    assert "Deploy question" in titles and "Unrelated question" not in titles
    assert "Sibling prefix" not in titles, "the filter matches whole path segments"
    _check(kb, golden, result, state=False)


def test_questions_path_filter_no_match(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Deploy question", "knowledge/deploys/canary.md")
    result = kb.run("questions", "--path", "knowledge/other")
    assert result.returncode == 0
    assert facts.questions(result.out) == []
    assert "knowledge/other" in result.out, "the empty result names the filter"
    _check(kb, golden, result, state=False)


def test_questions_path_filter_resolves_bare_name(kb: KB, golden: Golden) -> None:
    kb.create_article("deploys/canary.md", "# Canary")
    kb.create_question("q1.md", "Deploy question", "knowledge/deploys/canary.md")
    result = kb.run("questions", "--path", "canary.md")
    assert facts.questions(result.out) == [("Deploy question", "knowledge/deploys/canary.md")]
    _check(kb, golden, result, state=False)


@pytest.mark.bats("questions.bats", "questions --file reads single question")
def test_questions_file(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Test question")
    result = kb.run("questions", "--file", "q1.md")
    assert result.returncode == 0
    assert result.out == _question_text(kb, "open", "q1.md")
    _check(kb, golden, result, state=False)


def test_questions_file_resolved(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Done question")
    open_file = kb.layout.content / "questions" / "open" / "q1.md"
    open_file.rename(kb.layout.content / "questions" / "resolved" / "q1.md")
    result = kb.run("questions", "--file", "q1.md")
    assert result.returncode == 0
    assert result.out == _question_text(kb, "resolved", "q1.md")
    _check(kb, golden, result, state=False)


@pytest.mark.parametrize("name", ["missing.md", "../open/q1.md"], ids=["missing", "path"])
def test_questions_file_errors(kb: KB, golden: Golden, name: str) -> None:
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("questions", "--file", name), state=False)


def test_questions_full_and_all(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Open one", "knowledge/a.md")
    kb.create_question("q2.md", "Resolved one")
    q2 = kb.layout.content / "questions" / "open" / "q2.md"
    q2.rename(kb.layout.content / "questions" / "resolved" / "q2.md")
    listing = kb.run("questions", "--all")
    full = kb.run("questions", "--full")
    full_all = kb.run("questions", "--full", "--all")
    titles = [title for title, _ in facts.questions(listing.out)]
    assert titles[0] == "Open one" and titles[1].startswith("Resolved one")
    open_text = _question_text(kb, "open", "q1.md")
    resolved_text = _question_text(kb, "resolved", "q2.md")
    assert open_text in full.out and resolved_text not in full.out
    assert open_text in full_all.out and resolved_text in full_all.out
    golden.check("all", kb.norm(listing.out))
    golden.check("full", kb.norm(full.out))
    golden.check("full-all", kb.norm(full_all.out))


def test_questions_unknown_option(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("questions", "--bogus"), state=False)


# ask


@pytest.mark.bats("questions.bats", "ask creates question file")
def test_ask_creates_question(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("ask", "--title", "New question?", "--no-commit"))
    golden.contract("file", _only_question(kb))


@pytest.mark.bats("questions.bats", "ask includes --context in frontmatter")
def test_ask_context(kb: KB, golden: Golden) -> None:
    kb.create_article("topic.md", "# Topic")
    result = kb.run("ask", "--title", "About topic?", "--context", "topic.md", "--no-commit")
    _check(kb, golden, result)
    golden.contract("file", _only_question(kb))


def test_ask_context_missing(kb: KB, golden: Golden) -> None:
    result = kb.run("ask", "--title", "About?", "--context", "missing.md", "--no-commit")
    _check(kb, golden, result)


@pytest.mark.bats("questions.bats", "ask includes --body")
def test_ask_body(kb: KB, golden: Golden) -> None:
    result = kb.run("ask", "--title", "Question?", "--body", "Extra context here", "--no-commit")
    _check(kb, golden, result)
    golden.contract("file", _only_question(kb))


def test_ask_body_from_stdin(kb: KB, golden: Golden) -> None:
    result = kb.run(
        "ask", "--title", "Question?", "--body", "-", "--no-commit", stdin="Line one.\nLine two.\n"
    )
    _check(kb, golden, result)
    golden.contract("file", _only_question(kb))


@pytest.mark.audit("A-014")
def test_ask_body_that_looks_like_an_echo_option(kb: KB, golden: Golden) -> None:
    result = kb.run("ask", "--title", "Question?", "--body", "-n", "--no-commit")
    _check(kb, golden, result)
    golden.contract("file", _only_question(kb))


def test_ask_escapes_title(kb: KB, golden: Golden) -> None:
    title = 'Why "quoted" and back\\slash?'
    _check(kb, golden, kb.run("ask", "--title", title, "--source", "curator"))
    golden.contract("file", _only_question(kb))


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
    golden.contract("file", _only_question(kb, "resolved"))


def test_resolve_without_answer(kb: KB, golden: Golden) -> None:
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("resolve", "--file", "q1.md", "--no-commit"))
    golden.contract("file", _only_question(kb, "resolved"))


def test_resolve_answer_from_stdin_and_commit(kb: KB, golden: Golden) -> None:
    _today(kb)
    kb.create_question("q1.md", "Test question")
    kb.git("add", "-A")
    kb.git("commit", "-q", "-m", "Ask")
    result = kb.run("resolve", "--file", "q1.md", "--answer", "-", stdin="Long answer.\n")
    _check(kb, golden, result)
    golden.contract("file", _only_question(kb, "resolved"))


@pytest.mark.bats("questions.bats", "resolve fails for nonexistent question")
def test_resolve_missing(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("resolve", "--file", "nonexistent.md", "--no-commit"))


@pytest.mark.parametrize("args", [[], ["--file", "../open/q1.md"]], ids=["no-file", "path"])
def test_resolve_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_question("q1.md", "Test question")
    _check(kb, golden, kb.run("resolve", *args, "--no-commit"))
