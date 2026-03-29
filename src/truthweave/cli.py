from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hydra
from omegaconf import OmegaConf

from truthweave.briefs import (
    PHASES,
    approve_phase,
    brief_path,
    claim_ids_from_brief,
    default_brief,
    experiments_for_brief,
    load_brief,
    phase_at_least,
    save_brief,
    validate_brief_data,
)
from truthweave.benchmarks import render_benchmark_report, run_benchmark_suite
from truthweave.checks import (
    check_brief,
    check_claim_evidence,
    check_no_manual_numbers,
    check_packet,
    check_paper_freshness,
    check_profile,
    check_provenance,
    check_references,
    check_review,
    check_run_integrity,
    check_structure,
    check_verification,
)
from truthweave.checks.models import Issue
from truthweave.evidence import (
    build_claim_ledger,
    default_evidence,
    evidence_path,
    load_evidence,
    render_claim_report,
    save_evidence,
    validate_evidence_data,
)
from truthweave.papers import get_paper_by_id, load_paper_config, write_discovery_manifest
from truthweave.packet import build_reviewer_packet, render_packet
from truthweave.profiles import build_profile_report, render_profile_report
from truthweave.provenance import (
    build_provenance_ledger,
    default_provenance,
    load_provenance,
    provenance_path,
    render_provenance_report,
    save_provenance,
    validate_provenance_data,
)
from truthweave.references import (
    default_references,
    load_references,
    references_path,
    sync_references,
    verify_references,
)
from truthweave.registry import get_experiment_class
from truthweave.reviews import build_thread_review, render_review_markdown
from truthweave.runner import ExperimentRunner
from truthweave.utils import ensure_dir, find_latest_run, sha256_file, write_json
from truthweave.verify import build_verification_report, render_verification_report


