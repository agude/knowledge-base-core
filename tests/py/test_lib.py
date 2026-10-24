"""Shared library behavior, observed through the executables that use it.

lib.bats calls _lib.sh functions directly. These tests pin the same
behavior black-box: TTL parsing via section, option parsing via observe and
pending, escaping via observe, front-matter reading via questions, path
resolution via ask, commits via observe and ask, and the JSON encoder via
session-append without jq.
"""

from __future__ import annotations

import json
import re

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


# TTL parsing (ttl_days)


@pytest.mark.bats("lib.bats", "ttl_days normalizes decimal days and bounds seconds arithmetic")
@pytest.mark.bats("lib.bats", "retrieval marks out-of-range article and section TTLs invalid")
@pytest.mark.parametrize(
    "ttl", ["08", "000", "106751991167300", "106751991167301", "9223372036854775808"]
)
def test_ttl_bounds(kb: KB, golden: Golden, ttl: str) -> None:
    kb.create_article(
        "ttl.md", f"---\ntitle: TTL\nverified: 2026-10-04\nttl: {ttl}\n---\n## Service\nEvidence."
    )
    result = kb.run("section", "--file", "knowledge/ttl.md", "--number", "1", "--json")
    assert result.returncode == 0
    golden.contract("freshness", json.dumps(json.loads(result.out)["freshness"], indent=2) + "\n")


@pytest.mark.bats("lib.bats", "retrieval marks out-of-range article and section TTLs invalid")
@pytest.mark.parametrize("selector", [["--title"], ["--number", "1"]])
def test_out_of_range_section_ttl(kb: KB, golden: Golden, selector: list[str]) -> None:
    kb.create_article(
        "ttl-range.md",
        "---\ntitle: TTL range\nverified: 2026-10-04\nttl: 106751991167301\n---\n"
        "## Service\n<!-- kb-section: ttl=9223372036854775808 -->\nEvidence.",
    )
    result = kb.run("section", "--file", "knowledge/ttl-range.md", *selector, "--json")
    assert result.returncode == 0
    golden.contract("freshness", json.dumps(json.loads(result.out)["freshness"], indent=2) + "\n")


# Help text (show_help)


@pytest.mark.bats("lib.bats", "show_help extracts comment header")
@pytest.mark.parametrize("script", ["status", "observe", "ask"])
def test_help_is_the_comment_header(kb: KB, golden: Golden, script: str) -> None:
    result = kb.run(script, "--help")
    assert result.returncode == 0
    # Help opens with the command's one-line summary and shows its usage.
    assert result.out.lstrip().startswith(f"{script} - "), result.out[:80]
    assert "Usage:" in result.out
    _check(kb, golden, result)


# Option parsing (need_arg, parse_nonnegative_decimal)


@pytest.mark.bats("lib.bats", "need_arg fails when no argument follows flag")
@pytest.mark.bats("lib.bats", "need_arg succeeds when argument follows flag")
@pytest.mark.parametrize(
    "args",
    [["--title"], ["--title", "T", "--body"], ["--title", "--body", "B"]],
    ids=["title-last", "body-last", "flag-as-value"],
)
def test_option_arguments(kb: KB, golden: Golden, args: list[str]) -> None:
    _check(
        kb,
        golden,
        kb.run("observe", *args, "--no-commit")
        if args[-1] != "--body"
        else kb.run("observe", *args),
    )


@pytest.mark.bats("lib.bats", "parse_nonnegative_decimal normalizes leading zeroes")
@pytest.mark.bats("lib.bats", "parse_nonnegative_decimal rejects overflow")
@pytest.mark.parametrize("value", ["01000", "000", "999999999999999999999999999999", "1e3", "+5"])
def test_decimal_parsing(kb: KB, golden: Golden, value: str) -> None:
    kb.create_observation("a.md", "A", "Body")
    result = kb.run("pending", "--preview", "--max-bytes", value)
    if result.returncode == 0:
        assert f"Input budget: {int(value)} bytes" in result.out
    else:
        assert result.err.strip()
    _check(kb, golden, result)


# Escaping (yaml_escape) and front-matter reads (frontmatter_field)


