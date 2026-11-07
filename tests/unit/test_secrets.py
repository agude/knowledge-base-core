"""Tests of the secrets check: its findings, the lifetime of its scan file, and its lack of network use."""

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from detect_secrets.core import scan

from kb import secrets

SECRET_LINE = 'password = "hunter2hunter2"'


class Blocked(BaseException):
    """Raised by a recording socket. It is not an Exception, so no handler can absorb it."""


class Interrupted(BaseException):
    """Raised by a scanner to model interruption outside ordinary exception handling."""


def test_a_keyword_secret_is_found_on_its_line(tmp_path: Path) -> None:
    assert secrets.findings(tmp_path, f"Some prose.\n{SECRET_LINE}\n") == [("Secret Keyword", 2)]


def test_plain_prose_has_no_findings(tmp_path: Path) -> None:
    assert secrets.findings(tmp_path, "Resolver caches answers for an hour.\n") == []


def test_the_scan_file_is_deleted_after_a_clean_scan(tmp_path: Path) -> None:
    secrets.findings(tmp_path, "Plain.\n")
    assert list(tmp_path.iterdir()) == []


def test_the_scan_file_is_deleted_when_the_scan_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(filename: str) -> Iterator[object]:
        raise RuntimeError("scanner failed")

    monkeypatch.setattr(scan, "scan_file", broken)
    with pytest.raises(RuntimeError, match="scanner failed"):
        secrets.findings(tmp_path, "Plain.\n")
    assert list(tmp_path.iterdir()) == []


def test_the_scan_file_is_deleted_when_the_scanner_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(filename: str) -> Iterator[object]:
        raise Interrupted

    monkeypatch.setattr(scan, "scan_file", interrupted)
    with pytest.raises(Interrupted):
        secrets.findings(tmp_path, "Plain.\n")
    assert list(tmp_path.iterdir()) == []


def test_the_scan_file_is_written_in_the_directory_it_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def record(filename: str) -> Iterator[object]:
        seen.append(filename)
        return iter(())

    monkeypatch.setattr(scan, "scan_file", record)
    secrets.findings(tmp_path, "Plain.\n")
    assert len(seen) == 1
    assert Path(seen[0]).parent == tmp_path
    assert Path(seen[0]).name.startswith("scan-")
    assert seen[0].endswith(".md")


@pytest.mark.skipif(os.name == "nt", reason="POSIX umask behavior")
def test_the_scan_file_is_owner_only_with_a_group_readable_umask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modes: list[int] = []

    def inspect(filename: str) -> Iterator[object]:
        modes.append(Path(filename).stat().st_mode & 0o777)
        return iter(())

    monkeypatch.setattr(scan, "scan_file", inspect)
    previous = os.umask(0o022)
    try:
        secrets.findings(tmp_path, "Plain.\n")
    finally:
        os.umask(previous)

    assert modes == [0o600]


def test_a_scan_name_collision_preserves_the_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collision = tmp_path / "scan-01020304.md"
    collision.write_text("Keep this file.\n", encoding="utf-8")
    draws = iter([b"\x01\x02\x03\x04", b"\x05\x06\x07\x08"])
    monkeypatch.setattr(os, "urandom", lambda size: next(draws))

    assert secrets.findings(tmp_path, "Plain.\n") == []

    assert collision.read_text(encoding="utf-8") == "Keep this file.\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == [collision.name]


def test_the_scan_makes_no_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Load detect-secrets first. Its import loads ssl, which subclasses socket.socket.
    secrets.findings(tmp_path, "Warm up.\n")
    calls: list[str] = []

    def recording(name: str) -> object:
        def record(*args: object, **kwargs: object) -> None:
            calls.append(name)
            raise Blocked(name)

        return record

    monkeypatch.setattr(socket, "socket", recording("socket.socket"))
    monkeypatch.setattr(socket, "create_connection", recording("socket.create_connection"))
    assert secrets.findings(tmp_path, f"Prose.\n{SECRET_LINE}\n") == [("Secret Keyword", 2)]
    assert calls == []
