from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from truthweave.briefs import claim_specs_from_brief, load_brief, validate_brief_data
from truthweave.utils import ensure_dir, sha256_file, write_json


EVIDENCE_STATUSES = {"supported", "qualified", "unsupported", "stale", "missing"}
EVIDENCE_KINDS = {"variable", "artifact", "figure", "table", "manifest"}


def evidence_path(paper_dir: Path) -> Path:
    return paper_dir / "evidence.yml"


def claim_ledger_path(repo_root: Path, paper_id: str) -> Path:
    return repo_root / "artifacts" / "claims" / paper_id / "claim_ledger.json"


def default_evidence(paper_id: str, brief: dict[str, Any]) -> dict[str, Any]:
    claims: list[dict[str, Any]] = []
    for claim_id, spec in claim_specs_from_brief(brief).items():
        items = []
        expected_metrics = spec.get("expected_metrics", [])
        if isinstance(expected_metrics, list):
            for metric in expected_metrics:
                if isinstance(metric, str) and metric:
                    items.append(
                        {
                            "kind": "variable",
                            "artifact_path": "auto/variables.tex",
                            "variable": metric,
                            "source_ids": spec.get("source_ids", []),
                            "note": "Bind this claim to the generated variable once verified.",
                        }
                    )
        items.append(
            {
                "kind": "manifest",
                "artifact_path": "auto/MANIFEST.json",
                "manifest_pointer": "source.metrics_json_path",
                "source_ids": spec.get("source_ids", []),
                "note": "Points to the concrete metrics artifact behind the paper asset.",
            }
        )
        claims.append(
            {
                "claim_id": claim_id,
                "status": "missing",
                "note": str(spec.get("description", "")),
                "evidence": items,
            }
        )
    return {"paper_id": paper_id, "claims": claims}


def load_evidence(path: Path) -> dict[str, Any]:
    cfg = OmegaConf.load(path)
    data = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid evidence.yml at {path}")
    return data


def save_evidence(path: Path, data: dict[str, Any]) -> None:
    OmegaConf.save(OmegaConf.create(data), path)


def _resolve_path(repo_root: Path, paper_dir: Path, artifact_path: str) -> Path:
    candidate = Path(artifact_path)
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


def _load_manifest(paper_dir: Path) -> dict[str, Any]:
    return _load_json(paper_dir / "auto" / "MANIFEST.json") or {}


def _manifest_pointer(data: dict[str, Any], pointer: str) -> Any:
    current: Any = data
    for part in pointer.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(pointer)
        current = current[part]
    return current


def _extract_variable_value(variables_path: Path, variable: str) -> str | None:
    if not variables_path.exists():
        return None
    pattern = re.compile(r"\\newcommand\{\\%s\}\{([^}]*)\}" % re.escape(variable))
    match = pattern.search(variables_path.read_text())
    if not match:
        return None
    return match.group(1)


