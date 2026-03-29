from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from truthweave.checks.models import Issue
from truthweave.verify import (
    build_verification_report,
    replay_profile_path,
    verification_markdown_path,
    verification_report_path,
    verification_targets_csv_path,
)
from truthweave.utils import sha256_file


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    report_path = verification_report_path(repo_root, paper_id)
    report_md = verification_markdown_path(repo_root, paper_id)
    targets_csv = verification_targets_csv_path(repo_root, paper_id)
    replay_md = replay_profile_path(repo_root, paper_id)
    paths = [str(report_path), str(report_md), str(targets_csv), str(replay_md)]
    recheck = f"uv run truthweave verification-report --paper {paper_id} --format md"

    if not report_path.exists():
        issues.append(
            Issue(
                category="VERIFICATION_STALENESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message=f"Missing verification report for {paper_id}.",
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )
        return issues

    report = _load_json(report_path)
    if report is None:
        issues.append(
            Issue(
                category="VERIFICATION_STALENESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message=f"Invalid verification report JSON for {paper_id}.",
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )
        return issues

    missing_outputs = [
        str(path) for path in [report_md, targets_csv, replay_md] if not path.exists()
    ]
    if missing_outputs:
        issues.append(
            Issue(
                category="VERIFICATION_STALENESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Verification export is incomplete; missing outputs: "
                + ", ".join(missing_outputs),
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )

    current_report = build_verification_report(
        repo_root, paper_dir, paper_id, write_output=False
    )
    validation = current_report.get("validation", {})
    missing_verification_claims = validation.get("missing_verification_claims", [])
    if isinstance(missing_verification_claims, list) and missing_verification_claims:
        issues.append(
            Issue(
                category="VERIFICATION_COVERAGE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Claims marked verification_required are missing verification metadata: "
                + ", ".join(str(value) for value in missing_verification_claims),
                fix="Add verification stanzas to evidence.yml for each verification_required claim.",
                recheck=recheck,
                paths=paths,
            )
        )

    unresolved_targets = validation.get("unresolved_targets", [])
    if isinstance(unresolved_targets, list) and unresolved_targets:
        issues.append(
            Issue(
                category="VERIFICATION_POINTER_RESOLUTION",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Verification targets do not resolve cleanly: "
                + ", ".join(str(value) for value in unresolved_targets),
                fix="Update verification targets so they point to resolvable evidence artifacts and values.",
                recheck=recheck,
                paths=paths,
            )
        )

    policy_violations = validation.get("policy_violations", [])
    if isinstance(policy_violations, list) and policy_violations:
        issues.append(
            Issue(
                category="VERIFICATION_POLICY",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Verification policy violations detected: "
                + "; ".join(str(value) for value in policy_violations),
                fix="Align comparison_mode, expected_value, and tolerance with the referenced evidence kind.",
                recheck=recheck,
                paths=paths,
            )
        )

    stale_paths: list[str] = []
    reviewed_inputs = report.get("reviewed_inputs", {})
    if isinstance(reviewed_inputs, dict):
        for item in reviewed_inputs.values():
            if not isinstance(item, dict):
                continue
            rel_path = item.get("path")
            expected_sha = item.get("sha256")
            if not isinstance(rel_path, str) or not isinstance(expected_sha, str):
                continue
            current_path = repo_root / rel_path
            if not current_path.exists() or sha256_file(current_path) != expected_sha:
                stale_paths.append(rel_path)
    if stale_paths:
        issues.append(
            Issue(
                category="VERIFICATION_STALENESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Verification report is stale; upstream inputs changed: "
                + ", ".join(stale_paths),
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=stale_paths + paths,
            )
        )

    if (
        report.get("summary") != current_report.get("summary")
        or _target_snapshot(report) != _target_snapshot(current_report)
    ):
        issues.append(
            Issue(
                category="VERIFICATION_STALENESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Verification report no longer matches current evidence state.",
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )

    return issues


def _target_snapshot(report: dict[str, Any]) -> list[tuple[str, str, str, bool]]:
    snapshot: list[tuple[str, str, str, bool]] = []
    targets = report.get("targets", [])
    if not isinstance(targets, list):
        return snapshot
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_id = target.get("target_id")
        status = target.get("verification_status")
        comparison_mode = target.get("comparison_mode")
        if (
            not isinstance(target_id, str)
            or not isinstance(status, str)
            or not isinstance(comparison_mode, str)
        ):
            continue
        snapshot.append(
            (target_id, status, comparison_mode, bool(target.get("stale", False)))
        )
    return sorted(snapshot)
