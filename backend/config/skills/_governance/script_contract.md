# Canonical Skill Script Contract

## Required Interface
- Script must expose `main() -> int`.
- Script entrypoint must use `raise SystemExit(main())`.
- Exit codes:
  - `0`: success
  - `1`: validation/quality failure
  - `2`: usage/invalid arguments

## IO Contract
- Input source:
  - explicit file argument, or
  - stdin fallback for pipeline usage.
- Output modes:
  - human-readable text to stdout/stderr
  - optional JSON mode for automation.

## Error Semantics
- Validation failures must list concrete issues.
- Usage failures must print a one-line command synopsis.
- Exceptions should be handled and translated into deterministic messages.

## Enforcement
- Static contract check:
  - `python backend/scripts/validate_skill_script_contract.py`
- Runtime smoke checks:
  - `pytest backend/app/tests/test_skill_scripts_smoke.py -q`
