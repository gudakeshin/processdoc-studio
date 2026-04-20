# ADR: PPTX Canvas Renderer Strategy Spike

Date: 2026-04-19  
Status: Accepted (Tier 2 spike outcome)

## Context

Process Doc v2 currently renders PPTX from slide JSON using `python-pptx` only. We need a canvas preview path that enables inline edits while preserving `.pptx` output quality and existing remediation loops.

Two options were considered:

1. **Shared JSON, dual renderers**
   - Keep Python PPTX renderer as-is.
   - Add frontend React canvas renderer for the same slide schema.
2. **HTML-first source of truth**
   - Make HTML/canvas the primary model.
   - Convert HTML to PPTX downstream.

## Decision

Choose **Option 1: Shared JSON, dual renderers** for Tier 2.

## Why

- Lowest migration risk: preserves existing PPTX pipeline and QA/remediation behavior.
- Compatible with current targeted slide repair model (`prior_pptx_slides` + `pptx_visual_feedback`).
- Enables incremental rollout: canvas can be introduced without replacing export path.
- Clear testability: parity can be measured against fixed JSON samples.

## Spike Deliverables

1. **Canvas scaffold**  
   Added `frontend/components/deck-canvas/DeckCanvas.tsx` with support for:
   - `title`
   - `bullets`
   - `stat_cards`
   - `column_cards`
   - `stack_layers`
   - `table`
   - `section_divider`

2. **Parity harness**  
   Added `infra/scripts/pptx_canvas_parity_spike.py` and 3 sample decks in:
   - `infra/samples/deck_parity/sample_ops_exec_review.json`
   - `infra/samples/deck_parity/sample_finance_transform.json`
   - `infra/samples/deck_parity/sample_supply_chain.json`

3. **Generated report**  
   Running the harness writes:
   - `infra/reports/pptx_canvas_parity_report.json`

## Spike Results (3 sample decks)

- Sample count: 3
- Supported slide types in samples: all 7 expected
- Unsupported slide types: 0
- Missing titles: 0
- Structural parity score: `1.0` for all samples
- Overall pass: `true`

## Trade-offs

- Dual renderer maintenance burden exists and must be managed by parity tests.
- Structural parity is validated now; visual pixel parity is a follow-up (not completed in this spike).

## Follow-up Actions

Completed:

1. Added visual parity screenshot diff harness (target `<5%` diff per slide):
   - `infra/scripts/pptx_canvas_visual_diff_spike.py`
   - report output: `infra/reports/pptx_canvas_visual_diff_report.json`
2. Integrated `DeckCanvas` into project studio artifact panel behind feature flag:
   - flag: `NEXT_PUBLIC_DECK_CANVAS_ENABLED` (`false` disables preview)
3. Added inline element-path click annotations in canvas to prefill targeted update prompts.
4. Multi-format deck export (PPT-204):
   - `backend/app/core/deck_exporter.py` produces `deck.html` + `deck.pdf` alongside `output.pptx`.
   - Hooked into `PPTXDeliverable.render()` as a fail-open sidecar.
   - Surfaced via `/api/runs/{project}/{run}/artifacts` as `deck_html` + `deck_pdf_base64` and in `output_filenames` / `ready_downloads`.
   - Typed artifacts register `deck_html` and `deck_pdf` output types.
5. Parity harness schema-strict mode (PPT-201 follow-up):
   - `infra/scripts/pptx_canvas_parity_spike.py` now hard-fails when a sample
     contains an unsupported `slide_type` or a missing title regardless of
     aggregate parity score.
   - `backend/app/tests/test_pptx_canvas_parity_harness.py` exercises the
     harness from pytest so schema drift between the backend and the canvas
     is caught by the backend CI job, in addition to the existing
     `pptx.canvas.parity` make target.

Remaining: none at this time.

