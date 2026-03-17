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


def _collect_dir_hashes(base_dir: Path) -> dict[str, str]:
    if not base_dir.exists():
        return {}
    hashes: dict[str, str] = {}
    for path in sorted(base_dir.rglob("*")):
        if path.is_file():
            hashes[str(path.relative_to(base_dir).as_posix())] = sha256_file(path)
    return hashes


def _compute_argument_audit(tex_path: Path, variables_path: Path) -> dict[str, object]:
    defined = _extract_defined_metric_macros(variables_path)
    used = _extract_used_metric_macros(tex_path)
    supported = used & defined
    unsupported = sorted(used - defined)
    orphan = sorted(defined - used)
    claim_support = 1.0 if not used else len(supported) / len(used)
    return {
        "claim_support": round(claim_support, 4),
        "claims_count": len(used),
        "unsupported_claims": len(unsupported),
        "orphan_metrics": len(orphan),
        "unsupported_macros": unsupported,
        "orphan_macros": orphan,
    }


def _argument_policy(config: dict) -> tuple[float, int]:
    quality = config.get("quality", {})
    argument = quality.get("argument", {}) if isinstance(quality, dict) else {}
    min_claim_support_ci = argument.get("min_claim_support_ci", 1.0)
    max_orphan_metrics_dev = argument.get("max_orphan_metrics_dev", 0)
    if not isinstance(min_claim_support_ci, (int, float)):
        min_claim_support_ci = 1.0
    if not isinstance(max_orphan_metrics_dev, int):
        max_orphan_metrics_dev = 0
    return float(min_claim_support_ci), max_orphan_metrics_dev


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    config = load_paper_config(paper_dir / "truthweave.yml")
    min_claim_support_ci, max_orphan_metrics_dev = _argument_policy(config)
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

    generated = manifest.get("generated", {})
    expected_figures = generated.get("figures_sha256")
    expected_tables = generated.get("tables_sha256")
    if not isinstance(expected_figures, dict) or not isinstance(expected_tables, dict):
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        return [
            Issue(
                category="FRESHNESS",
                severity="FAIL",
                message=(
                    f"Missing figure/table provenance in MANIFEST for {paper_id}; "
                    "rebuild paper assets."
                ),
                fix=fix,
                recheck=recheck,
                paths=[str(manifest_path)],
            )
        ]

    figures_dir = paper_dir / config["paths"]["figures_dir"]
    tables_dir = paper_dir / config["paths"]["tables_dir"]
    actual_figures = _collect_dir_hashes(figures_dir)
    actual_tables = _collect_dir_hashes(tables_dir)
    if actual_figures != expected_figures or actual_tables != expected_tables:
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        return [
            Issue(
                category="FRESHNESS",
                severity="FAIL",
                message=(
                    f"Figure/table assets are stale for {paper_id}; "
                    "run build-paper-assets."
                ),
                fix=fix,
                recheck=recheck,
                paths=[str(manifest_path), str(figures_dir), str(tables_dir)],
            )
        ]

    tex_path = paper_dir / config.get("main", "main.tex")
    variables_path = auto_dir / "variables.tex"
    expected_argument_audit = generated.get("argument_audit")
    actual_argument_audit = _compute_argument_audit(tex_path, variables_path)
    if not isinstance(expected_argument_audit, dict):
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        issues.append(
            Issue(
                category="FRESHNESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message=(
                    f"Missing argument_audit in MANIFEST for {paper_id}; "
                    "rebuild paper assets."
                ),
                fix=fix,
                recheck=recheck,
                paths=[str(manifest_path), str(tex_path), str(variables_path)],
            )
        )
    if expected_argument_audit != actual_argument_audit:
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        issues.append(
            Issue(
                category="FRESHNESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message=(
                    f"Argument audit is stale for {paper_id}; "
                    "run build-paper-assets."
                ),
                fix=fix,
                recheck=recheck,
                paths=[str(manifest_path), str(tex_path), str(variables_path)],
            )
        )

    defined = _extract_defined_metric_macros(variables_path)
    used = _extract_used_metric_macros(tex_path)
    supported = used & defined

    # Claim support ratio tracks how many metric claims are backed by generated macros.
    support_ratio = 1.0 if not used else len(supported) / len(used)
    missing = sorted(used - defined)
    if mode == "ci" and support_ratio < min_claim_support_ci:
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        issues.append(
            Issue(
                category="ARGUMENT_SUPPORT",
                severity="FAIL",
                message=(
                    f"Claim support ratio below threshold for {paper_id}: "
                    f"claim_support={support_ratio:.2f} < min_claim_support_ci={min_claim_support_ci:.2f} "
                    f"(claims={len(used)}, unsupported_claims={len(missing)})"
                ),
                fix=(
                    "Align paper claims with generated metrics or lower "
                    "quality.argument.min_claim_support_ci in truthweave.yml when justified."
                ),
                recheck=recheck,
                paths=[str(tex_path), str(variables_path)],
            )
        )

    if missing:
        fix = f"uv run truthweave build-paper-assets --paper {paper_id}"
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        severity = "FAIL" if mode == "ci" else "WARN"
        issues.append(
            Issue(
                category="ARGUMENT_TRACE",
                severity=severity,
                message=(
                    f"Undefined metric macro(s) in {tex_path}: "
                    + ", ".join(f"\\{name}" for name in missing)
                    + f" (claim_support={support_ratio:.2f})"
                ),
                fix=(
                    "Ensure claims reference generated metric macros from "
                    "auto/variables.tex, then rebuild assets."
                ),
                recheck=recheck,
                paths=[str(tex_path), str(variables_path)],
            )
        )

    orphan = sorted(defined - used)
    if mode == "dev" and len(orphan) > max_orphan_metrics_dev:
        recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
        issues.append(
            Issue(
                category="ARGUMENT_COVERAGE",
                severity="WARN",
                message=(
                    "Unused metric macro(s) detected in auto/variables.tex: "
                    + ", ".join(f"\\{name}" for name in orphan)
                    + (
                        f" (claim_support={support_ratio:.2f}, orphan_metrics={len(orphan)}, "
                        f"max_orphan_metrics_dev={max_orphan_metrics_dev})"
                    )
                ),
                fix=(
                    "Reference generated metric macros in paper text or reduce "
                    "unused metric outputs in experiments/analysis."
                ),
                recheck=recheck,
                paths=[str(tex_path), str(variables_path)],
            )
        )

    return issues
