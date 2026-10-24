"""Markers that depend on the implementation under test."""

from __future__ import annotations

import pytest

from kbtest import impl as implmod


def xfail_bash(reason: str, *, strict: bool = True) -> pytest.MarkDecorator:
    """Expect failure under bash only: the audit decided bash's behavior is wrong.

    strict=True for a deterministic difference, so a bash that starts to pass
    is noticed. Every other implementation, the null controls included, runs
    the test normally.
    """
    return pytest.mark.xfail(implmod.selected_name() == "bash", reason=reason, strict=strict)
