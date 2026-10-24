"""--help and unknown options for every executable in the interface surface.

The parameters come from the bash tree's executables, so a new executable
without goldens fails here until its help and error output are pinned.
"""

from __future__ import annotations

import pytest

from kbtest.golden import Golden
from kbtest.impl import interface_executables
from kbtest.runner import KB

# Entry points that do not parse options (A-034). Hooks read their input from
# stdin; session-context takes no arguments; session-flush reads its first
# argument as a buffer path.
NO_OPTIONS = {
    "hooks/pre-commit",
    "session-context",
    "session-flush",
    "context",
}


def _no_options(name: str) -> bool:
    return name.startswith("adapters/") or name in NO_OPTIONS


def _params() -> list[object]:
    params = []
    for name in interface_executables():
        marks = []
        if _no_options(name):
            marks = [pytest.mark.audit("A-034")]
            # pre-commit fails outside a repository, so the null controls
            # catch it; the others exit 0 silently or as if invoked normally.
            if name != "hooks/pre-commit":
                marks.append(pytest.mark.null_ok("this entry point does not parse options (A-034)"))
        params.append(pytest.param(name, marks=marks, id=name.replace("/", "-")))
    return params


@pytest.mark.parametrize("script", _params())
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


@pytest.mark.parametrize("script", _params())
def test_unknown_option(kb: KB, golden: Golden, script: str) -> None:
    result = kb.run(script, "--no-such-option", stdin="")
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(kb.placeholder_instructions(result.out)))
    golden.check("stderr", kb.norm_err(result.err))
    if not _no_options(script):
        assert result.returncode != 0
        assert result.err.strip(), "an unknown option is reported"
