"""doctor: report format, exit codes, and installation findings.

doctor's tool probes (sort -z, sort -V, readlink -f, date, od, Bash version)
check the Bash runtime and are redesigned for Python (plan step 5). These
tests pin what survives the redesign: the line format, the summary, exit
codes, and the findings about the installation and content repository.
Lines from tool probes are filtered out of the goldens because they vary by
host.
"""

from __future__ import annotations

import re

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result

LINE = re.compile(
    r"^(PASS|WARN|FAIL) \[(retrieval|capture|curation|sync|development|adapters)\] \S.*$"
)
SUMMARY_OK = re.compile(r"^Doctor completed with \d+ warning\(s\)\.$")
SUMMARY_FAIL = re.compile(r"^Doctor found \d+ required failure\(s\) and \d+ warning\(s\)\.$")
# Tool probes: their presence and wording depend on the host.
PROBE = re.compile(
    r"is available|supports|can parse|missing command|SHA-256|tooling root is executable"
)


def _findings(kb: KB, result: Result, areas: tuple[str, ...]) -> str:
    """Report lines for the given areas, without host-dependent tool probes."""
    lines = []
    for line in result.out.splitlines():
        match = LINE.match(line)
        if match and match.group(2) in areas and not PROBE.search(line):
            lines.append(line)
    return kb.norm("\n".join(lines) + "\n")


def _assert_format(result: Result) -> None:
    lines = result.out.splitlines()
    assert lines, "doctor printed nothing"
    for line in lines[:-1] if result.returncode == 0 else lines:
        assert LINE.match(line), line
    if result.returncode == 0:
        assert SUMMARY_OK.match(lines[-1]), lines[-1]
        assert result.err == ""
    else:
        assert SUMMARY_FAIL.match(result.err.strip()), result.err


def _fake_node(kb: KB, version: str) -> None:
    node = kb.layout.bin / "node"
    node.write_text(
        f'#!/bin/sh\n[ "$1" = "-p" ] || exit 1\nprintf "{version}\\n"\n', encoding="utf-8"
    )
    node.chmod(0o755)


@pytest.fixture
def sessions(kb: KB) -> KB:
    kb.layout.sessions.mkdir(mode=0o700, parents=True)
    return kb


@pytest.mark.bats("doctor.bats", "doctor reports a passing retrieval and capture setup")
def test_doctor_passing_setup(sessions: KB, golden: Golden) -> None:
    result = sessions.run("doctor", "--require", "retrieval", "--require", "capture")
    assert result.returncode == 0
    _assert_format(result)
    golden.check("capture", _findings(sessions, result, ("capture",)))
    golden.check("curation", _findings(sessions, result, ("curation",)))
    # The capture smoke test leaves nothing behind.
    pending = sessions.layout.content / "observations" / "pending"
    assert list(pending.iterdir()) == []
    assert list(sessions.layout.sessions.iterdir()) == []


@pytest.mark.bats("doctor.bats", "doctor checks the installed adapters when required")
def test_doctor_adapters(sessions: KB, golden: Golden) -> None:
    _fake_node(sessions, "22.19.0")
    result = sessions.run("doctor", "--require", "adapters")
    assert result.returncode == 0
    _assert_format(result)
    golden.check("adapters", _findings(sessions, result, ("adapters",)))


@pytest.mark.bats("doctor.bats", "doctor rejects Node.js 22.18 for the Pi adapter")
@pytest.mark.bats("doctor.bats", "doctor accepts newer supported Node.js versions")
@pytest.mark.bats("doctor.bats", "doctor rejects malformed Node.js version output")
@pytest.mark.parametrize("version", ["22.18.0", "23.0.0", "not-a-version"])
def test_doctor_node_versions(sessions: KB, golden: Golden, version: str) -> None:
    _fake_node(sessions, version)
    result = sessions.run("doctor", "--require", "adapters")
    _assert_format(result)
    golden.contract("result", f"exit {result.returncode}\n")
    node_lines = [line for line in result.out.splitlines() if "Node.js" in line]
    golden.check("node", "\n".join(node_lines) + "\n")


def test_doctor_missing_node_is_a_warning(sessions: KB, golden: Golden) -> None:
    result = sessions.run("doctor")
    assert result.returncode == 0
    lines = [line for line in result.out.splitlines() if "[adapters]" in line and "node" in line]
    golden.check("node", "\n".join(lines) + "\n")


@pytest.mark.bats("doctor.bats", "doctor makes a requested missing content root fatal")
def test_doctor_missing_content_root(sessions: KB, golden: Golden) -> None:
    missing = sessions.layout.root / "missing"
    result = sessions.run("doctor", "--require", "curation", env={"KB_CONTENT_DIR": str(missing)})
    assert result.returncode == 1
    _assert_format(result)
    golden.check("curation", _findings(sessions, result, ("curation",)))


@pytest.mark.bats("doctor.bats", "doctor uses warnings for unrequested installation findings")
def test_doctor_unrequested_findings_warn(sessions: KB, golden: Golden) -> None:
    result = sessions.run("doctor", "--require", "retrieval")
    assert result.returncode == 0
    _assert_format(result)
    golden.check("curation", _findings(sessions, result, ("curation",)))


def test_doctor_installed_curation(sessions: KB, golden: Golden) -> None:
    sessions.run("install")
    result = sessions.run("doctor", "--require", "curation")
    assert result.returncode == 0
    _assert_format(result)
    golden.check("curation", _findings(sessions, result, ("curation",)))


def test_doctor_dirty_content_tree(sessions: KB, golden: Golden) -> None:
    sessions.create_article("a.md", "# A")
    result = sessions.run("doctor")
    golden.check("curation", _findings(sessions, result, ("curation",)))


@pytest.mark.parametrize("state", ["absent", "mode-755"])
def test_doctor_session_directory(kb: KB, golden: Golden, state: str) -> None:
    if state == "mode-755":
        kb.layout.sessions.mkdir(mode=0o755, parents=True)
        kb.layout.sessions.chmod(0o755)
    result = kb.run("doctor", "--require", "capture")
    _assert_format(result)
    golden.contract("result", f"exit {result.returncode}\n")
    lines = [line for line in result.out.splitlines() if "session directory" in line]
    golden.check("session", kb.norm("\n".join(lines) + "\n"))


@pytest.mark.parametrize("args", [["--require", "bogus"], ["--bogus"], ["--require"]])
def test_doctor_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    result = kb.run("doctor", *args)
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
