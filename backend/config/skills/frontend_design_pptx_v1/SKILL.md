---
id: frontend_design_pptx_v1
domain: Design System
display_name: Frontend Design (PPTX) Specialist
output_types:
- pptx
version: 1.0.0
description: Applies distinctive, production-grade frontend-inspired aesthetics to
  PPTX slide blueprint output.
use_when: the user wants slides with intentional visual hierarchy and cohesive aesthetic
  direction (frontend-inspired), while still producing valid JSON blueprints
tools:
- retrieve_context
- qa_validator
workflow_steps:
- Pick an aesthetic direction and define deck-wide hierarchy
- Draft slide titles in an ordered narrative flow
- Generate concise bullet points that emphasize key ideas
- Validate the JSON-only output contract
feedback_loop:
- Check hierarchy
- Tighten bullet text
- Remove generic filler
- Finalize JSON blueprint
freedom_level: medium
quality_thresholds:
  pptx: 0.9
acceptance_checks:
- Valid JSON with `slides` key and slide objects
- Concise scannable bullet points
- Cohesive slide ordering and hierarchy consistent with the aesthetic direction
- No non-JSON text in the output
default_representation: pptx
companion_files: []
source_url: https://github.com/anthropics/skills/tree/main/skills/frontend-design
sample_instruction: Create a PPTX blueprint deck with a bold aesthetic direction using
  cohesive slide hierarchy; output must be ONLY JSON as our pptx agent expects.
custom: false
---

# PPTX Visual Hierarchy — Design-Aware Blueprint Generation

This skill generates a **JSON slide blueprint** using the same `{"slides": [...]}` contract as
`pptx_v1`, but with a primary mandate of **visual hierarchy and layout variety**. The output is
rendered by the platform's python-pptx renderer using the Deloitte design system.

---

## Primary Mandate: Visual Intentionality

Every deck must tell a coherent visual story. Before generating slides, establish a hierarchy:

1. **Opening impact** — title slide sets the tone; use `badges` to surface 3–4 key themes
2. **Quantitative anchor** — a `stat_cards` slide early in the deck gives scale and urgency
3. **Conceptual frame** — `column_cards` presents the 3-pillar or 3-dimension view
4. **Process depth** — `stack_layers` and `table` slides carry the operational detail
5. **Action close** — final bullets slide with exactly 3 numbered next actions

**Never open with bullets. Never close with a table.**

---

## Layout Selection Rules

| Information type | Use this slide_type |
|---|---|
| Scale, KPIs, counts, SLA metrics | `stat_cards` |
| 3-dimension frameworks, pillars, capabilities | `column_cards` |
| Architecture layers, workflow phases, tiers | `stack_layers` |
| Step-by-step process, input/output pairs, ownership | `table` |
| Role mandates, policy points, ordered steps | `bullets` |
| Major section transitions | `section_divider` |

**Rule**: If the information fits in a table or cards, do not use bullets. Bullets are the
layout of last resort, not the default.

---

## Visual Rhythm: Fill and Accent Rotation

The renderer applies brand fills based on token values you specify. Vary fills across cards/rows
to create visual rhythm — avoid repeating the same fill across all items.

**stat_cards fill sequence**: `"dark"` → `"mid_dark"` → `"gray"`

**stack_layers fill sequence** (rotate in order):
`"green"` → `"mid_dark"` → `"dark"` → `"gray"` → `"dark_green"` → repeat

**column_cards accent sequence**: `"green"` → `"dark"` → `"gray"`

---

## Content Density per Slide Type

### `stat_cards` — all 3 cards must be fully populated
- `stat`: a concrete number or short KPI label (≤5 words)
- `label`: 2-line descriptor with context (e.g. "Process Steps\nacross 4 departments")
- `description`: 1–2 sentences explaining significance. **This fills the lower card half —
  a missing description leaves an empty void in the rendered slide.**

### `column_cards` — all 3 cards must have substantive bodies
- `body`: a full paragraph (3–5 sentences or ≤40 words) — not a bullet list
- `heading`: active verb phrase or capability name

### `stack_layers` — 3–7 rows
- Each `description` should be a meaningful phrase (8–15 words), not a title repeat
- `label` should be a short role/phase/tier identifier (≤3 words)

### `bullets` — content-adaptive
- 4–8 bullets per slide; renderer adjusts font size automatically based on count
- Each bullet: one clear, discrete point (≤15 words)
- Do NOT pad bullets to fill space — write the right number of items

---

## Hierarchy Anti-Patterns to Avoid

- **All-bullets decks**: if >50% of content slides are `bullets`, redesign to use cards/layers
- **Empty card bodies**: `stat_cards` without `description`, `column_cards` with one-word bodies
- **Title padding**: `subtitle` on every slide dilutes the title slide's visual impact
- **Uniform fills**: all `stack_layers` rows with the same `fill` token — rotate them
- **Bullet overflow**: more than 9 bullets on a single slide loses visual clarity

---

## Output Contract

Single JSON object, no preamble, no markdown fences:

```json
{"slides": [ ... ]}
```

Every slide requires `title` (≤10 words) and `slide_type`. Omit fields with null values.
