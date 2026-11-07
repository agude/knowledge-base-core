"""Tests for safe resolution of fixed writable content directories."""

import sys
from pathlib import Path

import pytest

from kb.content_paths import fixed_directory
from kb.errors import KbError


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")
@pytest.mark.parametrize("target_kind", ["internal", "external"])
def test_fixed_directory_rejects_symlinked_ancestors_before_creating(
    tmp_path: Path, target_kind: str
) -> None:
    root = tmp_path / "content"
    root.mkdir()
    target = root / "safe-area" if target_kind == "internal" else tmp_path / "external"
    (target / "pending").mkdir(parents=True)
    marker = target / "pending" / "keep.md"
    marker.write_text("keep", encoding="utf-8")
    observations = root / "observations"
    observations.symlink_to(target, target_is_directory=True)

    with pytest.raises(KbError, match="observe: content directory is a symlink"):
        fixed_directory(root, "observations/pending/new", command="observe", create=True)

    assert observations.is_symlink()
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (target / "pending" / "new").exists()
