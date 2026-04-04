# RACI — leading practices for transformation programmes

## Definitions (strict mode)

- **R (Responsible)** — Does the work for the task; there may be multiple R’s for large tasks if subdivided.
- **A (Accountable)** — Exactly **one** role per task owns the outcome and approves completion. In regulated environments, A is often tied to sign-off authority.
- **C (Consulted)** — Two-way input expected before the task completes.
- **I (Informed)** — One-way notice after decisions or milestones.

## Consulting programme patterns

1. **One A per row** — Prevents “committee accountability”. If two groups think they are A, split the activity or elevate to a single executive owner.
2. **Activities, not job titles in the first column** — Use verbs + object (“Approve vendor invoice posting”, “Reconcile intercompany accounts”). Roles go in column headers.
3. **Approval steps** — Explicit RACI rows for approvals (financial, legal, data owner) reduce rework.
4. **Handoffs** — Any handoff between org units should have a clear R on the sending side and A/R pair on the receiving side for the next step.
5. **RACI vs RAPID** — For executive decision forums, some clients prefer **RAPID** (Recommend, Agree, Perform, Input, Decide). If the user names RAPID, translate columns accordingly and document the mapping once.

## Quality checks

- [ ] Each activity has exactly one **A**.
- [ ] Each activity has at least one **R** (or intentional exception flagged).
- [ ] No role is **A** for every row (unless truly a small workstream — then consider splitting the matrix).
- [ ] **C** is not overloaded onto every cell (“consult everyone”) — dilution warning.
- [ ] Escalation path referenced for conflicts on A.

## SAP / shared services note

For SAP programmes, align RACI rows with process areas (e.g. Record-to-Report) and distinguish **business process owner**, **IT service owner**, and **data steward** where those roles exist.

## Related script

Run `python scripts/validate_raci_markdown.py <file.md>` on markdown table output when available.
