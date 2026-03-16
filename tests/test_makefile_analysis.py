from __future__ import annotations

from pathlib import Path


def test_make_analysis_target_exists() -> None:
    content = Path("Makefile").read_text()
    assert "analysis:" in content
    assert "truthweave.analysis." in content
