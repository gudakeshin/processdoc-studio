"""Tests for pptx_schema.py pre-render slide validator."""

from __future__ import annotations

import pytest

from app.core.pptx_schema import validate_slide_schema, SUPPORTED_SLIDE_TYPES


def test_all_phase3_types_are_supported() -> None:
    new_types = {"split_panel", "lanes", "workstream_cards", "tower_cards",
                 "roadmap_matrix", "swimlane_timeline", "flagship_cards"}
    assert new_types.issubset(SUPPORTED_SLIDE_TYPES)


def test_unknown_slide_type_flagged() -> None:
    slides = [{"slide_type": "sparkle_chart", "title": "X"}]
    v = validate_slide_schema(slides)
    assert any("unknown slide_type" in e for e in v)


def test_missing_slide_type_flagged() -> None:
    slides = [{"title": "No type"}]
    v = validate_slide_schema(slides)
    assert any("missing slide_type" in e for e in v)


def test_title_too_long_flagged() -> None:
    long_title = "A " * 50  # 100 chars
    slides = [{"slide_type": "bullets", "title": long_title, "bullets": ["x"]}]
    v = validate_slide_schema(slides)
    assert any("title too long" in e for e in v)


def test_empty_bullets_flagged() -> None:
    slides = [{"slide_type": "bullets", "title": "T", "bullets": []}]
    v = validate_slide_schema(slides)
    assert any("bullets" in e for e in v)


def test_empty_stat_cards_flagged() -> None:
    slides = [{"slide_type": "stat_cards", "title": "T", "stat_cards": []}]
    v = validate_slide_schema(slides)
    assert any("stat_cards" in e for e in v)


def test_column_cards_too_many_flagged() -> None:
    cards = [{"heading": f"H{i}", "body": "B", "accent": "dark"} for i in range(5)]
    slides = [{"slide_type": "column_cards", "title": "T", "column_cards": cards}]
    v = validate_slide_schema(slides)
    assert any("column_cards" in e for e in v)


def test_invalid_workstream_status_flagged() -> None:
    slides = [{
        "slide_type": "workstream_cards", "title": "T",
        "workstream_cards": [{"heading": "H", "body": "B", "status": "done"}],
    }]
    v = validate_slide_schema(slides)
    assert any("status" in e.lower() for e in v)


def test_valid_workstream_cards_clean() -> None:
    slides = [{
        "slide_type": "workstream_cards", "title": "T",
        "workstream_cards": [
            {"heading": "A", "body": "Body A", "status": "live"},
            {"heading": "B", "body": "Body B", "status": "in_build"},
            {"heading": "C", "body": "Body C", "status": "planned"},
        ],
    }]
    v = validate_slide_schema(slides)
    assert v == []


def test_roadmap_matrix_missing_periods_flagged() -> None:
    slides = [{
        "slide_type": "roadmap_matrix", "title": "T",
        "roadmap_matrix": {"tracks": [{"label": "Track A", "cells": []}]},
    }]
    v = validate_slide_schema(slides)
    assert any("periods" in e for e in v)


def test_valid_flagship_cards_clean() -> None:
    slides = [{
        "slide_type": "flagship_cards", "title": "T",
        "flagship_cards": [
            {"heading": "Product A", "body": "Core offering.", "kpis": [{"label": "Revenue", "value": "$4M"}]},
            {"heading": "Product B", "body": "Platform play.", "client": "Acme Corp"},
        ],
    }]
    v = validate_slide_schema(slides)
    assert v == []


def test_clean_classic_slides_pass() -> None:
    slides = [
        {"slide_type": "title", "title": "Intro"},
        {"slide_type": "bullets", "title": "Points", "bullets": ["One", "Two"]},
        {"slide_type": "stat_cards", "title": "Metrics",
         "stat_cards": [{"stat": "5", "label": "Steps", "description": "Five steps"}]},
    ]
    assert validate_slide_schema(slides) == []
