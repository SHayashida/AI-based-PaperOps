from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from truthweave.checks.models import Issue
from truthweave.profiles import (
    build_profile_report,
    profile_markdown_path,
    profile_report_path,
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
    current = build_profile_report(repo_root, paper_dir, paper_id, write_output=False)
    selected_profile = current.get("selected_profile")
    if not selected_profile:
        return issues

    report_path = profile_report_path(repo_root, paper_id)
    md_path = profile_markdown_path(repo_root, paper_id)
    recheck = f"uv run truthweave profile-report --paper {paper_id} --format md"
    paths = [str(report_path), str(md_path)]

    if not report_path.exists():
        issues.append(
            Issue(
                category="PROFILE_DECLARATION",
                severity="FAIL" if mode == "ci" else "WARN",
                message=f"Missing profile report for {paper_id} ({selected_profile}).",
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )
    else:
        report = _load_json(report_path)
        if report is None:
            issues.append(
                Issue(
                    category="PROFILE_DECLARATION",
                    severity="FAIL" if mode == "ci" else "WARN",
                    message=f"Invalid profile report JSON for {paper_id}.",
                    fix=f"Run: {recheck}",
                    recheck=recheck,
                    paths=paths,
                )
            )
        else:
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
            if stale_paths or report.get("summary") != current.get("summary"):
                issues.append(
                    Issue(
                        category="PROFILE_POLICY_COMPLIANCE",
                        severity="FAIL" if mode == "ci" else "WARN",
                        message="Profile report is stale for: " + ", ".join(
                            stale_paths or ["summary mismatch"]
                        ),
                        fix=f"Run: {recheck}",
                        recheck=recheck,
                        paths=stale_paths + paths,
                    )
                )

    validation = current.get("validation", {})
    declaration_errors = validation.get("declaration_errors", [])
    if isinstance(declaration_errors, list) and declaration_errors:
        issues.append(
            Issue(
                category="PROFILE_DECLARATION",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Profile declaration errors: " + "; ".join(str(v) for v in declaration_errors),
                fix="Select a valid research_profile declared under profiles/.",
                recheck=recheck,
                paths=paths,
            )
        )

    missing_required_fields = validation.get("missing_required_fields", [])
    if isinstance(missing_required_fields, list) and missing_required_fields:
        issues.append(
            Issue(
                category="PROFILE_REQUIRED_FIELDS",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Missing required profile fields: " + ", ".join(str(v) for v in missing_required_fields),
                fix="Fill the profile-required declarations in brief.yml.",
                recheck=recheck,
                paths=paths,
            )
        )

    missing_eval_fields = validation.get("missing_eval_fields", [])
    if isinstance(missing_eval_fields, list) and missing_eval_fields:
        issues.append(
            Issue(
                category="PROFILE_EVAL_PROTOCOL",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Missing profile evaluation protocol fields: " + ", ".join(str(v) for v in missing_eval_fields),
                fix="Complete the evaluation_protocol section required by the selected research profile.",
                recheck=recheck,
                paths=paths,
            )
        )

    baseline_coverage = validation.get("baseline_coverage", [])
    if isinstance(baseline_coverage, list) and baseline_coverage:
        issues.append(
            Issue(
                category="PROFILE_BASELINE_COVERAGE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Profile baseline coverage issues: " + "; ".join(str(v) for v in baseline_coverage),
                fix="Add the required baseline declarations to brief.yml.",
                recheck=recheck,
                paths=paths,
            )
        )

    policy_blockers = validation.get("policy_blockers", [])
    if isinstance(policy_blockers, list) and policy_blockers:
        issues.append(
            Issue(
                category="PROFILE_POLICY_COMPLIANCE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Profile policy blockers: " + "; ".join(str(v) for v in policy_blockers),
                fix="Bring evidence, provenance, and evaluation declarations into compliance with the selected profile.",
                recheck=recheck,
                paths=paths,
            )
        )

    forbidden_substitutes = validation.get("forbidden_substitutes", [])
    if isinstance(forbidden_substitutes, list) and forbidden_substitutes:
        issues.append(
            Issue(
                category="PROFILE_FORBIDDEN_SUBSTITUTE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Profile forbidden substitutes detected: " + ", ".join(str(v) for v in forbidden_substitutes),
                fix="Replace forbidden substitutes or change the research contract explicitly.",
                recheck=recheck,
                paths=paths,
            )
        )

    verification_expectations = validation.get("verification_expectations", [])
    if isinstance(verification_expectations, list) and verification_expectations:
        issues.append(
            Issue(
                category="PROFILE_VERIFICATION_EXPECTATIONS",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Profile verification expectation gaps: " + "; ".join(str(v) for v in verification_expectations),
                fix="Add or tighten verification metadata to satisfy the selected research profile.",
                recheck=recheck,
                paths=paths,
            )
        )

    return issues
