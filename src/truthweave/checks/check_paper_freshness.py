from __future__ import annotations

import json
import re
from pathlib import Path

from truthweave.checks.models import Issue
from truthweave.papers import load_paper_config
from truthweave.utils import sha256_file


def _extract_defined_metric_macros(variables_path: Path) -> set[str]:
    if not variables_path.exists():
        return set()
    pattern = re.compile(r"\\newcommand\{\\(Metric[A-Za-z0-9]+)\}\{")
    return set(pattern.findall(variables_path.read_text()))


def _extract_used_metric_macros(tex_path: Path) -> set[str]:
    if not tex_path.exists():
        return set()
    pattern = re.compile(r"\\(Metric[A-Za-z0-9]+)\b")
    return set(pattern.findall(tex_path.read_text()))


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    config = load_paper_config(paper_dir / "truthweave.yml")
    auto_dir = paper_dir / config["paths"]["auto_dir"]
    manifest_path = auto_dir / "MANIFEST.json"
    if not manifest_path.exists():
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        return [
            Issue(
                category="FRESHNESS",
                severity="FAIL",
                message=(
                    f"Missing papers/{paper_id}/auto/MANIFEST.json; "
                    "run build-paper-assets."
                ),
                fix=fix,
                recheck=recheck,
                paths=[str(manifest_path)],
            )
        ]

    manifest = json.loads(manifest_path.read_text())
    metrics_path = repo_root / manifest["source"]["metrics_json_path"]
    if not metrics_path.exists():
        fix = "uv run truthweave run exp=example"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        return [
            Issue(
                category="FRESHNESS",
                severity="FAIL",
                message=f"Missing metrics.json for {paper_id}: {metrics_path}",
                fix=fix,
                recheck=recheck,
                paths=[str(metrics_path)],
            )
        ]
    expected = manifest["source"]["metrics_json_sha256"]
    actual = sha256_file(metrics_path)
    if actual != expected:
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        return [
            Issue(
                category="FRESHNESS",
                severity="FAIL",
                message=f"Paper assets are stale for {paper_id}; run build-paper-assets.",
                fix=fix,
                recheck=recheck,
                paths=[str(manifest_path), str(metrics_path)],
            )
        ]

    tex_path = paper_dir / config.get("main", "main.tex")
    variables_path = auto_dir / "variables.tex"
    defined = _extract_defined_metric_macros(variables_path)
    used = _extract_used_metric_macros(tex_path)
    missing = sorted(used - defined)
    if missing:
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        severity = "FAIL" if mode == "ci" else "WARN"
        return [
            Issue(
                category="ARGUMENT_TRACE",
                severity=severity,
                message=(
                    f"Undefined metric macro(s) in {tex_path}: "
                    + ", ".join(f"\\{name}" for name in missing)
                ),
                fix=(
                    "Ensure claims reference generated metric macros from "
                    "auto/variables.tex, then rebuild assets."
                ),
                recheck=recheck,
                paths=[str(tex_path), str(variables_path)],
            )
        ]
    return []
