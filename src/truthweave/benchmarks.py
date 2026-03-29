from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from omegaconf import OmegaConf

from truthweave.briefs import claim_ids_from_brief, load_brief
from truthweave.profiles import build_profile_report
from truthweave.utils import ensure_dir, sha256_file, write_json


def benchmark_cases_dir(repo_root: Path) -> Path:
    return repo_root / "benchmarks" / "cases"


def benchmark_report_path(repo_root: Path) -> Path:
    return repo_root / "artifacts" / "benchmarks" / "benchmark_report.json"


def benchmark_markdown_path(repo_root: Path) -> Path:
    return repo_root / "artifacts" / "benchmarks" / "benchmark_report.md"


def load_benchmark_expectation(path: Path) -> dict[str, Any]:
    data = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid benchmark expectation file: {path}")
    return data


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    OmegaConf.save(OmegaConf.create(data), path)


def _default_truthweave_config(paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "engine": "latexmk",
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
            "thread": {"min_alignment_ci": 0.6},
        },
    }


def _default_references(paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "sources": [
            {
                "key": "example2024",
                "query": "Example Reference",
                "ids": {},
                "intent": "background",
                "required": True,
                "metadata": {
                    "entry_type": "article",
                    "title": "Example Reference",
                    "authors": ["Doe, Jane"],
                    "venue": "Journal of Examples",
                    "year": "2024",
                },
            }
        ],
    }


