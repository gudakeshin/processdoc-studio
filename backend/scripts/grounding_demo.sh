#!/usr/bin/env bash
# Automated grounding demo — validates audit acceptance criteria without a live UI session.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "=== Grounding demo (pytest) ==="
pytest \
  app/tests/test_source_chunks_grounding.py \
  app/tests/test_evaluator_pipeline_integrity.py \
  app/tests/test_evidence_soft_block.py \
  app/tests/test_phase3_reviewer_trust.py \
  app/tests/test_remaining_hardening.py \
  -q --tb=line
echo "=== Grounding demo passed ==="
