from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from truthweave.briefs import claim_specs_from_brief, load_brief, validate_brief_data
from truthweave.evidence import (
    VERIFICATION_COMPARISON_MODES,
    build_claim_ledger,
    claim_ledger_path,
    evidence_path,
)
from truthweave.provenance import (
    build_provenance_ledger,
    provenance_ledger_path,
    provenance_path,
)
from truthweave.utils import ensure_dir, sha256_file, write_json


VERIFICATION_STATUSES = {
    "verified_exact",
    "verified_within_tolerance",
    "not_reproduced",
    "blocked",
    "missing_metadata",
    "stale",
    "invalid",
}


def verification_dir(repo_root: Path, paper_id: str) -> Path:
    return repo_root / "artifacts" / "verification" / paper_id


def verification_report_path(repo_root: Path, paper_id: str) -> Path:
    return verification_dir(repo_root, paper_id) / "verification_report.json"


def verification_markdown_path(repo_root: Path, paper_id: str) -> Path:
    return verification_dir(repo_root, paper_id) / "verification_report.md"


def verification_targets_csv_path(repo_root: Path, paper_id: str) -> Path:
    return verification_dir(repo_root, paper_id) / "verification_targets.csv"


def replay_profile_path(repo_root: Path, paper_id: str) -> Path:
    return verification_dir(repo_root, paper_id) / "replay_profile.md"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _verification_reviewed_inputs(
    repo_root: Path, paper_dir: Path, paper_id: str
) -> dict[str, dict[str, str]]:
    reviewed_inputs: dict[str, dict[str, str]] = {}
    for label, path in {
        "brief_yml": paper_dir / "brief.yml",
        "evidence_yml": evidence_path(paper_dir),
        "data_sources_yml": provenance_path(paper_dir),
        "claim_ledger": claim_ledger_path(repo_root, paper_id),
        "provenance_ledger": provenance_ledger_path(repo_root, paper_id),
    }.items():
        if path.exists():
            reviewed_inputs[label] = {
                "path": str(path.relative_to(repo_root)),
                "sha256": sha256_file(path),
            }
    return reviewed_inputs


def _default_rerun_scope(item: dict[str, Any]) -> str:
    kind = item.get("kind")
    if kind in {"variable", "manifest"}:
        return "run_and_assets"
    return "assets_only"


def _default_rerun_commands(paper_id: str, item: dict[str, Any]) -> list[str]:
    kind = item.get("kind")
    if kind in {"variable", "manifest"}:
        return [
            "make run",
            f"uv run truthweave build-paper-assets --paper {paper_id}",
        ]
    return [f"uv run truthweave build-paper-assets --paper {paper_id}"]


def _comparison_actual_value(item: dict[str, Any], resolved: dict[str, Any]) -> Any:
    kind = item.get("kind")
    if kind in {"variable", "manifest"}:
        return resolved.get("value")
    return resolved.get("sha256")


def _source_flags(
    source_entries: list[dict[str, Any]], source_ids: list[str]
) -> tuple[list[str], list[str], list[str]]:
    manual: list[str] = []
    restricted: list[str] = []
    blocked: list[str] = []
    source_map = {
        str(entry.get("source_id")): entry
        for entry in source_entries
        if isinstance(entry, dict) and isinstance(entry.get("source_id"), str)
    }
    for source_id in source_ids:
        entry = source_map.get(source_id, {})
        acquisition_mode = entry.get("acquisition_mode")
        reproducibility_level = entry.get("reproducibility_level")
        status = entry.get("status")
        if reproducibility_level == "manual_step_required":
            manual.append(source_id)
        if acquisition_mode in {"credential_required", "licensed_restricted"} or reproducibility_level == "nonredistributable":
            restricted.append(source_id)
        if status == "unavailable" or source_id in manual or source_id in restricted:
            blocked.append(source_id)
    return manual, restricted, blocked