def _repo_root() -> Path:
    override = os.environ.get("TRUTHWEAVE_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _load_config(overrides: list[str]) -> Any:
    config_dir = _repo_root() / "conf"
    with hydra.initialize_config_dir(config_dir=str(config_dir), version_base=None):
        cfg = hydra.compose(config_name="base", overrides=overrides)
    return cfg


def _resolve_run_dir(cfg: Any) -> Path:
    runs_dir = _repo_root() / cfg.project.runs_dir
    run_subdir = OmegaConf.to_container(cfg, resolve=True)["experiment"][
        "output_subdir"
    ]
    return runs_dir / str(run_subdir)


def _format_metric_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _metric_macro_name(key: str) -> str:
    parts = [p for p in key.replace("-", "_").split("_") if p]
    return "Metric" + "".join(part.capitalize() for part in parts)


def _collect_dir_hashes(base_dir: Path) -> dict[str, str]:
    if not base_dir.exists():
        return {}
    hashes: dict[str, str] = {}
    for path in sorted(base_dir.rglob("*")):
        if path.is_file():
            hashes[str(path.relative_to(base_dir).as_posix())] = sha256_file(path)
    return hashes


def _extract_defined_metric_macros(variables_path: Path) -> set[str]:
    if not variables_path.exists():
        return set()
    pattern = re.compile(r"\\newcommand\{\\(Metric[A-Za-z0-9]+)\}\{")
    return set(pattern.findall(variables_path.read_text()))


def _extract_used_metric_macros(tex_path: Path) -> set[str]:
    if not tex_path.exists():
        return set()
    pattern = re.compile(r"\\(Metric[A-Za-z0-9]+)\b")
    return set(pattern.findall(tex_path.read_text()))


def _load_pipeline_config(repo_root: Path) -> dict[str, Any]:
    pipeline_path = repo_root / "conf" / "pipeline.yaml"
    if not pipeline_path.exists():
        return {}
    cfg = OmegaConf.load(pipeline_path)
    data = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_metrics_source(repo_root: Path, metrics_source: str | None) -> Path:
    pipeline = _load_pipeline_config(repo_root)
    latest_cfg = pipeline.get("latest", {}) if isinstance(pipeline, dict) else {}
    runs_dir = repo_root / latest_cfg.get("runs_dir", "runs")

    if metrics_source in (None, "latest"):
        run_dir = find_latest_run(runs_dir)
        if run_dir is None:
            raise SystemExit("No runs found. Execute a run first.")
        return run_dir

    run_dir = runs_dir / metrics_source
    if not run_dir.exists():
        raise SystemExit(f"Run not found: {run_dir}")
    return run_dir


def _emit_issues(issues: list[Issue], fail_in_ci: bool = True) -> None:
    warn_count = sum(1 for issue in issues if issue.severity == "WARN")
    fail_count = sum(1 for issue in issues if issue.severity == "FAIL")
    for issue in issues:
        print(_format_issue(issue))
    print(f"Summary: WARN={warn_count} FAIL={fail_count}")
    if fail_in_ci and fail_count:
        raise SystemExit(1)


def _approved_briefs_for_experiment(repo_root: Path, experiment_name: str) -> list[str]:
    manifest = write_discovery_manifest(repo_root)
    papers = json.loads(manifest.read_text()).get("papers", [])
    approved: list[str] = []
    for paper in papers:
        paper_id = paper["paper_id"]
        paper_dir = repo_root / paper["path"]
        path = brief_path(paper_dir)
        if not path.exists():
            continue
        brief = load_brief(path)
        if validate_brief_data(brief):
            continue
        if not phase_at_least(str(brief.get("phase_status")), "experiment_ready"):
            continue
        if experiment_name in experiments_for_brief(brief):
            approved.append(paper_id)
    return approved


def _claim_ledger_blockers(ledger: dict[str, Any]) -> list[str]:
    validation = ledger.get("validation", {})
    blockers: list[str] = []
    for field in [
        "schema_errors",
        "required_missing",
        "unresolved_claims",
        "stale_claims",
        "unsupported_major",
        "orphan_claim_ids",
    ]:
        values = validation.get(field, [])
        if isinstance(values, list) and values:
            blockers.append(f"{field}={', '.join(str(value) for value in values)}")
    return blockers


def _provenance_ledger_blockers(
    ledger: dict[str, Any], *, include_claim_gaps: bool
) -> list[str]:
    validation = ledger.get("validation", {})
    blockers: list[str] = []
    fields = [
        "schema_errors",
        "missing_required_sources",
        "unresolved_sources",
        "unavailable_sources",
        "stale_sources",
        "policy_violations",
        "forbidden_substitutes",
    ]
    if include_claim_gaps:
        fields.append("claim_provenance_gaps")
    for field in fields:
        values = validation.get(field, [])
        if isinstance(values, list) and values:
            blockers.append(f"{field}={', '.join(str(value) for value in values)}")
    return blockers


def _profile_report_blockers(
    report: dict[str, Any], *, include_verification_expectations: bool
) -> list[str]:
    validation = report.get("validation", {})
    blockers: list[str] = []
    fields = [
        "declaration_errors",
        "missing_required_fields",
        "missing_eval_fields",
        "baseline_coverage",
        "policy_blockers",
        "forbidden_substitutes",
    ]
    if include_verification_expectations:
        fields.append("verification_expectations")
    for field in fields:
        values = validation.get(field, [])
        if isinstance(values, list) and values:
            blockers.append(f"{field}={', '.join(str(value) for value in values)}")
    return blockers


def _build_paper_assets(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    config = load_paper_config(paper_dir / "truthweave.yml")
    inputs = config.get("inputs", {})
    metrics_source = inputs.get("metrics_source")

    run_dir = _resolve_metrics_source(repo_root, metrics_source)
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        raise SystemExit(f"Missing metrics.json in {run_dir}")

    metrics = json.loads(metrics_path.read_text())

    auto_dir = paper_dir / config["paths"]["auto_dir"]
    ensure_dir(auto_dir)
    variables_path = auto_dir / "variables.tex"

    lines = []
    for key, value in metrics.items():
        macro = _metric_macro_name(key)
        formatted = _format_metric_value(value)
        lines.append(f"\\newcommand{{\\{macro}}}{{{formatted}}}")

    variables_path.write_text("\n".join(lines) + "\n")

    tex_path = paper_dir / config.get("main", "main.tex")
    defined = _extract_defined_metric_macros(variables_path)
    used = _extract_used_metric_macros(tex_path)
    supported = used & defined
    unsupported = sorted(used - defined)
    orphan = sorted(defined - used)
    claim_support = 1.0 if not used else len(supported) / len(used)
    claim_ids: list[str] = []
    brief_file = brief_path(paper_dir)
    if brief_file.exists():
        claim_ids = claim_ids_from_brief(load_brief(brief_file))

    manifest = {
        "source": {
            "paper_id": paper_id,
            "run_dir": str(run_dir.relative_to(repo_root)),
            "metrics_source": metrics_source or "latest",
            "metrics_json_path": str(metrics_path.relative_to(repo_root)),
            "metrics_json_sha256": sha256_file(metrics_path),
        },
        "generated": {
            "variables_tex_sha256": sha256_file(variables_path),
            "figures_sha256": _collect_dir_hashes(
                paper_dir / config["paths"]["figures_dir"]
            ),
            "tables_sha256": _collect_dir_hashes(
                paper_dir / config["paths"]["tables_dir"]
            ),
            "argument_audit": {
                "claim_support": round(claim_support, 4),
                "claims_count": len(used),
                "unsupported_claims": len(unsupported),
                "orphan_metrics": len(orphan),
                "unsupported_macros": unsupported,
                "orphan_macros": orphan,
                "claim_ids": claim_ids,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    write_json(auto_dir / "MANIFEST.json", manifest)


def _build_paper(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    brief_file = brief_path(paper_dir)
    if not brief_file.exists():
        raise SystemExit(
            f"Missing brief.yml for {paper_id}. Run: uv run truthweave validate-brief --paper {paper_id}"
        )
    brief = load_brief(brief_file)
    errors = validate_brief_data(brief)
    if errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(errors))
    if not phase_at_least(str(brief.get("phase_status")), "draft_reviewed"):
        raise SystemExit(
            f"Paper {paper_id} must be at least draft_reviewed before build-paper. "
            f"Current phase: {brief.get('phase_status')}"
        )
    ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)
    blockers = _claim_ledger_blockers(ledger)
    if blockers:
        raise SystemExit(
            "Paper build blocked by claim-evidence issues:\n- " + "\n- ".join(blockers)
        )
    provenance_ledger = build_provenance_ledger(
        repo_root, paper_dir, paper_id, write_output=False
    )
    provenance_blockers = _provenance_ledger_blockers(
        provenance_ledger, include_claim_gaps=True
    )
    if provenance_blockers:
        raise SystemExit(
            "Paper build blocked by provenance issues:\n- "
            + "\n- ".join(provenance_blockers)
        )
    profile_report = build_profile_report(
        repo_root, paper_dir, paper_id, write_output=False
    )
    profile_blockers = _profile_report_blockers(
        profile_report, include_verification_expectations=True
    )
    if profile_blockers:
        raise SystemExit(
            "Paper build blocked by profile policy issues:\n- "
            + "\n- ".join(profile_blockers)
        )
    config = load_paper_config(paper_dir / "truthweave.yml")
    main_path = paper_dir / config["main"]
    if not main_path.exists():
        raise SystemExit(f"Missing main tex for {paper_id}: {main_path}")

    engine = config["engine"]
    output_dir = paper_dir / "build"
    ensure_dir(output_dir)

    if engine == "latexmk":
        latexmk_args = config.get("build", {}).get(
            "latexmk_args", ["-pdf", "-interaction=nonstopmode"]
        )
        if not isinstance(latexmk_args, list):
            latexmk_args = ["-pdf", "-interaction=nonstopmode"]
        cmd = [
            "latexmk",
            *latexmk_args,
            "-halt-on-error",
            f"-outdir={output_dir}",
            str(main_path),
        ]
    elif engine in {"pdflatex", "xelatex"}:
        cmd = [
            engine,
            "-interaction=nonstopmode",
            str(main_path),
        ]
    else:
        raise SystemExit(f"Unsupported engine '{engine}' for paper {paper_id}")

    if shutil.which(cmd[0]) is None:
        raise SystemExit(f"Missing tool '{cmd[0]}'; install it to build papers.")

    style = config.get("style", {})
    texinputs = []
    for entry in style.get("TEXINPUTS", ["styles", "."]):
        entry_path = (paper_dir / entry).resolve()
        texinputs.append(str(entry_path))
    texinputs_str = os.pathsep.join(texinputs) + os.pathsep + os.environ.get(
        "TEXINPUTS", ""
    )
    env = os.environ.copy()
    env["TEXINPUTS"] = texinputs_str

    subprocess.run(cmd, check=True, cwd=paper_dir, env=env)


def _build_paper_assets_legacy() -> None:
    repo_root = _repo_root()
    runs_dir = repo_root / "runs"
    run_dir = find_latest_run(runs_dir)
    if run_dir is None:
        raise SystemExit("No runs found. Execute a run first.")

    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        raise SystemExit(f"Missing metrics.json in {run_dir}")

    metrics = json.loads(metrics_path.read_text())

    auto_dir = repo_root / "paper" / "auto"
    ensure_dir(auto_dir)
    variables_path = auto_dir / "variables.tex"

    lines = []
    for key, value in metrics.items():
        macro = _metric_macro_name(key)
        formatted = _format_metric_value(value)
        lines.append(f"\\newcommand{{\\{macro}}}{{{formatted}}}")

    variables_path.write_text("\n".join(lines) + "\n")

    manifest = {
        "source": {
            "run_dir": str(run_dir.relative_to(repo_root)),
            "metrics_json_path": str(metrics_path.relative_to(repo_root)),
            "metrics_json_sha256": sha256_file(metrics_path),
        },
        "generated": {
            "variables_tex_sha256": sha256_file(variables_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    write_json(auto_dir / "MANIFEST.json", manifest)


def run_command(overrides: list[str]) -> None:
    from truthweave import experiments  # noqa: F401

    cfg = _load_config(overrides)
    run_dir = _resolve_run_dir(cfg)

    experiment_name = cfg.experiment.name
    approved_papers = _approved_briefs_for_experiment(_repo_root(), experiment_name)
    if not approved_papers:
        raise SystemExit(
            "No paper brief in phase experiment_ready or above references "
            f"experiment '{experiment_name}'. Add it to papers/<paper_id>/brief.yml "
            "planned_evidence and approve the phase first."
        )
    repo_root = _repo_root()
    for paper_id in approved_papers:
        paper = get_paper_by_id(repo_root, paper_id)
        paper_dir = repo_root / paper["path"]
        provenance_ledger = build_provenance_ledger(
            repo_root, paper_dir, paper_id, write_output=False
        )
        validation = provenance_ledger.get("validation", {})
        provenance_blockers: list[str] = []
        for field in [
            "schema_errors",
            "missing_required_sources",
            "unavailable_sources",
            "policy_violations",
            "forbidden_substitutes",
        ]:
            values = validation.get(field, [])
            if isinstance(values, list) and values:
                provenance_blockers.append(
                    f"{field}={', '.join(str(value) for value in values)}"
                )
        if provenance_blockers:
            raise SystemExit(
                f"Experiment run blocked by provenance issues for {paper_id}:\n- "
                + "\n- ".join(provenance_blockers)
            )
        profile_report = build_profile_report(
            repo_root, paper_dir, paper_id, write_output=False
        )
        profile_blockers = _profile_report_blockers(
            profile_report, include_verification_expectations=False
        )
        if profile_blockers:
            raise SystemExit(
                f"Experiment run blocked by profile policy issues for {paper_id}:\n- "
                + "\n- ".join(profile_blockers)
            )
    experiment_cls = get_experiment_class(experiment_name)
    experiment = experiment_cls(cfg, run_dir)

    runner = ExperimentRunner(cfg, run_dir, experiment)
    runner.run()


def discover_command() -> None:
    write_discovery_manifest(_repo_root())


def build_paper_assets_command(paper_id: str | None) -> None:
    if paper_id is None:
        legacy_dir = _repo_root() / "paper"
        if legacy_dir.exists():
            _build_paper_assets_legacy()
            return
        raise SystemExit("Provide --paper <paper_id> for multi-paper assets.")
    _build_paper_assets(paper_id)


def build_paper_command(paper_id: str) -> None:
    _build_paper(paper_id)


def _format_issue(issue: Issue) -> str:
    paths = ", ".join(issue.paths) if issue.paths else "(none)"
    fix = issue.fix or "(none)"
    recheck = issue.recheck or "(none)"
    return (
        f"[{issue.severity}:{issue.category}] {issue.message}\n"
        f"Paths: {paths}\n"
        f"Fix: {fix}\n"
        f"Recheck: {recheck}"
    )


def check_structure_command(mode: str) -> list[Issue]:
    repo_root = _repo_root()
    return check_structure.check(repo_root, mode)


def check_command(paper_id: str | None, mode: str) -> None:
    repo_root = _repo_root()
    issues: list[Issue] = []

    issues.extend(check_structure_command(mode))
    issues.extend(check_run_integrity.check(repo_root / "runs", mode, paper_id))

    if paper_id:
        paper = get_paper_by_id(repo_root, paper_id)
        paper_dir = repo_root / paper["path"]
        config = load_paper_config(paper_dir / "truthweave.yml")
        issues.extend(check_brief.check(repo_root, paper_dir, paper_id, mode))
        issues.extend(check_claim_evidence.check(repo_root, paper_dir, paper_id, mode))
        issues.extend(check_packet.check(repo_root, paper_dir, paper_id, mode))
        issues.extend(check_profile.check(repo_root, paper_dir, paper_id, mode))
        issues.extend(check_provenance.check(repo_root, paper_dir, paper_id, mode))
        issues.extend(check_verification.check(repo_root, paper_dir, paper_id, mode))
        issues.extend(
            check_paper_freshness.check(repo_root, paper_dir, paper_id, mode)
        )
        issues.extend(check_review.check(repo_root, paper_dir, paper_id, mode))
        issues.extend(check_references.check(repo_root, paper_dir, paper_id, mode))
        tex_path = paper_dir / config.get("main", "main.tex")
        issues.extend(check_no_manual_numbers.check(tex_path, mode, paper_id))
    else:
        manifest = write_discovery_manifest(repo_root)
        data = json.loads(manifest.read_text())
        for paper in data.get("papers", []):
            pid = paper["paper_id"]
            paper_dir = repo_root / paper["path"]
            issues.extend(check_brief.check(repo_root, paper_dir, pid, mode))
            issues.extend(check_claim_evidence.check(repo_root, paper_dir, pid, mode))
            issues.extend(check_packet.check(repo_root, paper_dir, pid, mode))
            issues.extend(check_profile.check(repo_root, paper_dir, pid, mode))
            issues.extend(check_provenance.check(repo_root, paper_dir, pid, mode))
            issues.extend(check_verification.check(repo_root, paper_dir, pid, mode))
            issues.extend(
                check_paper_freshness.check(repo_root, paper_dir, pid, mode)
            )
            issues.extend(check_review.check(repo_root, paper_dir, pid, mode))
            issues.extend(check_references.check(repo_root, paper_dir, pid, mode))
            config = load_paper_config(paper_dir / "truthweave.yml")
            tex_path = paper_dir / config.get("main", "main.tex")
            issues.extend(check_no_manual_numbers.check(tex_path, mode, pid))

        legacy_main = repo_root / "paper" / "main.tex"
        if legacy_main.exists():
            issues.extend(check_no_manual_numbers.check(legacy_main, mode, None))

    _emit_issues(issues)


def validate_brief_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    path = brief_path(repo_root / paper["path"])
    if not path.exists():
        raise SystemExit(f"Missing brief.yml for {paper_id}: {path}")
    brief = load_brief(path)
    errors = validate_brief_data(brief)
    if errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(errors))
    print(f"brief.yml is valid for {paper_id}")


def scaffold_evidence_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    brief = load_brief(brief_path(paper_dir))
    errors = validate_brief_data(brief)
    if errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(errors))
    path = evidence_path(paper_dir)
    if path.exists():
        raise SystemExit(f"evidence.yml already exists for {paper_id}: {path}")
    save_evidence(path, default_evidence(paper_id, brief))
    print(f"Created {path}")
    _print_allowed_files(repo_root, [str(path)])


def scaffold_provenance_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    brief = load_brief(brief_path(paper_dir))
    errors = validate_brief_data(brief)
    if errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(errors))
    path = provenance_path(paper_dir)
    if path.exists():
        raise SystemExit(f"data_sources.yml already exists for {paper_id}: {path}")
    save_provenance(path, default_provenance(paper_id, brief))
    print(f"Created {path}")
    _print_allowed_files(repo_root, [str(path)])


def validate_evidence_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    brief = load_brief(brief_path(paper_dir))
    brief_errors = validate_brief_data(brief)
    if brief_errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(brief_errors))
    path = evidence_path(paper_dir)
    if not path.exists():
        raise SystemExit(f"Missing evidence.yml for {paper_id}: {path}")
    evidence = load_evidence(path)
    errors = validate_evidence_data(evidence, brief)
    ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)
    blockers = _claim_ledger_blockers(ledger)
    if errors or blockers:
        messages = [*errors, *blockers]
        raise SystemExit("Invalid evidence.yml:\n- " + "\n- ".join(messages))
    print(f"evidence.yml is valid for {paper_id}")


def validate_provenance_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    brief = load_brief(brief_path(paper_dir))
    brief_errors = validate_brief_data(brief)
    if brief_errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(brief_errors))
    path = provenance_path(paper_dir)
    if not path.exists():
        raise SystemExit(f"Missing data_sources.yml for {paper_id}: {path}")
    provenance = load_provenance(path)
    errors = validate_provenance_data(provenance, brief)
    ledger = build_provenance_ledger(repo_root, paper_dir, paper_id, write_output=False)
    blockers = _provenance_ledger_blockers(ledger, include_claim_gaps=True)
    if errors or blockers:
        messages = [*errors, *blockers]
        raise SystemExit("Invalid data_sources.yml:\n- " + "\n- ".join(messages))
    print(f"data_sources.yml is valid for {paper_id}")


def validate_profile_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    report = build_profile_report(repo_root, paper_dir, paper_id, write_output=False)
    selected_profile = report.get("selected_profile")
    if not selected_profile:
        print(f"No research_profile selected for {paper_id}")
        return
    blockers = _profile_report_blockers(
        report, include_verification_expectations=True
    )
    if blockers:
        raise SystemExit(
            "Invalid profile configuration:\n- " + "\n- ".join(blockers)
        )
    print(f"research_profile is valid for {paper_id}: {selected_profile}")


def claim_report_command(paper_id: str, output_format: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=True)
    print(render_claim_report(ledger, output_format), end="")


def provenance_report_command(paper_id: str, output_format: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    ledger = build_provenance_ledger(repo_root, paper_dir, paper_id, write_output=True)
    print(render_provenance_report(ledger, output_format), end="")


def profile_report_command(paper_id: str, output_format: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    report = build_profile_report(repo_root, paper_dir, paper_id, write_output=True)
    print(render_profile_report(report, output_format), end="")


def reviewer_packet_command(paper_id: str, output_format: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    packet = build_reviewer_packet(repo_root, paper_dir, paper_id, write_output=True)
    print(render_packet(packet, output_format), end="")


def verification_report_command(paper_id: str, output_format: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    report = build_verification_report(repo_root, paper_dir, paper_id, write_output=True)
    print(render_verification_report(report, output_format), end="")


def verify_paper_command(paper_id: str, output_format: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    report = build_verification_report(repo_root, paper_dir, paper_id, write_output=True)
    print(render_verification_report(report, output_format), end="")
    failed_required = report.get("validation", {}).get("failed_required_targets", [])
    missing_claims = report.get("validation", {}).get("missing_verification_claims", [])
    if (isinstance(failed_required, list) and failed_required) or (
        isinstance(missing_claims, list) and missing_claims
    ):
        raise SystemExit(1)


def benchmark_contracts_command(
    case_ids: list[str] | None, output_format: str
) -> None:
    repo_root = _repo_root()
    report = run_benchmark_suite(
        repo_root, case_ids=case_ids or None, write_output=True
    )
    print(render_benchmark_report(report, output_format), end="")
    if int(report.get("summary", {}).get("regressions", 0)) > 0:
        raise SystemExit(1)


def approve_phase_command(paper_id: str, phase: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
    path = brief_path(paper_dir)
    if phase_at_least(phase, "evidence_reviewed"):
        ledger = build_claim_ledger(repo_root, paper_dir, paper_id, write_output=False)
        blockers = _claim_ledger_blockers(ledger)
        if blockers:
            raise SystemExit(
                "Cannot approve evidence_reviewed or later with claim-evidence issues:\n- "
                + "\n- ".join(blockers)
            )
        provenance_ledger = build_provenance_ledger(
            repo_root, paper_dir, paper_id, write_output=False
        )
        provenance_blockers = _provenance_ledger_blockers(
            provenance_ledger, include_claim_gaps=True
        )
        if provenance_blockers:
            raise SystemExit(
                "Cannot approve evidence_reviewed or later with provenance issues:\n- "
                + "\n- ".join(provenance_blockers)
            )
    brief = approve_phase(path, phase)
    print(f"Approved {paper_id} phase: {brief['phase_status']}")


def review_thread_command(paper_id: str, phase: str, output_format: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    review = build_thread_review(repo_root, repo_root / paper["path"], paper_id, phase)
    if output_format == "json":
        print(json.dumps(review, indent=2, sort_keys=True))
    else:
        print(render_review_markdown(review), end="")


def sync_refs_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    lock = sync_references(repo_root, repo_root / paper["path"], paper_id)
    print(
        f"Synced references for {paper_id}: {len(lock['entries'])} entries -> {lock['refs_bib_path']}"
    )


def verify_refs_command(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    messages = verify_references(repo_root, repo_root / paper["path"], paper_id)
    if not messages:
        print(f"Reference provenance OK for {paper_id}")
        return
    for message in messages:
        print(message)
    if any("does not match" in message or "Required reference" in message for message in messages):
        raise SystemExit(1)


def _argument_policy_thresholds(config: dict[str, Any]) -> tuple[float, int]:
    quality = config.get("quality", {})
    argument = quality.get("argument", {}) if isinstance(quality, dict) else {}
    min_claim_support_ci = argument.get("min_claim_support_ci", 1.0)
    max_orphan_metrics_dev = argument.get("max_orphan_metrics_dev", 0)
    if not isinstance(min_claim_support_ci, (int, float)):
        min_claim_support_ci = 1.0
    if not isinstance(max_orphan_metrics_dev, int):
        max_orphan_metrics_dev = 0
    return float(min_claim_support_ci), max_orphan_metrics_dev


def _audit_row_status(row: dict[str, object], mode: str) -> str:
    claim_support = row.get("claim_support")
    unsupported_claims = row.get("unsupported_claims")
    orphan_metrics = row.get("orphan_metrics")
    min_claim_support_ci = row.get("min_claim_support_ci")
    max_orphan_metrics_dev = row.get("max_orphan_metrics_dev")

    if not isinstance(claim_support, (int, float)):
        return "fail"
    if not isinstance(unsupported_claims, int):
        return "fail"
    if not isinstance(orphan_metrics, int):
        return "fail"
    if not isinstance(min_claim_support_ci, (int, float)):
        return "fail"
    if not isinstance(max_orphan_metrics_dev, int):
        return "fail"

    if claim_support < float(min_claim_support_ci) or unsupported_claims > 0:
        return "fail"
    if mode == "dev" and orphan_metrics > max_orphan_metrics_dev:
        return "warn"
    return "pass"


def argument_audit_command(paper_id: str | None, output_format: str, mode: str) -> None:
    repo_root = _repo_root()

    if paper_id:
        papers = [get_paper_by_id(repo_root, paper_id)]
    else:
        manifest = write_discovery_manifest(repo_root)
        data = json.loads(manifest.read_text())
        papers = data.get("papers", [])

    rows: list[dict[str, object]] = []
    for paper in papers:
        pid = paper["paper_id"]
        paper_dir = repo_root / paper["path"]
        config = load_paper_config(paper_dir / "truthweave.yml")
        min_claim_support_ci, max_orphan_metrics_dev = _argument_policy_thresholds(config)
        auto_dir = paper_dir / config["paths"]["auto_dir"]
        manifest_path = auto_dir / "MANIFEST.json"
        if not manifest_path.exists():
            raise SystemExit(
                f"Missing MANIFEST.json for {pid}. Run: uv run truthweave build-paper-assets --paper {pid}"
            )

        manifest_data = json.loads(manifest_path.read_text())
        audit = manifest_data.get("generated", {}).get("argument_audit", {})
        row: dict[str, object] = {
            "paper_id": pid,
            "claim_support": audit.get("claim_support"),
            "claims_count": audit.get("claims_count"),
            "unsupported_claims": audit.get("unsupported_claims"),
            "orphan_metrics": audit.get("orphan_metrics"),
            "claim_ids": audit.get("claim_ids", []),
            "min_claim_support_ci": min_claim_support_ci,
            "max_orphan_metrics_dev": max_orphan_metrics_dev,
        }
        row["status"] = _audit_row_status(row, mode)
        rows.append(
            row
        )

    if output_format == "json":
        payload = {
            "mode": mode,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "papers": rows,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "paper_id\tstatus\tclaim_support\tclaims_count\tunsupported_claims\t"
            "orphan_metrics\tmin_claim_support_ci\tmax_orphan_metrics_dev"
        )
        for row in rows:
            print(
                f"{row['paper_id']}\t{row['status']}\t{row['claim_support']}\t{row['claims_count']}\t"
                f"{row['unsupported_claims']}\t{row['orphan_metrics']}\t"
                f"{row['min_claim_support_ci']}\t{row['max_orphan_metrics_dev']}"
            )

    has_fail = any(row.get("status") == "fail" for row in rows)
    if mode == "ci" and has_fail:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="truthweave")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an experiment")
    run_parser.add_argument("overrides", nargs=argparse.REMAINDER)

    subparsers.add_parser("discover", help="Discover papers")

    assets_parser = subparsers.add_parser(
        "build-paper-assets", help="Generate paper assets"
    )
    assets_parser.add_argument("--paper")

    build_parser = subparsers.add_parser("build-paper", help="Build a paper")
    build_parser.add_argument("--paper", required=True)

    check_parser = subparsers.add_parser("check", help="Run checks")
    check_parser.add_argument("--paper")
    check_parser.add_argument("--mode", choices=["dev", "ci"], default="dev")

    audit_parser = subparsers.add_parser(
        "audit-argument", help="Report argument audit metrics from paper manifests"
    )
    audit_parser.add_argument("--paper")
    audit_parser.add_argument("--format", choices=["table", "json"], default="table")
    audit_parser.add_argument("--mode", choices=["dev", "ci"], default="dev")

    brief_parser = subparsers.add_parser(
        "validate-brief", help="Validate a paper brief"
    )
    brief_parser.add_argument("--paper", required=True)

    scaffold_evidence_parser = subparsers.add_parser(
        "scaffold-evidence", help="Create a starter evidence.yml from brief claim IDs"
    )
    scaffold_evidence_parser.add_argument("--paper", required=True)

    scaffold_provenance_parser = subparsers.add_parser(
        "scaffold-provenance", help="Create a starter data_sources.yml from brief source IDs"
    )
    scaffold_provenance_parser.add_argument("--paper", required=True)

    validate_evidence_parser = subparsers.add_parser(
        "validate-evidence", help="Validate evidence.yml against the brief and repo artifacts"
    )
    validate_evidence_parser.add_argument("--paper", required=True)

    validate_provenance_parser = subparsers.add_parser(
        "validate-provenance",
        help="Validate data_sources.yml against the brief and local provenance pointers",
    )
    validate_provenance_parser.add_argument("--paper", required=True)

    validate_profile_parser = subparsers.add_parser(
        "validate-profile",
        help="Validate the selected research_profile and required domain declarations",
    )
    validate_profile_parser.add_argument("--paper", required=True)

    claim_report_parser = subparsers.add_parser(
        "claim-report", help="Build a machine-readable claim ledger"
    )
    claim_report_parser.add_argument("--paper", required=True)
    claim_report_parser.add_argument("--format", choices=["table", "json", "md"], default="table")

    provenance_report_parser = subparsers.add_parser(
        "provenance-report", help="Build a machine-readable provenance ledger"
    )
    provenance_report_parser.add_argument("--paper", required=True)
    provenance_report_parser.add_argument(
        "--format", choices=["table", "json", "md"], default="table"
    )

    profile_report_parser = subparsers.add_parser(
        "profile-report", help="Build a machine-readable research profile report"
    )
    profile_report_parser.add_argument("--paper", required=True)
    profile_report_parser.add_argument(
        "--format", choices=["table", "json", "md"], default="table"
    )

    reviewer_packet_parser = subparsers.add_parser(
        "reviewer-packet", help="Build a reviewer-facing trust packet"
    )
    reviewer_packet_parser.add_argument("--paper", required=True)
    reviewer_packet_parser.add_argument(
        "--format", choices=["table", "json", "md"], default="table"
    )

    verification_report_parser = subparsers.add_parser(
        "verification-report", help="Build a machine-readable verification report"
    )
    verification_report_parser.add_argument("--paper", required=True)
    verification_report_parser.add_argument(
        "--format", choices=["table", "json", "md"], default="table"
    )

    verify_paper_parser = subparsers.add_parser(
        "verify-paper", help="Run deterministic claim verification for a paper"
    )
    verify_paper_parser.add_argument("--paper", required=True)
    verify_paper_parser.add_argument(
        "--format", choices=["table", "json", "md"], default="table"
    )

    benchmark_parser = subparsers.add_parser(
        "benchmark-contracts",
        help="Run the deterministic positive/negative domain-policy benchmark corpus",
    )
    benchmark_parser.add_argument("--case", action="append", dest="cases")
    benchmark_parser.add_argument(
        "--format", choices=["table", "json", "md"], default="table"
    )

    approve_parser = subparsers.add_parser(
        "approve-phase", help="Approve a paper phase transition"
    )
    approve_parser.add_argument("--paper", required=True)
    approve_parser.add_argument("--phase", choices=PHASES, required=True)

    review_parser = subparsers.add_parser(
        "review-thread", help="Generate a thread coherence review"
    )
    review_parser.add_argument("--paper", required=True)
    review_parser.add_argument("--phase", choices=PHASES, required=True)
    review_parser.add_argument("--format", choices=["json", "md"], default="md")

    sync_refs_parser = subparsers.add_parser(
        "sync-refs", help="Generate refs.bib and reference lock data"
    )
    sync_refs_parser.add_argument("--paper", required=True)

    verify_refs_parser = subparsers.add_parser(
        "verify-refs", help="Verify refs.bib against reference lock data"
    )
    verify_refs_parser.add_argument("--paper", required=True)

    structure_parser = subparsers.add_parser(
        "check-structure", help="Check repository structure"
    )
    structure_parser.add_argument("--mode", choices=["dev", "ci"], default="dev")

    create_parser = subparsers.add_parser("create-paper", help="Create a paper")
    create_parser.add_argument("paper_id")
    create_parser.add_argument("--from", dest="from_paper")
    create_parser.add_argument("--engine")

    create_exp_parser = subparsers.add_parser(
        "create-exp", help="Create an experiment scaffold"
    )
    create_exp_parser.add_argument("exp_name")

    create_analysis_parser = subparsers.add_parser(
        "create-analysis", help="Create an analysis scaffold"
    )
    create_analysis_parser.add_argument("analysis_name")
    create_analysis_parser.add_argument("--kind")

    create_dataset_parser = subparsers.add_parser(
        "create-dataset", help="Create a dataset scaffold"
    )
    create_dataset_parser.add_argument("dataset_id")

    args = parser.parse_args()

    if args.command == "run":
        overrides = [arg for arg in args.overrides if arg]
        run_command(overrides)
    elif args.command == "discover":
        discover_command()
    elif args.command == "build-paper-assets":
        build_paper_assets_command(args.paper)
    elif args.command == "build-paper":
        build_paper_command(args.paper)
    elif args.command == "create-paper":
        create_paper_command(args.paper_id, args.from_paper, args.engine)
    elif args.command == "check":
        check_command(args.paper, args.mode)
    elif args.command == "audit-argument":
        argument_audit_command(args.paper, args.format, args.mode)
    elif args.command == "validate-brief":
        validate_brief_command(args.paper)
    elif args.command == "scaffold-evidence":
        scaffold_evidence_command(args.paper)
    elif args.command == "scaffold-provenance":
        scaffold_provenance_command(args.paper)
    elif args.command == "validate-evidence":
        validate_evidence_command(args.paper)
    elif args.command == "validate-provenance":
        validate_provenance_command(args.paper)
    elif args.command == "validate-profile":
        validate_profile_command(args.paper)
    elif args.command == "claim-report":
        claim_report_command(args.paper, args.format)
    elif args.command == "provenance-report":
        provenance_report_command(args.paper, args.format)
    elif args.command == "profile-report":
        profile_report_command(args.paper, args.format)
    elif args.command == "reviewer-packet":
        reviewer_packet_command(args.paper, args.format)
    elif args.command == "verification-report":
        verification_report_command(args.paper, args.format)
    elif args.command == "verify-paper":
        verify_paper_command(args.paper, args.format)
    elif args.command == "benchmark-contracts":
        benchmark_contracts_command(args.cases, args.format)
    elif args.command == "approve-phase":
        approve_phase_command(args.paper, args.phase)
    elif args.command == "review-thread":
        review_thread_command(args.paper, args.phase, args.format)
    elif args.command == "sync-refs":
        sync_refs_command(args.paper)
    elif args.command == "verify-refs":
        verify_refs_command(args.paper)
    elif args.command == "check-structure":
        issues = check_structure_command(args.mode)
        for issue in issues:
            print(_format_issue(issue))
        if any(issue.severity == "FAIL" for issue in issues):
            raise SystemExit(1)
    elif args.command == "create-exp":
        create_exp_command(args.exp_name)
    elif args.command == "create-analysis":
        create_analysis_command(args.analysis_name, args.kind)
    elif args.command == "create-dataset":
        create_dataset_command(args.dataset_id)
    else:
        raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()


def create_paper_command(
    paper_id: str, base_paper_id: str | None, engine: str | None
) -> None:
    repo_root = _repo_root()
    papers_root = repo_root / "papers"
    ensure_dir(papers_root)
    target_dir = papers_root / paper_id
    if target_dir.exists():
        raise SystemExit(f"Paper already exists: {target_dir}")

    if engine and engine not in {"latexmk", "pdflatex", "xelatex"}:
        raise SystemExit(f"Unsupported engine '{engine}'")

    if base_paper_id:
        base = get_paper_by_id(repo_root, base_paper_id)
        base_dir = repo_root / base["path"]
        shutil.copytree(base_dir, target_dir)

        for subdir in ["auto", "figures", "tables"]:
            path = target_dir / subdir
            if path.exists():
                shutil.rmtree(path)
            ensure_dir(path)
            (path / ".gitkeep").write_text("")
        build_dir = target_dir / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)

        config_path = target_dir / "truthweave.yml"
        config = load_paper_config(config_path)
        config["paper_id"] = paper_id
        if engine:
            config["engine"] = engine
        OmegaConf.save(OmegaConf.create(config), config_path)
        brief_file = brief_path(target_dir)
        if brief_file.exists():
            brief = load_brief(brief_file)
            brief["paper_id"] = paper_id
            save_brief(brief_file, brief)
        refs_file = references_path(target_dir)
        if refs_file.exists():
            refs = load_references(refs_file)
            refs["paper_id"] = paper_id
            OmegaConf.save(OmegaConf.create(refs), refs_file)
        evidence_file = evidence_path(target_dir)
        if evidence_file.exists():
            evidence = load_evidence(evidence_file)
            evidence["paper_id"] = paper_id
            save_evidence(evidence_file, evidence)
        provenance_file = provenance_path(target_dir)
        if provenance_file.exists():
            provenance = load_provenance(provenance_file)
            provenance["paper_id"] = paper_id
            save_provenance(provenance_file, provenance)
    else:
        ensure_dir(target_dir)
        for subdir in ["styles", "auto", "figures", "tables"]:
            path = target_dir / subdir
            ensure_dir(path)
            (path / ".gitkeep").write_text("")

        config = {
            "paper_id": paper_id,
            "engine": engine or "latexmk",
            "main": "main.tex",
            "bib": "refs.bib",
            "paths": {
                "auto_dir": "auto",
                "figures_dir": "figures",
                "tables_dir": "tables",
            },
            "style": {"TEXINPUTS": ["styles", "."]},
            "build": {"latexmk_args": ["-pdf", "-interaction=nonstopmode"]},
            "inputs": {"metrics_source": "latest"},
            "quality": {
                "argument": {
                    "min_claim_support_ci": 1.0,
                    "max_orphan_metrics_dev": 0,
                },
                "thread": {
                    "min_alignment_ci": 0.6,
                },
            },
        }
        OmegaConf.save(OmegaConf.create(config), target_dir / "truthweave.yml")

        main_tex = (
            "\\documentclass{article}\n"
            "\\input{auto/variables.tex}\n\n"
            "\\begin{document}\n\n"
            "Example metric: \\MetricMean.\n\n"
            "\\end{document}\n"
        )
        (target_dir / "main.tex").write_text(main_tex)

        refs_bib = (
            "@article{example2024,\n"
            "  title={Example Reference},\n"
            "  author={Doe, Jane},\n"
            "  journal={Journal of Examples},\n"
            "  year={2024}\n"
            "}\n"
        )
        (target_dir / "refs.bib").write_text(refs_bib)
        save_brief(brief_path(target_dir), default_brief(paper_id))
        OmegaConf.save(
            OmegaConf.create(default_references(paper_id)),
            references_path(target_dir),
        )
        save_evidence(
            evidence_path(target_dir),
            default_evidence(paper_id, default_brief(paper_id)),
        )
        save_provenance(
            provenance_path(target_dir),
            default_provenance(paper_id, default_brief(paper_id)),
        )

    write_discovery_manifest(repo_root)
    allowed_paths = [
        str(target_dir / "truthweave.yml"),
        str(target_dir / "brief.yml"),
        str(target_dir / "evidence.yml"),
        str(target_dir / "data_sources.yml"),
        str(target_dir / "main.tex"),
        str(target_dir / "references.yml"),
        str(target_dir / "refs.bib"),
    ]
    _print_allowed_files(repo_root, allowed_paths)


def _to_camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_") if part)


def create_exp_command(exp_name: str) -> None:
    import re

    if not re.match(r"^[a-z][a-z0-9_]*$", exp_name):
        raise SystemExit(
            "exp_name must be lowercase letters, digits, underscores, and start with a letter."
        )

    repo_root = _repo_root()
    conf_dir = repo_root / "conf" / "exp"
    src_dir = repo_root / "src" / "truthweave" / "experiments"
    ensure_dir(conf_dir)
    ensure_dir(src_dir)

    yaml_path = conf_dir / f"{exp_name}.yaml"
    py_path = src_dir / f"{exp_name}.py"
    if yaml_path.exists() or py_path.exists():
        raise SystemExit(f"Experiment files already exist for {exp_name}")

    yaml_contents = (
        "# @package _global_\n\n"
        "experiment:\n"
        f"  name: {exp_name}\n\n"
        f"{exp_name}:\n"
        "  param: 1\n"
    )
    yaml_path.write_text(yaml_contents)

    class_name = f"{_to_camel(exp_name)}Experiment"
    py_contents = (
        "from __future__ import annotations\n\n"
        "from truthweave.registry import register_experiment\n"
        "from truthweave.runner import BaseExperiment\n\n\n"
        f"@register_experiment(\"{exp_name}\")\n"
        f"class {class_name}(BaseExperiment):\n"
        "    def setup(self) -> None:\n"
        f"        self.cfg_section = self.cfg.{exp_name}\n\n"
        "    def run(self) -> dict[str, float | str]:\n"
        "        return {\n"
        "            \"status\": \"ok\",\n"
        "            \"dummy_metric\": 1.0,\n"
        "        }\n\n"
        "    def teardown(self) -> None:\n"
        "        pass\n"
    )
    py_path.write_text(py_contents)

    init_path = src_dir / "__init__.py"
    import_line = f"from truthweave.experiments.{exp_name} import {class_name}\n"
    if init_path.exists():
        existing = init_path.read_text()
        if import_line not in existing:
            init_path.write_text(existing + import_line)
    else:
        init_path.write_text(import_line)

    print(f"Created {yaml_path}")
    print(f"Created {py_path}")
    print(f"Next: edit {yaml_path} and {py_path}")
    print(f"Run: uv run truthweave run exp={exp_name}")
    _print_allowed_files(repo_root, [str(yaml_path), str(py_path)])


def create_analysis_command(analysis_name: str, kind: str | None) -> None:
    import re

    if not re.match(r"^[a-z][a-z0-9_]*$", analysis_name):
        raise SystemExit(
            "analysis_name must be lowercase letters, digits, underscores, and start with a letter."
        )

    repo_root = _repo_root()
    analysis_dir = repo_root / "src" / "truthweave" / "analysis"
    ensure_dir(analysis_dir)

    init_path = analysis_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("__all__ = []\n")

    analysis_path = analysis_dir / f"{analysis_name}.py"
    if analysis_path.exists():
        raise SystemExit(f"Analysis file already exists: {analysis_path}")

    kind_comment = f"# kind: {kind}\n\n" if kind else ""
    analysis_contents = (
        "from __future__ import annotations\n\n"
        "import argparse\n"
        "import json\n"
        "from datetime import datetime, timezone\n"
        "from pathlib import Path\n\n"
        "from truthweave.utils import find_latest_run, ensure_dir\n\n\n"
        "def main() -> None:\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument(\"--runs_dir\", default=\"runs\")\n"
        "    parser.add_argument(\"--out_dir\", default=\"artifacts\")\n"
        "    parser.add_argument(\"--paper\")\n"
        "    parser.add_argument(\"--run_id\")\n"
        "    args = parser.parse_args()\n\n"
        "    runs_dir = Path(args.runs_dir)\n"
        "    run_dir = runs_dir / args.run_id if args.run_id else find_latest_run(runs_dir)\n"
        "    if run_dir is None:\n"
        "        raise SystemExit(\n"
        "            \"No runs found. Create one with: uv run truthweave run exp=<exp_name>\"\n"
        "        )\n"
        "    metrics_path = Path(run_dir) / \"metrics.json\"\n"
        "    if not metrics_path.exists():\n"
        "        raise SystemExit(f\"Missing metrics.json in {run_dir}\")\n"
        "    metrics = json.loads(metrics_path.read_text())\n\n"
        "    out_dir = Path(args.out_dir) / \"metrics\"\n"
        "    ensure_dir(out_dir)\n"
        "    out_path = out_dir / f\"" + analysis_name + ".json\"\n"
        "    payload = {\n"
        "        \"analysis\": \"" + analysis_name + "\",\n"
        "        \"run_id\": str(run_dir),\n"
        "        \"generated_at\": datetime.now(timezone.utc).isoformat(),\n"
        "        \"metrics\": metrics,\n"
        "    }\n"
        "    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))\n\n\n"
        "if __name__ == \"__main__\":\n"
        "    main()\n"
    )
    analysis_path.write_text(kind_comment + analysis_contents)

    print(f"Created {analysis_path}")
    print(
        f"Run: uv run python -m truthweave.analysis.{analysis_name} --run_id <run_id>"
    )
    _print_allowed_files(repo_root, [str(analysis_path)])


def create_dataset_command(dataset_id: str) -> None:
    import re

    if not re.match(r"^[a-z][a-z0-9_]*$", dataset_id):
        raise SystemExit(
            "dataset_id must be lowercase letters, digits, underscores, and start with a letter."
        )

    repo_root = _repo_root()
    data_root = repo_root / "data"
    ensure_dir(data_root)

    raw_dir = data_root / "raw" / dataset_id
    processed_dir = data_root / "processed" / dataset_id
    ensure_dir(raw_dir)
    ensure_dir(processed_dir)

    meta_path = raw_dir / "DATASET.md"
    if meta_path.exists():
        raise SystemExit(f"Dataset metadata already exists: {meta_path}")

    meta_contents = (
        "# Dataset Metadata\n\n"
        "## Description\n"
        "- TODO: describe the dataset.\n\n"
        "## Source\n"
        "- TODO: source URL or citation.\n\n"
        "## Schema\n"
        "- TODO: describe files/columns.\n\n"
        "## License/Privacy\n"
        "- TODO: license terms and privacy notes.\n"
    )
    meta_path.write_text(meta_contents)

    print(f"Created {meta_path}")
    print(f"Place raw files in: {raw_dir}")
    print("Reminder: raw data is not committed by default.")
    _print_allowed_files(repo_root, [str(meta_path)])


def _print_allowed_files(repo_root: Path, paths: list[str]) -> None:
    print("NEXT: Ask AI to edit ONLY these files:")
    for path in paths:
        rel = Path(path)
        if rel.is_absolute():
            rel = rel.relative_to(repo_root)
        print(f"- {rel}")
    print("Do not create new directories; CI will fail.")
