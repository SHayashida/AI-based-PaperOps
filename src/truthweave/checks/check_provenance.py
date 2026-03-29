from __future__ import annotations

from pathlib import Path

from truthweave.checks.models import Issue
from truthweave.provenance import build_provenance_ledger, provenance_ledger_path, provenance_path


def check(repo_root: Path, paper_dir: Path, paper_id: str, mode: str) -> list[Issue]:
    issues: list[Issue] = []
    ledger = build_provenance_ledger(repo_root, paper_dir, paper_id, write_output=False)
    validation = ledger.get("validation", {})
    recheck = f"uv run truthweave validate-provenance --paper {paper_id}"
    provenance_file = str(provenance_path(paper_dir))
    ledger_file = str(provenance_ledger_path(repo_root, paper_id))

    schema_errors = validation.get("schema_errors", [])
    missing_required_sources = validation.get("missing_required_sources", [])
    if isinstance(schema_errors, list) and schema_errors:
        issues.append(
            Issue(
                category="DATA_SOURCE_DECLARED",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Invalid data_sources.yml: " + "; ".join(str(err) for err in schema_errors),
                fix=f"Update papers/{paper_id}/data_sources.yml to satisfy the provenance schema.",
                recheck=recheck,
                paths=[provenance_file],
            )
        )
    if isinstance(missing_required_sources, list) and missing_required_sources:
        issues.append(
            Issue(
                category="DATA_SOURCE_DECLARED",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Required source IDs declared in brief.yml are missing from data_sources.yml: "
                + ", ".join(str(source_id) for source_id in missing_required_sources),
                fix=f"Run: uv run truthweave scaffold-provenance --paper {paper_id} and fill in each required source.",
                recheck=recheck,
                paths=[provenance_file, ledger_file],
            )
        )

    unresolved_sources = validation.get("unresolved_sources", [])
    if isinstance(unresolved_sources, list) and unresolved_sources:
        issues.append(
            Issue(
                category="DATA_SOURCE_POINTER_RESOLUTION",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Some provenance pointers do not resolve locally: "
                + ", ".join(str(source_id) for source_id in unresolved_sources),
                fix="Point each declared data source at concrete local files, directories, or manifest entries.",
                recheck=recheck,
                paths=[provenance_file, ledger_file],
            )
        )

    policy_violations = validation.get("policy_violations", [])
    if isinstance(policy_violations, list) and policy_violations:
        issues.append(
            Issue(
                category="DATA_SOURCE_POLICY",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Data acquisition policy violations detected: "
                + "; ".join(str(value) for value in policy_violations),
                fix="Make acquisition_mode, status, and reproducibility_level coherent with the actual source contract.",
                recheck=recheck,
                paths=[provenance_file, ledger_file],
            )
        )

    forbidden_substitutes = validation.get("forbidden_substitutes", [])
    if isinstance(forbidden_substitutes, list) and forbidden_substitutes:
        issues.append(
            Issue(
                category="FORBIDDEN_SUBSTITUTE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Claims are bound to prohibited source substitutes: "
                + ", ".join(str(value) for value in forbidden_substitutes),
                fix="Replace the prohibited source with the intended source class or update the brief contract explicitly.",
                recheck=recheck,
                paths=[provenance_file, ledger_file],
            )
        )

    claim_provenance_gaps = validation.get("claim_provenance_gaps", [])
    if isinstance(claim_provenance_gaps, list) and claim_provenance_gaps:
        issues.append(
            Issue(
                category="CLAIM_PROVENANCE_COVERAGE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Supported claims are not fully backed by admissible source declarations: "
                + "; ".join(str(value) for value in claim_provenance_gaps),
                fix="Bring each claim's required source IDs to acquired or verified status with resolvable provenance pointers.",
                recheck=recheck,
                paths=[provenance_file, ledger_file],
            )
        )

    stale_sources = validation.get("stale_sources", [])
    unavailable_sources = validation.get("unavailable_sources", [])
    stale_values = []
    if isinstance(stale_sources, list):
        stale_values.extend(str(value) for value in stale_sources)
    if isinstance(unavailable_sources, list):
        stale_values.extend(str(value) for value in unavailable_sources)
    if stale_values:
        issues.append(
            Issue(
                category="STALE_PROVENANCE",
                severity="FAIL" if mode == "ci" else "WARN",
                message="Stale or unavailable source declarations detected: " + ", ".join(stale_values),
                fix="Refresh the source snapshot, update stale pointers, or mark the affected claims as unsupported until the source is available again.",
                recheck=recheck,
                paths=[provenance_file, ledger_file],
            )
        )

    return issues
