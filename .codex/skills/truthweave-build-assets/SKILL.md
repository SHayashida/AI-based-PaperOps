---
name: truthweave-build-assets
description: Rebuild paper assets (figures/tables/variables) deterministically for a paper_id and confirm synchronization with checks.
version: 1.1
owner_agent: build-asset
---

# Inputs
- paper_id

# Role
- This skill is owned by the Build/Asset Agent.
- The skill may be routed by Orchestrator after experiment completion or freshness check failures.

# Rules
- You MUST run: `uv run truthweave build-paper-assets --paper <paper_id>`
- You MUST NOT manually edit generated outputs under `papers/<paper_id>/auto/`.
- You MUST NOT edit any non-allowed files in AGENTS.md.
- If build_toggle/config changes are needed but not allowed, propose a patch plan only.

# Safe automation boundary
- Auto-fix allowed:
   - Rebuild assets and run verification check.
   - Suggest deterministic rerun command sequences.
- Human approval required:
   - Any change to paper sources or repo structure.
   - Any change requiring edits outside Allowed edits.

# What you must output
1) **Build result**
   - Success/Fail
   - If Fail: the most relevant error lines and likely cause
2) **What changed**
   - List which asset categories likely updated (variables/figures/tables) based on build logs / file timestamps
3) **Verification**
   - Run: `uv run truthweave check --paper <paper_id> --mode ci`
   - Report PASS/FAIL and next action if FAIL
4) **Asset integrity evidence**
   - State whether generated outputs are derived from build command execution (not manual edits).
   - Report whether follow-up check indicates fresh assets.

# Common remediation playbook
- If build fails due to missing experiment outputs:
  - Provide commands to run the needed experiment first:
    `uv run truthweave run exp=<exp_name>`
  - Then rebuild assets again.
- If build fails due to environment/deps:
  - Provide exact missing package/error and suggest minimal `uv` steps.
