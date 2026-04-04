# Skill Script Governance Hub

This folder contains enterprise optimization artifacts for skill scripts only.

## Contents
- `script_inventory.json`: generated inventory of skill scripts and tiers.
- `criticality_tiers.yaml`: Tier A/B/C policy and handling rules.
- `script_contract.md`: canonical script interface and error contract.
- `token_optimization_playbook.md`: progressive disclosure and token controls.
- `modularization_blueprint.md`: decomposition plan for large script packs.
- `script_test_matrix.md`: smoke/deep testing plan and CI split.
- `governance_playbook.md`: ownership, release, approval workflow.
- `metrics_scorecard.md`: KPI definitions and alert thresholds.
- `quarterly_review_template.md`: recurring optimization cadence.

## Generation
- Refresh inventory:
  - `python backend/scripts/skill_script_inventory.py`
- Validate script contract:
  - `python backend/scripts/validate_skill_script_contract.py`