def validate_evidence_data(
    evidence: dict[str, Any], brief: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence.get("paper_id"), str) or not evidence["paper_id"].strip():
        errors.append("Missing or empty field: paper_id")

    claims = evidence.get("claims")
    if not isinstance(claims, list):
        return errors + ["evidence.yml must contain a claims list"]

    brief_claims = claim_specs_from_brief(brief)
    seen: set[str] = set()
    for idx, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claims[{idx}] must be a mapping")
            continue
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            errors.append(f"claims[{idx}].claim_id must be a non-empty string")
            continue
        if claim_id in seen:
            errors.append(f"Duplicate evidence entry for claim_id: {claim_id}")
        seen.add(claim_id)
        if claim_id not in brief_claims:
            errors.append(f"Unknown claim_id in evidence.yml: {claim_id}")

        status = claim.get("status")
        if status not in EVIDENCE_STATUSES:
            errors.append(
                f"claims[{idx}].status must be one of: {', '.join(sorted(EVIDENCE_STATUSES))}"
            )
        note = claim.get("note")
        if note is not None and not isinstance(note, str):
            errors.append(f"claims[{idx}].note must be a string")

        items = claim.get("evidence", [])
        if items is None:
            items = []
        if not isinstance(items, list):
            errors.append(f"claims[{idx}].evidence must be a list")
            continue
        if status in {"supported", "qualified", "stale"} and not items:
            errors.append(
                f"claims[{idx}] with status {status} must include at least one evidence item"
            )

        for item_idx, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"claims[{idx}].evidence[{item_idx}] must be a mapping")
                continue
            kind = item.get("kind")
            if kind not in EVIDENCE_KINDS:
                errors.append(
                    f"claims[{idx}].evidence[{item_idx}].kind must be one of: "
                    + ", ".join(sorted(EVIDENCE_KINDS))
                )
            artifact_path = item.get("artifact_path")
            if artifact_path is not None and not isinstance(artifact_path, str):
                errors.append(
                    f"claims[{idx}].evidence[{item_idx}].artifact_path must be a string"
                )
            if kind == "variable":
                variable = item.get("variable")
                if not isinstance(variable, str) or not variable:
                    errors.append(
                        f"claims[{idx}].evidence[{item_idx}].variable is required for variable evidence"
                    )
            if kind == "manifest":
                pointer = item.get("manifest_pointer")
                if not isinstance(pointer, str) or not pointer:
                    errors.append(
                        f"claims[{idx}].evidence[{item_idx}].manifest_pointer is required for manifest evidence"
                    )
            if kind in {"artifact", "figure", "table"} and not isinstance(
                artifact_path, str
            ):
                errors.append(
                    f"claims[{idx}].evidence[{item_idx}].artifact_path is required for {kind} evidence"
                )
            run_id = item.get("run_id")
            if run_id is not None and (not isinstance(run_id, str) or not run_id):
                errors.append(
                    f"claims[{idx}].evidence[{item_idx}].run_id must be a non-empty string"
                )
            source_ids = item.get("source_ids")
            if source_ids is not None and (
                not isinstance(source_ids, list)
                or any(
                    not isinstance(source_id, str) or not source_id
                    for source_id in source_ids
                )
            ):
                errors.append(
                    f"claims[{idx}].evidence[{item_idx}].source_ids must be a list of strings"
                )
            item_note = item.get("note")
            if item_note is not None and not isinstance(item_note, str):
                errors.append(
                    f"claims[{idx}].evidence[{item_idx}].note must be a string"
                )

    return errors


def _current_run_id(manifest: dict[str, Any]) -> str | None:
    run_dir = manifest.get("source", {}).get("run_dir")
    if not isinstance(run_dir, str) or not run_dir:
        return None
    return Path(run_dir).name