def _compare_target(
    item: dict[str, Any],
    resolved: dict[str, Any],
    verification: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str]]:
    issues: list[str] = []
    comparison_mode = verification.get("comparison_mode")
    if comparison_mode not in VERIFICATION_COMPARISON_MODES:
        issues.append("Unsupported comparison_mode")
        return "invalid", {"matched": False}, issues

    if resolved.get("stale"):
        return "stale", {"matched": False}, issues
    if resolved.get("issues"):
        issues.extend(str(issue) for issue in resolved.get("issues", []))
        return "invalid", {"matched": False}, issues

    kind = item.get("kind")
    actual = _comparison_actual_value(item, resolved)
    expected = verification.get("expected_value")
    tolerance = verification.get("tolerance")

    if comparison_mode == "file_exists":
        matched = bool(resolved.get("resolved"))
        return (
            "verified_exact" if matched else "not_reproduced",
            {"matched": matched, "actual": resolved.get("resolved_path")},
            issues,
        )

    if comparison_mode == "manifest_entry_present":
        if kind != "manifest":
            issues.append("manifest_entry_present requires manifest evidence")
            return "invalid", {"matched": False}, issues
        matched = bool(resolved.get("resolved"))
        return (
            "verified_exact" if matched else "not_reproduced",
            {"matched": matched, "actual": resolved.get("value")},
            issues,
        )

    if comparison_mode == "numeric_tolerance":
        if kind not in {"variable", "manifest"}:
            issues.append("numeric_tolerance requires variable or manifest evidence")
            return "invalid", {"matched": False}, issues
        try:
            actual_value = float(actual)
            expected_value = float(expected)
            tolerance_value = float(0.0 if tolerance is None else tolerance)
        except (TypeError, ValueError):
            issues.append("numeric_tolerance requires numeric actual and expected values")
            return "invalid", {"matched": False, "actual": actual, "expected": expected}, issues
        delta = abs(actual_value - expected_value)
        matched = delta <= tolerance_value
        return (
            "verified_within_tolerance" if matched else "not_reproduced",
            {
                "matched": matched,
                "actual": actual_value,
                "expected": expected_value,
                "tolerance": tolerance_value,
                "delta": delta,
            },
            issues,
        )

    if comparison_mode == "exact_match":
        matched = str(actual) == str(expected)
        return (
            "verified_exact" if matched else "not_reproduced",
            {"matched": matched, "actual": actual, "expected": expected},
            issues,
        )

    issues.append("Unsupported comparison_mode")
    return "invalid", {"matched": False}, issues


