from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from truthweave.briefs import load_brief, phase_at_least, validate_brief_data
from truthweave.evidence import build_claim_ledger, claim_ledger_path, evidence_path
from truthweave.provenance import (
    build_provenance_ledger,
    provenance_ledger_path,
    provenance_path,
)
from truthweave.references import (
    load_references,
    lock_path as references_lock_path,
    references_path,
    verify_references,
)
from truthweave.reviews import review_json_path
from truthweave.utils import ensure_dir, sha256_file, write_json
from truthweave.verify import build_verification_report


def packet_dir(repo_root: Path, paper_id: str) -> Path:
    return repo_root / "artifacts" / "packets" / paper_id


def packet_json_path(repo_root: Path, paper_id: str) -> Path:
    return packet_dir(repo_root, paper_id) / "packet.json"


def packet_md_path(repo_root: Path, paper_id: str) -> Path:
    return packet_dir(repo_root, paper_id) / "packet.md"


def packet_claims_csv_path(repo_root: Path, paper_id: str) -> Path:
    return packet_dir(repo_root, paper_id) / "claims.csv"


def packet_sources_csv_path(repo_root: Path, paper_id: str) -> Path:
    return packet_dir(repo_root, paper_id) / "sources.csv"


def packet_rerun_checklist_path(repo_root: Path, paper_id: str) -> Path:
    return packet_dir(repo_root, paper_id) / "rerun_checklist.md"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _review_status(
    repo_root: Path, paper_dir: Path, paper_id: str, phase_status: str
) -> tuple[dict[str, Any] | None, list[dict[str, str]], list[dict[str, str]]]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    path = review_json_path(repo_root, paper_id, "draft_reviewed")
    if not path.exists():
        payload = {
            "status": "missing",
            "path": str(path.relative_to(repo_root)),
            "alignment_score": None,
            "missing_evidence": [],
            "off_thesis_sections": [],
            "revision_actions": [],
        }
        target = blockers if phase_at_least(phase_status, "draft_reviewed") else warnings
        target.append(
            {
                "category": "REVIEW",
                "message": f"Missing draft_reviewed review artifact: {path.relative_to(repo_root)}",
            }
        )
        return payload, blockers, warnings

    review = _load_json(path)
    if review is None:
        blockers.append(
            {
                "category": "REVIEW",
                "message": f"Invalid review JSON: {path.relative_to(repo_root)}",
            }
        )
        return None, blockers, warnings

    stale_paths: list[str] = []
    reviewed_inputs = review.get("reviewed_inputs", {})
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
        blockers.append(
            {
                "category": "REVIEW",
                "message": "Review is stale for: " + ", ".join(stale_paths),
            }
        )

    alignment_score = review.get("alignment_score")
    if not isinstance(alignment_score, (int, float)):
        warnings.append(
            {"category": "REVIEW", "message": "Review alignment_score is missing."}
        )
    elif float(alignment_score) < 0.6:
        blockers.append(
            {
                "category": "REVIEW",
                "message": (
                    f"Thread alignment below expected threshold: {alignment_score:.2f}"
                ),
            }
        )

    payload = {
        "status": "stale" if stale_paths else "current",
        "path": str(path.relative_to(repo_root)),
        "alignment_score": alignment_score,
        "missing_evidence": review.get("missing_evidence", []),
        "off_thesis_sections": review.get("off_thesis_sections", []),
        "revision_actions": review.get("revision_actions", []),
    }
    return payload, blockers, warnings


