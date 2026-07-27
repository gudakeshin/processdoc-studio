"""Tests for deliverable archetype detection."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.deliverable_archetype import (
    detect_deliverable_archetype,
    is_meta_process_model,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "run_pov_apollo"


def test_apollo_instruction_detects_advisory_pov() -> None:
    instruction = (
        "Lets create a point of view note on Agentic AI interventions for Record to Report "
        "for Apollo Tyres I'd like to go with case_led Keep it horizontal across the full R2R cycle PPTX please"
    )
    assert detect_deliverable_archetype(instruction) == "advisory_pov"


def test_fixture_process_model_is_meta() -> None:
    pm = json.loads((FIXTURE_DIR / "process_model.json").read_text(encoding="utf-8"))
    assert is_meta_process_model(pm) is True


def test_operational_r2r_model_not_meta() -> None:
    pm = {
        "process_name": "Record to Report",
        "roles": ["Accountant", "Controller"],
        "steps": [
            {"id": "s1", "name": "Post journal entries", "role": "Accountant", "tools": ["ERP"], "outputs": []},
            {"id": "s2", "name": "Reconcile sub-ledgers", "role": "Accountant", "tools": ["ERP"], "outputs": []},
            {"id": "s3", "name": "Close books and report", "role": "Controller", "tools": ["ERP"], "outputs": []},
        ],
    }
    assert is_meta_process_model(pm) is False