def _manifest_for_workspace(repo_root: Path, paper_dir: Path, paper_id: str) -> dict[str, Any]:
    metrics_path = repo_root / "runs" / "run1" / "metrics.json"
    variables_path = paper_dir / "auto" / "variables.tex"
    claim_ids = claim_ids_from_brief(load_brief(paper_dir / "brief.yml"))
    return {
        "source": {
            "paper_id": paper_id,
            "run_dir": "runs/run1",
            "metrics_source": "latest",
            "metrics_json_path": "runs/run1/metrics.json",
            "metrics_json_sha256": sha256_file(metrics_path),
        },
        "generated": {
            "variables_tex_sha256": sha256_file(variables_path),
            "figures_sha256": {},
            "tables_sha256": {},
            "argument_audit": {
                "claim_support": 1.0,
                "claims_count": 1,
                "unsupported_claims": 0,
                "orphan_metrics": 0,
                "unsupported_macros": [],
                "orphan_macros": [],
                "claim_ids": claim_ids,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _materialize_benchmark_workspace(
    repo_root: Path, case_dir: Path, temp_repo: Path, case_id: str
) -> Path:
    (temp_repo / "conf").mkdir(parents=True, exist_ok=True)
    run_dir = temp_repo / "runs" / "run1"
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    paper_dir = temp_repo / "papers" / case_id
    for subdir in ["auto", "styles", "figures", "tables"]:
        (paper_dir / subdir).mkdir(parents=True, exist_ok=True)
    _write_text(
        temp_repo / "conf" / "base.yaml",
        "project:\n  runs_dir: runs\nruntime:\n  seed: 1\nexperiment:\n  name: example\n  output_subdir: run1\n",
    )
    for name, content in {
        "config_resolved.yaml": "{}",
        "git_commit.txt": "benchmark\n",
        "command.txt": "uv run truthweave run exp=example\n",
        "env_freeze.txt": "benchmark==1.0\n",
        "hardware.json": "{}",
        "seeds.json": "{}",
        "metrics.json": json.dumps({"mean": 0.5101}),
    }.items():
        _write_text(run_dir / name, content)
    _write_text(paper_dir / "styles" / ".gitkeep", "")
    _write_yaml(paper_dir / "truthweave.yml", _default_truthweave_config(case_id))
    _write_text(
        paper_dir / "main.tex",
        "\\documentclass{article}\n"
        "\\input{auto/variables.tex}\n\n"
        "\\begin{document}\n\n"
        "Example metric: \\MetricMean.\n\n"
        "\\end{document}\n",
    )
    _write_text(paper_dir / "refs.bib", "")
    _write_yaml(paper_dir / "references.yml", _default_references(case_id))
    _write_text(paper_dir / "auto" / "variables.tex", "\\newcommand{\\MetricMean}{0.5101}\n")

    profiles_src = repo_root / "profiles"
    if profiles_src.exists():
        shutil.copytree(profiles_src, temp_repo / "profiles", dirs_exist_ok=True)

    paper_overlay = case_dir / "paper"
    if paper_overlay.exists():
        shutil.copytree(paper_overlay, paper_dir, dirs_exist_ok=True)

    support_overlay = case_dir / "support"
    if support_overlay.exists() and any(path.is_file() for path in support_overlay.rglob("*")):
        shutil.copytree(support_overlay, temp_repo, dirs_exist_ok=True)

    write_json(
        paper_dir / "auto" / "MANIFEST.json",
        _manifest_for_workspace(temp_repo, paper_dir, case_id),
    )
    return paper_dir


def _capture_command(fn: Callable[..., Any], *args: Any) -> dict[str, Any]:
    buffer = io.StringIO()
    ok = True
    exit_code: int | str = 0
    with redirect_stdout(buffer), redirect_stderr(buffer):
        try:
            fn(*args)
        except SystemExit as exc:
            ok = False
            exit_code = exc.code
    output = buffer.getvalue()
    return {
        "ok": ok,
        "exit_code": 0 if ok else (exit_code if isinstance(exit_code, int) else 1),
        "message": "" if ok else str(exit_code),
        "output": output,
    }


def _parse_issue_categories(output: str) -> dict[str, list[str]]:
    fail_categories = sorted(set(re.findall(r"\[FAIL:([A-Z0-9_]+)\]", output)))
    warn_categories = sorted(set(re.findall(r"\[WARN:([A-Z0-9_]+)\]", output)))
    return {"fail_categories": fail_categories, "warn_categories": warn_categories}


def _run_case(repo_root: Path, case_dir: Path, expectation: dict[str, Any]) -> dict[str, Any]:
    from truthweave.cli import (
        build_paper_command,
        check_command,
        claim_report_command,
        profile_report_command,
        provenance_report_command,
        review_thread_command,
        reviewer_packet_command,
        sync_refs_command,
        validate_profile_command,
        verification_report_command,
        verify_paper_command,
    )

    case_id = str(expectation.get("case_id", case_dir.name))
    with tempfile.TemporaryDirectory(prefix=f"truthweave-benchmark-{case_id}-") as tmp:
        temp_repo = Path(tmp)
        _materialize_benchmark_workspace(repo_root, case_dir, temp_repo, case_id)
        previous_root = os.environ.get("TRUTHWEAVE_REPO_ROOT")
        os.environ["TRUTHWEAVE_REPO_ROOT"] = str(temp_repo)
        try:
            _capture_command(sync_refs_command, case_id)
            _capture_command(provenance_report_command, case_id, "md")
            _capture_command(claim_report_command, case_id, "md")
            _capture_command(review_thread_command, case_id, "draft_reviewed", "md")
            _capture_command(verification_report_command, case_id, "md")
            _capture_command(reviewer_packet_command, case_id, "md")
            _capture_command(profile_report_command, case_id, "md")

            profile_report = build_profile_report(
                temp_repo, temp_repo / "papers" / case_id, case_id, write_output=False
            )
            validate_profile = _capture_command(validate_profile_command, case_id)
            check_ci = _capture_command(check_command, case_id, "ci")
            verify_paper = _capture_command(verify_paper_command, case_id, "md")
            with patch("truthweave.cli.shutil.which", lambda _: "/usr/bin/true"), patch(
                "truthweave.cli.subprocess.run", lambda *args, **kwargs: None
            ):
                build_paper = _capture_command(build_paper_command, case_id)
        finally:
            if previous_root is None:
                os.environ.pop("TRUTHWEAVE_REPO_ROOT", None)
            else:
                os.environ["TRUTHWEAVE_REPO_ROOT"] = previous_root

    observed = {
        "selected_profile": profile_report.get("selected_profile"),
        "profile_report": {
            "ok": not bool(profile_report.get("blockers")),
            "blocker_categories": sorted(
                {
                    str(blocker.get("category"))
                    for blocker in profile_report.get("blockers", [])
                    if isinstance(blocker, dict) and isinstance(blocker.get("category"), str)
                }
            ),
            "warning_count": len(profile_report.get("warnings", [])),
        },
        "validate_profile": {
            "ok": bool(validate_profile["ok"]),
            "message": validate_profile["message"],
        },
        "check_ci": {
            "ok": bool(check_ci["ok"]),
            **_parse_issue_categories(str(check_ci["output"])),
        },
        "verify_paper": {"ok": bool(verify_paper["ok"])},
        "build_paper": {"ok": bool(build_paper["ok"])},
    }

    expected = expectation.get("expected", {})
    regressions: list[str] = []

    expected_selected_profile = expected.get("selected_profile")
    if expected_selected_profile and observed["selected_profile"] != expected_selected_profile:
        regressions.append(
            f"selected_profile expected {expected_selected_profile} but observed {observed['selected_profile']}"
        )

    for key in ["profile_report", "validate_profile", "check_ci", "verify_paper", "build_paper"]:
        expected_entry = expected.get(key, {})
        if not isinstance(expected_entry, dict):
            continue
        observed_entry = observed.get(key, {})
        if not isinstance(observed_entry, dict):
            continue
        if "ok" in expected_entry and bool(expected_entry["ok"]) != bool(observed_entry.get("ok")):
            regressions.append(f"{key}.ok expected {expected_entry['ok']} but observed {observed_entry.get('ok')}")
        for list_key in ["fail_categories", "warn_categories", "blocker_categories"]:
            if list_key in expected_entry:
                expected_list = sorted(str(v) for v in expected_entry.get(list_key, []))
                observed_list = sorted(str(v) for v in observed_entry.get(list_key, []))
                if expected_list != observed_list:
                    regressions.append(
                        f"{key}.{list_key} expected {expected_list} but observed {observed_list}"
                    )
        if "warning_count" in expected_entry:
            expected_count = int(expected_entry["warning_count"])
            observed_count = int(observed_entry.get("warning_count", 0))
            if expected_count != observed_count:
                regressions.append(
                    f"{key}.warning_count expected {expected_count} but observed {observed_count}"
                )

    return {
        "case_id": case_id,
        "profile": observed["selected_profile"],
        "kind": expectation.get("kind", "unspecified"),
        "description": expectation.get("description", ""),
        "expected": expected,
        "observed": observed,
        "regressions": regressions,
        "ok": not regressions,
    }


def run_benchmark_suite(
    repo_root: Path,
    case_ids: list[str] | None = None,
    write_output: bool = False,
) -> dict[str, Any]:
    cases_dir = benchmark_cases_dir(repo_root)
    requested = set(case_ids or [])
    case_dirs = [
        path
        for path in sorted(cases_dir.iterdir())
        if path.is_dir() and (not requested or path.name in requested)
    ]

    results: list[dict[str, Any]] = []
    for case_dir in case_dirs:
        expectation = load_benchmark_expectation(case_dir / "expectation.yml")
        results.append(_run_case(repo_root, case_dir, expectation))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "cases_total": len(results),
            "cases_passed": sum(1 for result in results if result.get("ok")),
            "cases_failed": sum(1 for result in results if not result.get("ok")),
            "positive_cases": sum(1 for result in results if result.get("kind") == "positive"),
            "negative_cases": sum(1 for result in results if result.get("kind") == "negative"),
            "regressions": sum(len(result.get("regressions", [])) for result in results),
        },
        "results": results,
    }

    if write_output:
        out_path = benchmark_report_path(repo_root)
        ensure_dir(out_path.parent)
        write_json(out_path, report)
        benchmark_markdown_path(repo_root).write_text(
            render_benchmark_report(report, "md")
        )
    return report


def render_benchmark_report(report: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output_format == "md":
        lines = [
            "# Benchmark Report",
            "",
            f"- cases_total: {report.get('summary', {}).get('cases_total', 0)}",
            f"- cases_passed: {report.get('summary', {}).get('cases_passed', 0)}",
            f"- cases_failed: {report.get('summary', {}).get('cases_failed', 0)}",
            f"- regressions: {report.get('summary', {}).get('regressions', 0)}",
            "",
            "## Cases",
        ]
        for result in report.get("results", []):
            if not isinstance(result, dict):
                continue
            status = "ok" if result.get("ok") else "regression"
            lines.append(
                f"- {result.get('case_id')}: {status} ({result.get('profile')}, kind={result.get('kind')})"
            )
            regressions = result.get("regressions", [])
            if isinstance(regressions, list):
                for regression in regressions:
                    lines.append(f"  - {regression}")
        return "\n".join(lines) + "\n"
    header = "case_id\tprofile\tkind\tok\tregressions"
    rows = [header]
    for result in report.get("results", []):
        if not isinstance(result, dict):
            continue
        rows.append(
            f"{result.get('case_id')}\t{result.get('profile')}\t{result.get('kind')}\t"
            f"{result.get('ok')}\t{len(result.get('regressions', []))}"
        )
    return "\n".join(rows) + "\n"
