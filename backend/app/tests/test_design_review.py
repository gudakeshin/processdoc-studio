"""Phase C — unified design-review gate (arc + action titles + evidence)."""
from __future__ import annotations

from app.services.design_review import review_deck


def _contract() -> dict:
    return {
        "arc": "pyramid",
        "governing_thought": "Automating P2P frees finance capacity",
        "slides": [
            {"action_title": "Manual hand-offs add eleven days to every close",
             "suggested_visual": "big_number"},
            {"action_title": "Three levers collapse the reconciliation bottleneck",
             "suggested_visual": "column_cards"},
        ],
    }


def test_clean_deck_passes() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "big_number", "title": "Manual hand-offs add eleven days to every close"},
        {"slide_type": "column_cards", "title": "Three levers collapse the reconciliation bottleneck"},
    ]
    report = review_deck(slides, process_model=None, storyline_contract=_contract())
    assert report["status"] == "pass", report["summary"]
    assert report["remediation_hints"] == []
    assert report["scores"]["arc_coherence"]["status"] == "pass"


def test_label_titles_flagged_with_prescriptive_hint() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "bullets", "title": "Overview"},
        {"slide_type": "bullets", "title": "Current State"},
    ]
    report = review_deck(slides, process_model=None, storyline_contract=None)
    assert report["status"] in ("warn", "fail")
    sources = {h["source"] for h in report["remediation_hints"]}
    assert "action_title" in sources
    # Hints must point at a specific slide and tell the model what to do.
    at_hints = [h for h in report["remediation_hints"] if h["source"] == "action_title"]
    assert all(h["slide_index"] > 0 for h in at_hints)
    assert any("action title" in h["instruction"].lower() for h in at_hints)


def test_unsupported_claim_flagged() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "big_number", "title": "We will save $5M in year one",
         "big_number": {"stat": "$5M"}},
    ]
    report = review_deck(slides, process_model={}, storyline_contract=None)
    sources = {h["source"] for h in report["remediation_hints"]}
    assert "evidence" in sources
    assert report["scores"]["evidence"]["unsupported"] >= 1


def test_missing_arc_beat_flagged() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "big_number", "title": "Manual hand-offs add eleven days to every close"},
        # second beat ("three levers ...") is absent
    ]
    report = review_deck(slides, process_model=None, storyline_contract=_contract())
    arc_hints = [h for h in report["remediation_hints"] if h["source"] == "arc_coherence"]
    assert arc_hints
    assert any("levers" in h["instruction"].lower() for h in arc_hints)


def test_arc_skipped_without_contract() -> None:
    slides = [{"slide_type": "big_number", "title": "Costs climb 18% without action"}]
    report = review_deck(slides, process_model=None, storyline_contract=None)
    assert report["scores"]["arc_coherence"]["status"] == "skip"


# ── visual fidelity ──────────────────────────────────────────────────────────

def _rich_contract() -> dict:
    return {
        "arc": "pyramid",
        "governing_thought": "Automating P2P frees finance capacity",
        "slides": [
            {"action_title": "Two forces define the competitive position",
             "suggested_visual": "two_by_two"},
            {"action_title": "Five stages compose the procurement value chain",
             "suggested_visual": "value_chain"},
        ],
    }


def test_visual_fidelity_passes_when_types_and_fields_match() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "two_by_two", "title": "Two forces define the competitive position",
         "quadrants": [{"label": "A"}, {"label": "B"}], "x_label": "x", "y_label": "y"},
        {"slide_type": "value_chain", "title": "Five stages compose the procurement value chain",
         "stages": [{"label": "S1"}, {"label": "S2"}]},
    ]
    report = review_deck(slides, process_model=None, storyline_contract=_rich_contract())
    assert report["scores"]["visual_fidelity"]["status"] == "pass"
    assert not any(h["source"] == "visual_fidelity" for h in report["remediation_hints"])


