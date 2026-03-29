from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from truthweave.briefs import (
    claim_specs_from_brief,
    expected_source_ids_from_brief,
    load_brief,
    validate_brief_data,
)
from truthweave.evidence import build_claim_ledger
from truthweave.utils import ensure_dir, sha256_file, write_json


SOURCE_TYPES = {
    "dataset",
    "api",
    "registry",
    "document",
    "manual_extract",
    "synthetic",
}
ACQUISITION_MODES = {
    "public",
    "credential_required",
    "manual_download",
    "licensed_restricted",
    "generated_internal",
}
SOURCE_STATUSES = {"declared", "acquired", "verified", "stale", "unavailable"}
REPRODUCIBILITY_LEVELS = {
    "fully_reproducible",
    "partially_reproducible",
    "manual_step_required",
    "nonredistributable",
}
POINTER_KINDS = {"file", "directory", "manifest"}


def provenance_path(paper_dir: Path) -> Path:
    return paper_dir / "data_sources.yml"


def provenance_ledger_path(repo_root: Path, paper_id: str) -> Path:
    return repo_root / "artifacts" / "provenance" / paper_id / "provenance_ledger.json"


def default_provenance(paper_id: str, brief: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for source_id in expected_source_ids_from_brief(brief):
        sources.append(
            {
                "source_id": source_id,
                "title": "Describe this data source",
                "source_type": "dataset",
                "acquisition_mode": "public",
                "status": "declared",
                "license_note": "Document the license or access restriction here.",
                "reproducibility_level": "fully_reproducible",
                "pointers": [],
                "snapshot": "Add version / snapshot / hash note",
                "note": "",
            }
        )
    return {"paper_id": paper_id, "sources": sources}


def load_provenance(path: Path) -> dict[str, Any]:
    cfg = OmegaConf.load(path)
    data = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid data_sources.yml at {path}")
    return data


def save_provenance(path: Path, data: dict[str, Any]) -> None:
    OmegaConf.save(OmegaConf.create(data), path)


def _resolve_path(repo_root: Path, paper_dir: Path, path_value: str) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    repo_candidate = repo_root / candidate
    if repo_candidate.exists():
        return repo_candidate
    return paper_dir / candidate


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _manifest_pointer(data: dict[str, Any], pointer: str) -> Any:
    current: Any = data
    for part in pointer.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(pointer)
        current = current[part]
    return current


def validate_provenance_data(
    provenance: dict[str, Any], brief: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    paper_id = provenance.get("paper_id")
    if not isinstance(paper_id, str) or not paper_id.strip():
        errors.append("Missing or empty field: paper_id")

    sources = provenance.get("sources")
    if not isinstance(sources, list):
        return errors + ["data_sources.yml must contain a sources list"]

    seen: set[str] = set()
    expected_sources = set(expected_source_ids_from_brief(brief))
    for idx, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{idx}] must be a mapping")
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"sources[{idx}].source_id must be a non-empty string")
            continue
        if source_id in seen:
            errors.append(f"Duplicate source_id in data_sources.yml: {source_id}")
        seen.add(source_id)
        for field in [
            "title",
            "source_type",
            "acquisition_mode",
            "status",
            "license_note",
            "reproducibility_level",
            "snapshot",
        ]:
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"sources[{idx}].{field} must be a non-empty string")

        if source.get("source_type") not in SOURCE_TYPES:
            errors.append(
                f"sources[{idx}].source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}"
            )
        if source.get("acquisition_mode") not in ACQUISITION_MODES:
            errors.append(
                f"sources[{idx}].acquisition_mode must be one of: "
                + ", ".join(sorted(ACQUISITION_MODES))
            )
        if source.get("status") not in SOURCE_STATUSES:
            errors.append(
                f"sources[{idx}].status must be one of: {', '.join(sorted(SOURCE_STATUSES))}"
            )
        if source.get("reproducibility_level") not in REPRODUCIBILITY_LEVELS:
            errors.append(
                f"sources[{idx}].reproducibility_level must be one of: "
                + ", ".join(sorted(REPRODUCIBILITY_LEVELS))
            )
        note = source.get("note")
        if note is not None and not isinstance(note, str):
            errors.append(f"sources[{idx}].note must be a string")

        pointers = source.get("pointers")
        if not isinstance(pointers, list):
            errors.append(f"sources[{idx}].pointers must be a list")
            continue
        if source.get("status") in {"acquired", "verified", "stale"} and not pointers:
            errors.append(
                f"sources[{idx}] with status {source.get('status')} must include at least one pointer"
            )
        for pointer_idx, pointer in enumerate(pointers):
            if not isinstance(pointer, dict):
                errors.append(
                    f"sources[{idx}].pointers[{pointer_idx}] must be a mapping"
                )
                continue
            kind = pointer.get("kind")
            if kind not in POINTER_KINDS:
                errors.append(
                    f"sources[{idx}].pointers[{pointer_idx}].kind must be one of: "
                    + ", ".join(sorted(POINTER_KINDS))
                )
            path_value = pointer.get("path")
            if not isinstance(path_value, str) or not path_value:
                errors.append(
                    f"sources[{idx}].pointers[{pointer_idx}].path must be a non-empty string"
                )
            if kind == "manifest":
                manifest_pointer = pointer.get("manifest_pointer")
                if not isinstance(manifest_pointer, str) or not manifest_pointer:
                    errors.append(
                        f"sources[{idx}].pointers[{pointer_idx}].manifest_pointer is required for manifest pointers"
                    )
            run_id = pointer.get("run_id")
            if run_id is not None and (not isinstance(run_id, str) or not run_id):
                errors.append(
                    f"sources[{idx}].pointers[{pointer_idx}].run_id must be a non-empty string"
                )
            version_note = pointer.get("version_note")
            if version_note is not None and not isinstance(version_note, str):
                errors.append(
                    f"sources[{idx}].pointers[{pointer_idx}].version_note must be a string"
                )

    missing_expected = [source_id for source_id in expected_sources if source_id not in seen]
    if missing_expected:
        errors.append(
            "Missing declared source_id(s) required by brief.yml: "
            + ", ".join(missing_expected)
        )
    return errors


