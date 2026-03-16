from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hydra
from omegaconf import OmegaConf

from truthweave.checks import (
    check_no_manual_numbers,
    check_paper_freshness,
    check_run_integrity,
    check_structure,
)
from truthweave.checks.models import Issue
from truthweave.papers import get_paper_by_id, load_paper_config, write_discovery_manifest
from truthweave.registry import get_experiment_class
from truthweave.runner import ExperimentRunner
from truthweave.utils import ensure_dir, find_latest_run, sha256_file, write_json


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
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    write_json(auto_dir / "MANIFEST.json", manifest)


def _build_paper(paper_id: str) -> None:
    repo_root = _repo_root()
    paper = get_paper_by_id(repo_root, paper_id)
    paper_dir = repo_root / paper["path"]
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
            "-output-directory",
            str(output_dir),
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
    from paperops import experiments  # noqa: F401

    cfg = _load_config(overrides)
    run_dir = _resolve_run_dir(cfg)

    experiment_name = cfg.experiment.name
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
        issues.extend(
            check_paper_freshness.check(repo_root, paper_dir, paper_id, mode)
        )
        tex_path = paper_dir / config.get("main", "main.tex")
        issues.extend(check_no_manual_numbers.check(tex_path, mode, paper_id))
    else:
        manifest = write_discovery_manifest(repo_root)
        data = json.loads(manifest.read_text())
        for paper in data.get("papers", []):
            pid = paper["paper_id"]
            paper_dir = repo_root / paper["path"]
            issues.extend(
                check_paper_freshness.check(repo_root, paper_dir, pid, mode)
            )
            config = load_paper_config(paper_dir / "truthweave.yml")
            tex_path = paper_dir / config.get("main", "main.tex")
            issues.extend(check_no_manual_numbers.check(tex_path, mode, pid))

        legacy_main = repo_root / "paper" / "main.tex"
        if legacy_main.exists():
            issues.extend(check_no_manual_numbers.check(legacy_main, mode, None))

    warn_count = sum(1 for issue in issues if issue.severity == "WARN")
    fail_count = sum(1 for issue in issues if issue.severity == "FAIL")
    for issue in issues:
        print(_format_issue(issue))

    print(f"Summary: WARN={warn_count} FAIL={fail_count}")
    if fail_count:
        print("CI will fail")
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
        }
        OmegaConf.save(OmegaConf.create(config), target_dir / "truthweave.yml")

        main_tex = (
            "\\\\documentclass{article}\\n"
            "\\\\input{auto/variables.tex}\\n\\n"
            "\\\\begin{document}\\n\\n"
            "Example metric: \\\\BestAccuracy.\\n\\n"
            "\\\\end{document}\\n"
        )
        (target_dir / "main.tex").write_text(main_tex)

        refs_bib = (
            "@article{example2024,\\n"
            "  title={Example Reference},\\n"
            "  author={Doe, Jane},\\n"
            "  journal={Journal of Examples},\\n"
            "  year={2024}\\n"
            "}\\n"
        )
        (target_dir / "refs.bib").write_text(refs_bib)

    write_discovery_manifest(repo_root)
    allowed_paths = [
        str(target_dir / "truthweave.yml"),
        str(target_dir / "main.tex"),
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

