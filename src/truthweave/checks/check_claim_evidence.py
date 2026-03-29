from __future__ import annotations

from pathlib import Path

from truthweave.checks.models import Issue
from truthweave.evidence import build_claim_ledger, claim_ledger_path, evidence_path


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)
    validation = ledger.get("validation", {})
    recheck = f"uv run truthweave validate-evidence --paper {paper_id}"
    evidence_file = str(evidence_path(paper_dir))
    ledger_file = str(claim_ledger_path(repo_root, paper_id))

    schema_errors = validation.get("schema_errors", [])
    if isinstance(schema_errors, list) and schema_errors:
        issues.append(
            Issue(
                category="CLAIM_POINTER_RESOLUTION",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Invalid evidence.yml: " + "; ".join(str(err) for err in schema_errors),
                fix=f"Update papers/{paper_id}/evidence.yml to satisfy the evidence schema.",
                recheck=recheck,
                paths=[evidence_file],
            )
        )

    orphan_claim_ids = validation.get("orphan_claim_ids", [])
    if isinstance(orphan_claim_ids, list) and orphan_claim_ids:
        issues.append(
            Issue(
                category="ORPHAN_EVIDENCE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Evidence entries reference unknown claim IDs: " + ", ".join(orphan_claim_ids),
                fix=(
                    "Remove orphan evidence entries or align them with claim IDs "
                    "declared in brief.yml."
                ),
                recheck=recheck,
                paths=[evidence_file],
            )
        )

    required_missing = validation.get("required_missing", [])
    if isinstance(required_missing, list) and required_missing:
        issues.append(
            Issue(
                category="CLAIM_COVERAGE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Required claims are missing evidence entries or resolved support: "
                + ", ".join(required_missing),
                fix=f"Run: uv run truthweave scaffold-evidence --paper {paper_id} and update the resulting evidence.yml",
                recheck=recheck,
                paths=[evidence_file, ledger_file],
            )
        )

    unresolved_claims = validation.get("unresolved_claims", [])
    if isinstance(unresolved_claims, list) and unresolved_claims:
        issues.append(
            Issue(
                category="CLAIM_POINTER_RESOLUTION",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Some claim evidence pointers do not resolve cleanly: " + ", ".join(unresolved_claims),
                fix="Point each claim at concrete generated artifacts and variables that exist in the repository.",
                recheck=recheck,
                paths=[evidence_file, ledger_file],
            )
        )

    stale_claims = validation.get("stale_claims", [])
    if isinstance(stale_claims, list) and stale_claims:
        issues.append(
            Issue(
                category="CLAIM_STALENESS",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Claim evidence is stale for: " + ", ".join(stale_claims),
                fix=(
                    "Refresh evidence pointers so they match the current paper assets "
                    "and source run provenance."
                ),
                recheck=recheck,
                paths=[evidence_file, ledger_file],
            )
        )

    unsupported_major = validation.get("unsupported_major", [])
    if isinstance(unsupported_major, list) and unsupported_major:
        issues.append(
            Issue(
                category="UNSUPPORTED_MAJOR_CLAIM",
                severity="FAIL",
                message="Required claims are explicitly unsupported: " + ", ".join(unsupported_major),
                fix=(
                    "Do not build the paper until these claims are downgraded, "
                    "qualified, or backed by concrete evidence."
                ),
                recheck=recheck,
                paths=[evidence_file, ledger_file],
            )
        )

    return issues
