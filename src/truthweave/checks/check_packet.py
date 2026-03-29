from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from truthweave.checks.models import Issue
from truthweave.packet import (
    build_reviewer_packet,
    packet_claims_csv_path,
    packet_json_path,
    packet_md_path,
    packet_rerun_checklist_path,
    packet_sources_csv_path,
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


def _claim_snapshot(packet: dict[str, Any]) -> list[tuple[str, str, bool, bool]]:
    claims = packet.get("claims", [])
    snapshot: list[tuple[str, str, bool, bool]] = []
    if not isinstance(claims, list):
        return snapshot
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        status = claim.get("status")
        if not isinstance(claim_id, str) or not isinstance(status, str):
            continue
        snapshot.append(
            (
                claim_id,
                status,
                bool(claim.get("required", False)),
                bool(claim.get("stale", False)),
            )
        )
    return sorted(snapshot)


def _source_snapshot(packet: dict[str, Any]) -> list[tuple[str, str, str, bool]]:
    sources = packet.get("sources", [])
    snapshot: list[tuple[str, str, str, bool]] = []
    if not isinstance(sources, list):
        return snapshot
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        status = source.get("status")
        reproducibility_level = source.get("reproducibility_level")
        if (
            not isinstance(source_id, str)
            or not isinstance(status, str)
            or not isinstance(reproducibility_level, str)
        ):
            continue
        snapshot.append(
            (
                source_id,
                status,
                reproducibility_level,
                bool(source.get("stale", False)),
            )
        )
    return sorted(snapshot)


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    packet_path = packet_json_path(repo_root, paper_id)
    packet_md = packet_md_path(repo_root, paper_id)
    claims_csv = packet_claims_csv_path(repo_root, paper_id)
    sources_csv = packet_sources_csv_path(repo_root, paper_id)
    checklist = packet_rerun_checklist_path(repo_root, paper_id)
    paths = [
        str(packet_path),
        str(packet_md),
        str(claims_csv),
        str(sources_csv),
        str(checklist),
    ]
    recheck = f"uv run truthweave reviewer-packet --paper {paper_id} --format md"

    if not packet_path.exists():
        issues.append(
            Issue(
                category="PACKET_CONSISTENCY",
                severity="FAIL" if mode == "ci" else "WARN",
                message=f"Missing reviewer packet for {paper_id}.",
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )
        return issues

    packet = _load_json(packet_path)
    if packet is None:
        issues.append(
            Issue(
                category="PACKET_CONSISTENCY",
                severity="FAIL" if mode == "ci" else "WARN",
                message=f"Invalid reviewer packet JSON for {paper_id}.",
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )
        return issues

    missing_outputs = [str(path) for path in [packet_md, claims_csv, sources_csv, checklist] if not path.exists()]
    if missing_outputs:
        issues.append(
            Issue(
                category="PACKET_CONSISTENCY",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Reviewer packet is incomplete; missing outputs: " + ", ".join(missing_outputs),
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )

    stale_paths: list[str] = []
    reviewed_inputs = packet.get("reviewed_inputs", {})
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
                category="PACKET_STALENESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Reviewer packet is stale; upstream inputs changed: " + ", ".join(stale_paths),
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=stale_paths + paths,
            )
        )

    current_packet = build_reviewer_packet(repo_root, paper_dir, paper_id, write_output=False)
    if (
        packet.get("summary") != current_packet.get("summary")
        or _claim_snapshot(packet) != _claim_snapshot(current_packet)
        or _source_snapshot(packet) != _source_snapshot(current_packet)
    ):
        issues.append(
            Issue(
                category="PACKET_CONSISTENCY",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Reviewer packet no longer matches current claim/source state.",
                fix=f"Run: {recheck}",
                recheck=recheck,
                paths=paths,
            )
        )

    return issues
