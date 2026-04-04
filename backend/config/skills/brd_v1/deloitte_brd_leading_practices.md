# BRD leading practices (consulting-grade)

Use this when expanding or QA’ing a BRD. Content aligns with patterns common across large-scale transformation firms and with requirements-management guidance from IIBA (traceability, unambiguous statements).

## Principles

1. **Requirements vs design** — The BRD states *what* the business needs and under what constraints; it does not prescribe vendor-specific configuration, code structure, or detailed UX unless those are contractual constraints.
2. **Traceability** — Every requirement should be uniquely identifiable and linkable to objectives, process steps, tests, and changes. Industry guidance treats traceability as core to requirements life-cycle management ([IIBA — Trace requirements](https://www.iiba.org/knowledgehub/business-analysis-body-of-knowledge-babok-guide/5-requirements-life-cycle-management/5-1-trace-requirements/)).
3. **Testability** — Functional statements in **EARS** (Easy Approach to Requirements Syntax) style reduce ambiguity. Each requirement should be verifiable.
4. **Scope discipline** — In/out of scope, interfaces, and reporting boundaries prevent scope creep and rework.

## BRD quality checklist

- [ ] Executive summary ties requirements to measurable business outcomes (not feature wishlists).
- [ ] Scope is bounded with explicit exclusions and interface systems.
- [ ] Stakeholders and user roles are named; proxy roles avoided where real owners exist.
- [ ] Current state reflects pain points, volumes, and control weaknesses that *motivate* change.
- [ ] Assumptions, dependencies, and constraints are explicit (regulatory, technical, timeline).
- [ ] Functional requirements: unique IDs, EARS patterns, **MoSCoW** priority, owner.
- [ ] NFRs: measurable targets (latency, availability, RTO/RPO, retention, audit, regions).
- [ ] Data: master data entities, ownership, retention, privacy/residency where relevant.
- [ ] Reporting: consumer roles, frequency, definitions, lineage to source fields (high level).
- [ ] Governance: sign-off authority, change-control process, RTM expectation (BRD → design → test).

## Requirements traceability matrix (RTM) — minimum columns

| Req ID | Section | Business objective | Process ref | Priority | Design ref (TBD) | Test ref (TBD) |

The BRD may include a starter RTM or state that downstream phases will extend it.

## Anti-patterns

- Mixing “shall” business requirements with detailed Fiori app IDs or ABAP object names (move to solution design).
- User stories only, with no acceptance criteria tied to requirement IDs.
- NFRs stated as “fast”, “secure”, “available” without thresholds.

## Related

- SAP-led programmes: see [`sap_s4hana_requirements_primer.md`](./sap_s4hana_requirements_primer.md) in this folder for fit-to-standard, gaps, and phase alignment.
