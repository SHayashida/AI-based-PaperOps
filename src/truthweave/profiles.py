from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from truthweave.briefs import claim_specs_from_brief, load_brief, validate_brief_data
from truthweave.evidence import build_claim_ledger, evidence_path
from truthweave.provenance import build_provenance_ledger, provenance_path
from truthweave.utils import ensure_dir, sha256_file, write_json
from truthweave.verify import build_verification_report, verification_report_path


def profiles_dir(repo_root: Path) -> Path:
    return repo_root / "profiles"


def profile_report_path(repo_root: Path, paper_id: str) -> Path:
    return repo_root / "artifacts" / "profiles" / paper_id / "profile_report.json"


def profile_markdown_path(repo_root: Path, paper_id: str) -> Path:
    return repo_root / "artifacts" / "profiles" / paper_id / "profile_report.md"


def load_profile_definition(repo_root: Path, profile_id: str) -> dict[str, Any] | None:
    path = profiles_dir(repo_root) / f"{profile_id}.yml"
    if not path.exists():
        return None
    data = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
    return data if isinstance(data, dict) else None


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _get_nested(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _baseline_entries(brief: dict[str, Any]) -> list[dict[str, Any]]:
    baselines = brief.get("baselines", [])
    entries: list[dict[str, Any]] = []
    if not isinstance(baselines, list):
        return entries
    for baseline in baselines:
        if isinstance(baseline, str):
            entries.append({"name": baseline, "kind": ""})
        elif isinstance(baseline, dict):
            entries.append(baseline)
    return entries


def _profile_inputs(
    repo_root: Path, paper_dir: Path, paper_id: str, profile_path: Path
) -> dict[str, dict[str, str]]:
    reviewed_inputs: dict[str, dict[str, str]] = {}
    for label, path in {
        "brief_yml": paper_dir / "brief.yml",
        "evidence_yml": evidence_path(paper_dir),
        "data_sources_yml": provenance_path(paper_dir),
        "verification_report": verification_report_path(repo_root, paper_id),
        "profile_yml": profile_path,
    }.items():
        if path.exists():
            reviewed_inputs[label] = {
                "path": str(path.relative_to(repo_root)),
                "sha256": sha256_file(path),
            }
    return reviewed_inputs


def build_profile_report(
    repo_root: Path,
    paper_dir: Path,
    paper_id: str,
    write_output: bool = False,
) -> dict[str, Any]:
    brief = load_brief(paper_dir / "brief.yml")
    brief_errors = validate_brief_data(brief)
    if brief_errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(brief_errors))

    selected_profile = str(brief.get("research_profile", "") or "").strip()
    if not selected_profile:
        report = {
            "paper_id": paper_id,
            "selected_profile": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "profile_selected": False,
                "blockers": 0,
                "warnings": 0,
                "required_claims": 0,
            },
            "blockers": [],
            "warnings": [],
            "validation": {},
            "reviewed_inputs": {},
        }
        return report

    profile_path = profiles_dir(repo_root) / f"{selected_profile}.yml"
    profile = load_profile_definition(repo_root, selected_profile)
    declaration_errors: list[str] = []
    if profile is None:
        declaration_errors.append(
            f"Unknown research_profile '{selected_profile}'; expected a profile under profiles/{selected_profile}.yml"
        )
        profile = {
            "profile_id": selected_profile,
            "description": "",
            "required_brief_fields": [],
            "required_evaluation_protocol_fields": [],
            "warnings": [],
        }

    claim_specs = claim_specs_from_brief(brief)
    claim_ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)
    provenance_ledger = build_provenance_ledger(
        repo_root, paper_dir, paper_id, write_output=False
    )
    verification = build_verification_report(
        repo_root, paper_dir, paper_id, write_output=False
    )

    missing_required_fields: list[str] = []
    missing_eval_fields: list[str] = []
    baseline_coverage: list[str] = []
    policy_blockers: list[str] = []
    forbidden_substitutes: list[str] = []
    verification_expectations: list[str] = []
    warnings: list[str] = []

    required_brief_fields = profile.get("required_brief_fields", [])
    if isinstance(required_brief_fields, list):
        for field in required_brief_fields:
            if not isinstance(field, str) or not field:
                continue
            value = _get_nested(brief, field)
            if value in (None, "", [], {}):
                missing_required_fields.append(field)

    required_eval_fields = profile.get("required_evaluation_protocol_fields", [])
    evaluation_protocol = brief.get("evaluation_protocol", {})
    if not isinstance(evaluation_protocol, dict):
        evaluation_protocol = {}
    if isinstance(required_eval_fields, list):
        for field in required_eval_fields:
            if not isinstance(field, str) or not field:
                continue
            value = evaluation_protocol.get(field)
            if value in (None, "", [], {}):
                missing_eval_fields.append(field)

    min_baselines = profile.get("min_baselines", 0)
    baselines = _baseline_entries(brief)
    if isinstance(min_baselines, int) and len(baselines) < min_baselines:
        baseline_coverage.append(
            f"Expected at least {min_baselines} baseline declaration(s); found {len(baselines)}"
        )

    claim_entries = claim_ledger.get("entries", [])
    if not isinstance(claim_entries, list):
        claim_entries = []
    provenance_entries = provenance_ledger.get("entries", [])
    if not isinstance(provenance_entries, list):
        provenance_entries = []
    source_map = {
        str(entry.get("source_id")): entry
        for entry in provenance_entries
        if isinstance(entry, dict) and isinstance(entry.get("source_id"), str)
    }

    if profile.get("require_claim_source_ids"):
        for claim_id, spec in claim_specs.items():
            if bool(spec.get("required", True)) and not spec.get("source_ids"):
                policy_blockers.append(
                    f"{claim_id} must declare source_ids under profile {selected_profile}"
                )

    provenance_validation = provenance_ledger.get("validation", {})
    if isinstance(provenance_validation.get("forbidden_substitutes"), list):
        forbidden_substitutes.extend(
            str(value) for value in provenance_validation["forbidden_substitutes"]
        )

    require_verification = bool(
        profile.get("require_verification_for_required_claims", False)
    )
    if require_verification:
        for claim_id, spec in claim_specs.items():
            if bool(spec.get("required", True)) and not bool(
                spec.get("verification_required", False)
            ):
                verification_expectations.append(
                    f"{claim_id} must set verification_required: true"
                )
        missing_verification_claims = verification.get("validation", {}).get(
            "missing_verification_claims", []
        )
        if isinstance(missing_verification_claims, list):
            verification_expectations.extend(
                f"{claim_id} is missing verification metadata"
                for claim_id in missing_verification_claims
            )

    required_verification_modes = profile.get("required_verification_modes_any_of", [])
    if isinstance(required_verification_modes, list) and required_verification_modes:
        targets = verification.get("targets", [])
        if not isinstance(targets, list):
            targets = []
        for claim_id, spec in claim_specs.items():
            if not bool(spec.get("required", True)):
                continue
            claim_modes = {
                str(target.get("comparison_mode"))
                for target in targets
                if isinstance(target, dict) and target.get("claim_id") == claim_id
            }
            if claim_modes and not claim_modes.intersection(
                {str(mode) for mode in required_verification_modes}
            ):
                verification_expectations.append(
                    f"{claim_id} must use one of {', '.join(str(mode) for mode in required_verification_modes)}"
                )

    required_evidence_kinds = profile.get("required_evidence_kinds_any_of", [])
    if isinstance(required_evidence_kinds, list) and required_evidence_kinds:
        required_set = {str(value) for value in required_evidence_kinds}
        for claim_entry in claim_entries:
            if not isinstance(claim_entry, dict) or not bool(
                claim_entry.get("required", False)
            ):
                continue
            claim_id = str(claim_entry.get("claim_id", ""))
            kinds = {
                str(item.get("kind"))
                for item in claim_entry.get("evidence_pointers", [])
                if isinstance(item, dict)
            }
            if kinds and not kinds.intersection(required_set):
                policy_blockers.append(
                    f"{claim_id} must include one of the required evidence kinds: {', '.join(sorted(required_set))}"
                )

    if selected_profile == "simulation_abm":
        for claim_entry in claim_entries:
            if not isinstance(claim_entry, dict) or not bool(
                claim_entry.get("required", False)
            ):
                continue
            claim_id = str(claim_entry.get("claim_id", ""))
            resolved = claim_entry.get("resolved_artifacts", [])
            if not isinstance(resolved, list):
                resolved = []
            has_run_backed = False
            for item in resolved:
                if not isinstance(item, dict):
                    continue
                target_path = item.get("target_path")
                resolved_path = item.get("resolved_path")
                if isinstance(target_path, str) and target_path.startswith("runs/"):
                    has_run_backed = True
                if isinstance(resolved_path, str) and resolved_path.startswith("runs/"):
                    has_run_backed = True
            if not has_run_backed:
                policy_blockers.append(
                    f"{claim_id} must point to concrete run-backed artifacts under simulation_abm"
                )

        if all(
            str(entry.get("source_type")) == "synthetic"
            for entry in provenance_entries
            if isinstance(entry, dict)
        ):
            warnings.append(
                "All declared sources are synthetic; keep simulated evidence clearly separated from observational claims."
            )

    if selected_profile == "finance_ml":
        data_regime = evaluation_protocol.get("data_regime")
        if data_regime == "real_market":
            real_world_sources = [
                entry
                for entry in provenance_entries
                if isinstance(entry, dict)
                and str(entry.get("source_type")) in {"dataset", "registry", "api"}
                and str(entry.get("acquisition_mode"))
                != "generated_internal"
            ]
            if not real_world_sources:
                policy_blockers.append(
                    "finance_ml with data_regime=real_market requires at least one non-synthetic market/registry source"
                )
        if all(
            str(entry.get("source_type")) == "synthetic"
            for entry in provenance_entries
            if isinstance(entry, dict)
        ):
            warnings.append(
                "finance_ml profile is currently backed only by synthetic sources."
            )

    if selected_profile == "formal_methods":
        for key in ["proof_checker_path", "proof_witness_path"]:
            value = evaluation_protocol.get(key)
            if isinstance(value, str) and value:
                path = Path(value)
                candidate = repo_root / path if not path.is_absolute() else path
                if not candidate.exists():
                    policy_blockers.append(
                        f"{key} does not resolve locally: {value}"
                    )

    profile_warnings = profile.get("warnings", [])
    if isinstance(profile_warnings, list):
        warnings.extend(str(value) for value in profile_warnings if isinstance(value, str))

    blockers = []
    blockers.extend(
        {"category": "PROFILE_DECLARATION", "message": message}
        for message in declaration_errors
    )
    blockers.extend(
        {"category": "PROFILE_REQUIRED_FIELDS", "message": message}
        for message in missing_required_fields
    )
    blockers.extend(
        {"category": "PROFILE_EVAL_PROTOCOL", "message": message}
        for message in missing_eval_fields
    )
    blockers.extend(
        {"category": "PROFILE_BASELINE_COVERAGE", "message": message}
        for message in baseline_coverage
    )
    blockers.extend(
        {"category": "PROFILE_POLICY_COMPLIANCE", "message": message}
        for message in policy_blockers
    )
    blockers.extend(
        {"category": "PROFILE_FORBIDDEN_SUBSTITUTE", "message": message}
        for message in forbidden_substitutes
    )
    blockers.extend(
        {"category": "PROFILE_VERIFICATION_EXPECTATIONS", "message": message}
        for message in verification_expectations
    )

    report = {
        "paper_id": paper_id,
        "selected_profile": selected_profile,
        "profile_description": profile.get("description", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "profile_selected": True,
            "blockers": len(blockers),
            "warnings": len(warnings),
            "required_claims": sum(
                1 for spec in claim_specs.values() if bool(spec.get("required", True))
            ),
            "baseline_count": len(baselines),
        },
        "blockers": blockers,
        "warnings": warnings,
        "validation": {
            "declaration_errors": declaration_errors,
            "missing_required_fields": missing_required_fields,
            "missing_eval_fields": missing_eval_fields,
            "baseline_coverage": baseline_coverage,
            "policy_blockers": policy_blockers,
            "forbidden_substitutes": forbidden_substitutes,
            "verification_expectations": verification_expectations,
        },
        "reviewed_inputs": _profile_inputs(repo_root, paper_dir, paper_id, profile_path),
    }

    if write_output:
        out_path = profile_report_path(repo_root, paper_id)
        ensure_dir(out_path.parent)
        write_json(out_path, report)
        profile_markdown_path(repo_root, paper_id).write_text(
            render_profile_report(report, "md")
        )
    return report


def render_profile_report(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output_format == "md":
        lines = [
            f"# Profile Report: {report['paper_id']}",
            "",
            f"- profile: {report.get('selected_profile') or '(none)'}",
            f"- blockers: {report.get('summary', {}).get('blockers', 0)}",
            f"- warnings: {report.get('summary', {}).get('warnings', 0)}",
        ]
        if report.get("selected_profile"):
            lines.extend(["", "## Blockers"])
            for blocker in report.get("blockers", []):
                if isinstance(blocker, dict):
                    lines.append(f"- [{blocker['category']}] {blocker['message']}")
            lines.extend(["", "## Warnings"])
            for warning in report.get("warnings", []):
                lines.append(f"- {warning}")
        return "\n".join(lines) + "\n"
    summary = report.get("summary", {})
    return (
        "paper_id\tprofile\tblockers\twarnings\n"
        f"{report['paper_id']}\t{report.get('selected_profile') or '(none)'}\t"
        f"{summary.get('blockers', 0)}\t{summary.get('warnings', 0)}\n"
    )
