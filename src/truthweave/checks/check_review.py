from __future__ import annotations

import json
from pathlib import Path

from truthweave.briefs import load_brief, phase_at_least, validate_brief_data
from truthweave.checks.models import Issue
from truthweave.papers import load_paper_config
from truthweave.reviews import review_json_path
from truthweave.utils import sha256_file


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    brief_path = paper_dir / "brief.yml"
    if not brief_path.exists():
        return issues
    brief = load_brief(brief_path)
    if validate_brief_data(brief):
        return issues
    phase_status = str(brief.get("phase_status"))
    review_path = review_json_path(repo_root, paper_id, "draft_reviewed")
    if not review_path.exists():
        if phase_at_least(phase_status, "draft_reviewed"):
            severity = "FAIL" if mode == "ci" else "WARN"
            issues.append(
                Issue(
                    category="REVIEW_STALENESS",
                    severity=severity,
                    message=f"Missing draft_reviewed thread review for {paper_id}.",
                    fix=f"Run: uv run truthweave review-thread --paper {paper_id} --phase draft_reviewed",
                    recheck=f"uv run truthweave check --paper {paper_id} --mode {mode}",
                    paths=[str(review_path)],
                )
            )
        return issues

    review = json.loads(review_path.read_text())
    config = load_paper_config(paper_dir / "truthweave.yml")
    quality = config.get("quality", {})
    thread = quality.get("thread", {}) if isinstance(quality, dict) else {}
    min_alignment_ci = thread.get("min_alignment_ci", 0.6)
    if not isinstance(min_alignment_ci, (int, float)):
        min_alignment_ci = 0.6
    reviewed_inputs = review.get("reviewed_inputs", {})
    stale_paths: list[str] = []
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
        severity = "FAIL" if mode == "ci" and phase_at_least(phase_status, "draft_reviewed") else "WARN"
        issues.append(
            Issue(
                category="REVIEW_STALENESS",
                severity=severity,
                message=(
                    f"Thread review is stale for {paper_id}; inputs changed after review: "
                    + ", ".join(stale_paths)
                ),
                fix=f"Run: uv run truthweave review-thread --paper {paper_id} --phase draft_reviewed",
                recheck=f"uv run truthweave check --paper {paper_id} --mode {mode}",
                paths=stale_paths + [str(review_path)],
            )
        )

    alignment_score = review.get("alignment_score", 0.0)
    severity = "FAIL" if mode == "ci" and phase_at_least(phase_status, "draft_reviewed") else "WARN"
    if not isinstance(alignment_score, (int, float)) or float(alignment_score) < float(
        min_alignment_ci
    ):
        issues.append(
            Issue(
                category="THREAD_COHERENCE",
                severity=severity,
                message=(
                    f"Thread alignment below threshold for {paper_id}: "
                    f"alignment_score={alignment_score} < min_alignment_ci={min_alignment_ci}"
                ),
                fix=(
                    "Revise sections flagged by the thread review so they connect "
                    "back to the central claim."
                ),
                recheck=f"uv run truthweave review-thread --paper {paper_id} --phase draft_reviewed",
                paths=[str(review_path)],
            )
        )
    return issues
