# SAP / S/4HANA requirements primer (for BRDs)

Use when the BRD supports an **SAP-centric** programme (greenfield, brownfield, or selective move to S/4HANA). This is not a substitute for SAP’s official methodology; it helps structure BRD content the way implementation teams expect.

## Public framing

- **SAP Activate** phases (Discover, Prepare, Explore, Realize, Deploy, Run) structure discovery through go-live; see SAP’s own methodology overview ([Describing the methodology structure — SAP Learning](https://learning.sap.com/learning-journeys/discovering-sap-activate-implementation-tools-and-methodology/describing-the-methodology-structure)).
- Alliance firms often position **selective** or value-led transformation paths when moving from ECC to S/4; see Deloitte’s public alliance positioning ([Selective Transformation — Deloitte / SAP](https://www.deloitte.com/cbc/en/alliances/sap/about/selective-transformation.html)).

## How this maps to your BRD sections

| BRD section | SAP-oriented emphasis |
|-------------|------------------------|
| Scope | Landscapes (ECC vs S/4), modules in scope, regions, integrations, data objects in scope |
| Current state | Pain in Record-to-Report, Order-to-Cash, etc.; custom code inventory *as pain driver*, not as BRD design |
| Functional requirements | **Fit-to-standard** first: process in standard vs required variant vs gap. Use requirement IDs that can attach to **Work Items** / backlog later |
| NFRs | Batch windows, peak volumes, legal retention, audit, languages, roles/security model at conceptual level |
| Data | Conversion vs migration boundaries; cut-over sensitive masters (customer, vendor, material, GL) |
| Reporting | SAP Datasphere / BW/4, group reporting, legacy report retirement |
| Governance | Solution validation cadence, fit-gap log ownership, architectural decision log hooks |

## Fit–standard–gap pattern (for functional requirements)

For each process area, tag requirements (in text or a sub-table) as one of:

- **Fit** — Covered by standard SAP with minimal configuration documented elsewhere.
- **Standard+** — Acceptable enhancement within defined guardrails (workflow, form, permitted extensibility).
- **Gap** — Requires design decision: configuration workaround, approved extension, or interface — flag for **gap log** / RAID.

## Deliverables that often pair with the BRD

- **Process models** (see process-map skill) at L2/L3 for in-scope chains.
- **RACI** for key process controls and approval points.
- **Approach note** when methodology or trade-offs are contested.

## Caution

Do not invent custom transaction codes or unreleased SAP product claims. Prefer “[SAP standard process area]” language unless the user supplies system facts.