def build_verification_report(
    repo_root: Path,
    paper_dir: Path,
    paper_id: str,
    write_output: bool = False,
) -> dict[str, Any]:
    brief = load_brief(paper_dir / "brief.yml")
    brief_errors = validate_brief_data(brief)
    if brief_errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(brief_errors))

    claim_specs = claim_specs_from_brief(brief)
    claim_ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)
    provenance_ledger = build_provenance_ledger(
        repo_root, paper_dir, paper_id, write_output=False
    )
    source_entries = provenance_ledger.get("entries", [])
    if not isinstance(source_entries, list):
        source_entries = []

    schema_errors: list[str] = []
    missing_verification_claims: list[str] = []
    unresolved_targets: list[str] = []
    policy_violations: list[str] = []
    stale_targets: list[str] = []
    failed_required_targets: list[str] = []

    claim_entries = claim_ledger.get("entries", [])
    if not isinstance(claim_entries, list):
        claim_entries = []

    targets: list[dict[str, Any]] = []
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for claim_entry in claim_entries:
        if not isinstance(claim_entry, dict):
            continue
        claim_id = str(claim_entry.get("claim_id", ""))
        spec = claim_specs.get(claim_id, {})
        verification_required = bool(spec.get("verification_required", False))
        evidence_pointers = claim_entry.get("evidence_pointers", [])
        resolved_artifacts = claim_entry.get("resolved_artifacts", [])
        if not isinstance(evidence_pointers, list):
            evidence_pointers = []
        if not isinstance(resolved_artifacts, list):
            resolved_artifacts = []

        claim_targets: list[dict[str, Any]] = []
        for item_index, (item, resolved) in enumerate(
            zip(evidence_pointers, resolved_artifacts)
        ):
            if not isinstance(item, dict) or not isinstance(resolved, dict):
                continue
            verification = item.get("verification")
            if verification is None:
                continue
            if not isinstance(verification, dict):
                schema_errors.append(
                    f"{claim_id}.evidence[{item_index}].verification must be a mapping"
                )
                continue

            source_ids = item.get("source_ids", spec.get("source_ids", []))
            if not isinstance(source_ids, list):
                source_ids = []
            manual_sources, restricted_sources, blocked_sources = _source_flags(
                source_entries, [str(source_id) for source_id in source_ids]
            )
            rerun_scope = verification.get("rerun_scope") or _default_rerun_scope(item)
            rerun_commands = verification.get("rerun_commands")
            if not isinstance(rerun_commands, list) or not rerun_commands:
                rerun_commands = _default_rerun_commands(paper_id, item)

            verification_status, comparison_result, comparison_issues = _compare_target(
                item, resolved, verification
            )
            issues = list(comparison_issues)
            if blocked_sources:
                verification_status = "blocked"
                issues.append(
                    "Verification replay is blocked by source restrictions: "
                    + ", ".join(blocked_sources)
                )
            if verification_status == "stale":
                stale_targets.append(f"{claim_id}[{item_index}]")
            if verification_status == "invalid":
                unresolved_targets.append(f"{claim_id}[{item_index}]")
            if comparison_issues:
                policy_violations.append(
                    f"{claim_id}[{item_index}]: {'; '.join(comparison_issues)}"
                )
            if verification_required and verification_status in {
                "not_reproduced",
                "blocked",
                "invalid",
                "stale",
            }:
                failed_required_targets.append(f"{claim_id}[{item_index}]")

            target = {
                "target_id": f"{claim_id}:{item_index}",
                "claim_id": claim_id,
                "required": bool(claim_entry.get("required", False)),
                "verification_required": verification_required,
                "verification_status": verification_status,
                "comparison_mode": verification.get("comparison_mode"),
                "comparison_result": comparison_result,
                "target_pointer": {
                    "kind": item.get("kind"),
                    "artifact_path": item.get("artifact_path"),
                    "variable": item.get("variable"),
                    "manifest_pointer": item.get("manifest_pointer"),
                },
                "resolved_target": resolved,
                "rerun_scope": rerun_scope,
                "rerun_commands": rerun_commands,
                "source_ids": source_ids,
                "manual_step_sources": manual_sources,
                "restricted_sources": restricted_sources,
                "blocked_sources": blocked_sources,
                "stale": bool(resolved.get("stale", False)) or verification_status == "stale",
                "note": verification.get("note") or item.get("note") or claim_entry.get("note"),
                "qualification": claim_entry.get("note"),
                "issues": issues,
            }
            targets.append(target)
            claim_targets.append(target)

        if verification_required and not claim_targets:
            missing_verification_claims.append(claim_id)
        by_claim[claim_id] = claim_targets

    verifiable_required_claims = [
        claim_id
        for claim_id, spec in claim_specs.items()
        if bool(spec.get("required", True)) and bool(spec.get("verification_required", False))
    ]
    verified_required_claims = []
    blocked_required_claims = []
    for claim_id in verifiable_required_claims:
        claim_targets = by_claim.get(claim_id, [])
        statuses = {target["verification_status"] for target in claim_targets}
        if claim_targets and statuses <= {"verified_exact", "verified_within_tolerance"}:
            verified_required_claims.append(claim_id)
        elif "blocked" in statuses:
            blocked_required_claims.append(claim_id)

    replay_profile = {
        "commands": [
            "uv sync",
            "make run",
            f"uv run truthweave build-paper-assets --paper {paper_id}",
            f"uv run truthweave verify-paper --paper {paper_id}",
        ],
        "targets": [
            {
                "claim_id": target["claim_id"],
                "target_id": target["target_id"],
                "rerun_scope": target["rerun_scope"],
                "rerun_commands": target["rerun_commands"],
                "blocked_sources": target["blocked_sources"],
            }
            for target in targets
        ],
    }

    summary = {
        "targets_total": len(targets),
        "required_targets": sum(1 for target in targets if bool(target["required"])),
        "verified_exact": sum(
            1 for target in targets if target["verification_status"] == "verified_exact"
        ),
        "verified_within_tolerance": sum(
            1
            for target in targets
            if target["verification_status"] == "verified_within_tolerance"
        ),
        "not_reproduced": sum(
            1 for target in targets if target["verification_status"] == "not_reproduced"
        ),
        "blocked": sum(1 for target in targets if target["verification_status"] == "blocked"),
        "missing_verification_metadata": len(missing_verification_claims),
        "stale": sum(1 for target in targets if bool(target["stale"])),
        "verifiable_required_claims": len(verifiable_required_claims),
        "verified_required_claims": len(verified_required_claims),
        "blocked_required_claims": len(blocked_required_claims),
    }

    report = {
        "paper_id": paper_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "targets": targets,
        "replay_profile": replay_profile,
        "validation": {
            "schema_errors": schema_errors,
            "missing_verification_claims": missing_verification_claims,
            "unresolved_targets": unresolved_targets,
            "policy_violations": policy_violations,
            "stale_targets": stale_targets,
            "failed_required_targets": failed_required_targets,
        },
        "reviewed_inputs": _verification_reviewed_inputs(repo_root, paper_dir, paper_id),
    }

    if write_output:
        out_dir = verification_dir(repo_root, paper_id)
        ensure_dir(out_dir)
        write_json(verification_report_path(repo_root, paper_id), report)
        verification_markdown_path(repo_root, paper_id).write_text(
            render_verification_report(report, "md")
        )
        _write_targets_csv(verification_targets_csv_path(repo_root, paper_id), targets)
        replay_profile_path(repo_root, paper_id).write_text(
            _render_replay_profile(report)
        )
        manifest_path = paper_dir / "auto" / "MANIFEST.json"
        manifest = _load_json(manifest_path)
        if manifest is not None:
            generated = manifest.get("generated")
            if not isinstance(generated, dict):
                generated = {}
                manifest["generated"] = generated
            generated["verification"] = {
                "path": str(
                    verification_report_path(repo_root, paper_id).relative_to(repo_root)
                ),
                "markdown_path": str(
                    verification_markdown_path(repo_root, paper_id).relative_to(repo_root)
                ),
                "targets_csv_path": str(
                    verification_targets_csv_path(repo_root, paper_id).relative_to(
                        repo_root
                    )
                ),
                "summary": summary,
            }
            write_json(manifest_path, manifest)
    return report


