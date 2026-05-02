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

# PPTX Deck Generation — Deloitte Visual Standard

This skill generates the content specifications for a **fully-branded, production-ready PPTX presentation deck**. 
Your output is a structured `{"slides": [...]}` JSON object that the platform immediately renders into an actual 
.pptx file that users can download and open in PowerPoint. Your output IS the deck — no further manual steps needed.
You do NOT write python code or call shell tools. Your entire output is valid JSON.

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
  "slide_type": "title|bullets|stat_cards|column_cards|stack_layers|table|chart|section_divider|big_number|process_flow",
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
    "type": "bar|line|pie|column|area|doughnut|column_stacked",
    "categories": ["string"],
    "series": [{"name": "string", "values": [0.0]}],
    "subtitle": "string — data source citation ≤15 words"
  },
  "big_number": {
    "stat": "string — headline metric (e.g. '$400M', '87%', '14')",
    "label": "string — 2–5 word descriptor",
    "context": "string — 1 sentence of context (optional)",
    "fill": "dark|green|mid_dark"
  },
  "process_flow": {
    "steps": [
      {"label": "string ≤4 words", "description": "string ≤12 words",
       "fill": "green|dark|mid_dark|dark_green|mid"}
    ]
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

### `chart`
Use for trends, rankings, or composition data where the **shape** of the data is the message.

**Supported types:** `"column"` (compare items across periods), `"bar"` (rankings), `"line"` (trends over time), `"pie"` (part-of-whole, ≤5 segments), `"area"` (cumulative volume), `"doughnut"` (single ratio), `"column_stacked"` (stacked comparison).

**Rules:**
- `categories`: 3–8 labels; each `series` needs `name` and `values` (numbers only, same length as categories)
- Use ≤3 series; add `subtitle` to cite the data source
- Prefer `chart` over a second `stat_cards` when time-series or benchmark data is available

Minimum valid chart: `{"type": "column", "categories": ["Q1","Q2","Q3","Q4"], "series": [{"name": "Savings ($M)", "values": [12,24,45,67]}], "subtitle": "Source: FY2024 actuals"}`

### `big_number`
Use when **one KPI is the entire story** of a slide. The stat renders at 80pt — choose a number with genuine impact. Derive from ProcessModel or enrichment analytics; do not invent. Use at most once per deck.
- `fill`: use `"dark"`, `"green"`, or `"mid_dark"` only (light fills break contrast with the large stat)

### `process_flow`
Horizontal arrow chain for **sequential ordered steps** — use instead of `stack_layers` when the order is the story. Use 3–5 steps.
- `label`: ≤4 words (step name)
- `description`: ≤12 words (what happens)
- Rotate `fill` across steps: `"green"`, `"dark"`, `"mid_dark"`, `"dark_green"`, `"mid"`

### `section_divider`
Full-bleed dark slide for major section breaks. Include only `title` and optionally `subtitle`.

---

## Executive Story Guidance (Boardroom Standard)

When building executive-grade decks (PPTX_ARTIFACT_RENDERER_ENABLED), elevate your narrative:

**Pre-Composition Planning (Internal):**
1. **Thesis Statement** — Distill the deck's argument to one sentence (e.g., "This process transformation unlocks $2.3M in annual savings and improves customer response time by 40%.")
2. **Audience Decision** — What decision/action will this deck unlock? (Approval, budget allocation, resource commitment, strategic pivot.)
3. **Slide-by-Slide Story Arc** — Map each slide's role in the narrative:
   - Slide 1–2: Establish the problem/opportunity (current state pain, market context)
   - Slide 3–4: Present the business case (opportunity size, ROI, stakeholder benefit)
   - Slide 5–7: Describe the solution/approach (design, phasing, dependencies)
   - Slide 8–10: Seal the ask (recommended actions, next steps, owner accountability)
4. **Evidence Plan** — Before writing each metric:
   - Is this from ProcessModel? (✓ use it)
   - Is this from uploaded/source data? (✓ cite it; add source_refs to slide notes)
   - Is this an inference/estimate? (⚠️ label explicitly: "estimated", "projected", ~, ±)
   - Is this made up? (✗ stop; derive from data or reframe the claim)

**Deck Composition Rules (Executive Standard):**
- **One dominant object per slide** — choose ONE narrative anchor (a stat, a chart trend, a workflow) per slide; support with bullets/labels only
- **Shorter copy** — stat_cards descriptions should be ≤2 sentences; column_card bodies ≤40 words; no padding
- **Evidence visibility** — Include data sources (citations, ranges) directly in slides; use speaker_notes for assumptions
- **No generic headers** — Replace context headings like "Process Context" with specifics (e.g., "Why This Matters: 3-Month Manual Effort Vs. Automated SLA")
- **Consistent branding** — Use the branding palette throughout; avoid gray as a default (use dark/green/mid_dark for intentional contrast)

**Claim Substantiation Checklist:**
- ✓ Financial claims ($M, ROI, savings) → ProcessModel.financials or explicit user instruction
- ✓ Volume/scale claims (N steps, N roles, N systems) → ProcessModel.steps/.roles/.systems counts
- ✓ Improvement claims (X% faster, Y% cheaper) → source data, benchmarks, or labeled assumption
- ✗ Avoid: vague metrics without source, percentages without baselines, "significant" / "major" without numbers

---

## Mandatory Slide Sequence

1. `slide_type: "title"` — process name as title, `subtitle: "Process Overview"`, badges
2. `slide_type: "stat_cards"` — 3 KPI cards from ProcessModel metrics
3. `slide_type: "column_cards"` OR `"process_flow"` — use `column_cards` for three-pillar frameworks; use `process_flow` when 3–5 steps are strictly ordered
4. `slide_type: "stack_layers"` — architecture / workflow layers (one row per phase)
5. `slide_type: "bullets"` — Process Overview, one bullet per role mandate
6. `slide_type: "table"` — Workflow Walkthrough: Step | Owner | Input → Output
7. `slide_type: "chart"` (if time-series or benchmark data exists), `"big_number"` (if one metric dominates), or `"stat_cards"` (for three parallel KPIs). **Never use `"bullets"` here.**
8+ Additional content slides as needed
Final: `slide_type: "bullets"`, title "Recommended Next Actions", exactly 3 numbered actions

---

## Layout Variety Mandate

**Never produce a deck that is 80%+ bullets slides.** A well-designed deck uses the full range
of layout types. Aim for at most 40% bullets slides; use `stat_cards`, `column_cards`, `process_flow`,
`stack_layers`, `table`, `chart`, and `big_number` to convey structured information more effectively.

---

## Quality Rules

- `title` and `slide_type` required on every slide — missing either fails validation
- `stat_cards`: exactly 3 items; include `description` in every card (≤25 words)
- `column_cards`: exactly 3 items; `body` ≤40 words
- `stack_layers`: `description` ≤20 words per row
- `big_number`: `fill` must be `dark`, `green`, or `mid_dark` — light fills break contrast
- `process_flow`: 2–5 steps required; each step needs `label` and `fill`
- Do not mix `bullets` and `table` on the same slide
- `footer_note` is a single line — do not use it for multi-sentence explanations
- Derive metrics from ProcessModel; do not invent numbers not in the source data
