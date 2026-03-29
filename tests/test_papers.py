from __future__ import annotations

import json
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from truthweave.cli import create_paper_command, discover_command
from truthweave.papers import load_paper_config
from truthweave.checks import check_structure


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPERS_DIR = REPO_ROOT / "papers"


def _cleanup_paper(paper_id: str) -> None:
    target = PAPERS_DIR / paper_id
    if target.exists():
        for child in target.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(target.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        target.rmdir()


def test_create_paper_creates_structure() -> None:
    paper_id = "tmp_paper_a"
    _cleanup_paper(paper_id)
    create_paper_command(paper_id, None, None)
    try:
        paper_dir = PAPERS_DIR / paper_id
        assert (paper_dir / "truthweave.yml").exists()
        assert (paper_dir / "brief.yml").exists()
        assert (paper_dir / "evidence.yml").exists()
        assert (paper_dir / "data_sources.yml").exists()
        assert (paper_dir / "main.tex").exists()
        assert (paper_dir / "references.yml").exists()
        assert (paper_dir / "refs.bib").exists()
        assert (paper_dir / "styles" / ".gitkeep").exists()
        cfg = load_paper_config(paper_dir / "truthweave.yml")
        assert cfg["paper_id"] == paper_id
    finally:
        _cleanup_paper(paper_id)


def test_create_paper_clone() -> None:
    base_id = "basepaper"
    new_id = "clonepaper"
    _cleanup_paper(base_id)
    _cleanup_paper(new_id)

    base_dir = PAPERS_DIR / base_id
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "styles").mkdir(parents=True, exist_ok=True)
    (base_dir / "auto").mkdir(parents=True, exist_ok=True)
    (base_dir / "figures").mkdir(parents=True, exist_ok=True)
    (base_dir / "tables").mkdir(parents=True, exist_ok=True)
    (base_dir / "styles" / "style.sty").write_text("% style")
    (base_dir / "auto" / "generated.txt").write_text("generated")
    config = {
        "paper_id": base_id,
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
    OmegaConf.save(OmegaConf.create(config), base_dir / "truthweave.yml")
    OmegaConf.save(
        OmegaConf.create(
            {
                "paper_id": base_id,
                "phase_status": "release_ready",
                "central_claim": "c",
                "so_what": "s",
                "novelty": "n",
                "target_reader": "t",
                "key_questions": ["k"],
                "expected_source_ids": ["base_source"],
                "planned_evidence": [
                    {
                        "claim_id": "main_claim",
                        "required": True,
                        "experiment": "example",
                        "description": "d",
                        "source_ids": ["base_source"],
                        "prohibited_substitutes": [],
                    }
                ],
                "non_goals": ["x"],
            }
        ),
        base_dir / "brief.yml",
    )
    OmegaConf.save(
        OmegaConf.create(
            {
                "paper_id": base_id,
                "claims": [
                    {
                        "claim_id": "main_claim",
                        "status": "supported",
                        "evidence": [
                            {
                                "kind": "variable",
                                "artifact_path": "auto/variables.tex",
                                "variable": "MetricMean",
                                "source_ids": ["base_source"],
                            }
                        ],
                    }
                ],
            }
        ),
        base_dir / "evidence.yml",
    )
    OmegaConf.save(
        OmegaConf.create(
            {
                "paper_id": base_id,
                "sources": [
                    {
                        "source_id": "base_source",
                        "title": "Base synthetic source",
                        "source_type": "synthetic",
                        "acquisition_mode": "generated_internal",
                        "status": "verified",
                        "license_note": "Generated in repo",
                        "reproducibility_level": "fully_reproducible",
                        "pointers": [
                            {"kind": "file", "path": "main.tex"},
                        ],
                        "snapshot": "base-snapshot",
                        "note": "",
                    }
                ],
            }
        ),
        base_dir / "data_sources.yml",
    )
    OmegaConf.save(
        OmegaConf.create(
            {
                "paper_id": base_id,
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
        base_dir / "references.yml",
    )
    (base_dir / "main.tex").write_text("\\input{auto/variables.tex}")
    (base_dir / "refs.bib").write_text("@article{a}")

    create_paper_command(new_id, base_id, None)
    try:
        new_dir = PAPERS_DIR / new_id
        assert (new_dir / "styles" / "style.sty").exists()
        assert not (new_dir / "auto" / "generated.txt").exists()
        assert (new_dir / "brief.yml").exists()
        assert (new_dir / "evidence.yml").exists()
        assert (new_dir / "data_sources.yml").exists()
        assert (new_dir / "references.yml").exists()
        cfg = load_paper_config(new_dir / "truthweave.yml")
        assert cfg["paper_id"] == new_id
    finally:
        _cleanup_paper(base_id)
        _cleanup_paper(new_id)


def test_discover_index_sorted() -> None:
    ids = ["zz_test", "aa_test"]
    for pid in ids:
        _cleanup_paper(pid)
        create_paper_command(pid, None, None)

    try:
        discover_command()
        index = REPO_ROOT / "artifacts" / "manifests" / "papers_index.json"
        data = json.loads(index.read_text())
        paper_ids = [p["paper_id"] for p in data["papers"]]
        assert paper_ids == sorted(paper_ids)
    finally:
        for pid in ids:
            _cleanup_paper(pid)


def test_check_structure_detects_stray_top_level(tmp_path: Path) -> None:
    contract = {
        "top_level": {"allow_dirs": ["conf"], "allow_files": []},
        "rules": {"allow_hidden": False},
    }
    conf_dir = tmp_path / "conf"
    conf_dir.mkdir()
    OmegaConf.save(OmegaConf.create(contract), conf_dir / "repo_contract.yml")
    (tmp_path / "stray").mkdir()

    issues = check_structure.check(tmp_path, mode="ci")
    assert issues
    assert issues[0].category == "STRUCTURE"