def _reference_summary(
    repo_root: Path, paper_dir: Path, paper_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    issues = verify_references(repo_root, paper_dir, paper_id)
    for message in issues:
        target = blockers if ("does not match" in message or "Required reference" in message) else warnings
        target.append({"category": "REFERENCES", "message": message})

    lock = _load_json(references_lock_path(repo_root, paper_id))
    if lock is not None:
        entries = lock.get("entries", [])
        if not isinstance(entries, list):
            entries = []
        references = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            metadata = entry.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            references.append(
                {
                    "key": entry.get("key"),
                    "title": metadata.get("title"),
                    "year": metadata.get("year"),
                    "intent": entry.get("intent"),
                    "required": bool(entry.get("required", False)),
                    "status": entry.get("status"),
                    "provider": entry.get("provider"),
                }
            )
        return references, blockers, warnings

    refs_data = load_references(references_path(paper_dir))
    references = []
    for entry in refs_data.get("sources", []):
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        references.append(
            {
                "key": entry.get("key"),
                "title": metadata.get("title"),
                "year": metadata.get("year"),
                "intent": entry.get("intent"),
                "required": bool(entry.get("required", False)),
                "status": "unlocked",
                "provider": "manual",
            }
        )
    if references:
        warnings.append(
            {
                "category": "REFERENCES",
                "message": "Reference lock is missing; packet falls back to references.yml.",
            }
        )
    return references, blockers, warnings


def _source_blocks_rerun(entry: dict[str, Any]) -> bool:
    acquisition_mode = entry.get("acquisition_mode")
    reproducibility_level = entry.get("reproducibility_level")
    status = entry.get("status")
    return bool(
        status == "unavailable"
        or acquisition_mode in {"credential_required", "licensed_restricted"}
        or reproducibility_level in {"manual_step_required", "nonredistributable"}
    )


def _source_blocks_redistribution(entry: dict[str, Any]) -> bool:
    acquisition_mode = entry.get("acquisition_mode")
    reproducibility_level = entry.get("reproducibility_level")
    return bool(
        acquisition_mode in {"credential_required", "licensed_restricted"}
        or reproducibility_level == "nonredistributable"
    )


def _packet_reviewed_inputs(
    repo_root: Path, paper_dir: Path, paper_id: str
) -> dict[str, dict[str, str]]:
    reviewed_inputs: dict[str, dict[str, str]] = {}
    for label, path in {
        "brief_yml": paper_dir / "brief.yml",
        "evidence_yml": evidence_path(paper_dir),
        "data_sources_yml": provenance_path(paper_dir),
        "references_yml": references_path(paper_dir),
        "refs_bib": paper_dir / "refs.bib",
        "main_tex": paper_dir / "main.tex",
        "claim_ledger": claim_ledger_path(repo_root, paper_id),
        "provenance_ledger": provenance_ledger_path(repo_root, paper_id),
        "review_json": review_json_path(repo_root, paper_id, "draft_reviewed"),
        "references_lock": references_lock_path(repo_root, paper_id),
    }.items():
        if path.exists():
            reviewed_inputs[label] = {
                "path": str(path.relative_to(repo_root)),
                "sha256": sha256_file(path),
            }
    return reviewed_inputs


def build_reviewer_packet(
    repo_root: Path,
    paper_dir: Path,
    paper_id: str,
    write_output: bool = False,
) -> dict[str, Any]:
    brief = load_brief(paper_dir / "brief.yml")
    brief_errors = validate_brief_data(brief)
    if brief_errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(brief_errors))

    claim_ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)
    provenance_ledger = build_provenance_ledger(
        repo_root, paper_dir, paper_id, write_output=False
    )
    references, reference_blockers, reference_warnings = _reference_summary(
        repo_root, paper_dir, paper_id
    )
    review, review_blockers, review_warnings = _review_status(
        repo_root, paper_dir, paper_id, str(brief.get("phase_status"))
    )
    verification = build_verification_report(
        repo_root, paper_dir, paper_id, write_output=False
    )

    source_entries = provenance_ledger.get("entries", [])
    if not isinstance(source_entries, list):
        source_entries = []
    source_map = {
        str(entry.get("source_id")): entry
        for entry in source_entries
        if isinstance(entry, dict) and isinstance(entry.get("source_id"), str)
    }

    claim_entries = claim_ledger.get("entries", [])
    if not isinstance(claim_entries, list):
        claim_entries = []
    claims: list[dict[str, Any]] = []
    for entry in claim_entries:
        if not isinstance(entry, dict):
            continue
        source_ids = entry.get("source_ids", [])
        if not isinstance(source_ids, list):
            source_ids = []
        claims.append(
            {
                "claim_id": entry.get("claim_id"),
                "required": bool(entry.get("required", False)),
                "status": entry.get("status"),
                "stale": bool(entry.get("stale", False)),
                "description": entry.get("description"),
                "note": entry.get("note"),
                "expected_metrics": entry.get("expected_metrics", []),
                "source_ids": source_ids,
                "source_states": [
                    {
                        "source_id": source_id,
                        "status": source_map.get(source_id, {}).get("status"),
                        "reproducibility_level": source_map.get(source_id, {}).get(
                            "reproducibility_level"
                        ),
                    }
                    for source_id in source_ids
                ],
                "evidence_pointers": entry.get("evidence_pointers", []),
                "resolved_artifacts": entry.get("resolved_artifacts", []),
                "issues": entry.get("issues", []),
            }
        )

    sources: list[dict[str, Any]] = []
    for entry in source_entries:
        if not isinstance(entry, dict):
            continue
        sources.append(
            {
                "source_id": entry.get("source_id"),
                "title": entry.get("title"),
                "source_type": entry.get("source_type"),
                "acquisition_mode": entry.get("acquisition_mode"),
                "status": entry.get("status"),
                "reproducibility_level": entry.get("reproducibility_level"),
                "license_note": entry.get("license_note"),
                "stale": bool(entry.get("stale", False)),
                "resolved_pointers": entry.get("resolved_pointers", []),
                "dependent_claims": entry.get("dependent_claims", []),
                "blocks_local_rerun": _source_blocks_rerun(entry),
                "blocks_redistribution": _source_blocks_redistribution(entry),
                "policy_issues": entry.get("policy_issues", []),
                "issues": entry.get("issues", []),
            }
        )

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    claim_validation = claim_ledger.get("validation", {})
    provenance_validation = provenance_ledger.get("validation", {})
    for category, field, label in [
        ("CLAIMS", "schema_errors", "Claim schema errors"),
        ("CLAIMS", "required_missing", "Required claims missing evidence"),
        ("CLAIMS", "unsupported_major", "Required claims explicitly unsupported"),
        ("CLAIMS", "unresolved_claims", "Claim evidence pointers unresolved"),
        ("CLAIMS", "stale_claims", "Claim evidence stale"),
        ("CLAIMS", "orphan_claim_ids", "Orphan evidence entries"),
        ("SOURCES", "schema_errors", "Source schema errors"),
        ("SOURCES", "missing_required_sources", "Required sources missing"),
        ("SOURCES", "unresolved_sources", "Source pointers unresolved"),
        ("SOURCES", "unavailable_sources", "Unavailable sources"),
        ("SOURCES", "stale_sources", "Stale sources"),
        ("SOURCES", "policy_violations", "Source policy violations"),
        ("SOURCES", "forbidden_substitutes", "Forbidden substitutes in use"),
        ("SOURCES", "claim_provenance_gaps", "Claims lack admissible source coverage"),
    ]:
        values = (
            claim_validation.get(field, [])
            if category == "CLAIMS"
            else provenance_validation.get(field, [])
        )
        if isinstance(values, list) and values:
            blockers.append(
                {
                    "category": category,
                    "message": f"{label}: {', '.join(str(value) for value in values)}",
                }
            )

    blockers.extend(reference_blockers)
    warnings.extend(reference_warnings)
    blockers.extend(review_blockers)
    warnings.extend(review_warnings)

    optional_claims = [
        claim["claim_id"] for claim in claims if not bool(claim.get("required", False))
    ]
    qualified_claims = [
        claim["claim_id"] for claim in claims if claim.get("status") == "qualified"
    ]
    stale_claims = [claim["claim_id"] for claim in claims if bool(claim.get("stale", False))]
    unresolved_claims = [
        claim["claim_id"] for claim in claims if isinstance(claim.get("issues"), list) and claim["issues"]
    ]
    restricted_sources = [
        source["source_id"] for source in sources if bool(source.get("blocks_redistribution", False))
    ]
    manual_step_sources = [
        source["source_id"]
        for source in sources
        if source.get("reproducibility_level") == "manual_step_required"
    ]
    synthetic_sources = [
        source["source_id"] for source in sources if source_map.get(source["source_id"], {}).get("source_type") == "synthetic"
    ]

    warnings.extend(
        {"category": "CLAIMS", "message": f"Qualified claim: {claim_id}"}
        for claim_id in qualified_claims
    )
    warnings.extend(
        {"category": "CLAIMS", "message": f"Optional claim: {claim_id}"}
        for claim_id in optional_claims
    )
    warnings.extend(
        {"category": "SOURCES", "message": f"Restricted redistribution: {source_id}"}
        for source_id in restricted_sources
    )
    warnings.extend(
        {"category": "SOURCES", "message": f"Manual step required: {source_id}"}
        for source_id in manual_step_sources
    )

    reproducibility = {
        "local_rerun_commands": [
            "uv sync",
            "make run",
            f"uv run truthweave build-paper-assets --paper {paper_id}",
            f"uv run truthweave sync-refs --paper {paper_id}",
            f"uv run truthweave provenance-report --paper {paper_id} --format md",
            f"uv run truthweave claim-report --paper {paper_id} --format md",
            f"uv run truthweave review-thread --paper {paper_id} --phase draft_reviewed --format md",
            f"uv run truthweave reviewer-packet --paper {paper_id} --format md",
            f"uv run truthweave check --paper {paper_id} --mode ci",
            f"uv run truthweave build-paper --paper {paper_id}",
        ],
        "manual_step_required_sources": manual_step_sources,
        "restricted_sources": restricted_sources,
        "synthetic_sources": synthetic_sources,
        "partially_reproducible_sources": [
            source["source_id"]
            for source in sources
            if source.get("reproducibility_level") == "partially_reproducible"
        ],
        "notes": [
            "Local rerun commands are deterministic repo-local commands inferred from current TruthWeave workflow."
        ],
    }

    restricted_notes = [
        f"{source['source_id']}: acquisition_mode={source['acquisition_mode']}, reproducibility_level={source['reproducibility_level']}"
        for source in sources
        if bool(source.get("blocks_local_rerun", False))
        or bool(source.get("blocks_redistribution", False))
    ]

    reviewed_inputs = _packet_reviewed_inputs(repo_root, paper_dir, paper_id)
    readiness = "blocked" if blockers else ("qualified" if warnings else "ready")
    summary = {
        "claims_total": len(claims),
        "required_claims": sum(1 for claim in claims if bool(claim.get("required", False))),
        "supported_claims": sum(1 for claim in claims if claim.get("status") == "supported"),
        "qualified_claims": len(qualified_claims),
        "optional_claims": len(optional_claims),
        "sources_total": len(sources),
        "manual_step_sources": len(manual_step_sources),
        "restricted_sources": len(restricted_sources),
        "reference_entries": len(references),
        "overall_blockers": len(blockers),
        "overall_warnings": len(warnings),
        "verifiable_required_claims": verification.get("summary", {}).get(
            "verifiable_required_claims", 0
        ),
        "verified_required_claims": verification.get("summary", {}).get(
            "verified_required_claims", 0
        ),
        "verification_blocked": verification.get("summary", {}).get("blocked", 0),
        "missing_verification_metadata": verification.get("summary", {}).get(
            "missing_verification_metadata", 0
        ),
    }

    packet = {
        "paper": {
            "paper_id": paper_id,
            "phase_status": brief.get("phase_status"),
            "central_claim": brief.get("central_claim"),
            "so_what": brief.get("so_what"),
            "novelty": brief.get("novelty"),
            "target_reader": brief.get("target_reader"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "readiness": readiness,
        },
        "summary": summary,
        "blockers": blockers,
        "warnings": warnings,
        "claims": claims,
        "sources": sources,
        "references": references,
        "review": review,
        "verification": {
            "summary": verification.get("summary", {}),
            "failed_required_targets": verification.get("validation", {}).get(
                "failed_required_targets", []
            ),
            "missing_verification_claims": verification.get("validation", {}).get(
                "missing_verification_claims", []
            ),
        },
        "reproducibility": reproducibility,
        "risks": {
            "qualified_claims": qualified_claims,
            "optional_claims": optional_claims,
            "stale_claims": stale_claims,
            "stale_sources": provenance_validation.get("stale_sources", []),
            "unresolved_claims": unresolved_claims,
            "unresolved_sources": provenance_validation.get("unresolved_sources", []),
            "failed_required_verification_targets": verification.get("validation", {}).get(
                "failed_required_targets", []
            ),
            "restricted_reproducibility_notes": restricted_notes,
        },
        "reviewed_inputs": reviewed_inputs,
    }

    if write_output:
        out_dir = packet_dir(repo_root, paper_id)
        ensure_dir(out_dir)
        write_json(packet_json_path(repo_root, paper_id), packet)
        packet_md_path(repo_root, paper_id).write_text(render_packet(packet, "md"))
        _write_claims_csv(packet_claims_csv_path(repo_root, paper_id), claims)
        _write_sources_csv(packet_sources_csv_path(repo_root, paper_id), sources)
        packet_rerun_checklist_path(repo_root, paper_id).write_text(
            _render_rerun_checklist(packet)
        )
        manifest_path = paper_dir / "auto" / "MANIFEST.json"
        manifest = _load_json(manifest_path)
        if manifest is not None:
            generated = manifest.get("generated")
            if not isinstance(generated, dict):
                generated = {}
                manifest["generated"] = generated
            generated["reviewer_packet"] = {
                "path": str(packet_json_path(repo_root, paper_id).relative_to(repo_root)),
                "markdown_path": str(packet_md_path(repo_root, paper_id).relative_to(repo_root)),
                "claims_csv_path": str(
                    packet_claims_csv_path(repo_root, paper_id).relative_to(repo_root)
                ),
                "sources_csv_path": str(
                    packet_sources_csv_path(repo_root, paper_id).relative_to(repo_root)
                ),
                "summary": summary,
            }
            write_json(manifest_path, manifest)
    return packet


def _write_claims_csv(path: Path, claims: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "claim_id",
                "required",
                "status",
                "stale",
                "source_ids",
                "evidence_items",
                "resolved_artifacts",
            ]
        )
        for claim in claims:
            resolved = claim.get("resolved_artifacts", [])
            if not isinstance(resolved, list):
                resolved = []
            writer.writerow(
                [
                    claim.get("claim_id"),
                    claim.get("required"),
                    claim.get("status"),
                    claim.get("stale"),
                    ";".join(str(source_id) for source_id in claim.get("source_ids", [])),
                    len(claim.get("evidence_pointers", [])),
                    ";".join(
                        str(item.get("resolved_path", item.get("artifact_path", "")))
                        for item in resolved
                        if isinstance(item, dict)
                    ),
                ]
            )


