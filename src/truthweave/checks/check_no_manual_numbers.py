from __future__ import annotations

import re
from pathlib import Path

from truthweave.checks.models import Issue


def check(tex_path: Path, mode: str, paper_id: str | None) -> list[Issue]:
    if not tex_path.exists():
        fix = "Create the paper main.tex or run truthweave create-paper <paper_id>."
        recheck = f"uv run truthweave check --mode {mode}"
        if paper_id:
            recheck += f" --paper {paper_id}"
        return [
            Issue(
                category="PAPER_NUMBERS",
                severity="FAIL" if mode == "ci" else "WARN",
                message=f"Missing tex file: {tex_path}",
                fix=fix,
                recheck=recheck,
                paths=[str(tex_path)],
            )
        ]

    decimal_pattern = re.compile(r"\b\d+\.\d+\b")
    percent_pattern = re.compile(r"\b\d+%")

    violations = []
    for idx, raw_line in enumerate(tex_path.read_text().splitlines(), start=1):
        if "truthweave-allow-number" in raw_line:
            continue
        line = raw_line.split("%", 1)[0]
        if decimal_pattern.search(line) or percent_pattern.search(line):
            violations.append(f"line {idx}: {raw_line.strip()}")

    if violations:
        fix = (
            "Replace inline numbers with TeX macros from auto/variables.tex or "
            "append `% truthweave-allow-number` to allowlist."
        )
        recheck = f"uv run truthweave check --mode {mode}"
        if paper_id:
            recheck += f" --paper {paper_id}"
        return [
            Issue(
                category="PAPER_NUMBERS",
                severity="FAIL" if mode == "ci" else "WARN",
                message=f"Manual numbers detected in {tex_path}",
                fix=fix,
                recheck=recheck,
                paths=[str(tex_path)],
            )
        ]
    return []
