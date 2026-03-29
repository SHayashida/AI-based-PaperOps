from __future__ import annotations

from pathlib import Path

from truthweave.briefs import PHASES, load_brief, validate_brief_data
from truthweave.checks.models import Issue


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    path = paper_dir / "brief.yml"
    recheck = f"uv run truthweave check --paper {paper_id} --mode {mode}"
    if not path.exists():
        severity = "FAIL" if mode == "ci" else "WARN"
        return [
            Issue(
                category="THESIS_LOCK",
                severity=severity,
                message=f"Missing brief.yml for {paper_id}; define the paper thesis before continuing.",
                fix=f"Create papers/{paper_id}/brief.yml or run: uv run truthweave validate-brief --paper {paper_id}",
                recheck=recheck,
                paths=[str(path)],
            )
        ]

    brief = load_brief(path)
    errors = validate_brief_data(brief)
    if errors:
        severity = "FAIL" if mode == "ci" else "WARN"
        return [
            Issue(
                category="THESIS_LOCK",
                severity=severity,
                message="Invalid brief.yml: " + "; ".join(errors),
                fix=f"Update papers/{paper_id}/brief.yml to satisfy the brief schema.",
                recheck=f"uv run truthweave validate-brief --paper {paper_id}",
                paths=[str(path)],
            )
        ]

    phase_status = brief.get("phase_status")
    if phase_status not in PHASES:
        severity = "FAIL" if mode == "ci" else "WARN"
        return [
            Issue(
                category="THESIS_LOCK",
                severity=severity,
                message=f"Invalid phase_status '{phase_status}' in brief.yml.",
                fix=f"Run: uv run truthweave approve-phase --paper {paper_id} --phase idea_locked",
                recheck=f"uv run truthweave validate-brief --paper {paper_id}",
                paths=[str(path)],
            )
        ]

    if mode == "ci" and phase_status not in {"draft_reviewed", "release_ready"}:
        return [
            Issue(
                category="THESIS_LOCK",
                severity="FAIL",
                message=(
                    f"Paper {paper_id} is not ready for CI release checks: "
                    f"phase_status={phase_status} < draft_reviewed"
                ),
                fix=(
                    "Advance the paper via `uv run truthweave approve-phase --paper "
                    f"{paper_id} --phase draft_reviewed` after a successful thread review."
                ),
                recheck=recheck,
                paths=[str(path)],
            )
        ]

    return []

