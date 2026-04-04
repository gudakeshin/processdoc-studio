# Script Test Matrix

## PR-Blocking Smoke (Tier A)
- `brd_v1/scripts/check_brd_sections.py`
- `approach_note_v1/scripts/check_approach_sections.py`
- `proposal_finance_transformation_v1/scripts/check_proposal_signals.py`
- `raci_v2/scripts/validate_raci_markdown.py`

## PR Optional / Unit (Tier B)
- `pptx_v1/scripts/clean.py`
- `docx_v1/scripts/accept_changes.py`
- `docx_v1/scripts/comment.py`

## Nightly Deep (Tier C)
- `xlsx_v1/scripts/recalc.py`
- `pptx_v1/scripts/thumbnail.py`
- `pdf_v1/scripts/convert_pdf_to_images.py`

## CI Split
- PR pipeline:
  - script contract static check
  - Tier A smoke tests
- Nightly pipeline:
  - Tier C integration tests with binary/tooling checks
