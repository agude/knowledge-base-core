"""Self-tests for the harness. They never run an implementation's executables."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kbtest import bats_map, corpus
from kbtest import env as envmod
from kbtest import impl as implmod
from kbtest.golden import Golden
from kbtest.leaks import find_leaks
from kbtest.normalize import NormalizationError, Normalizer
from kbtest.runner import KB

pytestmark = pytest.mark.harness


# Environment


def test_base_env_inherits_nothing(kb: KB, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_OBSERVE", "1")
    monkeypatch.setenv("PYTHONPATH", "/hostile")
    env = envmod.base_env(kb.layout, kb.layout.root)
    assert "KNOWLEDGE_OBSERVE" not in env
    assert "PYTHONPATH" not in env


def test_path_puts_selected_tools_first_and_excludes_venv(kb: KB) -> None:
    env = envmod.base_env(kb.layout, kb.layout.root)
    entries = env["PATH"].split(":")
    assert entries[0] == str(kb.layout.bin)
    assert not any(".venv" in entry for entry in entries)
    for name in ("bash", "python3", "git", "jq", "logger"):
        assert (kb.layout.bin / name).exists(), name


def test_confined_variables_point_inside_root(kb: KB) -> None:
    env = envmod.base_env(kb.layout, kb.layout.root)
    envmod.assert_confined(env, kb.layout.root)


@pytest.mark.parametrize("name", envmod.CONFINED)
def test_confinement_rejects_escape(kb: KB, name: str) -> None:
    env = envmod.base_env(kb.layout, kb.layout.root)
    env[name] = str(Path.home())
    with pytest.raises(envmod.HarnessError, match=name):
        envmod.assert_confined(env, kb.layout.root)


def test_overrides_are_confined_too(kb: KB) -> None:
    tree = implmod.Impl("bash", implmod.BASH_SCRIPTS, implmod.REPO)
    with pytest.raises(envmod.HarnessError, match="SESSION_DIR"):
        kb.env(tree, {"SESSION_DIR": "/tmp"})


def test_override_none_unsets(kb: KB) -> None:
    tree = implmod.Impl("bash", implmod.BASH_SCRIPTS, implmod.REPO)
    assert "SESSION_DIR" not in kb.env(tree, {"SESSION_DIR": None})


def test_selected_python_is_standard_library_only() -> None:
    selected = envmod.tools().python
    probe = subprocess.run(
        [str(selected), "-I", "-c", "import pytest"], capture_output=True, check=False
    )
    assert probe.returncode != 0


def test_venv_python_is_rejected() -> None:
    # The interpreter running pytest can import pytest.
    with pytest.raises(envmod.HarnessError, match="pytest is importable"):
        envmod._check_python(Path(sys.executable))


def test_no_jq_hides_jq(no_jq: KB) -> None:
    tree = implmod.Impl("bash", implmod.BASH_SCRIPTS, implmod.REPO)
    env = no_jq.env(tree)
    probe = subprocess.run(["/bin/sh", "-c", "command -v jq"], env=env, check=False)
    assert probe.returncode != 0
    present = subprocess.run(
        ["/bin/sh", "-c", "command -v git && command -v awk"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert present.returncode == 0


def test_content_repo_is_initialized(kb: KB) -> None:
    content = kb.layout.content
    for sub in ("knowledge", "observations/pending", "questions/open", "sources"):
        assert (content / sub).is_dir()
    assert len(kb.commits()) == 1


def test_git_commits_are_deterministic(kb: KB, tmp_path_factory: pytest.TempPathFactory) -> None:
    other = KB(
        layout=envmod.Layout.under(tmp_path_factory.mktemp("other")),
        resolve_impl=kb.resolve_impl,
        default_impl=kb.default_impl,
        session_prefix=kb.session_prefix,
    )
    other.setup()
    assert kb.commits() == other.commits()


def test_session_ids_carry_prefix(kb: KB) -> None:
    first, second = kb.session_id(), kb.session_id()
    assert first.startswith(kb.session_prefix)
    assert first != second


# Running


def _fake_python_tree(root: Path, script: str, body: str) -> implmod.Impl:
    scripts = root / "python"
    path = scripts / script
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return implmod.Impl("python", scripts, root)


def test_python_traceback_fails_the_test(kb: KB, tmp_path: Path) -> None:
    tree = _fake_python_tree(
        tmp_path / "fake",
        "status",
        "#!/bin/sh\necho 'Traceback (most recent call last):' >&2\nexit 1\n",
    )
    kb.resolve_impl = lambda name: tree
    with pytest.raises(pytest.fail.Exception, match="uncaught exception"):
        kb.run("status")


def test_unported_python_script_skips(kb: KB, tmp_path: Path) -> None:
    tree = _fake_python_tree(tmp_path / "fake", "status", "#!/bin/sh\nexit 0\n")
    kb.resolve_impl = lambda name: tree
    with pytest.raises(pytest.skip.Exception, match="not ported"):
        kb.run("search", "x")


def test_run_records_invocations(kb: KB, tmp_path: Path) -> None:
    tree = _fake_python_tree(tmp_path / "fake", "status", "#!/bin/sh\nexit 0\n")
    kb.resolve_impl = lambda name: tree
    kb.run("status")
    assert kb.invocations == [("python", "status")]


# Implementations


def test_interface_executables_cover_scripts_and_adapters() -> None:
    names = implmod.interface_executables()
    assert "search" in names
    assert "hooks/pre-commit" in names
    assert "adapters/claude/pretool-allow" in names
    assert "adapters/codex/session-end" in names
    assert "_lib.sh" not in names
    assert not any(name.startswith("adapters/pi") for name in names)


@pytest.mark.parametrize("code", [0, 1])
def test_null_tree_exits_silently(tmp_path: Path, code: int) -> None:
    scripts = implmod.build_null_tree(tmp_path, code)
    assert sorted(
        p.relative_to(scripts).as_posix() for p in scripts.rglob("*") if p.is_file()
    ) == sorted(implmod.interface_executables())
    result = subprocess.run([str(scripts / "search"), "x"], capture_output=True, check=False)
    assert (result.returncode, result.stdout, result.stderr) == (code, b"", b"")


def test_scripts_dir_override_keeps_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KB_IMPL", "bash")
    monkeypatch.setenv("KB_SCRIPTS_DIR", str(tmp_path))
    tree = implmod.resolve("bash", tmp_path)
    assert (tree.name, tree.scripts_dir) == ("bash", tmp_path.resolve())


# Normalizer


def test_observation_names_get_stable_labels() -> None:
    normalize = Normalizer()
    text = "20261023T101112-0a1b2c3d.md\n20261023T101113-ffffffff.md\n20261023T101112-0a1b2c3d.md\n"
    assert normalize(text) == "<OBS-1>.md\n<OBS-2>.md\n<OBS-1>.md\n"


@pytest.mark.parametrize(
    "name",
    ["20261023T101112-0A1B2C3D.md", "20261023T101112-0a1b.md", "20261023T101112-0a1b2c3dz.md"],
)
def test_observation_name_outside_contract_is_rejected(name: str) -> None:
    with pytest.raises(NormalizationError, match="does not match"):
        Normalizer()(name)


def test_batch_ids_get_stable_labels() -> None:
    normalize = Normalizer()
    text = "20261024T014331-1510271.tsv 20261024T014332-99.tsv.meta 20261024T014331-1510271.tsv"
    assert normalize(text) == "<BATCH-1>.tsv <BATCH-2>.tsv.meta <BATCH-1>.tsv"


def test_created_and_buffer_timestamps() -> None:
    normalize = Normalizer()
    text = (
        "created: 2026-10-23T10:11:12Z\n"
        '{"role":"user","timestamp":1792792078}\n'
        '{"role":"user","timestamp":1792792078.565548}\n'
    )
    assert normalize(text) == (
        "created: <TIMESTAMP>\n"
        '{"role":"user","timestamp":<EPOCH>}\n'
        '{"role":"user","timestamp":<EPOCH>}\n'
    )


def test_paths_longest_first(tmp_path: Path) -> None:
    normalize = Normalizer()
    normalize.add_path(tmp_path, "<ROOT>")
    normalize.add_path(tmp_path / "content", "<CONTENT>")
    assert normalize(f"{tmp_path / 'content'}/x {tmp_path}/y") == "<CONTENT>/x <ROOT>/y"


def test_commit_prefixes() -> None:
    full = "0123456789abcdef0123456789abcdef01234567"
    normalize = Normalizer(commits=[full])
    assert (
        normalize(f"{full[:7]} and {full} and deadbeef") == "<COMMIT-1> and <COMMIT-1> and deadbeef"
    )


def test_stderr_tool_messages() -> None:
    normalize = Normalizer()
    text = "fatal: not a git repository\njq: error: syntax\nError: our own message\n"
    assert normalize.stderr(text) == "<git fatal>\n<jq message>\nError: our own message\n"


# Golden files


def test_golden_missing_fails_without_writing(tmp_path: Path) -> None:
    golden = Golden(tmp_path / "g", update=False)
    with pytest.raises(AssertionError, match="missing golden file"):
        golden.check("out", "text")
    assert not (tmp_path / "g").exists()


def test_golden_mismatch_fails(tmp_path: Path) -> None:
    Golden(tmp_path, update=True).check("out", "one\n")
    with pytest.raises(AssertionError, match="differs"):
        Golden(tmp_path, update=False).check("out", "two\n")
    Golden(tmp_path, update=False).check("out", "one\n")


# Leak detection


def test_leaks_by_prefix(tmp_path: Path) -> None:
    (tmp_path / "session-pytest-abc-1.jsonl").touch()
    (tmp_path / "session-live.jsonl").touch()
    assert [p.name for p in find_leaks(tmp_path, "pytest-abc-", strict=False)] == [
        "session-pytest-abc-1.jsonl"
    ]
    assert len(find_leaks(tmp_path, "pytest-abc-", strict=True)) == 2


def test_leaks_missing_directory(tmp_path: Path) -> None:
    assert find_leaks(tmp_path / "absent", "x", strict=True) == []


def test_real_session_dir_follows_xdg_runtime_dir() -> None:
    from kbtest.leaks import real_session_dir

    path = real_session_dir({"XDG_RUNTIME_DIR": "/run/user/1"})
    assert path == Path(f"/run/user/1/knowledge-sessions-{os.getuid()}")
    assert real_session_dir({}) == Path(f"/tmp/knowledge-sessions-{os.getuid()}")


# Bats mapping


def _mapping_sources(
    root: Path, test_source: str, ported: str, not_ported: str
) -> bats_map.Sources:
    bats_dir = root / "bats"
    bats_dir.mkdir()
    (bats_dir / "demo.bats").write_text(
        '@test "first behavior" {\n    true\n}\n\n@test "second behavior" {\n    true\n}\n',
        encoding="utf-8",
    )
    test_dir = root / "py"
    test_dir.mkdir()
    (test_dir / "test_demo.py").write_text(test_source, encoding="utf-8")
    (root / "ported.txt").write_text(ported, encoding="utf-8")
    (root / "NOT_PORTED.md").write_text(not_ported, encoding="utf-8")
    return bats_map.Sources(bats_dir, root / "ported.txt", root / "NOT_PORTED.md", test_dir)


_DEMO_TEST = """
import pytest

