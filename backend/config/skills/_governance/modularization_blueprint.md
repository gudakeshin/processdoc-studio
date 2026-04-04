# Modularization Blueprint (docx/pptx/xlsx)

## Target Layout
- `scripts/parsers/`
- `scripts/validators/`
- `scripts/transformers/`
- `scripts/renderers/`
- `scripts/orchestrators/`

## Shared Layer
- Use shared helper modules from `backend/config/skills/_shared_scripts/`.
- Keep script contract and structured output helpers centralized.

## Migration Sequence
1. Extract validators from monolithic scripts first.
2. Extract parser and transformation functions second.
3. Keep orchestrators thin and dependency-aware.
4. Preserve CLI compatibility while moving internals.

## Compatibility Guardrails
- No breaking CLI changes in minor versions.
- Add wrappers for legacy script names if module paths change.
- Maintain deterministic output order for validator scripts.
