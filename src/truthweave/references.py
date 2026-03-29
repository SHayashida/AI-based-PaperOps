from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from omegaconf import OmegaConf

from truthweave.utils import ensure_dir, sha256_file, write_json


REFERENCE_INTENTS = {
    "background",
    "method",
    "baseline",
    "comparison",
    "claim_support",
}

Resolver = Callable[[dict[str, Any]], dict[str, Any] | None]


def references_path(paper_dir: Path) -> Path:
    return paper_dir / "references.yml"


def default_references(paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "sources": [
            {
                "key": "example2024",
                "query": "Example Reference",
                "ids": {"doi": "", "arxiv": "", "openalex": "", "semantic_scholar": ""},
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


def load_references(path: Path) -> dict[str, Any]:
    cfg = OmegaConf.load(path)
    data = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid references.yml at {path}")
    return data


def validate_references_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["references.yml must contain a non-empty sources list"]

    for idx, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{idx}] must be a mapping")
            continue
        for field in ["key", "query", "intent", "required"]:
            if field not in source:
                errors.append(f"sources[{idx}] missing field: {field}")
        key = source.get("key")
        if not isinstance(key, str) or not key.strip():
            errors.append(f"sources[{idx}].key must be a non-empty string")
        intent = source.get("intent")
        if intent not in REFERENCE_INTENTS:
            errors.append(
                f"sources[{idx}].intent must be one of: {', '.join(sorted(REFERENCE_INTENTS))}"
            )
        required = source.get("required")
        if not isinstance(required, bool):
            errors.append(f"sources[{idx}].required must be a boolean")
        ids = source.get("ids")
        if ids is not None and not isinstance(ids, dict):
            errors.append(f"sources[{idx}].ids must be a mapping when provided")
    return errors


def _render_bibtex(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata", {})
    authors = metadata.get("authors", [])
    author_value = " and ".join(authors) if isinstance(authors, list) else ""
    fields = {
        "title": metadata.get("title", ""),
        "author": author_value,
        "journal": metadata.get("venue", ""),
        "year": metadata.get("year", ""),
    }
    entry_type = metadata.get("entry_type", "article")
    lines = [f"@{entry_type}{{{entry['key']},"]
    for key, value in fields.items():
        if value:
            lines.append(f"  {key}={{" + str(value) + "},")
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)


def _resolve_entry(source: dict[str, Any], resolver: Resolver | None) -> dict[str, Any]:
    resolved = resolver(source) if resolver else None
    if resolved is None:
        metadata = source.get("metadata")
        if not isinstance(metadata, dict):
            resolved = {
                "status": "unresolved",
                "provider": "manual",
                "metadata": {},
            }
        else:
            resolved = {
                "status": "resolved",
                "provider": "manual",
                "metadata": metadata,
            }

    entry = {
        "key": source["key"],
        "query": source["query"],
        "ids": source.get("ids", {}),
        "intent": source["intent"],
        "required": source["required"],
        "provider": resolved.get("provider", "manual"),
        "status": resolved.get("status", "unresolved"),
        "metadata": resolved.get("metadata", {}),
    }
    if entry["status"] == "resolved":
        entry["bibtex"] = _render_bibtex(entry)
        entry["bibtex_sha256"] = sha256_file_from_text(entry["bibtex"])
    return entry


def sha256_file_from_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lock_path(repo_root: Path, paper_id: str) -> Path:
    return repo_root / "artifacts" / "references" / paper_id / "references.lock.json"


def sync_references(
    repo_root: Path,
    paper_dir: Path,
    paper_id: str,
    resolver: Resolver | None = None,
) -> dict[str, Any]:
    refs_data = load_references(references_path(paper_dir))
    errors = validate_references_data(refs_data)
    if errors:
        raise SystemExit("Invalid references.yml:\n- " + "\n- ".join(errors))

    entries = [_resolve_entry(source, resolver) for source in refs_data["sources"]]
    bib_entries = [entry["bibtex"] for entry in entries if entry.get("bibtex")]
    bib_text = "\n\n".join(bib_entries).strip() + ("\n" if bib_entries else "")

    refs_bib_path = paper_dir / "refs.bib"
    refs_bib_path.write_text(bib_text)

    lock = {
        "paper_id": paper_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "refs_bib_path": str(refs_bib_path.relative_to(repo_root)),
        "refs_bib_sha256": sha256_file(refs_bib_path),
        "entries": entries,
    }
    out_path = lock_path(repo_root, paper_id)
    ensure_dir(out_path.parent)
    write_json(out_path, lock)
    return lock


def verify_references(repo_root: Path, paper_dir: Path, paper_id: str) -> list[str]:
    issues: list[str] = []
    refs_bib_path = paper_dir / "refs.bib"
    current_exists = refs_bib_path.exists()
    current_sha = sha256_file(refs_bib_path) if current_exists else None

    lp = lock_path(repo_root, paper_id)
    if not lp.exists():
        if current_exists:
            issues.append(
                f"Missing references.lock.json for {paper_id}; refs.bib is not provenance-backed."
            )
        return issues

    lock = json.loads(lp.read_text())
    expected_sha = lock.get("refs_bib_sha256")
    if not isinstance(expected_sha, str) or not current_exists:
        issues.append(f"Reference lock is incomplete for {paper_id}.")
        return issues
    if current_sha != expected_sha:
        issues.append(f"refs.bib does not match references.lock.json for {paper_id}.")

    for entry in lock.get("entries", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("required") and entry.get("status") != "resolved":
            issues.append(
                f"Required reference '{entry.get('key', 'unknown')}' is unresolved."
            )
    return issues