def test_visual_fidelity_flags_wrong_slide_type() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "column_cards", "title": "Two forces define the competitive position"},
        {"slide_type": "value_chain", "title": "Five stages compose the procurement value chain",
         "stages": [{"label": "S1"}, {"label": "S2"}]},
    ]
    report = review_deck(slides, process_model=None, storyline_contract=_rich_contract())
    vhints = [h for h in report["remediation_hints"] if h["source"] == "visual_fidelity"]
    assert len(vhints) == 1
    assert vhints[0]["slide_index"] == 2  # 1-based deck index of the column_cards slide
    assert "two_by_two" in vhints[0]["instruction"]
    assert report["status"] in ("warn", "fail")


def test_visual_fidelity_flags_missing_figure_fields() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "two_by_two", "title": "Two forces define the competitive position"},  # no quadrants
    ]
    report = review_deck(slides, process_model=None, storyline_contract=_rich_contract())
    vhints = [h for h in report["remediation_hints"] if h["source"] == "visual_fidelity"]
    assert len(vhints) == 1
    assert "quadrants" in vhints[0]["instruction"]
    assert "missing" in vhints[0]["instruction"].lower()


def test_visual_fidelity_ignores_non_rich_visuals() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "bullets", "title": "Manual hand-offs add eleven days to every close"},
        {"slide_type": "table", "title": "Three levers collapse the reconciliation bottleneck"},
    ]
    # _contract() suggests big_number / column_cards — neither is a rich visual.
    report = review_deck(slides, process_model=None, storyline_contract=_contract())
    assert report["scores"]["visual_fidelity"]["status"] == "skip"
    assert not any(h["source"] == "visual_fidelity" for h in report["remediation_hints"])


def test_visual_fidelity_skipped_without_contract() -> None:
    slides = [{"slide_type": "two_by_two", "title": "Costs climb 18% without action"}]
    report = review_deck(slides, process_model=None, storyline_contract=None)
    assert report["scores"]["visual_fidelity"]["status"] == "skip"
    assert not any(h["source"] == "visual_fidelity" for h in report["remediation_hints"])


# ── internal-markup leak ─────────────────────────────────────────────────────

def test_markup_leak_flags_raw_wiki_tokens() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "process_flow", "title": "Knowledge ingestion flows end to end",
         "process_flow": {"steps": [
             {"label": "Inter-page links: [[page_id|Human Title]]"},
             {"label": "Audit trail appended to log.md"},
         ]}},
    ]
    report = review_deck(slides, process_model=None, storyline_contract=None)
    mhints = [h for h in report["remediation_hints"] if h["source"] == "markup_leak"]
    assert len(mhints) == 1
    assert mhints[0]["slide_index"] == 2
    assert "humanize" in mhints[0]["instruction"].lower()
    assert report["scores"]["markup_leak"]["status"] == "fail"
    assert report["status"] == "fail"


def test_markup_leak_clean_when_humanized() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "process_flow", "title": "Knowledge ingestion flows end to end",
         "process_flow": {"steps": [
             {"label": "Inter-page links weave sources into a connected corpus"},
             {"label": "Audit trail is timestamped and fully traceable"},
         ]}},
    ]
    report = review_deck(slides, process_model=None, storyline_contract=None)
    assert report["scores"]["markup_leak"]["status"] == "pass"
    assert not any(h["source"] == "markup_leak" for h in report["remediation_hints"])


def test_review_document_flags_missing_arc_beat() -> None:
    from app.services.design_review import review_document

    md = (
        "# Executive Brief\n\n"
        "## Manual hand-offs add eleven days to every close\n\n"
        "Evidence here.\n"
    )
    report = review_document(md, process_model=None, storyline_contract=_contract())
    arc_hints = [h for h in report["remediation_hints"] if h["source"] == "arc_coherence"]
    assert arc_hints
    assert report["status"] in ("warn", "fail")


def test_review_document_passes_aligned_sections() -> None:
    from app.services.design_review import review_document

    md = (
        "# Executive Brief\n\n"
        "## Manual hand-offs add eleven days to every close\n\n"
        "Cycle time evidence.\n\n"
        "## Three levers collapse the reconciliation bottleneck\n\n"
        "Governance, gates, automation.\n"
    )
    report = review_document(md, process_model=None, storyline_contract=_contract())
    assert report["scores"]["arc_coherence"]["status"] == "pass"
