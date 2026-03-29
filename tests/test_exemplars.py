from __future__ import annotations

from pathlib import Path

from truthweave.briefs import load_brief


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_finance_exemplar_declares_finance_profile() -> None:
    paper_dir = REPO_ROOT / "papers" / "finance_exemplar"
    brief = load_brief(paper_dir / "brief.yml")
    assert brief["research_profile"] == "finance_ml"
    assert brief["evaluation_protocol"]["temporal_split"]
    assert len(brief["baselines"]) >= 1


def test_formal_methods_exemplar_declares_proof_bundle() -> None:
    paper_dir = REPO_ROOT / "papers" / "formal_methods_exemplar"
    brief = load_brief(paper_dir / "brief.yml")
    assert brief["research_profile"] == "formal_methods"
    assert (paper_dir / "proofs" / "checker.txt").exists()
    assert (paper_dir / "proofs" / "witness.txt").exists()
