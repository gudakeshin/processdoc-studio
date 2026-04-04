# Process mapping — leading practices (transformation-ready)

Use when designing swimlane / BPM-style maps that must hold up in SAP, finance transformation, or operating-model work.

## Hierarchy

- **L0** — Value chain or end-to-end domain (e.g. Record-to-Report).
- **L1** — Major subprocess groups (e.g. general ledger close, consolidation).
- **L2/L3** — Operational steps suitable for swimlane maps; this skill targets **L2/L3** detail in diagrams.net form.

## Conventions

1. **Swimlanes = accountable role or org unit**, not systems. Put systems on the flow as labelled artifacts or notes when needed.
2. **Start / end** — One clear start; end may branch only if outcomes truly differ (e.g. rejected vs approved).
3. **Decisions** — Diamond or explicit gateway; **every branch has a label** (yes/no, above threshold, etc.).
4. **Handoffs** — When work crosses a lane, show the triggering event and avoid orphan connectors.
5. **Controls** — Optional overlay: mark control IDs or “key control” on steps that matter for SOX / audit (KC).

## SIPOC companion (lightweight)

For workshops, a one-page **SIPOC** per scope slice often precedes the swimlane:

| Suppliers | Inputs | Process (L2 name) | Outputs | Customers |

You may summarize SIPOC in narrative near the map if not visualized.

## SAP alignment

- Tie subprocess names to SAP **process areas** and implementation phasing (Discover/Prepare/Explore…) where the programme uses SAP Activate ([methodology overview](https://learning.sap.com/learning-journeys/discovering-sap-activate-implementation-tools-and-methodology/describing-the-methodology-structure)).
- Flag **fit vs gap** candidates on steps that are known customization hotspots (pricing, intercompany, revenue recognition).

## Quality checklist

- [ ] Every path from start reaches a defined end state.
- [ ] No unlabelled decision branches.
- [ ] Lane ownership matches RACI for approvals on the same activities (when RACI exists).
- [ ] Manual shadow steps (spreadsheets, email) shown if they carry material risk.

## Pairing with other skills

- **BRD** — Functional requirements reference process IDs / map version.
- **RACI** — Same activity verbs as map task labels.
- **Approach note** — When future-state design is contested, document options before locking the map.
