from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from truthweave.utils import ensure_dir, write_json


def _default_paper_config() -> dict[str, Any]:
    return {
        "paper_id": "",
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
            }
        },
    }


def _merge_defaults(defaults: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    merged = defaults.copy()
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = merged[key].copy()
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def load_paper_config(path: Path) -> dict[str, Any]:
    cfg = OmegaConf.load(path)
    data = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid truthweave.yml at {path}")
    merged = _merge_defaults(_default_paper_config(), data)
    return merged


def discover_papers(repo_root: Path) -> dict[str, Any]:
    papers_dir = repo_root / "papers"
    if not papers_dir.exists():
        return {"papers": [], "generated_at": datetime.now(timezone.utc).isoformat()}

    entries = []
    for config_path in sorted(papers_dir.rglob("truthweave.yml")):
        paper_dir = config_path.parent
        config = load_paper_config(config_path)
        paper_id = config.get("paper_id") or paper_dir.name
        main = config.get("main", "main.tex")
        engine = config.get("engine", "latexmk")
        bib = config.get("bib", "refs.bib")

        entries.append(
            {
                "paper_id": paper_id,
                "path": str(paper_dir.relative_to(repo_root)),
                "engine": engine,
                "main": main,
                "bib": bib,
            }
        )

    entries.sort(key=lambda item: item["paper_id"])
    return {"papers": entries, "generated_at": datetime.now(timezone.utc).isoformat()}


def write_discovery_manifest(repo_root: Path) -> Path:
    manifest = discover_papers(repo_root)
    out_dir = repo_root / "artifacts" / "manifests"
    ensure_dir(out_dir)
    out_path = out_dir / "papers_index.json"
    write_json(out_path, manifest)
    return out_path


def get_paper_by_id(repo_root: Path, paper_id: str) -> dict[str, Any]:
    manifest = discover_papers(repo_root)
    for paper in manifest["papers"]:
        if paper["paper_id"] == paper_id:
            return paper
    raise SystemExit(f"Unknown paper_id '{paper_id}'. Run paperops discover.")
