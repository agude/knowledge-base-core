"""Tests for `python -m kb`."""

import runpy
import sys

import pytest


def test_module_entry_point_runs_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["kb", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("kb", run_name="__main__")
    assert exit_info.value.code == 0
