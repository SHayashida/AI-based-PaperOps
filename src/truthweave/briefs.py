from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf


PHASES = [
    "idea_locked",
    "experiment_ready",
    "evidence_reviewed",
    "draft_reviewed",
    "release_ready",
]


def brief_path(paper_dir: Path) -> Path:
    return paper_dir / "brief.yml"


def default_brief(paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "phase_status": "idea_locked",
        "expected_source_ids": ["example_simulated_data"],
        "central_claim": "State the single most important claim this paper will defend.",
        "so_what": "Explain why this claim matters for the target reader.",
        "novelty": "State what is meaningfully new about the work.",
        "target_reader": "Researchers who care about reproducible AI-driven paper workflows.",
        "key_questions": [
            "Which research question must the paper answer unambiguously?"
        ],
        "planned_evidence": [
            {
                "claim_id": "main_claim",
                "required": True,
                "experiment": "example",
                "description": "Evidence that supports the central claim.",
                "expected_metrics": ["MetricMean"],
                "source_ids": ["example_simulated_data"],
                "prohibited_substitutes": [],
            }
        ],
        "non_goals": [
            "Fully autonomous paper writing without a human approval step."
        ],
        "phase_history": [
            {
                "phase": "idea_locked",
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "note": "Initial scaffold created.",
            }
        ],
    }


def load_brief(path: Path) -> dict[str, Any]:
    cfg = OmegaConf.load(path)
    data = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid brief.yml at {path}")
    return data


def validate_brief_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_strings = [
        "paper_id",
        "phase_status",
        "central_claim",
        "so_what",
        "novelty",
        "target_reader",
    ]
    for field in required_strings:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"Missing or empty field: {field}")

    phase_status = data.get("phase_status")
    if phase_status not in PHASES:
        errors.append(
            "Invalid phase_status; expected one of: " + ", ".join(PHASES)
        )

    for field in ["key_questions", "planned_evidence", "non_goals"]:
        value = data.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"Missing or empty list: {field}")

    expected_source_ids = data.get("expected_source_ids")
    if expected_source_ids is not None and (
        not isinstance(expected_source_ids, list)
        or any(
            not isinstance(source_id, str) or not source_id
            for source_id in expected_source_ids
        )
    ):
        errors.append("expected_source_ids must be a list of strings")

    planned = data.get("planned_evidence", [])
    if isinstance(planned, list):
        for idx, item in enumerate(planned):
            if not isinstance(item, dict):
                errors.append(f"planned_evidence[{idx}] must be a mapping")
                continue
            for field in ["claim_id", "experiment", "description"]:
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f"planned_evidence[{idx}] missing or empty field: {field}"
                    )
            metrics = item.get("expected_metrics")
            if metrics is not None and (
                not isinstance(metrics, list)
                or any(not isinstance(metric, str) or not metric for metric in metrics)
            ):
                errors.append(
                    f"planned_evidence[{idx}].expected_metrics must be a list of strings"
                )
            required = item.get("required")
            if required is not None and not isinstance(required, bool):
                errors.append(f"planned_evidence[{idx}].required must be a boolean")
            source_ids = item.get("source_ids")
            if source_ids is not None and (
                not isinstance(source_ids, list)
                or any(
                    not isinstance(source_id, str) or not source_id
                    for source_id in source_ids
                )
            ):
                errors.append(
                    f"planned_evidence[{idx}].source_ids must be a list of strings"
                )
            prohibited = item.get("prohibited_substitutes")
            if prohibited is not None and (
                not isinstance(prohibited, list)
                or any(
                    not isinstance(value, str) or not value for value in prohibited
                )
            ):
                errors.append(
                    f"planned_evidence[{idx}].prohibited_substitutes must be a list of strings"
                )

    return errors


def phase_index(phase: str) -> int:
    if phase not in PHASES:
        raise ValueError(f"Unknown phase: {phase}")
    return PHASES.index(phase)


def phase_at_least(current: str, required: str) -> bool:
    return phase_index(current) >= phase_index(required)


def claim_ids_from_brief(brief: dict[str, Any]) -> list[str]:
    return list(claim_specs_from_brief(brief).keys())


def claim_specs_from_brief(brief: dict[str, Any]) -> dict[str, dict[str, Any]]:
    planned = brief.get("planned_evidence", [])
    if not isinstance(planned, list):
        return {}
    specs: dict[str, dict[str, Any]] = {}
    for item in planned:
        if not isinstance(item, dict):
            continue
        claim_id = item.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id or claim_id in specs:
            continue
        specs[claim_id] = {
            "claim_id": claim_id,
            "required": bool(item.get("required", True)),
            "experiment": item.get("experiment"),
            "description": item.get("description"),
            "expected_metrics": item.get("expected_metrics", []),
            "source_ids": item.get("source_ids", []),
            "prohibited_substitutes": item.get("prohibited_substitutes", []),
        }
    return specs


def required_claim_ids_from_brief(brief: dict[str, Any]) -> list[str]:
    return [
        claim_id
        for claim_id, spec in claim_specs_from_brief(brief).items()
        if bool(spec.get("required", True))
    ]


def expected_source_ids_from_brief(brief: dict[str, Any]) -> list[str]:
    explicit = brief.get("expected_source_ids")
    values: list[str] = []
    if isinstance(explicit, list):
        for source_id in explicit:
            if isinstance(source_id, str) and source_id and source_id not in values:
                values.append(source_id)
    for spec in claim_specs_from_brief(brief).values():
        source_ids = spec.get("source_ids", [])
        if isinstance(source_ids, list):
            for source_id in source_ids:
                if isinstance(source_id, str) and source_id and source_id not in values:
                    values.append(source_id)
    return values


def experiments_for_brief(brief: dict[str, Any]) -> set[str]:
    experiments: set[str] = set()
    planned = brief.get("planned_evidence", [])
    if not isinstance(planned, list):
        return experiments
    for item in planned:
        if not isinstance(item, dict):
            continue
        experiment = item.get("experiment")
        if isinstance(experiment, str) and experiment:
            experiments.add(experiment)
    return experiments


def save_brief(path: Path, brief: dict[str, Any]) -> None:
    OmegaConf.save(OmegaConf.create(brief), path)


def approve_phase(path: Path, phase: str) -> dict[str, Any]:
    brief = load_brief(path)
    errors = validate_brief_data(brief)
    if errors:
        raise SystemExit(
            "Cannot approve phase with invalid brief.yml:\n- " + "\n- ".join(errors)
        )
    current = brief.get("phase_status", "idea_locked")
    if phase not in PHASES:
        raise SystemExit(f"Unknown phase '{phase}'. Expected one of: {', '.join(PHASES)}")
    if phase_index(phase) < phase_index(current):
        raise SystemExit(
            f"Cannot move phase backwards: current={current}, requested={phase}"
        )

    brief["phase_status"] = phase
    history = brief.get("phase_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "phase": phase,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "note": f"Approved via truthweave approve-phase --phase {phase}",
        }
    )
    brief["phase_history"] = history
    save_brief(path, brief)
    return brief