def _write_targets_csv(path: Path, targets: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "target_id",
                "claim_id",
                "required",
                "verification_required",
                "verification_status",
                "comparison_mode",
                "target_pointer",
                "rerun_scope",
                "source_ids",
                "stale",
            ]
        )
        for target in targets:
            pointer = target.get("target_pointer", {})
            if not isinstance(pointer, dict):
                pointer = {}
            writer.writerow(
                [
                    target.get("target_id"),
                    target.get("claim_id"),
                    target.get("required"),
                    target.get("verification_required"),
                    target.get("verification_status"),
                    target.get("comparison_mode"),
                    json.dumps(pointer, sort_keys=True),
                    target.get("rerun_scope"),
                    ";".join(str(source_id) for source_id in target.get("source_ids", [])),
                    target.get("stale"),
                ]
            )


def _render_replay_profile(report: dict[str, Any]) -> str:
    lines = [
        f"# Replay Profile: {report['paper_id']}",
        "",
        "## Minimal Commands",
    ]
    for command in report.get("replay_profile", {}).get("commands", []):
        lines.append(f"- `{command}`")
    lines.extend(["", "## Verification Targets"])
    for target in report.get("replay_profile", {}).get("targets", []):
        if not isinstance(target, dict):
            continue
        lines.append(
            f"- {target.get('target_id')}: scope={target.get('rerun_scope')}, "
            f"blocked_sources={','.join(str(value) for value in target.get('blocked_sources', [])) or '(none)'}"
        )
    return "\n".join(lines) + "\n"


def render_verification_report(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output_format == "md":
        lines = [
            f"# Verification Report: {report['paper_id']}",
            "",
            "## Summary",
            f"- targets_total: {report['summary']['targets_total']}",
            f"- verified_exact: {report['summary']['verified_exact']}",
            f"- verified_within_tolerance: {report['summary']['verified_within_tolerance']}",
            f"- not_reproduced: {report['summary']['not_reproduced']}",
            f"- blocked: {report['summary']['blocked']}",
            f"- missing_verification_metadata: {report['summary']['missing_verification_metadata']}",
            "",
            "## Targets",
        ]
        for target in report.get("targets", []):
            if not isinstance(target, dict):
                continue
            lines.append(
                f"- {target['target_id']}: status={target['verification_status']}, "
                f"mode={target['comparison_mode']}, scope={target['rerun_scope']}"
            )
        if report.get("validation", {}).get("failed_required_targets"):
            lines.extend(["", "## Failed Required Targets"])
            for target_id in report["validation"]["failed_required_targets"]:
                lines.append(f"- {target_id}")
        return "\n".join(lines) + "\n"

    header = "target_id\tclaim_id\tstatus\tcomparison_mode\trerun_scope\tstale"
    rows = [header]
    for target in report.get("targets", []):
        if not isinstance(target, dict):
            continue
        rows.append(
            f"{target['target_id']}\t{target['claim_id']}\t{target['verification_status']}\t"
            f"{target['comparison_mode']}\t{target['rerun_scope']}\t{target['stale']}"
        )
    return "\n".join(rows) + "\n"
