# SAP Activate ↔ process mapping (alignment note)

Use when the process map supports **SAP Discover / Prepare / Explore** style workshops.

## Phase touchpoints

| Activate phase | What maps typically prove |
|----------------|---------------------------|
| Discover | Value case drivers, scope boundaries, L0/L1 pain |
| Prepare | Governance, workshop plan, modelling standards |
| Explore | Fit-to-standard walkthroughs, **L2/L3** to-be drafts, gap triggers |
| Realize | Detailed design deltas; often out of scope for high-level BRD maps |

Official phase descriptions: [SAP Learning — methodology structure](https://learning.sap.com/learning-journeys/discovering-sap-activate-implementation-tools-and-methodology/describing-the-methodology-structure).

## Modelling hygiene for Explore

- Name subprocesses so they can roll up to SAP **best-practice** scenario names where applicable.
- Mark **variance** points (pricing, account determination, cut-off, intercompany) as decisions on the diagram.
- Keep **manual workarounds** visible — they drive backlog and data fixes in Realize.

## Relationship to BRD

Export **activity IDs** or stable labels from the map and reference them in functional requirement text (`Process ref` in RTM).