def _resolve_item(
    repo_root: Path,
    paper_dir: Path,
    manifest: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    kind = str(item.get("kind"))
    artifact_path = str(item.get("artifact_path", ""))
    if kind == "variable" and not artifact_path:
        artifact_path = "auto/variables.tex"
    if kind == "manifest" and not artifact_path:
        artifact_path = "auto/MANIFEST.json"

    resolved: dict[str, Any] = {
        "kind": kind,
        "artifact_path": artifact_path,
        "manifest_pointer": item.get("manifest_pointer"),
        "run_id": item.get("run_id"),
        "source_ids": item.get("source_ids", []),
        "note": item.get("note"),
        "resolved": False,
        "stale": False,
        "issues": [],
    }

    path = _resolve_path(repo_root, paper_dir, artifact_path) if artifact_path else None
    if path is not None:
        resolved["resolved_path"] = str(path.relative_to(repo_root)) if path.exists() else str(path)

    current_run_id = _current_run_id(manifest)
    declared_run_id = item.get("run_id")
    if isinstance(declared_run_id, str) and declared_run_id and current_run_id and declared_run_id != current_run_id:
        resolved["stale"] = True
        resolved["issues"].append(
            f"run_id mismatch: declared={declared_run_id}, current={current_run_id}"
        )

    if kind == "variable":
        if path is None or not path.exists():
            resolved["issues"].append(f"Missing variable artifact: {artifact_path}")
            return resolved
        variable = str(item.get("variable", ""))
        value = _extract_variable_value(path, variable)
        if value is None:
            resolved["issues"].append(
                f"Variable \\{variable} not found in {path.relative_to(repo_root)}"
            )
            return resolved
        resolved["resolved"] = True
        resolved["variable"] = variable
        resolved["value"] = value
        resolved["sha256"] = sha256_file(path)
        return resolved

    if kind == "manifest":
        if path is None or not path.exists():
            resolved["issues"].append(f"Missing manifest artifact: {artifact_path}")
            return resolved
        manifest_data = _load_json(path)
        if manifest_data is None:
            resolved["issues"].append(f"Invalid manifest JSON: {artifact_path}")
            return resolved
        pointer = str(item.get("manifest_pointer", ""))
        try:
            value = _manifest_pointer(manifest_data, pointer)
        except KeyError:
            resolved["issues"].append(f"Manifest pointer not found: {pointer}")
            return resolved
        resolved["resolved"] = True
        resolved["value"] = value
        resolved["sha256"] = sha256_file(path)
        if isinstance(value, str):
            target = _resolve_path(repo_root, paper_dir, value)
            if target.exists():
                resolved["target_path"] = str(target.relative_to(repo_root))
                resolved["target_sha256"] = sha256_file(target)
            else:
                resolved["issues"].append(f"Manifest target does not exist: {value}")
        return resolved

    if path is None or not path.exists():
        resolved["issues"].append(f"Missing artifact: {artifact_path}")
        return resolved
    resolved["resolved"] = True
    resolved["sha256"] = sha256_file(path)
    parts = path.parts
    if (
        kind in {"artifact", "figure", "table"}
        and current_run_id
        and "runs" in parts
        and declared_run_id is None
    ):
        runs_index = parts.index("runs")
        if runs_index + 1 < len(parts):
            artifact_run_id = parts[runs_index + 1]
            if artifact_run_id != current_run_id:
                resolved["stale"] = True
                resolved["issues"].append(
                    f"artifact points to {artifact_run_id}, current manifest uses {current_run_id}"
                )
    return resolved


def build_claim_ledger(
    repo_root: Path,
    paper_dir: Path,
    paper_id: str,
    write_output: bool = False,
) -> dict[str, Any]:
    brief = load_brief(paper_dir / "brief.yml")
    brief_errors = validate_brief_data(brief)
    if brief_errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(brief_errors))

    brief_claims = claim_specs_from_brief(brief)
    manifest = _load_manifest(paper_dir)
    path = evidence_path(paper_dir)
    evidence_data = {"paper_id": paper_id, "claims": []}
    schema_errors: list[str] = []
    orphan_claim_ids: list[str] = []
    if path.exists():
        evidence_data = load_evidence(path)
        schema_errors = validate_evidence_data(evidence_data, brief)
        orphan_claim_ids = [
            str(claim.get("claim_id"))
            for claim in evidence_data.get("claims", [])
            if isinstance(claim, dict)
            and isinstance(claim.get("claim_id"), str)
            and claim["claim_id"] not in brief_claims
        ]

    evidence_claims = {
        claim["claim_id"]: claim
        for claim in evidence_data.get("claims", [])
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    entries: list[dict[str, Any]] = []
    required_missing: list[str] = []
    unsupported_major: list[str] = []
    unresolved_claims: list[str] = []
    stale_claims: list[str] = []
    for claim_id, spec in brief_claims.items():
        claim = evidence_claims.get(claim_id)
        required = bool(spec.get("required", True))
        declared_status = "missing" if claim is None else str(claim.get("status", "missing"))
        item_defs = []
        if claim is not None:
            raw_items = claim.get("evidence", [])
            if isinstance(raw_items, list):
                item_defs = [item for item in raw_items if isinstance(item, dict)]

        resolved_items = [
            _resolve_item(repo_root, paper_dir, manifest, item) for item in item_defs
        ]
        has_resolution_errors = any(item["issues"] for item in resolved_items)
        has_stale = any(bool(item["stale"]) for item in resolved_items)
        blocking_missing = claim is None or (declared_status in {"supported", "qualified"} and not resolved_items)

        final_status = declared_status
        if claim is None:
            final_status = "missing"
        elif declared_status == "stale" or has_stale:
            final_status = "stale"
        elif has_resolution_errors:
            final_status = "missing"
        elif declared_status not in EVIDENCE_STATUSES:
            final_status = "missing"

        if required and final_status == "missing":
            required_missing.append(claim_id)
        if required and final_status == "unsupported":
            unsupported_major.append(claim_id)
        if has_resolution_errors:
            unresolved_claims.append(claim_id)
        if final_status == "stale":
            stale_claims.append(claim_id)

        entries.append(
            {
                "claim_id": claim_id,
                "required": required,
                "description": spec.get("description"),
                "expected_metrics": spec.get("expected_metrics", []),
                "source_ids": spec.get("source_ids", []),
                "declared_status": declared_status,
                "status": final_status,
                "stale": final_status == "stale",
                "note": None if claim is None else claim.get("note"),
                "evidence_pointers": item_defs,
                "resolved_artifacts": resolved_items,
                "issues": [
                    issue
                    for item in resolved_items
                    for issue in item.get("issues", [])
                ],
            }
        )

    summary = {
        "supported": sum(1 for entry in entries if entry["status"] == "supported"),
        "qualified": sum(1 for entry in entries if entry["status"] == "qualified"),
        "unsupported": sum(1 for entry in entries if entry["status"] == "unsupported"),
        "stale": sum(1 for entry in entries if entry["status"] == "stale"),
        "missing": sum(1 for entry in entries if entry["status"] == "missing"),
        "required_claims": sum(1 for spec in brief_claims.values() if spec["required"]),
    }
    ledger = {
        "paper_id": paper_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brief_path": str((paper_dir / "brief.yml").relative_to(repo_root)),
        "evidence_path": str(path.relative_to(repo_root)),
        "manifest_path": str((paper_dir / "auto" / "MANIFEST.json").relative_to(repo_root)),
        "entries": entries,
        "summary": summary,
        "validation": {
            "schema_errors": schema_errors,
            "orphan_claim_ids": orphan_claim_ids,
            "required_missing": required_missing,
            "unsupported_major": unsupported_major,
            "unresolved_claims": unresolved_claims,
            "stale_claims": stale_claims,
        },
    }

    if write_output:
        out_path = claim_ledger_path(repo_root, paper_id)
        ensure_dir(out_path.parent)
        write_json(out_path, ledger)
        manifest_path = paper_dir / "auto" / "MANIFEST.json"
        manifest_data = _load_json(manifest_path)
        if manifest_data is not None:
            generated = manifest_data.get("generated")
            if not isinstance(generated, dict):
                generated = {}
                manifest_data["generated"] = generated
            generated["claim_ledger"] = {
                "path": str(out_path.relative_to(repo_root)),
                "summary": summary,
            }
            write_json(manifest_path, manifest_data)
    return ledger


def render_claim_report(ledger: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(ledger, indent=2, sort_keys=True) + "\n"
    if output_format == "md":
        lines = [
            f"# Claim Report: {ledger['paper_id']}",
            "",
            "## Summary",
            f"- supported: {ledger['summary']['supported']}",
            f"- qualified: {ledger['summary']['qualified']}",
            f"- unsupported: {ledger['summary']['unsupported']}",
            f"- stale: {ledger['summary']['stale']}",
            f"- missing: {ledger['summary']['missing']}",
            "",
            "## Claims",
        ]
        for entry in ledger["entries"]:
            lines.append(f"- {entry['claim_id']}: {entry['status']}")
        return "\n".join(lines) + "\n"

    header = "claim_id\tstatus\trequired\tstale\tevidence_items"
    rows = [header]
    for entry in ledger["entries"]:
        rows.append(
            f"{entry['claim_id']}\t{entry['status']}\t{entry['required']}\t"
            f"{entry['stale']}\t{len(entry['evidence_pointers'])}"
        )
    return "\n".join(rows) + "\n"
