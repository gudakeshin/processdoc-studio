# Skill Script Metrics Scorecard

## Reliability
- Script smoke pass rate (target >= 99%)
- Tier A defect escape rate (target <= 1% per release)

## Efficiency
- Average token load per skill run
- Reference load ratio (loaded vs available references)

## Quality
- Validator fail rate by skill family
- Remediation loop count per deliverable

## Delivery Velocity
- Time to resolve script regressions
- Release lead time by tier

## Alert Thresholds
- Smoke pass rate < 97%: block rollout
- Tier A defect escape > 2%: trigger quality review
- Token load +20% WoW: trigger optimization review
