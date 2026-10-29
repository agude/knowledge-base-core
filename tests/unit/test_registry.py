"""Tests for the command registry."""

import pytest

from kb import registry
from kb.errors import KbError
from kb.registry import Command


def test_find_returns_the_registered_command(monkeypatch: pytest.MonkeyPatch) -> None:
    first = Command(name="first", summary="First.", run=lambda args: 0)
    second = Command(name="second", summary="Second.", run=lambda args: 1)
    monkeypatch.setattr(registry, "COMMANDS", (first, second))
    assert registry.find("second") is second


def test_find_rejects_an_unregistered_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        registry, "COMMANDS", (Command(name="first", summary="First.", run=lambda args: 0),)
    )
    with pytest.raises(KbError, match=r"^Unknown command: nosuch$"):
        registry.find("nosuch")
