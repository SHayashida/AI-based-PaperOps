# AGENTS.md — TruthWeave Agent Contract (Template Repo)

## Mission
You are operating inside a TruthWeave template repository.
Your goal is to help with reproducible, auditable paper workflows without breaking the template structure.

This file is the lightweight contract.
Detailed execution procedures live in skill files under `.codex/skills/**`.

## Non-negotiables (safety rails)
- Never fabricate results, citations, or file contents. If unsure, propose a verification plan.
- Keep changes minimal and reviewable (small diffs).
- Do not move/rename directories or restructure the project.
- Do not manually edit auto-generated outputs under `papers/<paper_id>/auto/` (these must be produced by build steps).

## Allowed edits (STRICT)
Unless the user explicitly asks otherwise, you may ONLY edit:
- `conf/exp/<exp_name>.yaml`
- `src/truthweave/experiments/<exp_name>.py`
- Files under `.codex/skills/**` (to maintain skills)
- `AGENTS.md` itself

Everything else is read-only by default.

## Agent role split (do not collapse into one heavy agent)

- Orchestrator Agent
  - Owns planning, task routing, and run order decisions.
  - Delegates implementation details to specialized skills.
- Experiment Agent
  - Owns experiment configuration and experiment code changes.
  - Operates only within allowed experiment edit paths.
- Argument/Quality Agent
  - Owns quality checks, root-cause analysis, and argument integrity diagnostics.
  - Must report measurable evidence (failing checks, affected paths, rerun commands).
- Build/Asset Agent
  - Owns deterministic asset build and freshness verification.
  - Never edits generated outputs manually.

## Skills (.codex/skills/)

This repository includes structured skills for AI agents. Current skills:

### truthweave-build-assets
- Rebuilds paper assets (figures/tables/variables.tex) deterministically
- Verifies synchronization with checks
- Auto-remediates common build failures (missing experiments, stale deps)

### truthweave-check
- Runs CI checks for a given paper_id
- Diagnoses failures with root cause analysis
- Proposes minimal fixes (or patch plans if outside allowed edits)
- Provides exact rerun commands

Skill files are the source of truth for runbooks.

**To maintain skills**: Edit files under `.codex/skills/<skill_name>/SKILL.md`. Follow the frontmatter format and include:
- Inputs
- Rules
- Output format
- Common remediation playbook
- Safe automation boundary (auto-fix vs requires human approval)

## Core commands (single source of truth)
- Run experiment: `uv run truthweave run exp=<exp_name>`
- Discover: `uv run truthweave discover`
- Build paper assets: `uv run truthweave build-paper-assets --paper <paper_id>`
- Check: `uv run truthweave check --paper <paper_id> --mode ci`
- Build PDF: `uv run truthweave build-paper --paper <paper_id>`

## Definition of done for any change
- `uv run truthweave check --paper <paper_id> --mode ci` passes (or you explain exactly why it cannot).
- Any new/updated result is traceable to a run (config/seed/git hash) and appears via generated assets/variables, not manual paper edits.
- For user-facing workflows, README command flow must remain executable in a clean environment.

## Interaction style
- When you propose edits, show:
  1) What failed and why
  2) Minimal fix (files + diff summary)
  3) Exact commands to re-run
