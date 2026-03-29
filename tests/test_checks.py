from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from truthweave.cli import (
    argument_audit_command,
    build_paper_command,
    claim_report_command,
    check_command,
    create_exp_command,
    provenance_report_command,
    reviewer_packet_command,
    run_command,
    scaffold_evidence_command,
    scaffold_provenance_command,
    validate_brief_command,
    validate_evidence_command,
    validate_provenance_command,
)
from truthweave.checks import check_structure
from truthweave.evidence import build_claim_ledger
from truthweave.packet import build_reviewer_packet
from truthweave.provenance import build_provenance_ledger
from truthweave.references import sync_references
from truthweave.reviews import build_thread_review


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _setup_min_repo(tmp_path: Path) -> None:
    (tmp_path / "conf").mkdir()
    _write_file(
        tmp_path / "conf" / "base.yaml",
        "project:\n  runs_dir: runs\nruntime:\n  seed: 1\nexperiment:\n  name: example\n  output_subdir: run1\n",
    )
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
        paper_dir / "brief.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": paper_id,
                "phase_status": "release_ready",
                "central_claim": "Metrics flow from experiments into paper claims.",
                "so_what": "This keeps the argument auditable.",
                "novelty": "The workflow links runs and writing.",
                "target_reader": "Researchers.",
                "key_questions": ["Can the main claim be traced?"],
                "expected_source_ids": ["example_source"],
                "planned_evidence": [
                    {
                        "claim_id": "main_claim",
                        "required": True,
                        "experiment": "example",
                        "description": "MetricMean supports the main claim.",
                        "expected_metrics": ["MetricMean"],
                        "source_ids": ["example_source"],
                        "prohibited_substitutes": [],
                    }
                ],
                "non_goals": ["Autonomous publication."],
            }
        ),
    )
    _write_file(
        paper_dir / "evidence.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": paper_id,
                "claims": [
                    {
                        "claim_id": "main_claim",
                        "status": "supported",
                        "note": "Bound to generated metric and manifest provenance.",
                        "evidence": [
                            {
                                "kind": "variable",
                                "artifact_path": "auto/variables.tex",
                                "variable": "MetricMean",
                                "source_ids": ["example_source"],
                            },
                            {
                                "kind": "manifest",
                                "artifact_path": "auto/MANIFEST.json",
                                "manifest_pointer": "source.metrics_json_path",
                                "run_id": "run1",
                                "source_ids": ["example_source"],
                            },
                        ],
                    }
                ],
            }
        ),
    )
    _write_file(
        paper_dir / "data_sources.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": paper_id,
                "sources": [
                    {
                        "source_id": "example_source",
                        "title": "Synthetic example source",
                        "source_type": "synthetic",
                        "acquisition_mode": "generated_internal",
                        "status": "verified",
                        "license_note": "Generated inside the test repo.",
                        "reproducibility_level": "fully_reproducible",
                        "pointers": [
                            {
                                "kind": "file",
                                "path": "conf/base.yaml",
                                "version_note": "Test config anchor",
                            },
                            {
                                "kind": "manifest",
                                "path": "auto/MANIFEST.json",
                                "manifest_pointer": "source.metrics_json_path",
                                "run_id": "run1",
                            },
                        ],
                        "snapshot": "run1",
                        "note": "Test provenance entry.",
                    }
                ],
            }
        ),
    )
    _write_file(
        paper_dir / "references.yml",
        OmegaConf.to_yaml(
            {
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
        ),
    )
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
                "quality": {"thread": {"min_alignment_ci": 0.6}},
            }
        ),
    )
    _write_file(paper_dir / "main.tex", "Example metric: \\MetricMean.\n")
    _write_file(paper_dir / "auto" / "variables.tex", "\\newcommand{\\MetricMean}{1}\n")
    _write_file(paper_dir / "refs.bib", "")

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
                "claim_ids": ["main_claim"],
            },
            "generated_at": "2024-01-01T00:00:00Z",
        },
    }
    _write_file(paper_dir / "auto" / "MANIFEST.json", json.dumps(manifest))
    sync_references(tmp_path, paper_dir, paper_id)
    build_claim_ledger(tmp_path, paper_dir, paper_id, write_output=True)
    build_provenance_ledger(tmp_path, paper_dir, paper_id, write_output=True)
    build_thread_review(tmp_path, paper_dir, paper_id, "draft_reviewed")
    build_reviewer_packet(tmp_path, paper_dir, paper_id, write_output=True)


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


def test_validate_brief_command_accepts_valid_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    validate_brief_command("paper1")


def test_validate_evidence_command_accepts_valid_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    validate_evidence_command("paper1")


def test_validate_provenance_command_accepts_valid_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    validate_provenance_command("paper1")


def test_scaffold_evidence_command_creates_starter_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    (tmp_path / "papers" / "paper1" / "evidence.yml").unlink()
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    scaffold_evidence_command("paper1")

    evidence = OmegaConf.to_container(
        OmegaConf.load(tmp_path / "papers" / "paper1" / "evidence.yml"),
        resolve=True,
    )
    assert evidence["claims"][0]["claim_id"] == "main_claim"


