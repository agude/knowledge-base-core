"""Fixtures for the black-box characterization suite.

KB_IMPL selects the implementation (bash, python, null0, null1). See
tests/py/README.md.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kbtest import env as envmod
from kbtest import impl as implmod
from kbtest.golden import Golden, directory_for
from kbtest.leaks import find_leaks, real_session_dir
from kbtest.runner import KB


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        help="Write golden files from actual output instead of comparing.",
    )


def pytest_report_header(config: pytest.Config) -> list[str]:
    tools = envmod.tools()
    return [
        f"KB_IMPL: {implmod.selected_name()}",
        f"bash: {tools.bash}  python3: {tools.python}  jq: {tools.jq}",
        f"locale: {envmod.utf8_locale()}",
    ]


@pytest.fixture(scope="session")
def session_prefix() -> str:
    """Prefix for every session ID the suite uses, unique per run."""
    return f"pytest-{uuid.uuid4().hex[:12]}-"


@pytest.fixture(scope="session", autouse=True)
def leak_check(session_prefix: str) -> Iterator[None]:
    """After the suite, fail if test files appeared in the real session directory."""
    yield
    strict = os.environ.get("CI") == "true"
    directory = real_session_dir()
    leaks = find_leaks(directory, session_prefix, strict=strict)
    if leaks:
        names = ", ".join(path.name for path in leaks)
        pytest.fail(f"files leaked into the real session directory {directory}: {names}")


@pytest.fixture(scope="session")
def impls() -> Iterator[dict[str, implmod.Impl]]:
    """Cache of implementation trees, built on first use."""
    cache: dict[str, implmod.Impl] = {}
    yield cache
    for tree in cache.values():
        if tree.name == "bash" and tree.scripts_dir != implmod.BASH_SCRIPTS:
            implmod.remove_worktree(tree.kb_root)


@pytest.fixture(scope="session")
def _impl_scratch(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("impls")


@pytest.fixture(scope="session")
def _mirror_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("sysbin")


@pytest.fixture
def kb(
    tmp_path: Path,
    impls: dict[str, implmod.Impl],
    _impl_scratch: Path,
    session_prefix: str,
) -> KB:
    """A fresh content repository and a runner for the selected implementation."""

    def resolve(name: str) -> implmod.Impl:
        if name not in impls:
            impls[name] = implmod.resolve(name, _impl_scratch)
        return impls[name]

    fixture = KB(
        layout=envmod.Layout.under(tmp_path),
        resolve_impl=resolve,
        default_impl=implmod.selected_name(),
        session_prefix=session_prefix,
    )
    fixture.setup()
    return fixture


@pytest.fixture
def without_tools(kb: KB, _mirror_root: Path) -> Callable[..., KB]:
    """Return a function that removes the named tools from PATH for kb."""

    def remove(*names: str) -> KB:
        kb.without_tools(frozenset(names), _mirror_root)
        return kb

    return remove


@pytest.fixture
def no_jq(without_tools: Callable[..., KB]) -> KB:
    """The kb fixture with jq absent. jq is optional in production."""
    return without_tools("jq")


@pytest.fixture
def hooked(kb: KB) -> KB:
    """The kb fixture with the implementation's pre-commit hook installed."""
    tree = kb.resolve_impl(kb.default_impl)
    hooks = kb.layout.content / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").symlink_to(tree.executable("hooks/pre-commit"))
    # The hook stamps `updated:` with the real UTC date.
    kb.normalizer.extra[datetime.now(UTC).strftime("%Y-%m-%d")] = "<TODAY>"
    return kb


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    module = Path(request.node.path).stem
    return Golden(
        directory_for(module, request.node.name),
        update=request.config.getoption("--update-golden"),
    )


# Null-control reporting. tests/py/nullcheck.py sets KB_NULL_REPORT and reads
# one JSON line per test.


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    outcome = yield
    report_path = os.environ.get("KB_NULL_REPORT")
    if not report_path:
        return
    report = outcome.get_result()
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        record = {
            "nodeid": report.nodeid,
            "outcome": report.outcome,
            "null_ok": item.get_closest_marker("null_ok") is not None,
        }
        with Path(report_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
