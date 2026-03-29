from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from truthweave.briefs import claim_ids_from_brief, load_brief, validate_brief_data
from truthweave.evidence import claim_ledger_path, evidence_path
from truthweave.provenance import provenance_ledger_path, provenance_path
from truthweave.utils import ensure_dir, sha256_file, write_json


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "your",
    "will",
    "have",
    "been",
    "were",
    "which",
    "their",
    "there",
    "about",
    "paper",
    "claim",
}

_CONTEXT_TITLES = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "references",
    "appendix",
}


def review_json_path(repo_root: Path, paper_id: str, phase: str) -> Path:
    return repo_root / "artifacts" / "reviews" / paper_id / f"{phase}.json"


def _normalize_text(text: str) -> str:
    text = re.sub(r"%.*", "", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", text)
    text = re.sub(r"[{}\\\\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(text: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
        if token not in _STOPWORDS
    }
    return tokens


def _extract_sections(tex_text: str) -> list[dict[str, str]]:
    pattern = re.compile(r"\\section\{([^}]+)\}")
    matches = list(pattern.finditer(tex_text))
    if not matches:
        body = _normalize_text(tex_text)
        return [{"title": "document", "content": body}] if body else []

    sections: list[dict[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(tex_text)
        title = match.group(1).strip()
        content = _normalize_text(tex_text[start:end])
        sections.append({"title": title, "content": content})
    return sections


def _load_manifest_metrics(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    try:
        data = json.loads(manifest_path.read_text())
    except json.JSONDecodeError:
        return set()
    audit = data.get("generated", {}).get("argument_audit", {})
    claim_ids = audit.get("claim_ids", [])
    if not isinstance(claim_ids, list):
        claim_ids = []
    return {str(value) for value in claim_ids if isinstance(value, str)}


def build_thread_review(
    repo_root: Path, paper_dir: Path, paper_id: str, phase: str
) -> dict[str, Any]:
    brief = load_brief(paper_dir / "brief.yml")
    errors = validate_brief_data(brief)
    if errors:
        raise SystemExit("Invalid brief.yml:\n- " + "\n- ".join(errors))

    tex_path = paper_dir / "main.tex"
    manifest_path = paper_dir / "auto" / "MANIFEST.json"
    refs_path = paper_dir / "refs.bib"
    if not tex_path.exists():
        raise SystemExit(f"Missing main.tex for {paper_id}: {tex_path}")

    tex_text = tex_path.read_text()
    sections = _extract_sections(tex_text)
    doc_tokens = _tokenize(_normalize_text(tex_text))
    brief_tokens = _tokenize(
        " ".join(
            [
                str(brief.get("central_claim", "")),
                str(brief.get("so_what", "")),
                str(brief.get("novelty", "")),
                str(brief.get("target_reader", "")),
                " ".join(str(item) for item in brief.get("key_questions", [])),
            ]
        )
    )
    non_goal_tokens = _tokenize(
        " ".join(str(item) for item in brief.get("non_goals", []))
    )
    planned = brief.get("planned_evidence", [])
    evidence_terms: set[str] = set()
    expected_metrics: set[str] = set()
    planned_experiments: set[str] = set()
    if isinstance(planned, list):
        for item in planned:
            if not isinstance(item, dict):
                continue
            evidence_terms |= _tokenize(str(item.get("description", "")))
            experiment = item.get("experiment")
            if isinstance(experiment, str) and experiment:
                planned_experiments.add(experiment.lower())
            metrics = item.get("expected_metrics", [])
            if isinstance(metrics, list):
                for metric in metrics:
                    if isinstance(metric, str) and metric:
                        expected_metrics.add(metric)
    claim_ids = claim_ids_from_brief(brief)
    evidence_terms |= {claim_id.lower() for claim_id in claim_ids}
    evidence_terms |= planned_experiments
    manifest_claim_ids = _load_manifest_metrics(manifest_path)

    section_map: list[dict[str, Any]] = []
    off_thesis_sections: list[str] = []
    supports = 0
    context = 0
    unsupported = 0
    for section in sections:
        title = section["title"]
        content = section["content"]
        section_tokens = _tokenize(title + " " + content)
        overlap = sorted((section_tokens & brief_tokens) | (section_tokens & evidence_terms))
        title_lower = title.lower()
        metric_hits = [metric for metric in expected_metrics if metric in content]
        citations = re.findall(r"\\cite\{([^}]+)\}", content)

        classification = "unsupported"
        reason = "No clear link to the brief."
        if section_tokens & non_goal_tokens:
            classification = "off_thesis"
            reason = "Section overlaps with declared non-goals."
        elif overlap or metric_hits:
            classification = "supports_claim"
            reason = "Section references thesis/evidence terms."
        elif title_lower in _CONTEXT_TITLES or citations:
            classification = "context_only"
            reason = "Section provides context or supporting citations."
        else:
            classification = "unsupported"
            reason = "Section needs a clearer link to the central claim."

        if classification == "supports_claim":
            supports += 1
        elif classification == "context_only":
            context += 1
        elif classification == "off_thesis":
            off_thesis_sections.append(title)
        else:
            unsupported += 1

        section_map.append(
            {
                "title": title,
                "classification": classification,
                "overlap_terms": overlap,
                "metric_hits": metric_hits,
                "reason": reason,
            }
        )

    total_sections = max(len(section_map), 1)
    alignment_score = round((supports + 0.5 * context) / total_sections, 4)

    missing_evidence: list[str] = []
    if isinstance(planned, list):
        for item in planned:
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id", ""))
            experiment = str(item.get("experiment", ""))
            description = str(item.get("description", ""))
            metrics = item.get("expected_metrics", [])
            metric_list = [metric for metric in metrics if isinstance(metric, str)]
            has_metric = not metric_list or any(metric in tex_text for metric in metric_list)
            has_experiment = not experiment or experiment.lower() in doc_tokens
            has_claim = not claim_id or claim_id.lower() in doc_tokens or claim_id in manifest_claim_ids
            if not (has_metric or has_experiment or has_claim):
                missing_evidence.append(description or claim_id or experiment)

    revision_actions: list[str] = []
    if off_thesis_sections:
        revision_actions.append(
            "Tighten or remove sections that do not support the central claim: "
            + ", ".join(off_thesis_sections)
        )
    if unsupported:
        revision_actions.append(
            "Add explicit transitions from unsupported sections back to the central claim."
        )
    if missing_evidence:
        revision_actions.append(
            "Add evidence for planned items: " + "; ".join(missing_evidence)
        )
    if not revision_actions:
        revision_actions.append("Thread is coherent at the current heuristic threshold.")

    reviewed_inputs = {}
    for label, path in {
        "brief_yml": paper_dir / "brief.yml",
        "evidence_yml": evidence_path(paper_dir),
        "data_sources_yml": provenance_path(paper_dir),
        "main_tex": tex_path,
        "refs_bib": refs_path,
        "claim_ledger": claim_ledger_path(repo_root, paper_id),
        "provenance_ledger": provenance_ledger_path(repo_root, paper_id),
    }.items():
        if path.exists():
            reviewed_inputs[label] = {
                "path": str(path.relative_to(repo_root)),
                "sha256": sha256_file(path),
            }

    review = {
        "paper_id": paper_id,
        "phase": phase,
        "alignment_score": alignment_score,
        "section_map": section_map,
        "missing_evidence": missing_evidence,
        "off_thesis_sections": off_thesis_sections,
        "revision_actions": revision_actions,
        "reviewed_inputs": reviewed_inputs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    out_path = review_json_path(repo_root, paper_id, phase)
    ensure_dir(out_path.parent)
    write_json(out_path, review)
    return review


def render_review_markdown(review: dict[str, Any]) -> str:
    lines = [
        f"# Thread Review: {review['paper_id']} ({review['phase']})",
        "",
        f"- alignment_score: {review['alignment_score']}",
        f"- off_thesis_sections: {len(review['off_thesis_sections'])}",
        f"- missing_evidence: {len(review['missing_evidence'])}",
        "",
        "## Actions",
    ]
    for action in review["revision_actions"]:
        lines.append(f"- {action}")
    lines.append("")
    lines.append("## Sections")
    for section in review["section_map"]:
        lines.append(
            f"- {section['title']}: {section['classification']} ({section['reason']})"
        )
    return "\n".join(lines) + "\n"


def load_review(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