def _write_sources_csv(path: Path, sources: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "source_id",
                "status",
                "acquisition_mode",
                "reproducibility_level",
                "stale",
                "blocks_local_rerun",
                "blocks_redistribution",
                "dependent_claims",
            ]
        )
        for source in sources:
            writer.writerow(
                [
                    source.get("source_id"),
                    source.get("status"),
                    source.get("acquisition_mode"),
                    source.get("reproducibility_level"),
                    source.get("stale"),
                    source.get("blocks_local_rerun"),
                    source.get("blocks_redistribution"),
                    ";".join(str(value) for value in source.get("dependent_claims", [])),
                ]
            )


def _render_rerun_checklist(packet: dict[str, Any]) -> str:
    lines = [
        f"# Rerun Checklist: {packet['paper']['paper_id']}",
        "",
        "## Commands",
    ]
    for command in packet.get("reproducibility", {}).get("local_rerun_commands", []):
        lines.append(f"- [ ] `{command}`")
    manual = packet.get("reproducibility", {}).get("manual_step_required_sources", [])
    restricted = packet.get("reproducibility", {}).get("restricted_sources", [])
    if manual:
        lines.extend(["", "## Manual Steps"])
        for source_id in manual:
            lines.append(f"- [ ] Review manual acquisition notes for `{source_id}`")
    if restricted:
        lines.extend(["", "## Restricted Sources"])
        for source_id in restricted:
            lines.append(f"- [ ] Confirm redistribution/access policy for `{source_id}`")
    return "\n".join(lines) + "\n"


