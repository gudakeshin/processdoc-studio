---
id: pptx_v1
domain: Presentations
display_name: PPTX Deck Builder
output_types:
- pptx
version: 1.0.0
description: Creates, edits, and validates presentation decks with layout, visual
  hierarchy, and slide-quality checks. Use when deliverables involve .pptx files,
  decks, or slides.
use_when: a task requires creating, updating, parsing, or repackaging powerpoint presentations
tools:
- retrieve_context
- format_table
- qa_validator
- style_enforcer
workflow_steps:
- Define narrative and slide-level structure
- Build or edit slides with intentional visual design
- Run content and visual QA checks
- Fix layout/content defects and finalize deck
feedback_loop:
- Draft deck
- Run text and visual QA
- Fix layout and clarity issues
- Re-verify and finalize
freedom_level: medium
quality_thresholds:
  pptx: 0.9
acceptance_checks:
- Slides have consistent hierarchy and spacing
- No text overflow or overlapping elements
- No leftover placeholder content
- Deck supports intended narrative flow
default_representation: pptx
companion_files: []
source_url: https://github.com/anthropics/skills/tree/main/skills/pptx
sample_instruction: Build a 10-slide executive deck summarizing current-state process
  issues, opportunities, and a 90-day action plan.
custom: false
---

# PPTX Blueprint Generation — Deloitte Visual Standard

This skill generates a **JSON slide blueprint** — a structured `{"slides": [...]}` object that is
rendered into a fully-branded python-pptx deck by the platform renderer. You do NOT write python
code or call shell tools. Your entire output is valid JSON.

---

## Output Contract

Your response MUST be a single JSON object and nothing else:

```json
{"slides": [ ... ]}
```

No preamble, no explanation, no markdown fences around the JSON. The renderer will reject any
non-JSON text.

---

## Slide Object Schema

Every slide requires `title` (≤10 words) and `slide_type`. All other fields are optional — omit
keys whose values would be null.

```json
{
  "title": "string — ≤10 words (required)",
  "slide_type": "title|bullets|stat_cards|column_cards|stack_layers|table|chart|section_divider",
  "subtitle": "string | omit",
  "bullets": ["string — each ≤15 words"] ,
  "badges": ["string — short pill labels, title slide only"],
  "stat_cards": [
    {"stat": "string — number or short metric", "label": "string — 2-line explanation",
     "description": "string — 1–2 sentences filling card body", "fill": "dark|mid_dark|gray"}
  ],
  "column_cards": [
    {"heading": "string", "accent": "green|dark|gray", "body": "string — ≤40 words"}
  ],
  "stack_layers": [
    {"label": "string — ≤3 words", "description": "string — ≤15 words",
     "fill": "green|dark|mid_dark|gray|dark_green"}
  ],
  "table": {
    "headers": ["string"],
    "rows": [["string"]],
    "x": 0.28, "y": 1.0, "w": 9.44, "h": 4.3
  },
  "chart": {
    "type": "bar|line|pie",
    "categories": ["string"],
    "series": [{"name": "string", "values": [0.0]}]
  },
  "footer_note": "string — single-line band at slide bottom (use sparingly)"
}
```

---

## Slide Type Guidance

### `title`
Opening slide. Use `subtitle`, `badges` (up to 4 short capability phrases). No bullets.

### `bullets`
Standard content slide. Use `bullets` (4–8 items). Keep each bullet to a clear, discrete point.
**Content-adaptive sizing**: the renderer automatically adjusts font size based on bullet count —
write the right number for the content, not to fill space.

### `stat_cards`
Three equal-width cards spanning the full slide. **Exactly 3 items in `stat_cards`.**
- `stat`: a short number or KPI (e.g. "14 Steps", "3 Roles", "48h SLA")
- `label`: 2-line descriptor (e.g. "Active Process Steps\nacross 3 business units")
- `description`: 1–2 sentences of context filling the lower half of the card
- `fill`: rotate fills across cards — e.g. `["dark", "mid_dark", "gray"]`
Do not fabricate metrics; derive from ProcessModel step/role/decision counts or metadata.

### `column_cards`
Three equal-width columns with an accent top bar. **Exactly 3 items in `column_cards`.**
Good for three-pillar frameworks, capability dimensions, or workstream areas.
- `accent`: controls the top bar color — vary across cards for visual contrast
- `body`: substantive paragraph (≤40 words), not a bullet list

### `stack_layers`
Horizontal rows for architecture layers, workflow phases, or transformation themes. 3–7 rows.
- `label`: the short row identifier (role, phase, tier)
- `description`: what happens in this layer
- Rotate `fill` tokens to create visual rhythm: `"green"`, `"mid_dark"`, `"dark"`, `"gray"`, `"dark_green"`

### `table`
Use for structured data: step-by-step workflows, input/output matrices, ownership tables.
- Header row renders in brand dark fill with white text
- Keep cells concise (≤8 words per cell)
- Use default table coordinates unless content demands adjustment

### `section_divider`
Full-bleed dark slide for major section breaks. Include only `title` and optionally `subtitle`.

---

## Mandatory Slide Sequence

1. `slide_type: "title"` — process name as title, `subtitle: "Process Overview"`, badges
2. `slide_type: "stat_cards"` — 3 KPI cards from ProcessModel metrics
3. `slide_type: "column_cards"` — 3-pillar framework relevant to this process
4. `slide_type: "stack_layers"` — architecture / workflow layers (one row per phase)
5. `slide_type: "bullets"` — Process Overview, one bullet per role mandate
6. `slide_type: "table"` — Workflow Walkthrough: Step | Owner | Input → Output
7. `slide_type: "stat_cards"` — Key Metrics and Controls (strongly preferred over bullets)
8+ Additional content slides as needed
Final: `slide_type: "bullets"`, title "Recommended Next Actions", exactly 3 numbered actions

---

## Layout Variety Mandate

**Never produce a deck that is 80%+ bullets slides.** A well-designed deck uses the full range
of layout types. Aim for at most 40% bullets slides; use stat_cards, column_cards, stack_layers,
and table to convey structured information more effectively.

---

## Quality Rules

- `title` and `slide_type` required on every slide — missing either fails validation
- `stat_cards`: exactly 3 items; include `description` in every card
- `column_cards`: exactly 3 items
- Do not mix `bullets` and `table` on the same slide
- `footer_note` is a single line — do not use it for multi-sentence explanations
- Derive metrics from ProcessModel; do not invent numbers not in the source data