def _policy_issues(source: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    source_type = source.get("source_type")
    acquisition_mode = source.get("acquisition_mode")
    reproducibility_level = source.get("reproducibility_level")
    status = source.get("status")

    if acquisition_mode == "licensed_restricted" and reproducibility_level == "fully_reproducible":
        issues.append("licensed_restricted cannot be fully_reproducible")
    if acquisition_mode == "credential_required" and reproducibility_level == "fully_reproducible":
        issues.append("credential_required cannot be fully_reproducible")
    if acquisition_mode == "manual_download" and reproducibility_level == "fully_reproducible":
        issues.append("manual_download cannot be fully_reproducible")
    if acquisition_mode == "generated_internal" and source_type != "synthetic":
        issues.append("generated_internal should use source_type=synthetic")
    if status == "unavailable" and reproducibility_level == "fully_reproducible":
        issues.append("unavailable sources cannot be fully_reproducible")
    return issues


def _resolve_pointer(
    repo_root: Path, paper_dir: Path, pointer: dict[str, Any]
) -> dict[str, Any]:
    kind = str(pointer.get("kind"))
    path_value = str(pointer.get("path", ""))
    resolved = {
        "kind": kind,
        "path": path_value,
        "manifest_pointer": pointer.get("manifest_pointer"),
        "run_id": pointer.get("run_id"),
        "version_note": pointer.get("version_note"),
        "resolved": False,
        "stale": False,
        "issues": [],
    }
    path = _resolve_path(repo_root, paper_dir, path_value)
    resolved["resolved_path"] = str(path.relative_to(repo_root)) if path.exists() else str(path)

    if kind == "directory":
        if not path.exists() or not path.is_dir():
            resolved["issues"].append(f"Missing directory pointer: {path_value}")
            return resolved
        resolved["resolved"] = True
        return resolved

    if kind == "file":
        if not path.exists() or not path.is_file():
            resolved["issues"].append(f"Missing file pointer: {path_value}")
            return resolved
        resolved["resolved"] = True
        resolved["sha256"] = sha256_file(path)
        return resolved

    if not path.exists() or not path.is_file():
        resolved["issues"].append(f"Missing manifest pointer file: {path_value}")
        return resolved
    data = _load_json(path)
    if data is None:
        resolved["issues"].append(f"Invalid manifest JSON: {path_value}")
        return resolved
    pointer_value = str(pointer.get("manifest_pointer", ""))
    try:
        value = _manifest_pointer(data, pointer_value)
    except KeyError:
        resolved["issues"].append(f"Manifest pointer not found: {pointer_value}")
        return resolved
    resolved["resolved"] = True
    resolved["value"] = value
    resolved["sha256"] = sha256_file(path)
    if isinstance(value, str):
        target = _resolve_path(repo_root, paper_dir, value)
        if target.exists():
            resolved["target_path"] = str(target.relative_to(repo_root))
            if target.is_file():
                resolved["target_sha256"] = sha256_file(target)
        else:
            resolved["issues"].append(f"Manifest target does not exist: {value}")
    declared_run_id = pointer.get("run_id")
    if isinstance(declared_run_id, str) and declared_run_id:
        path_parts = path.parts
        if "runs" in path_parts:
            runs_index = path_parts.index("runs")
            if runs_index + 1 < len(path_parts):
                current_run_id = path_parts[runs_index + 1]
                if declared_run_id != current_run_id:
                    resolved["stale"] = True
                    resolved["issues"].append(
                        f"run_id mismatch: declared={declared_run_id}, current={current_run_id}"
                    )
    return resolved


def build_provenance_ledger(
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
    expected_source_ids = expected_source_ids_from_brief(brief)
    provenance_file = provenance_path(paper_dir)
    provenance = {"paper_id": paper_id, "sources": []}
    schema_errors: list[str] = []
    if provenance_file.exists():
        provenance = load_provenance(provenance_file)
        schema_errors = validate_provenance_data(provenance, brief)

    sources = provenance.get("sources", [])
    source_map = {
        source["source_id"]: source
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    evidence_ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)

    entries: list[dict[str, Any]] = []
    unresolved_sources: list[str] = []
    unavailable_sources: list[str] = []
    stale_sources: list[str] = []
    policy_violations: list[str] = []
    missing_required_sources = [
        source_id for source_id in expected_source_ids if source_id not in source_map
    ]
    forbidden_substitutes: list[str] = []
    claim_provenance_gaps: list[str] = []

    source_to_claims: dict[str, list[str]] = {source_id: [] for source_id in expected_source_ids}
    for claim_id, spec in claim_specs.items():
        for source_id in spec.get("source_ids", []) if isinstance(spec.get("source_ids"), list) else []:
            source_to_claims.setdefault(source_id, []).append(claim_id)

    for source_id, source in source_map.items():
        pointers = source.get("pointers", [])
        resolved_pointers = []
        if isinstance(pointers, list):
            resolved_pointers = [
                _resolve_pointer(repo_root, paper_dir, pointer)
                for pointer in pointers
                if isinstance(pointer, dict)
            ]
        issues = [issue for pointer in resolved_pointers for issue in pointer.get("issues", [])]
        policy = _policy_issues(source)
        dependent_claims = source_to_claims.get(source_id, [])
        is_stale = source.get("status") == "stale" or any(
            bool(pointer.get("stale")) for pointer in resolved_pointers
        )
        if issues:
            unresolved_sources.append(source_id)
        if source.get("status") == "unavailable":
            unavailable_sources.append(source_id)
        if is_stale:
            stale_sources.append(source_id)
        if policy:
            policy_violations.append(f"{source_id}: {'; '.join(policy)}")
        entries.append(
            {
                "source_id": source_id,
                "title": source.get("title"),
                "source_type": source.get("source_type"),
                "acquisition_mode": source.get("acquisition_mode"),
                "status": source.get("status"),
                "reproducibility_level": source.get("reproducibility_level"),
                "license_note": source.get("license_note"),
                "snapshot": source.get("snapshot"),
                "note": source.get("note"),
                "resolved_pointers": resolved_pointers,
                "stale": is_stale,
                "policy_issues": policy,
                "dependent_claims": dependent_claims,
                "issues": issues,
            }
        )

    admissible_sources = {
        entry["source_id"]
        for entry in entries
        if entry["status"] in {"acquired", "verified"}
        and not entry["stale"]
        and not entry["issues"]
        and not entry["policy_issues"]
    }

    for claim_entry in evidence_ledger.get("entries", []):
        claim_id = str(claim_entry.get("claim_id"))
        spec = claim_specs.get(claim_id, {})
        expected_for_claim = spec.get("source_ids", [])
        if not isinstance(expected_for_claim, list):
            expected_for_claim = []
        if claim_entry.get("status") in {"supported", "qualified"} and expected_for_claim:
            missing = [source_id for source_id in expected_for_claim if source_id not in admissible_sources]
            if missing:
                claim_provenance_gaps.append(f"{claim_id}: {', '.join(missing)}")

        prohibited = spec.get("prohibited_substitutes", [])
        if not isinstance(prohibited, list):
            prohibited = []
        for source_id in expected_for_claim:
            source = source_map.get(source_id)
            if source is None:
                continue
            source_type = source.get("source_type")
            acquisition_mode = source.get("acquisition_mode")
            if source_id in prohibited or source_type in prohibited or acquisition_mode in prohibited:
                forbidden_substitutes.append(f"{claim_id}: {source_id}")

    summary = {
        "sources": len(entries),
        "verified": sum(1 for entry in entries if entry["status"] == "verified"),
        "acquired": sum(1 for entry in entries if entry["status"] == "acquired"),
        "declared": sum(1 for entry in entries if entry["status"] == "declared"),
        "stale": sum(1 for entry in entries if entry["stale"]),
        "unavailable": sum(1 for entry in entries if entry["status"] == "unavailable"),
    }
    ledger = {
        "paper_id": paper_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance_path": str(provenance_file.relative_to(repo_root)),
        "entries": entries,
        "summary": summary,
        "validation": {
            "schema_errors": schema_errors,
            "missing_required_sources": missing_required_sources,
            "unresolved_sources": unresolved_sources,
            "unavailable_sources": unavailable_sources,
            "stale_sources": stale_sources,
            "policy_violations": policy_violations,
            "forbidden_substitutes": forbidden_substitutes,
            "claim_provenance_gaps": claim_provenance_gaps,
        },
    }

    if write_output:
        out_path = provenance_ledger_path(repo_root, paper_id)
        ensure_dir(out_path.parent)
        write_json(out_path, ledger)
        manifest_path = paper_dir / "auto" / "MANIFEST.json"
        manifest_data = _load_json(manifest_path)
        if manifest_data is not None:
            generated = manifest_data.get("generated")
            if not isinstance(generated, dict):
                generated = {}
                manifest_data["generated"] = generated
            generated["provenance_ledger"] = {
                "path": str(out_path.relative_to(repo_root)),
                "summary": summary,
            }
            write_json(manifest_path, manifest_data)
    return ledger


def render_provenance_report(ledger: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(ledger, indent=2, sort_keys=True) + "\n"
    if output_format == "md":
        lines = [
            f"# Provenance Report: {ledger['paper_id']}",
            "",
            "## Summary",
            f"- sources: {ledger['summary']['sources']}",
            f"- verified: {ledger['summary']['verified']}",
            f"- acquired: {ledger['summary']['acquired']}",
            f"- declared: {ledger['summary']['declared']}",
            f"- stale: {ledger['summary']['stale']}",
            f"- unavailable: {ledger['summary']['unavailable']}",
            "",
            "## Sources",
        ]
        for entry in ledger["entries"]:
            lines.append(
                f"- {entry['source_id']}: {entry['status']} / {entry['reproducibility_level']}"
            )
        return "\n".join(lines) + "\n"

    header = "source_id\tstatus\tacquisition_mode\treproducibility_level\tstale\tdependent_claims"
    rows = [header]
    for entry in ledger["entries"]:
        rows.append(
            f"{entry['source_id']}\t{entry['status']}\t{entry['acquisition_mode']}\t"
            f"{entry['reproducibility_level']}\t{entry['stale']}\t"
            f"{','.join(entry['dependent_claims'])}"
        )
    return "\n".join(rows) + "\n"