def render_packet(packet: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(packet, indent=2, sort_keys=True) + "\n"
    if output_format == "md":
        lines = [
            f"# Reviewer Packet: {packet['paper']['paper_id']}",
            "",
            "## Paper Summary",
            f"- phase: {packet['paper']['phase_status']}",
            f"- readiness: {packet['paper']['readiness']}",
            f"- central claim: {packet['paper']['central_claim']}",
            f"- so what: {packet['paper']['so_what']}",
            f"- blockers: {packet['summary']['overall_blockers']}",
            f"- warnings: {packet['summary']['overall_warnings']}",
            "",
            "## Claims",
        ]
        for claim in packet.get("claims", []):
            if not isinstance(claim, dict):
                continue
            lines.append(
                f"- {claim['claim_id']}: status={claim['status']}, required={claim['required']}, "
                f"sources={','.join(str(value) for value in claim.get('source_ids', [])) or '(none)'}"
            )
        lines.extend(["", "## Sources"])
        for source in packet.get("sources", []):
            if not isinstance(source, dict):
                continue
            lines.append(
                f"- {source['source_id']}: status={source['status']}, "
                f"acquisition_mode={source['acquisition_mode']}, "
                f"reproducibility={source['reproducibility_level']}"
            )
        lines.extend(["", "## References"])
        for ref in packet.get("references", []):
            if not isinstance(ref, dict):
                continue
            lines.append(
                f"- {ref.get('key')}: {ref.get('title')} ({ref.get('year')}) [{ref.get('status')}]"
            )
        lines.extend(["", "## Reproducibility"])
        for command in packet.get("reproducibility", {}).get("local_rerun_commands", []):
            lines.append(f"- `{command}`")
        lines.extend(["", "## Verification"])
        verification = packet.get("verification", {})
        if isinstance(verification, dict):
            summary = verification.get("summary", {})
            if isinstance(summary, dict):
                lines.append(
                    f"- verifiable_required_claims: {summary.get('verifiable_required_claims', 0)}"
                )
                lines.append(
                    f"- verified_required_claims: {summary.get('verified_required_claims', 0)}"
                )
                lines.append(
                    f"- missing_verification_metadata: {summary.get('missing_verification_metadata', 0)}"
                )
        lines.extend(["", "## Risks"])
        for section, values in packet.get("risks", {}).items():
            if isinstance(values, list) and values:
                lines.append(f"- {section}: {', '.join(str(value) for value in values)}")
        if packet.get("blockers"):
            lines.extend(["", "## Blockers"])
            for blocker in packet["blockers"]:
                lines.append(f"- [{blocker['category']}] {blocker['message']}")
        if packet.get("warnings"):
            lines.extend(["", "## Warnings"])
            for warning in packet["warnings"]:
                lines.append(f"- [{warning['category']}] {warning['message']}")
        return "\n".join(lines) + "\n"

    header = "paper_id\treadiness\tclaims\tsources\tblockers\twarnings"
    summary = packet.get("summary", {})
    row = (
        f"{packet['paper']['paper_id']}\t{packet['paper']['readiness']}\t"
        f"{summary.get('claims_total', 0)}\t{summary.get('sources_total', 0)}\t"
        f"{summary.get('overall_blockers', 0)}\t{summary.get('overall_warnings', 0)}"
    )
    return header + "\n" + row + "\n"
