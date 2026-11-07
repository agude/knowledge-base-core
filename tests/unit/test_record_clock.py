"""Observe and gap use one UTC clock for metadata and generated names."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import cli, model

from .test_hook import ARTICLE, git, repo


@pytest.fixture
def content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = repo(tmp_path / "content", {"knowledge/seed.md": ARTICLE.encode()})
    git(root, "config", "user.name", "Clock Test")
    git(root, "config", "user.email", "clock@example.invalid")
    monkeypatch.setenv("KB_CONTENT", str(root))
    monkeypatch.setenv("KB_TODAY", "2026-10-26")
    monkeypatch.chdir(root)
    return root


def record(command: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    arguments = [command, "--title", "Clock", "--body", "Use the shared clock."]
    if command == "gap":
        arguments.extend(["--context", "future/area"])
    code = cli.main(arguments)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.parametrize("command", ["observe", "gap"])
def test_fixed_clock_controls_created_timestamp_and_filename(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    monkeypatch.setenv("KB_NOW", "2024-02-03T04:05:06+02:00")

    code, out, err = record(command, capsys)

    assert (code, err) == (0, "")
    relative = out.removeprefix("Wrote: ").strip()
    assert Path(relative).name.startswith("20240203T020506-")
    document = model.parse(relative, (content / relative).read_text(encoding="utf-8"))
    assert document.scalar("created") == "2024-02-03T02:05:06Z"
    assert git(content, "show", f"HEAD:{relative}") == (content / relative).read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("command", ["observe", "gap"])
def test_invalid_fixed_clock_is_a_command_error_before_publication(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    monkeypatch.setenv("KB_NOW", "not-a-time")
    head = git(content, "rev-parse", "HEAD")
    before = git(content, "write-tree")

    code, out, err = record(command, capsys)

    assert (code, out) == (1, "")
    assert err.startswith(f"{command}: ")
    assert "KB_NOW must be a time-zone-aware ISO timestamp" in err
    assert git(content, "rev-parse", "HEAD") == head
    assert git(content, "write-tree") == before
    assert git(content, "status", "--porcelain=v1") == ""
    assert not (content / ".git/kb-tmp").exists()


@pytest.mark.parametrize("command", ["observe", "gap"])
def test_unset_fixed_clock_uses_current_utc_time(
    content: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    monkeypatch.delenv("KB_NOW", raising=False)
    before = datetime.now(UTC).replace(microsecond=0)

    code, out, err = record(command, capsys)

    after = datetime.now(UTC)
    assert (code, err) == (0, "")
    relative = out.removeprefix("Wrote: ").strip()
    created = model.parse(relative, (content / relative).read_text(encoding="utf-8")).scalar(
        "created"
    )
    assert created is not None
    when = datetime.fromisoformat(created)
    assert before <= when <= after
    assert Path(relative).name.startswith(when.strftime("%Y%m%dT%H%M%S-"))