@pytest.mark.bats("lib.bats", "yaml_escape escapes double quotes")
@pytest.mark.bats("lib.bats", "yaml_escape escapes backslashes")
def test_title_escaping_round_trip(kb: KB, golden: Golden) -> None:
    title = 'say "hello" path\\to\\file'
    assert kb.run("observe", "--title", title, "--body", "B", "--no-commit").returncode == 0
    (path,) = (kb.layout.content / "observations" / "pending").glob("*.md")
    text = path.read_text(encoding="utf-8")
    created = re.search(r"^created: (\S+)$", text, re.MULTILINE)
    assert created
    kb.normalizer.extra[created.group(1)] = "<TIMESTAMP>"
    golden.contract("file", kb.norm(text))
    # The listing reads the title back through the front-matter parser.
    golden.check("listing", kb.norm(kb.run("pending").out))


@pytest.mark.bats("lib.bats", "frontmatter_field extracts unquoted value")
@pytest.mark.bats("lib.bats", "frontmatter_field extracts quoted value")
@pytest.mark.bats("lib.bats", "frontmatter_field returns 1 for missing field")
def test_front_matter_reads(kb: KB, golden: Golden) -> None:
    open_dir = kb.layout.content / "questions" / "open"
    (open_dir / "a.md").write_text(
        '---\ntitle: "Hello World"\ncontext: knowledge/a.md\n---\n', encoding="utf-8"
    )
    (open_dir / "b.md").write_text("---\ntitle: Unquoted title\n---\n", encoding="utf-8")
    (open_dir / "c.md").write_text("---\nsource: test\n---\n", encoding="utf-8")
    (open_dir / "d.md").write_text("no front matter\n", encoding="utf-8")
    (open_dir / "e.md").write_text(
        '---\ntitle: "Escaped \\"q\\" and \\\\"\n---\n', encoding="utf-8"
    )
    result = kb.run("questions")
    titles = [line[2:] for line in result.out.splitlines() if line.startswith("- ")]
    assert titles == [
        "Hello World (knowledge/a.md)",
        "Unquoted title",
        "",
        "",
        'Escaped "q" and \\',
    ]
    _check(kb, golden, result)


# Commits (commit_paths, locked_commit)


@pytest.mark.bats("lib.bats", "locked_commit commits only the named paths")
def test_commit_only_named_paths(kb: KB, golden: Golden) -> None:
    kb.create_article("staged-by-someone-else.md", "# Draft")
    kb.git("add", "knowledge/staged-by-someone-else.md")
    assert kb.run("observe", "--title", "Obs", "--body", "Body").returncode == 0
    golden.contract("head", kb.norm(kb.git("show", "--name-only", "--format=%s", "HEAD")))
    golden.contract("status", kb.git("status", "--porcelain"))


@pytest.mark.bats("lib.bats", "locked_commit returns nonzero when the commit is rejected")
@pytest.mark.bats("lib.bats", "locked_commit releases the lock after a rejected commit")
@pytest.mark.parametrize("script", ["ask", "observe"])
def test_rejected_commit(kb: KB, golden: Golden, script: str) -> None:
    hook = kb.layout.content / ".git" / "hooks" / "pre-commit"
    hook.write_text('#!/bin/sh\necho "rejected by test hook" >&2\nexit 1\n', encoding="utf-8")
    hook.chmod(0o755)
    args = ["--title", "Q"] if script == "ask" else ["--title", "Obs", "--body", "Body"]
    result = kb.run(script, *args)
    _check(kb, golden, result)
    assert not (kb.layout.content / ".observe.lock").exists()


# Path resolution (resolve_path), through ask --context


def _sort_indented(text: str) -> str:
    """Sort the indented match lines, which come from an unsorted find (A-029)."""
    lines = text.splitlines(keepends=True)
    matches = iter(sorted(line for line in lines if line.startswith("  ")))
    return "".join(next(matches) if line.startswith("  ") else line for line in lines)


