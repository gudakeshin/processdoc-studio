---
id: process_map_v2
domain: Strategy & Ops
display_name: Process Map Modeling Specialist
output_types:
- process_map
version: 2.0.0
description: Builds lane-aware process maps with decisions and handoffs. Use when
  teams need a visual model of sequence, ownership, and branching logic.
use_when: teams need a visual model of sequence, ownership, and branching logic
tools:
- retrieve_context
- search_leading_practices
- process_model_query
- drawio_process_model_to_xml
- diagram_builder
- qa_validator
workflow_steps:
- Identify actors, steps, and decision points
- Lay out swimlanes by role ownership
- Connect sequence and decision branches with labels
- Validate start/end nodes, handoffs, and flow consistency
feedback_loop:
- Draft diagram
- Run structural checks
- Fix disconnected nodes and lane mismatches
- Finalize
freedom_level: low
quality_thresholds:
  process_map: 0.9
acceptance_checks:
- Includes Start and End nodes
- Uses swimlanes by role
- Decision branches are labeled and connected
- Flow direction is consistent
- Handoffs match lane ownership
default_representation: drawio_xml
companion_files:
- ./deloitte_process_mapping_leading_practices.md
- ./sap_activate_process_alignment.md
sample_instruction: Create a swimlane process map for customer complaint handling
  with decision branches for severity and escalation.
custom: false
---

# Process Map Generation Guide — diagrams.net (draw.io) Format

Produce a diagrams.net-compatible XML process map with full swimlane layout, decision branches,
and consistent flow. Companion files (`deloitte_process_mapping_leading_practices.md` and
`sap_activate_process_alignment.md`) are loaded automatically — apply their conventions.

---

## Hierarchy Level

This skill targets **L2/L3 operational detail** — swimlane maps showing individual steps, roles,
and decision branches. Do not produce L0 value-chain maps or L4 system-interaction diagrams
unless explicitly requested.

---

## Node Types

| Shape | diagrams.net style | Use for |
|---|---|---|
| Rounded rectangle | `rounded=1` | Process steps (tasks) |
| Diamond | `rhombus` or decision style | Decision points / gateways |
| Oval/circle | `ellipse` | Start and End nodes |
| Rectangle | `shape=document` | Artifacts / deliverables passed between lanes |

**Every map must have exactly one Start node and at least one End node.**
If outcomes truly differ (e.g. approved vs rejected), use separate End nodes for each outcome.

---

## Swimlane Layout

- One lane per accountable role or org unit from ProcessModel.roles
- Systems and tools appear as **labelled artifacts on connectors** or annotation notes — they do
  not get their own swimlanes
- Lane ordering: place the lane that initiates the process at the top; sequence other lanes by
  first-interaction order
- Use `swimlane` cell style with `startSize` for the lane header width

---

## Decision Branch Rules

Every diamond gateway must:
1. Have **labeled outgoing connectors** — "Yes / No", "> threshold / ≤ threshold", etc.
2. Connect to a defined next step on **every branch** — no dangling connectors
3. Merge back to a common step where paths reconverge (use a merge gateway or note)

If a branch leads to a loop-back (retry / rework), label the connector with the loop condition.

---

## Handoffs

When control passes from one lane to another:
- Show the **triggering artifact** or event on the crossing connector (e.g. "Approved PO")
- The sending lane's last step connects to the artifact; the artifact connects to the receiving
  lane's first step
- Ensure lane ownership on the destination step matches the receiving role

---

## Controls Overlay (Optional)

For SOX / audit-relevant processes, annotate key-control steps with a control ID label:
- Add a small annotation shape tagged `KC: [control-ID]` adjacent to the step
- List all key controls in an XML `<!-- Controls: -->` comment at the end of the XML

---

## Quality Checklist (apply before finalising)

- [ ] Every path from Start reaches a defined End state (no dead ends)
- [ ] No unlabelled decision branches
- [ ] Lane ownership matches the ProcessModel.swimlanes assignment for each step
- [ ] All role names in the diagram match ProcessModel.roles exactly
- [ ] Handoff connectors cross lanes at most once per logical step (no spaghetti flows)
- [ ] Manual shadow steps (spreadsheets, email approvals) shown if they carry material risk

---

## SAP Programme Alignment

When the process belongs to an SAP programme, align subprocess names and step labels with SAP
Activate phases (Discover / Prepare / Explore / Realize / Deploy / Run) per the companion file.
Flag **fit vs gap** candidates on steps that are known customisation hotspots (pricing,
intercompany, revenue recognition).
