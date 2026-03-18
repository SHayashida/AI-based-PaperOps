from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from truthweave.cli import argument_audit_command, check_command, create_exp_command
from truthweave.checks import check_structure


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _setup_min_repo(tmp_path: Path) -> None:
    (tmp_path / "conf").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "papers").mkdir()
    (tmp_path / "src" / "truthweave").mkdir(parents=True)

    run_dir = tmp_path / "runs" / "run1"
    (run_dir / "artifacts").mkdir(parents=True)
    for name in [
        "config_resolved.yaml",
        "git_commit.txt",
        "command.txt",
        "env_freeze.txt",
        "hardware.json",
        "seeds.json",
        "metrics.json",
    ]:
        _write_file(run_dir / name, "{}")


def _setup_paper(tmp_path: Path, paper_id: str, stale_manifest: bool) -> None:
    paper_dir = tmp_path / "papers" / paper_id
    (paper_dir / "auto").mkdir(parents=True)
    (paper_dir / "styles").mkdir()
    (paper_dir / "figures").mkdir()
    (paper_dir / "tables").mkdir()
    _write_file(
        paper_dir / "truthweave.yml",
        OmegaConf.to_yaml(
            {
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
            }
        ),
    )
    _write_file(paper_dir / "main.tex", "Example metric: \\MetricMean.\n")
    _write_file(paper_dir / "auto" / "variables.tex", "\\newcommand{\\MetricMean}{1}\n")

    run_dir = tmp_path / "runs" / "run1"
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps({"metric": 1}))
    digest = sha256(metrics_path.read_bytes()).hexdigest()
    if stale_manifest:
        digest = "0" * 64
    manifest = {
        "source": {
            "paper_id": paper_id,
            "run_dir": "runs/run1",
            "metrics_source": "latest",
            "metrics_json_path": "runs/run1/metrics.json",
            "metrics_json_sha256": digest,
        },
        "generated": {
            "variables_tex_sha256": "0" * 64,
            "figures_sha256": {},
            "tables_sha256": {},
            "argument_audit": {
                "claim_support": 1.0,
                "claims_count": 1,
                "unsupported_claims": 0,
                "orphan_metrics": 0,
                "unsupported_macros": [],
                "orphan_macros": [],
            },
            "generated_at": "2024-01-01T00:00:00Z",
        },
    }
    _write_file(paper_dir / "auto" / "MANIFEST.json", json.dumps(manifest))


def test_check_mode_dev_does_not_fail_on_structure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    (tmp_path / "stray").mkdir()
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    check_command(None, mode="dev")
    output = capsys.readouterr().out
    assert "[WARN:STRUCTURE]" in output
    assert "Fix:" in output


def test_check_mode_ci_fails_on_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    (tmp_path / "stray").mkdir()
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command(None, mode="ci")


def test_structure_check_rejects_stray_dirs_in_ci(tmp_path: Path) -> None:
    (tmp_path / "conf").mkdir()
    (tmp_path / "stray").mkdir()
    issues = check_structure.check(tmp_path, mode="ci")
    assert issues
    assert issues[0].severity == "FAIL"


def test_fix_message_includes_fix_and_recheck(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=True)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")
    output = capsys.readouterr().out
    assert "Fix: uv run truthweave build-paper-assets --paper paper1" in output
    assert "Recheck: uv run truthweave check --paper paper1 --mode ci" in output


def test_create_exp_scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "conf" / "exp").mkdir(parents=True)
    (tmp_path / "src" / "truthweave" / "experiments").mkdir(parents=True)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    create_exp_command("myexp")

    assert (tmp_path / "conf" / "exp" / "myexp.yaml").exists()
    assert (tmp_path / "src" / "truthweave" / "experiments" / "myexp.py").exists()


def test_check_mode_ci_fails_on_undefined_metric_macro(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(tmp_path / "papers" / "paper1" / "main.tex", "Claim: \\MetricUnknown.\n")
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:ARGUMENT_TRACE]" in output
    assert "\\MetricUnknown" in output


def test_check_mode_dev_warns_on_orphan_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "auto" / "variables.tex",
        "\\newcommand{\\MetricMean}{1}\n\\newcommand{\\MetricN}{1000}\n",
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    check_command("paper1", mode="dev")

    output = capsys.readouterr().out
    assert "[WARN:ARGUMENT_COVERAGE]" in output
    assert "claim_support=1.00" in output


def test_check_mode_ci_fails_on_stale_figure_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(tmp_path / "papers" / "paper1" / "figures" / "f1.txt", "artifact")
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "Figure/table assets are stale" in output


def test_check_mode_ci_fails_on_stale_argument_audit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(tmp_path / "papers" / "paper1" / "main.tex", "No claims here.\n")
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "Argument audit is stale" in output


def test_check_mode_ci_fails_on_claim_support_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "truthweave.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "engine": "latexmk",
                "main": "main.tex",
                "bib": "refs.bib",
                "paths": {
                    "auto_dir": "auto",
                    "figures_dir": "figures",
                    "tables_dir": "tables",
                },
                "quality": {
                    "argument": {
                        "min_claim_support_ci": 0.9,
                    }
                },
            }
        ),
    )
    _write_file(
        tmp_path / "papers" / "paper1" / "main.tex",
        "Claim: \\MetricMean and \\MetricUnknown.\n",
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:ARGUMENT_SUPPORT]" in output
    assert "claim_support=0.50 < min_claim_support_ci=0.90" in output


def test_check_mode_dev_respects_orphan_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "truthweave.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "engine": "latexmk",
                "main": "main.tex",
                "bib": "refs.bib",
                "paths": {
                    "auto_dir": "auto",
                    "figures_dir": "figures",
                    "tables_dir": "tables",
                },
                "quality": {
                    "argument": {
                        "max_orphan_metrics_dev": 1,
                    }
                },
            }
        ),
    )
    _write_file(
        tmp_path / "papers" / "paper1" / "auto" / "variables.tex",
        "\\newcommand{\\MetricMean}{1}\n\\newcommand{\\MetricN}{1000}\n",
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    check_command("paper1", mode="dev")

    output = capsys.readouterr().out
    assert "[WARN:ARGUMENT_COVERAGE]" not in output


def test_argument_audit_command_outputs_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    argument_audit_command("paper1", "json")

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert len(payload["papers"]) == 1
    assert payload["papers"][0]["paper_id"] == "paper1"
    assert payload["papers"][0]["claim_support"] == 1.0


def test_argument_audit_command_requires_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    paper_dir = tmp_path / "papers" / "paper1"
    (paper_dir / "auto").mkdir(parents=True)
    (paper_dir / "styles").mkdir()
    _write_file(
        paper_dir / "truthweave.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "engine": "latexmk",
                "main": "main.tex",
                "paths": {
                    "auto_dir": "auto",
                    "figures_dir": "figures",
                    "tables_dir": "tables",
                },
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        argument_audit_command("paper1", "json")
