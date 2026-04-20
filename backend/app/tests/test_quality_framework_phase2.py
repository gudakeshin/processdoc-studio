"""Phase 2 — unified quality framework structural completeness (PPTX + markdown outputs)."""

from __future__ import annotations

import json

from app.core.quality_framework import UnifiedQualityFramework


def test_unified_framework_flags_incomplete_pptx() -> None:
    bad = json.dumps(
        {
            "slides": [
                {"slide_type": "title", "title": "P2P Process"},
                {"slide_type": "stat_cards", "title": "Metrics", "stat_cards": []},
            ]
        }
    )
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="pptx",
        text=bad,
        metadata={},
        context={"branding": None},
    )
    assert report["passed"] is False
    assert report["aggregate_score"] < 0.75
    struct = report["dimensions"].get("structural_completeness")
    assert struct is not None
    assert float(struct["score"]) < 0.5
    assert struct["issues"]


def test_unified_framework_accepts_complete_pptx() -> None:
    good = json.dumps(
        {
            "slides": [
                {"slide_type": "title", "title": "P2P Process"},
                {
                    "slide_type": "stat_cards",
                    "title": "Metrics",
                    "stat_cards": [
                        {"stat": "14", "label": "Steps", "description": "Steps"},
                        {"stat": "5", "label": "Roles", "description": "Roles"},
                        {"stat": "3", "label": "Systems", "description": "Systems"},
                    ],
                },
                {
                    "slide_type": "column_cards",
                    "title": "Pillars",
                    "column_cards": [
                        {"heading": "P1", "body": "Body1"},
                        {"heading": "P2", "body": "Body2"},
                        {"heading": "P3", "body": "Body3"},
                    ],
                },
                {"slide_type": "bullets", "title": "Next Steps", "bullets": ["Action 1", "Action 2"]},
            ]
        }
    )
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="pptx",
        text=good,
        metadata={},
        context={"branding": None},
    )
    assert report["passed"] is True
    assert report["aggregate_score"] >= 0.75


def test_unified_framework_docx_without_headings_soft_warning() -> None:
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="docx",
        text="Plain paragraph with enough characters to satisfy content quality. " * 5,
        metadata={},
        context={"branding": None},
    )
    assert report["dimensions"]["structural_completeness"]["score"] < 1.0
    assert report["passed"] is True


def test_unified_framework_flags_visual_density_for_pptx() -> None:
    dense = json.dumps(
        {
            "slides": [
                {
                    "slide_type": "bullets",
                    "title": "This title is intentionally long to trigger hierarchy warnings in visual checks",
                    "bullets": [
                        "This bullet is intentionally very long and verbose to force a line length warning for readability",
                        "Another dense bullet with too many words that should not fit comfortably on a single executive slide",
                        "Third bullet repeats the same pattern with excessive detail for deterministic visual QA heuristics",
                        "Fourth bullet keeps adding clutter and visual noise across the body area",
                        "Fifth bullet keeps adding clutter and visual noise across the body area",
                        "Sixth bullet keeps adding clutter and visual noise across the body area",
                        "Seventh bullet keeps adding clutter and visual noise across the body area",
                        "Eighth bullet keeps adding clutter and visual noise across the body area",
                        "Ninth bullet keeps adding clutter and visual noise across the body area",
                    ],
                }
            ]
        }
    )
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="pptx",
        text=dense,
        metadata={},
        context={"branding": None},
    )
    visual = report["dimensions"].get("visual_quality")
    assert visual is not None
    assert visual["score"] < 0.75
    assert visual["issues"]


def test_unified_framework_accepts_clean_visual_pptx() -> None:
    clean = json.dumps(
        {
            "slides": [
                {
                    "slide_type": "title",
                    "title": "Finance Transformation",
                    "subtitle": "Executive overview",
                    "badges": ["CFO", "6-month roadmap"],
                },
                {
                    "slide_type": "stat_cards",
                    "title": "Impact Metrics",
                    "stat_cards": [
                        {"stat": "14", "label": "Process Steps", "description": "Current end-to-end workflow.", "fill": "dark"},
                        {"stat": "5", "label": "Teams", "description": "Groups involved in delivery.", "fill": "mid_dark"},
                        {"stat": "3", "label": "Systems", "description": "Core platforms in scope.", "fill": "gray"},
                    ],
                },
            ]
        }
    )
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="pptx",
        text=clean,
        metadata={},
        context={"branding": None},
    )
    visual = report["dimensions"].get("visual_quality")
    assert visual is not None
    assert visual["score"] >= 0.9


def test_narrative_coherence_flags_heading_only_skeleton() -> None:
    skeleton = "\n".join([
        "# Executive Summary",
        "# Approach",
        "# Next Steps",
    ])
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="docx",
        text=skeleton,
        metadata={},
        context={"branding": None},
    )
    narrative = report["dimensions"].get("narrative_coherence")
    assert narrative is not None
    assert narrative["score"] < 0.75
    assert narrative["issues"]
    assert any("paragraph" in str(issue).lower() or "short" in str(issue).lower() for issue in narrative["issues"])


def test_narrative_coherence_flags_bullet_only_document() -> None:
    bullets_only = "\n".join([
        "- Step one: analyze",
        "- Step two: design",
        "- Step three: implement",
        "- Step four: validate",
    ] * 3)
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="docx",
        text=bullets_only,
        metadata={},
        context={"branding": None},
    )
    narrative = report["dimensions"].get("narrative_coherence")
    assert narrative is not None
    assert narrative["score"] < 0.75
    assert narrative["remediation_hint"]


def test_narrative_coherence_accepts_structured_narrative() -> None:
    rich = "\n\n".join([
        "# Executive Summary",
        (
            "The finance transformation program addresses persistent gaps in month-end close "
            "and forecasting. We examined the current workflow, interviewed stakeholders across "
            "controllership and FP&A, and benchmarked against peer institutions to establish a "
            "credible baseline. Therefore, this narrative sets the context for the roadmap that follows."
        ),
        "# Current State",
        (
            "However, several processes still rely on manual reconciliations and spreadsheet rollups. "
            "These controls introduce both risk and cycle time that compress the window available for "
            "analysis. Moreover, the fragmented toolchain prevents a consistent source of truth, which "
            "makes variance explanation slow. Consequently, leadership lacks timely insight during the close."
        ),
        "# Target State",
        (
            "The future state consolidates reporting onto a unified platform and automates the "
            "reconciliation backbone. Finally, as a result of those changes, close cycle time drops "
            "and forecast accuracy rises, giving the executive team the confidence to act faster."
        ),
    ])
    fw = UnifiedQualityFramework()
    report = fw.evaluate_deliverable(
        output_type="docx",
        text=rich,
        metadata={},
        context={"branding": None},
    )
    narrative = report["dimensions"].get("narrative_coherence")
    assert narrative is not None
    assert narrative["score"] >= 0.9
    assert not narrative["issues"]
