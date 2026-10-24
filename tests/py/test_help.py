"""--help and unknown options for every executable in the interface surface.

The parameters come from the bash tree's executables, so a new executable
without goldens fails here until its help and error output are pinned.
"""

from __future__ import annotations

import pytest

from kbtest.golden import Golden
from kbtest.impl import interface_executables
from kbtest.marks import xfail_bash
from kbtest.runner import KB

# Host entry points, which do not parse options (A-034): hooks read their
# input from stdin, and session-context takes no arguments.
NO_OPTIONS = {
    "hooks/pre-commit",
    "session-context",
}

# Commands that should parse options but do not under bash (A-034). Bash's
# context already prints help; it ignores unknown options.
UNPARSED = xfail_bash("A-034: bash's context and session-flush do not parse options")
SHOULD_PARSE = {"help": {"session-flush"}, "unknown": {"context", "session-flush"}}


def _no_options(name: str) -> bool:
    return name.startswith("adapters/") or name in NO_OPTIONS


def _params(test: str) -> list[object]:
    params = []
    for name in interface_executables():
        marks = []
        if name in SHOULD_PARSE[test]:
            marks = [UNPARSED]
        elif _no_options(name) and name != "hooks/pre-commit":
            # pre-commit fails outside a repository, so the null controls
            # catch it; the others exit 0 silently or as if invoked normally.
            marks = [pytest.mark.null_ok("a host entry point ignores options (A-034)")]
        params.append(pytest.param(name, marks=marks, id=name.replace("/", "-")))
    return params


@pytest.mark.parametrize("script", _params("help"))
def test_help(kb: KB, golden: Golden, script: str) -> None:
    result = kb.run(script, "--help", stdin="")
    golden.contract("result", f"exit {result.returncode}\n")
    # Help is static text with example file names (A-001), so it is pinned
    # without normalization, except entry points that print session context.
    out = kb.placeholder_instructions(result.out)
    golden.check("stdout", kb.norm(out) if _no_options(script) else out)
    golden.check("stderr", kb.norm_err(result.err))
    if not _no_options(script):
        assert result.returncode == 0
        assert "usage" in result.out.lower(), "help shows how to call the command"


@pytest.mark.parametrize("script", _params("unknown"))
def test_unknown_option(kb: KB, golden: Golden, script: str) -> None:
    result = kb.run(script, "--no-such-option", stdin="")
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(kb.placeholder_instructions(result.out)))
    golden.check("stderr", kb.norm_err(result.err))
    if not _no_options(script):
        assert result.returncode != 0
        assert result.err.strip(), "an unknown option is reported"
