# Skill Script Governance Playbook

## Ownership Model
- Each skill pack has:
  - Skill owner
  - Technical reviewer
  - Quality steward

## Release Semantics
- Patch: bug fixes, no CLI contract change.
- Minor: additive behavior, backward compatible.
- Major: breaking script contract or output format changes.

## Approval Workflow
1. Author change and update tests.
2. Technical review for correctness and compatibility.
3. Quality review for methodology and output consistency.
4. Merge and staged rollout.

## Rollout Policy
- Pilot high-risk changes on a subset of use cases.
- Promote after smoke metrics and defect thresholds pass.
