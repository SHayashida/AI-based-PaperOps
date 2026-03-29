from __future__ import annotations

from pathlib import Path

from truthweave.benchmarks import (
    benchmark_cases_dir,
    load_benchmark_expectation,
    render_benchmark_report,
    run_benchmark_suite,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_benchmark_expectation() -> None:
    path = (
        benchmark_cases_dir(REPO_ROOT)
        / "finance_ml_positive"
        / "expectation.yml"
    )
    expectation = load_benchmark_expectation(path)
    assert expectation["case_id"] == "finance_ml_positive"
    assert expectation["expected"]["check_ci"]["ok"] is True


def test_run_benchmark_suite_positive_case() -> None:
    report = run_benchmark_suite(
        REPO_ROOT, case_ids=["simulation_abm_positive"], write_output=False
    )
    assert report["summary"]["cases_total"] == 1
    assert report["summary"]["regressions"] == 0
    assert report["results"][0]["ok"] is True


def test_run_benchmark_suite_negative_case() -> None:
    report = run_benchmark_suite(
        REPO_ROOT,
        case_ids=["formal_methods_negative_missing_verification"],
        write_output=False,
    )
    assert report["summary"]["cases_total"] == 1
    assert report["summary"]["regressions"] == 0
    assert report["results"][0]["observed"]["verify_paper"]["ok"] is False


def test_render_benchmark_report_markdown() -> None:
    report = run_benchmark_suite(
        REPO_ROOT, case_ids=["finance_ml_missing_baseline"], write_output=False
    )
    rendered = render_benchmark_report(report, "md")
    assert "# Benchmark Report" in rendered
    assert "finance_ml_missing_baseline" in rendered