def test_scaffold_provenance_command_creates_starter_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    (tmp_path / "papers" / "paper1" / "data_sources.yml").unlink()
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    scaffold_provenance_command("paper1")

    provenance = OmegaConf.to_container(
        OmegaConf.load(tmp_path / "papers" / "paper1" / "data_sources.yml"),
        resolve=True,
    )
    assert provenance["sources"][0]["source_id"] == "example_source"


def test_run_command_requires_experiment_ready_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "brief.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "phase_status": "idea_locked",
                "central_claim": "c",
                "so_what": "s",
                "novelty": "n",
                "target_reader": "t",
                "key_questions": ["k"],
                "planned_evidence": [
                    {
                        "claim_id": "main_claim",
                        "required": True,
                        "experiment": "example",
                        "description": "d",
                    }
                ],
                "non_goals": ["x"],
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr("truthweave.cli._load_config", lambda overrides: OmegaConf.create(
        {
            "project": {"runs_dir": "runs"},
            "runtime": {"seed": 1},
            "experiment": {"name": "example", "output_subdir": "run1"},
        }
    ))

    with pytest.raises(SystemExit):
        run_command(["exp=example"])


def test_run_command_blocks_unavailable_required_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "data_sources.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "sources": [
                    {
                        "source_id": "example_source",
                        "title": "Synthetic example source",
                        "source_type": "synthetic",
                        "acquisition_mode": "generated_internal",
                        "status": "unavailable",
                        "license_note": "Generated inside the test repo.",
                        "reproducibility_level": "manual_step_required",
                        "pointers": [],
                        "snapshot": "run1",
                        "note": "",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr("truthweave.cli._load_config", lambda overrides: OmegaConf.create(
        {
            "project": {"runs_dir": "runs"},
            "runtime": {"seed": 1},
            "experiment": {"name": "example", "output_subdir": "run1"},
        }
    ))

    with pytest.raises(SystemExit):
        run_command(["exp=example"])


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

    argument_audit_command("paper1", "json", "dev")

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["mode"] == "dev"
    assert len(payload["papers"]) == 1
    assert payload["papers"][0]["paper_id"] == "paper1"
    assert payload["papers"][0]["claim_support"] == 1.0
    assert payload["papers"][0]["status"] == "pass"


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
        argument_audit_command("paper1", "json", "dev")


def test_argument_audit_command_ci_fails_on_threshold_breach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                "paths": {
                    "auto_dir": "auto",
                    "figures_dir": "figures",
                    "tables_dir": "tables",
                },
                "quality": {"argument": {"min_claim_support_ci": 1.0}},
            }
        ),
    )
    manifest_path = tmp_path / "papers" / "paper1" / "auto" / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["generated"]["argument_audit"]["claim_support"] = 0.5
    manifest["generated"]["argument_audit"]["unsupported_claims"] = 1
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        argument_audit_command("paper1", "json", "ci")


def test_claim_report_command_writes_claim_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    claim_report_command("paper1", "json")

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["entries"][0]["claim_id"] == "main_claim"
    assert (
        tmp_path / "artifacts" / "claims" / "paper1" / "claim_ledger.json"
    ).exists()
    manifest = json.loads((tmp_path / "papers" / "paper1" / "auto" / "MANIFEST.json").read_text())
    assert manifest["generated"]["claim_ledger"]["path"] == "artifacts/claims/paper1/claim_ledger.json"


def test_provenance_report_command_writes_provenance_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    provenance_report_command("paper1", "json")

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["entries"][0]["source_id"] == "example_source"
    assert (
        tmp_path / "artifacts" / "provenance" / "paper1" / "provenance_ledger.json"
    ).exists()
    manifest = json.loads((tmp_path / "papers" / "paper1" / "auto" / "MANIFEST.json").read_text())
    assert (
        manifest["generated"]["provenance_ledger"]["path"]
        == "artifacts/provenance/paper1/provenance_ledger.json"
    )


def test_reviewer_packet_command_writes_packet_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    reviewer_packet_command("paper1", "json")

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["paper"]["paper_id"] == "paper1"
    packet_dir = tmp_path / "artifacts" / "packets" / "paper1"
    assert (packet_dir / "packet.json").exists()
    assert (packet_dir / "packet.md").exists()
    assert (packet_dir / "claims.csv").exists()
    assert (packet_dir / "sources.csv").exists()
    assert (packet_dir / "rerun_checklist.md").exists()
    manifest = json.loads((tmp_path / "papers" / "paper1" / "auto" / "MANIFEST.json").read_text())
    assert (
        manifest["generated"]["reviewer_packet"]["path"]
        == "artifacts/packets/paper1/packet.json"
    )


def test_check_mode_ci_fails_on_stale_thread_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(tmp_path / "papers" / "paper1" / "main.tex", "Claim changed \\MetricMean.\n")
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:REVIEW_STALENESS]" in output


def test_check_mode_ci_fails_on_stale_reviewer_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(tmp_path / "papers" / "paper1" / "main.tex", "Claim changed \\MetricMean.\n")
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:PACKET_STALENESS]" in output


