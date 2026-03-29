from __future__ import annotations

from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from truthweave.checks.models import Issue


def _default_contract() -> dict[str, Any]:
    return {
        "top_level": {
            "allow_dirs": [
                ".github",
                ".venv",
                "artifacts",
                "benchmarks",
                "conf",
                "data",
                "paper",
                "papers",
                "profiles",
                "runs",
                "src",
                "tests",
            ],
            "allow_files": [
                ".gitignore",
                "Makefile",
                "PaperOps Template v0.md",
                "README.md",
                "Snakefile",
                "pyproject.toml",
                "uv.lock",
            ],
        },
        "rules": {
            "require_paperops_yml": True,
            "allow_hidden": True,
        },
    }


def _load_contract(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "conf" / "repo_contract.yml"
    if not path.exists():
        return _default_contract()
    data = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
    if not isinstance(data, dict):
        return _default_contract()
    merged = _default_contract()
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = merged[key].copy()
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def check(repo_root: Path, mode: str) -> list[Issue]:
    contract = _load_contract(repo_root)
    top_level = contract.get("top_level", {})
    allow_dirs = set(top_level.get("allow_dirs", []))
    allow_files = set(top_level.get("allow_files", []))
    rules = contract.get("rules", {})
    allow_hidden = bool(rules.get("allow_hidden", True))

    errors: list[str] = []

    for entry in repo_root.iterdir():
        name = entry.name
        if name.startswith(".") and allow_hidden:
            continue
        if entry.is_dir() and name not in allow_dirs:
            errors.append(f"Unexpected top-level dir: {name}")
        if entry.is_file() and name not in allow_files:
            errors.append(f"Unexpected top-level file: {name}")

    src_dir = repo_root / "src"
    if src_dir.exists():
        for entry in src_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name == "truthweave":
                continue
            if entry.name.endswith(".egg-info"):
                continue
            errors.append(f"Unexpected src package dir: src/{entry.name}")

    experiments_dir = repo_root / "src" / "truthweave" / "experiments"
    for entry in repo_root.rglob("experiments"):
        if any(part.startswith(".") for part in entry.parts):
            continue
        if entry.is_dir() and entry.resolve() != experiments_dir.resolve():
            errors.append(f"Unexpected experiments dir: {entry.relative_to(repo_root)}")

    analysis_dir = repo_root / "src" / "truthweave" / "analysis"
    for entry in repo_root.rglob("analysis"):
        if any(part.startswith(".") for part in entry.parts):
            continue
        if entry.is_dir() and entry.resolve() != analysis_dir.resolve():
            errors.append(f"Unexpected analysis dir: {entry.relative_to(repo_root)}")

    data_dir = repo_root / "data"
    if data_dir.exists():
        for entry in data_dir.iterdir():
            if entry.is_dir() and entry.name not in {"raw", "processed"}:
                errors.append(f"Unexpected data dir: data/{entry.name}")

    papers_dir = repo_root / "papers"
    if papers_dir.exists():
        for entry in papers_dir.iterdir():
            if entry.is_file():
                errors.append(f"Unexpected file under papers/: {entry.name}")
                continue
            paperops_yml = entry / "truthweave.yml"
            if rules.get("require_paperops_yml", True) and not paperops_yml.exists():
                errors.append(f"Missing truthweave.yml in papers/{entry.name}")

    if errors:
        fix = "Move files into allowed dirs or delete stray dirs. Offenders: " + "; ".join(
            errors
        )
        recheck = f"uv run truthweave check --mode {mode}"
        severity = "FAIL" if mode == "ci" else "WARN"
        return [
            Issue(
                category="STRUCTURE",
                severity=severity,
                message="Structure check failed: " + "; ".join(errors),
                fix=fix,
                recheck=recheck,
                paths=errors,
            )
        ]
    return []
