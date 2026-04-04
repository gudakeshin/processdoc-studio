# Token Optimization Playbook (Skill Scripts)

## Progressive Disclosure Rules
- Keep each `SKILL.md` focused on routing logic and minimal instructions.
- Put detailed methodology in references and load only per use case.
- Add explicit decision trees near top of each `SKILL.md`.

## Bundling Rules
- Bundle repeated logic into script modules instead of regenerating ad-hoc code.
- Prefer reusable validator/formatter scripts for recurring operations.

## Reference Hygiene
- References over 100 lines must include a compact table of contents.
- Use short, sectioned files by sub-domain (close, FP&A, GBS, working capital).

## Budget Targets
- Target skill load: under 2,500 tokens for base `SKILL.md`.
- Target domain reference load: under 800 tokens per selected branch.
- Avoid loading more than two large references in first pass.

## Anti-Patterns
- Monolithic all-domain references loaded by default.
- Repeated long prose where compact bullet templates suffice.
- Script generation loops for checks that already have bundled scripts.