@pytest.mark.bats("lib.bats", "resolve_path finds knowledge-relative path")
@pytest.mark.bats("lib.bats", "resolve_path prepends knowledge/ for bare filename")
@pytest.mark.bats("lib.bats", "resolve_path fails for nonexistent file")
@pytest.mark.bats("lib.bats", "resolve_path refuses a path escaping the content root")
@pytest.mark.bats("lib.bats", "resolve_path refuses an absolute path outside the content root")
@pytest.mark.bats("lib.bats", "resolve_path refuses a symlink pointing out of the content root")
@pytest.mark.bats("lib.bats", "resolve_path still accepts ordinary paths")
@pytest.mark.parametrize(
    "context",
    [
        "knowledge/topic.md",
        "topic.md",
        "deep.md",
        "sub",
        "<CONTENT>/knowledge/topic.md",
        "no-such-file.md",
        "../../../../etc/passwd",
        "/etc/passwd",
        "knowledge/sneaky.md",
        "dup.md",
    ],
    ids=[
        "relative",
        "bare",
        "basename-search",
        "directory",
        "absolute-inside",
        "missing",
        "escape",
        "absolute-outside",
        "symlink-out",
        "ambiguous",
    ],
)
def test_context_resolution(kb: KB, golden: Golden, context: str) -> None:
    kb.create_article("topic.md", "# Topic")
    kb.create_article("sub/deep.md", "# Deep")
    kb.create_article("a/dup.md", "# A")
    kb.create_article("b/dup.md", "# B")
    (kb.layout.content / "knowledge" / "sneaky.md").symlink_to("/etc/passwd")
    value = context.replace("<CONTENT>", str(kb.layout.content))
    result = kb.run("ask", "--title", "Q?", "--context", value, "--no-commit")
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", _sort_indented(kb.norm_err(result.err)))
    files = sorted((kb.layout.content / "questions" / "open").glob("*.md"))
    golden.contract(
        "question", kb.norm(files[0].read_text(encoding="utf-8")) if files else "none\n"
    )


@pytest.mark.bats("lib.bats", "section refuses to read outside the content root")
@pytest.mark.bats("lib.bats", "toc refuses to scan outside the content root")
@pytest.mark.bats("lib.bats", "archive refuses a filename containing a path")
@pytest.mark.bats("lib.bats", "resolve refuses a question filename containing a path")
@pytest.mark.parametrize(
    "command",
    [
        ["section", "--file", "../../../../etc/passwd", "--number", "1"],
        ["toc", "--path", "../../../../etc"],
        ["archive", "../outside.md"],
        ["resolve", "--file", "../../etc/passwd"],
    ],
    ids=["section", "toc", "archive", "resolve"],
)
def test_scripts_refuse_escaping_paths(kb: KB, golden: Golden, command: list[str]) -> None:
    outside = kb.layout.content / "observations" / "outside.md"
    outside.write_text("not yours\n", encoding="utf-8")
    _check(kb, golden, kb.run(*command))
    assert outside.read_text(encoding="utf-8") == "not yours\n"


# JSON encoding of buffer messages without jq (json_quote, json_quote_file)


@pytest.mark.bats(
    "lib.bats", "streaming JSON encoder round trips all bytes without scratch allocation"
)
def test_jq_free_encoder_round_trip(no_jq: KB, golden: Golden) -> None:
    session_id = no_jq.session_id()
    no_jq.layout.sessions.mkdir(mode=0o700, parents=True)
    buffer = no_jq.layout.sessions / f"session-{session_id}.jsonl"
    buffer.touch(mode=0o600)
    message = bytes(range(1, 32)) + 'Unicode café 日本語; quotes " and backslashes \\\n\n'.encode()
    result = no_jq.run(
        "session-append", "--file", str(buffer), "--role", "user", "--message", "-", stdin=message
    )
    assert result.returncode == 0, result.err
    line = buffer.read_bytes()
    golden.contract("buffer", no_jq.norm(line.decode("utf-8")))
    record = json.loads(line)
    assert record["message"].encode("utf-8") == message
    empty = no_jq.run(
        "session-append", "--file", str(buffer), "--role", "user", "--message", "-", stdin=b""
    )
    assert empty.returncode == 0
    assert buffer.read_bytes() == line, "an empty message appends nothing"


def test_jq_encoder_round_trip(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    kb.layout.sessions.mkdir(mode=0o700, parents=True)
    buffer = kb.layout.sessions / f"session-{session_id}.jsonl"
    buffer.touch(mode=0o600)
    message = bytes(range(1, 32)) + 'Unicode café 日本語; quotes " and backslashes \\\n\n'.encode()
    result = kb.run(
        "session-append", "--file", str(buffer), "--role", "user", "--message", "-", stdin=message
    )
    assert result.returncode == 0, result.err
    line = buffer.read_bytes()
    golden.contract("buffer", kb.norm(line.decode("utf-8")))
    assert json.loads(line)["message"].encode("utf-8") == message
    assert buffer.stat().st_size == len(line)