@pytest.mark.bats("demo.bats", "first behavior")
def test_first():
    pass
"""


def test_bats_mapping_reports_unmapped_test(tmp_path: Path) -> None:
    sources = _mapping_sources(tmp_path, _DEMO_TEST, "demo.bats\n", "")
    assert bats_map.problems(sources) == [
        "demo.bats: @test 'second behavior' has no pytest test and no NOT_PORTED entry"
    ]


def test_bats_mapping_accepts_not_ported_row(tmp_path: Path) -> None:
    row = "| `demo.bats` | second behavior | Asserts the od fallback. |\n"
    sources = _mapping_sources(tmp_path, _DEMO_TEST, "demo.bats\n", row)
    assert bats_map.problems(sources) == []


def test_bats_mapping_reports_unknown_names(tmp_path: Path) -> None:
    source = _DEMO_TEST + '\n@pytest.mark.bats("demo.bats", "renamed")\ndef test_x():\n    pass\n'
    row = "| `demo.bats` | gone | Reason. |\n"
    sources = _mapping_sources(tmp_path, source, "", row)
    assert bats_map.problems(sources) == [
        "demo.bats has no @test 'gone'",
        "demo.bats has no @test 'renamed'",
    ]


def test_bats_mapping_requires_reason(tmp_path: Path) -> None:
    row = "| `demo.bats` | second behavior |  |\n"
    sources = _mapping_sources(tmp_path, _DEMO_TEST, "demo.bats\n", row)
    assert "has no reason" in bats_map.problems(sources)[0]


def test_bats_mapping() -> None:
    """Every @test in a completed bats file maps to pytest or NOT_PORTED.md."""
    tests_py = Path(__file__).parent
    sources = bats_map.Sources(
        bats_dir=tests_py.parent,
        ported_list=tests_py / "bats_ported.txt",
        not_ported=tests_py / "NOT_PORTED.md",
        test_dir=tests_py,
    )
    assert bats_map.problems(sources) == []


def test_transcript_renders_runs(kb: KB, tmp_path: Path) -> None:
    tree = _fake_python_tree(
        tmp_path / "fake", "status", "#!/bin/sh\necho out; echo err >&2; exit 3\n"
    )
    kb.resolve_impl = lambda name: tree
    text = kb.transcript(kb.run("status", "--flag"))
    assert text == "$ status --flag\nexit 3\n--- stdout\nout\n--- stderr\nerr\n"


# Golden tiers


def test_reference_mode_records_without_failing(tmp_path: Path) -> None:
    from kbtest.golden import ReferenceReport

    Golden(tmp_path, update=True).check("out", "bash output\n")
    report = ReferenceReport()
    golden = Golden(tmp_path, update=False, mode="reference", report=report, nodeid="t::x")
    golden.check("out", "python output\n")
    assert len(report.entries) == 1
    assert report.entries[0][0] == "t::x [out]"
    assert "-bash output" in report.render()


def test_contract_fails_in_reference_mode(tmp_path: Path) -> None:
    Golden(tmp_path, update=True).contract("format", "a: 1\n")
    golden = Golden(tmp_path, update=False, mode="reference")
    with pytest.raises(AssertionError, match="contract golden"):
        golden.contract("format", "a: 2\n")


def test_unknown_golden_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="golden mode"):
        Golden(tmp_path, update=False, mode="loose")


# Surface inventory


def _surface_rows(text: str) -> dict[str, list[tuple[str, list[str]]]]:
    sections: dict[str, list[tuple[str, list[str]]]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current and line.startswith("| ") and not line.startswith(("| Entry", "|---")):
            entry, tests = line[2:].rsplit(" | ", 1)
            refs = [ref.strip().strip("`") for ref in tests.rstrip(" |").split(",") if ref.strip()]
            sections[current].append((entry, refs))
    return sections


def _test_exists(ref: str) -> bool:
    import ast

    module, _, function = ref.partition("::")
    path = Path(__file__).parent / module
    if not path.is_file() or not function:
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(isinstance(node, ast.FunctionDef) and node.name == function for node in tree.body)


def test_surface_inventory() -> None:
    """Every executable has inventory rows, and every row names existing tests."""
    text = (Path(__file__).parent / "SURFACE.md").read_text(encoding="utf-8")
    sections = _surface_rows(text)
    problems = []
    executables = set(implmod.interface_executables())
    for name in sorted(executables):
        if not sections.get(name):
            problems.append(f"{name}: no rows")
    for name, rows in sections.items():
        if name not in executables:
            problems.append(f"{name}: not an executable")
        for entry, refs in rows:
            if not refs:
                problems.append(f"{name} {entry}: no tests")
            problems += [f"{name} {entry}: no test {ref}" for ref in refs if not _test_exists(ref)]
    assert problems == []


def test_surface_inventory_rejects_unknown_tests(tmp_path: Path) -> None:
    rows = _surface_rows(
        "## demo\n\n| Entry | Tests |\n|---|---|\n| `--x` | `test_harness.py::nope` |\n"
    )
    assert rows == {"demo": [("`--x`", ["test_harness.py::nope"])]}
    assert not _test_exists("test_harness.py::nope")
    assert _test_exists("test_harness.py::test_surface_inventory")


def _digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_corpus_is_deterministic(tmp_path: Path) -> None:
    corpus.generate(tmp_path / "a", scale=1, seed=7)
    corpus.generate(tmp_path / "b", scale=1, seed=7)
    corpus.generate(tmp_path / "c", scale=1, seed=8)
    first = _digest(tmp_path / "a")
    assert first == _digest(tmp_path / "b")
    assert first != _digest(tmp_path / "c")
    articles = [name for name in first if name.startswith("knowledge/")]
    archived = [name for name in first if name.startswith("observations/archived/")]
    assert (len(articles), len(archived)) == (corpus.COUNTS["article"], corpus.COUNTS["archived"])


def test_bash_matches_frozen_tag() -> None:
    """After the freeze, scripts/ changes only by moving the bash-frozen tag."""
    if not implmod.frozen_tag_exists():
        pytest.skip("bash is not frozen yet")
    result = subprocess.run(
        ["git", "diff", "--stat", implmod.FROZEN_TAG, "--", "scripts/"],
        cwd=implmod.REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "", f"scripts/ differs from {implmod.FROZEN_TAG}:\n{result.stdout}"


def test_only_the_selected_python_is_visible(kb: KB) -> None:
    """The preamble's interpreter search finds KB_PYTHON and nothing else."""
    tree = kb.resolve_impl(kb.default_impl)
    env = kb.env(tree)
    found = []
    for directory in env["PATH"].split(":"):
        for minor in range(11, 21):
            path = Path(directory) / f"python3.{minor}"
            if path.exists():
                found.append(path)
    assert found == [kb.layout.bin / f"python3.{envmod.python_minor()}"]
    assert env["KB_PYTHON_DIRS"] == ""
    assert (kb.layout.bin / "python3").resolve() == envmod.tools().python.resolve()


def test_git_usage_dump_is_normalized() -> None:
    """git's usage text changes between releases; it reads as one placeholder."""
    text = (
        "fatal: not a git repository\nusage: git diff --no-index [<options>] <path> <path>\n\n"
        "Diff output format options\n    -p, --patch           generate patch\n\n"
        "pre-commit: could not inspect staged link-target paths.\n"
    )
    assert Normalizer().stderr(text) == (
        "<git fatal>\n<git usage>\npre-commit: could not inspect staged link-target paths.\n"
    )
