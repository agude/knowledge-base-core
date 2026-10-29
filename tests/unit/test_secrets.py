"""Tests of the secrets check: its findings, the lifetime of its scan file, and its lack of network use."""

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from detect_secrets.core import scan

from kb import secrets

SECRET_LINE = 'password = "hunter2hunter2"'


class Blocked(BaseException):
    """Raised by a recording socket. It is not an Exception, so no handler can absorb it."""


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
