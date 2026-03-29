from __future__ import annotations

from pathlib import Path

from truthweave.checks.models import Issue
from truthweave.references import lock_path, verify_references


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    paths = [str(paper_dir / "refs.bib"), str(lock_path(repo_root, paper_id))]
    messages = verify_references(repo_root, paper_dir, paper_id)
    for message in messages:
        severity = "WARN"
        if "does not match" in message or "Required reference" in message:
            severity = "FAIL" if mode == "ci" else "WARN"
        issues.append(
            Issue(
                category="REFERENCE_PROVENANCE",
                severity=severity,
                message=message,
                fix=f"Run: uv run truthweave sync-refs --paper {paper_id}",
                recheck=f"uv run truthweave verify-refs --paper {paper_id}",
                paths=paths,
            )
        )
    return issues