def test_check_mode_ci_fails_on_reference_lock_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(tmp_path / "papers" / "paper1" / "refs.bib", "@article{broken,\n  title={Broken}\n}\n")
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:REFERENCE_PROVENANCE]" in output


def test_check_mode_ci_fails_on_missing_claim_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "evidence.yml",
        OmegaConf.to_yaml({"paper_id": "paper1", "claims": []}),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:CLAIM_COVERAGE]" in output


def test_check_mode_ci_fails_on_missing_reviewer_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    packet_dir = tmp_path / "artifacts" / "packets" / "paper1"
    for path in packet_dir.iterdir():
        path.unlink()
    packet_dir.rmdir()
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:PACKET_CONSISTENCY]" in output


def test_check_mode_ci_fails_on_orphan_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "evidence.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "claims": [
                    {
                        "claim_id": "ghost_claim",
                        "status": "supported",
                        "evidence": [
                            {
                                "kind": "artifact",
                                "artifact_path": "runs/run1/metrics.json",
                            }
                        ],
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:ORPHAN_EVIDENCE]" in output


def test_check_mode_ci_fails_on_missing_declared_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "data_sources.yml",
        OmegaConf.to_yaml({"paper_id": "paper1", "sources": []}),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:DATA_SOURCE_DECLARED]" in output


def test_check_mode_ci_fails_on_unresolved_source_pointer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "data_sources.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "sources": [
                    {
                        "source_id": "example_source",
                        "title": "Synthetic example source",
                        "source_type": "synthetic",
                        "acquisition_mode": "generated_internal",
                        "status": "verified",
                        "license_note": "Generated inside the test repo.",
                        "reproducibility_level": "fully_reproducible",
                        "pointers": [{"kind": "file", "path": "missing.txt"}],
                        "snapshot": "run1",
                        "note": "",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:DATA_SOURCE_POINTER_RESOLUTION]" in output


def test_check_mode_ci_fails_on_forbidden_substitute(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "brief.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "phase_status": "release_ready",
                "central_claim": "Metrics flow from experiments into paper claims.",
                "so_what": "This keeps the argument auditable.",
                "novelty": "The workflow links runs and writing.",
                "target_reader": "Researchers.",
                "key_questions": ["Can the main claim be traced?"],
                "expected_source_ids": ["example_source"],
                "planned_evidence": [
                    {
                        "claim_id": "main_claim",
                        "required": True,
                        "experiment": "example",
                        "description": "MetricMean supports the main claim.",
                        "expected_metrics": ["MetricMean"],
                        "source_ids": ["example_source"],
                        "prohibited_substitutes": ["synthetic"],
                    }
                ],
                "non_goals": ["Autonomous publication."],
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))

    with pytest.raises(SystemExit):
        check_command("paper1", mode="ci")

    output = capsys.readouterr().out
    assert "[FAIL:FORBIDDEN_SUBSTITUTE]" in output


def test_build_paper_command_blocks_unsupported_major_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "evidence.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "claims": [
                    {
                        "claim_id": "main_claim",
                        "status": "unsupported",
                        "evidence": [],
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr("truthweave.cli.shutil.which", lambda _: "/usr/bin/true")
    monkeypatch.setattr("truthweave.cli.subprocess.run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit):
        build_paper_command("paper1")


def test_build_paper_command_blocks_invalid_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "data_sources.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "sources": [
                    {
                        "source_id": "example_source",
                        "title": "Synthetic example source",
                        "source_type": "synthetic",
                        "acquisition_mode": "generated_internal",
                        "status": "stale",
                        "license_note": "Generated inside the test repo.",
                        "reproducibility_level": "fully_reproducible",
                        "pointers": [
                            {
                                "kind": "manifest",
                                "path": "auto/MANIFEST.json",
                                "manifest_pointer": "source.metrics_json_path",
                                "run_id": "run0",
                            }
                        ],
                        "snapshot": "run0",
                        "note": "",
                    }
                ],
            }
        ),
    )
    monkeypatch.setenv("TRUTHWEAVE_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr("truthweave.cli.shutil.which", lambda _: "/usr/bin/true")
    monkeypatch.setattr("truthweave.cli.subprocess.run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit):
        build_paper_command("paper1")


def test_build_claim_ledger_marks_stale_when_run_id_drifts(tmp_path: Path) -> None:
    _setup_min_repo(tmp_path)
    _setup_paper(tmp_path, "paper1", stale_manifest=False)
    _write_file(
        tmp_path / "papers" / "paper1" / "evidence.yml",
        OmegaConf.to_yaml(
            {
                "paper_id": "paper1",
                "claims": [
                    {
                        "claim_id": "main_claim",
                        "status": "supported",
                        "evidence": [
                            {
                                "kind": "manifest",
                                "artifact_path": "auto/MANIFEST.json",
                                "manifest_pointer": "source.metrics_json_path",
                                "run_id": "run0",
                            }
                        ],
                    }
                ],
            }
        ),
    )

    ledger = build_claim_ledger(tmp_path, tmp_path / "papers" / "paper1", "paper1")

    assert ledger["entries"][0]["status"] == "stale"
