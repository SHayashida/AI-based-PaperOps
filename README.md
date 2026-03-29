# TruthWeave Template v1

[![CI](https://github.com/SHayashida/TruthWeave/actions/workflows/ci.yml/badge.svg)](https://github.com/SHayashida/TruthWeave/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Reproducible research workflow template for academic papers. Ensures experiments are traceable, paper metrics are automatically synced, and manual number updates are eliminated.

[日本語版 README はこちら](README.ja.md)

## Quickstart

```bash
uv sync
uv run truthweave validate-brief --paper example
uv run truthweave validate-provenance --paper example
uv run truthweave run exp=example
uv run truthweave discover
uv run truthweave build-paper-assets --paper example
uv run truthweave sync-refs --paper example
uv run truthweave validate-evidence --paper example
uv run truthweave provenance-report --paper example --format md
uv run truthweave claim-report --paper example --format md
uv run truthweave review-thread --paper example --phase draft_reviewed --format md
uv run truthweave reviewer-packet --paper example --format md
uv run truthweave verify-paper --paper example --format md
uv run truthweave check --paper example
```

## Overview

TruthWeave enforces a structured workflow for academic paper writing:

```
Experiment (conf/exp + src/truthweave/experiments)
  -> runs/
  -> artifacts/
  -> papers/<paper_id>/auto
  -> PDF
```

## Core Workflows

### Adding a New Paper

```bash
uv run truthweave create-paper <paper_id>
# Or copy from an existing paper:
uv run truthweave create-paper <paper_id> --from <base_paper_id>
```

Conference-specific `.cls`/`.sty` files should be placed in `papers/<paper_id>/styles/`.

### Adding a New Experiment

```bash
uv run truthweave create-exp <exp_name>
```

**AI Collaboration Template** (restrict editable files):

```
This repository has a fixed structure.
Allowed files to edit:
- conf/exp/<exp_name>.yaml
- src/truthweave/experiments/<exp_name>.py
Do not create or modify any other files/directories.
```

Run the experiment:

```bash
uv run truthweave run exp=<exp_name>
```

### Adding a Dataset

```bash
uv run truthweave create-dataset <dataset_id>
```

Place raw data files in `data/raw/<dataset_id>/`.

### Adding Analysis/Figures

```bash
uv run truthweave create-analysis <analysis_name>
make analysis NAME=<analysis_name>
# Or run directly:
uv run python -m truthweave.analysis.<analysis_name>
```

### Building Paper Assets

Sync metrics, figures, and tables to the paper:

```bash
uv run truthweave build-paper-assets --paper <paper_id>
```

The paper should use `\input{auto/variables.tex}` and reference macros instead of hardcoded numbers.

### Claim Evidence Binding

Bind each brief claim to concrete repo artifacts:

```bash
uv run truthweave scaffold-evidence --paper <paper_id>
uv run truthweave validate-evidence --paper <paper_id>
uv run truthweave claim-report --paper <paper_id> --format md
```

`evidence.yml` references canonical `claim_id` values from `brief.yml` and points to deterministic artifacts such as:
- generated variables in `auto/variables.tex`
- manifest pointers in `auto/MANIFEST.json`
- concrete files under `runs/`, `papers/<paper_id>/figures/`, or `papers/<paper_id>/tables/`

The generated claim ledger is written to `artifacts/claims/<paper_id>/claim_ledger.json`.

### Data Source Provenance

Declare the admissible data acquisition contract before relying on evidence:

```bash
uv run truthweave scaffold-provenance --paper <paper_id>
uv run truthweave validate-provenance --paper <paper_id>
uv run truthweave provenance-report --paper <paper_id> --format md
```

`data_sources.yml` is repo-local and deterministic. It records each `source_id` declared by `brief.yml`, its acquisition mode, reproducibility level, and local pointers such as files, directories, and manifest references. The generated provenance ledger is written to `artifacts/provenance/<paper_id>/provenance_ledger.json`.

### Reviewer Packet Export

Export a reviewer-facing trust packet that aggregates the current thesis, claims, evidence, sources, references, and reproducibility caveats:

```bash
uv run truthweave reviewer-packet --paper <paper_id> --format md
```

This writes:
- `artifacts/packets/<paper_id>/packet.json`
- `artifacts/packets/<paper_id>/packet.md`
- `artifacts/packets/<paper_id>/claims.csv`
- `artifacts/packets/<paper_id>/sources.csv`
- `artifacts/packets/<paper_id>/rerun_checklist.md`

The packet is intended for reviewers, coauthors, and future maintainers who need a compact audit bundle without reading the whole repo first.

### Verification Harness

Export and run a deterministic verification profile for major claims:

```bash
uv run truthweave verification-report --paper <paper_id> --format md
uv run truthweave verify-paper --paper <paper_id> --format md
```

This writes:
- `artifacts/verification/<paper_id>/verification_report.json`
- `artifacts/verification/<paper_id>/verification_report.md`
- `artifacts/verification/<paper_id>/verification_targets.csv`
- `artifacts/verification/<paper_id>/replay_profile.md`

The reviewer packet is for inspection. The verification harness is for executable replay and comparison against declared evidence targets.

### Building the PDF

```bash
uv run truthweave build-paper --paper <paper_id>
```

Requires `latexmk` or similar LaTeX tools installed.

### Pre-Commit Checks

```bash
uv run truthweave check --paper <paper_id> --mode dev
uv run truthweave check --paper <paper_id> --mode ci
```

- **dev mode**: STRUCTURE/PAPER_NUMBERS produce warnings only
- **ci mode**: STRUCTURE/PAPER_NUMBERS cause failures

## Troubleshooting

| Symptom | Cause | Solution |
| --- | --- | --- |
| MANIFEST is stale | Assets not regenerated | `uv run truthweave build-paper-assets --paper <paper_id>` |
| No runs found | Experiment not executed | `uv run truthweave run exp=<exp_name>` |
| Structure check fail | Repository layout violation | Use scaffolding commands to restructure |
| Manual inline numbers detected | Hardcoded numbers in `.tex` | Replace with macros or append `% truthweave-allow-number` |

## Paper Workflow

- Papers live under `papers/<paper_id>/` with a `truthweave.yml` configuration
- `brief.yml` is the canonical source of claim IDs and phase status
- `data_sources.yml` records admissible data acquisition and provenance state for each declared source ID
- `evidence.yml` binds each claim ID to concrete evidence objects
- `truthweave discover` scans for `truthweave.yml` and writes `artifacts/manifests/papers_index.json`
- `truthweave build-paper-assets --paper <paper_id>` writes `papers/<paper_id>/auto/variables.tex` and `papers/<paper_id>/auto/MANIFEST.json`
- `truthweave provenance-report --paper <paper_id>` writes `artifacts/provenance/<paper_id>/provenance_ledger.json`
- `truthweave claim-report --paper <paper_id>` writes `artifacts/claims/<paper_id>/claim_ledger.json`
- `truthweave reviewer-packet --paper <paper_id>` writes `artifacts/packets/<paper_id>/packet.json` plus human-readable exports
- `truthweave verification-report --paper <paper_id>` writes `artifacts/verification/<paper_id>/verification_report.json`
- `truthweave verify-paper --paper <paper_id>` runs deterministic claim verification and exits nonzero when required verification targets fail
- `truthweave build-paper --paper <paper_id>` builds the LaTeX paper using the engine in `truthweave.yml`
- Make targets: `make assets PAPER=<paper_id>`, `make refs PAPER=<paper_id>`, `make provenance PAPER=<paper_id>`, `make claims PAPER=<paper_id>`, `make review PAPER=<paper_id>`, `make packet PAPER=<paper_id>`, `make verify PAPER=<paper_id>`, `make paper PAPER=<paper_id>`

## Workflow Summary: Canonical Paper Flow

1. `uv run truthweave create-paper mypaper`
2. Fill `brief.yml` and run `uv run truthweave validate-brief --paper mypaper`
3. Declare references in `references.yml` and run `uv run truthweave sync-refs --paper mypaper`
4. Declare required source IDs in `brief.yml` and `data_sources.yml`, then run `uv run truthweave validate-provenance --paper mypaper`
5. Run experiments with `uv run truthweave run exp=<exp_name>`
6. Sync paper assets with `uv run truthweave build-paper-assets --paper mypaper`
7. Bind claims with `uv run truthweave validate-evidence --paper mypaper`
8. Build the provenance ledger with `uv run truthweave provenance-report --paper mypaper --format md`
9. Build the claim ledger with `uv run truthweave claim-report --paper mypaper --format md`
10. Run `uv run truthweave review-thread --paper mypaper --phase draft_reviewed --format md`
11. Generate the reviewer packet with `uv run truthweave reviewer-packet --paper mypaper --format md`
12. Verify major claims with `uv run truthweave verify-paper --paper mypaper --format md`
13. Run `uv run truthweave check --paper mypaper --mode ci`
14. Build the PDF with `uv run truthweave build-paper --paper mypaper`

## Workflow Summary: Add Experiment

1. `uv run truthweave create-exp myexp`
2. Ask AI to edit ONLY the created files
3. Add or update the matching claim entry in `brief.yml`
4. `uv run truthweave approve-phase --paper <paper_id> --phase experiment_ready`
5. `uv run truthweave run exp=myexp`

## Workflow Summary: Add Analysis

1. `uv run truthweave create-analysis my_analysis`
2. Ask AI to edit ONLY the created file
3. `make analysis NAME=my_analysis`

## Workflow Summary: Add Dataset

1. `uv run truthweave create-dataset mydata`
2. Place raw files into `data/raw/mydata/`

## Codex/AI Agent Skills

This repository includes structured skills for AI agents (Codex, GitHub Copilot, etc.) in `.codex/skills/`:

### Available Skills

#### `truthweave-build-assets`
- **Purpose**: Rebuild paper assets (figures/tables/variables) deterministically for a paper_id
- **Usage**: Automatically invoked when AI needs to regenerate paper outputs
- **Key Commands**: `uv run truthweave build-paper-assets --paper <paper_id>`
- **Constraints**: Never manually edit `papers/<paper_id>/auto/`

#### `truthweave-check`
- **Purpose**: Run TruthWeave CI checks, diagnose failures, and propose fixes
- **Usage**: Automatically invoked for validation and troubleshooting
- **Key Commands**: `uv run truthweave check --paper <paper_id> --mode ci`
- **Capabilities**: Detects stale assets, missing metadata, structure violations

### Maintaining Skills

To add or modify skills:

1. Create/edit skill in `.codex/skills/<skill_name>/SKILL.md`
2. Follow the frontmatter format:
   ```yaml
   ---
   name: skill-name
   description: Brief description
   ---
   ```
3. Include: Inputs, Rules, Output format, Remediation playbook
4. Skills are automatically available to AI agents

See [AGENTS.md](AGENTS.md) for the agent contract and editing constraints.

## AI Prompt Template

When collaborating with AI agents:

```
You are editing this repo.
Allowed files to edit:
- <list paths from scaffold output>
Do not create new directories; CI will fail.
```

## Check Modes

- `truthweave check` defaults to **dev mode** (STRUCTURE/PAPER_NUMBERS warn only)
- `truthweave check --mode ci` treats STRUCTURE/PAPER_NUMBERS as failures

## Multi-Paper Workflow (Fastest Path)

```bash
uv run truthweave create-paper demo_paper
uv run truthweave validate-brief --paper demo_paper
uv run truthweave validate-provenance --paper demo_paper
uv run truthweave run exp=example
uv run truthweave build-paper-assets --paper demo_paper
uv run truthweave sync-refs --paper demo_paper
uv run truthweave provenance-report --paper demo_paper --format md
uv run truthweave claim-report --paper demo_paper --format md
uv run truthweave review-thread --paper demo_paper --phase draft_reviewed --format md
uv run truthweave reviewer-packet --paper demo_paper --format md
uv run truthweave verify-paper --paper demo_paper --format md
uv run truthweave build-paper --paper demo_paper
uv run truthweave check --paper demo_paper
make assets-all
make refs-all
make provenance-all
make claims-all
make review-all
make packet-all
make verify-all
make paper-all
make check-all
```

## Pipeline Configuration

`conf/pipeline.yaml` defines what counts as the latest run and which sources flow into assets.

## License

See [LICENSE](LICENSE) file for details.
