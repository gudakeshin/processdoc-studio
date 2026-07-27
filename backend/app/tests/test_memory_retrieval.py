"""Unit tests for memory retrieval, compaction, and consent logic."""

from __future__ import annotations

import pytest

from app.services.retrieval import (
    TieredContextEngine,
    _BM25Index,
    _build_bm25_index,
    _tokenize,
)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_lowercases_and_splits_on_non_alphanumeric(self):
        assert _tokenize("Hello World") == ["hello", "world"]
        assert _tokenize("test-case") == ["test", "case"]
        assert _tokenize("foo_bar.baz") == ["foo", "bar", "baz"]

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_numbers_preserved(self):
        toks = _tokenize("ISO 9001")
        assert "iso" in toks
        assert "9001" in toks


# ---------------------------------------------------------------------------
# BM25 index construction
# ---------------------------------------------------------------------------

class TestBuildBM25Index:
    def test_empty_corpus(self):
        idx = _build_bm25_index([])
        assert idx.tokenized == []
        assert idx.avgdl == 0.0
        assert idx.df == {}

    def test_single_chunk(self):
        idx = _build_bm25_index(["hello world"])
        assert idx.dl == [2]
        assert idx.avgdl == 2.0
        assert idx.df["hello"] == 1

    def test_document_frequency_counts_unique_terms(self):
        idx = _build_bm25_index(["hello world", "hello foo"])
        assert idx.df["hello"] == 2  # appears in both docs
        assert idx.df["world"] == 1
        assert idx.df["foo"] == 1

    def test_avgdl(self):
        idx = _build_bm25_index(["a b", "a b c d"])  # dl=[2,4], avg=3
        assert idx.avgdl == 3.0


# ---------------------------------------------------------------------------
# BM25 scoring
# ---------------------------------------------------------------------------

class TestBM25Scores:
    def test_empty_corpus_returns_empty(self):
        engine = TieredContextEngine()
        idx = _build_bm25_index([])
        assert engine._bm25_scores(idx, "query") == []

    def test_relevant_chunk_scores_higher(self):
        engine = TieredContextEngine()
        chunks = [
            "procurement approval workflow process",
            "quarterly earnings dividends shareholders",
            "vendor procurement selection approval steps",
        ]
        idx = _build_bm25_index(chunks)
        scores = engine._bm25_scores(idx, "procurement approval")
        assert scores[0] > scores[1]
        assert scores[2] > scores[1]

    def test_zero_score_for_no_overlap(self):
        engine = TieredContextEngine()
        idx = _build_bm25_index(["apple orange", "banana grape"])
        scores = engine._bm25_scores(idx, "procurement")
        assert all(s == 0.0 for s in scores)

    def test_backward_compat_accepts_list_of_str(self):
        engine = TieredContextEngine()
        chunks = ["hello world", "foo bar baz"]
        scores = engine._bm25_scores(chunks, "hello")
        assert len(scores) == 2
        assert scores[0] > scores[1]

    def test_cached_index_matches_inline_index(self):
        engine = TieredContextEngine()
        chunks = ["document about approval", "something else entirely"]
        idx = _build_bm25_index(chunks)
        scores_cached = engine._bm25_scores(idx, "approval")
        scores_inline = engine._bm25_scores(chunks, "approval")
        assert scores_cached == scores_inline


# ---------------------------------------------------------------------------
# Multi-query max
# ---------------------------------------------------------------------------

class TestMultiQueryMax:
    def test_takes_max_over_variants(self):
        engine = TieredContextEngine()
        chunks = [
            "procurement workflow",
            "best practices for document review standards",
        ]
        idx = _build_bm25_index(chunks)
        single = engine._bm25_scores(idx, "procurement")
        multi = engine._multi_query_max(idx, ["procurement", "best practices standards frameworks"])
        # chunk 1 should score higher with multi-query than single
        assert multi[1] > single[1]

    def test_empty_queries_returns_zeros(self):
        engine = TieredContextEngine()
        idx = _build_bm25_index(["hello", "world"])
        assert engine._multi_query_max(idx, []) == [0.0, 0.0]

    def test_single_query_equals_bm25_scores(self):
        engine = TieredContextEngine()
        chunks = ["foo bar", "baz qux"]
        idx = _build_bm25_index(chunks)
        assert engine._multi_query_max(idx, ["foo"]) == engine._bm25_scores(idx, "foo")


# ---------------------------------------------------------------------------
# MMR selection
# ---------------------------------------------------------------------------

class TestMMRSelect:
    def test_selects_relevant_chunks(self):
        engine = TieredContextEngine()
        chunks = [
            "procurement vendor selection process",
            "quarterly financial report analysis",
            "vendor approval procurement steps",
        ]
        idx = _build_bm25_index(chunks)
        scores = engine._bm25_scores(idx, "procurement vendor")
        candidates = sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True)[:3]
        selected = engine._mmr_select(candidates, chunks, max_chars=10000)
        # relevant chunks (0 and 2) should be preferred over unrelated (1)
        assert 0 in selected or 2 in selected

    def test_respects_char_budget(self):
        engine = TieredContextEngine()
        chunks = ["x" * 600] * 10
        candidates = [(i, 1.0) for i in range(10)]
        selected = engine._mmr_select(candidates, chunks, max_chars=1000)
        total_chars = sum(len(chunks[i]) for i in selected)
        # should stop once budget is met
        assert total_chars >= 1000
        assert len(selected) <= 2  # 600*2 = 1200 >= 1000

    def test_empty_candidates(self):
        engine = TieredContextEngine()
        assert engine._mmr_select([], ["chunk"], max_chars=1000) == []


# ---------------------------------------------------------------------------
# Auto summary deduplication
# ---------------------------------------------------------------------------

class TestAutoSummary:
    def test_deduplicates_repeated_events(self):
        items = [
            "qa_outcome: formatting check passed",
            "qa_outcome: formatting check passed",
            "qa_outcome: formatting check passed",
            "guardrail_outcome: no PII detected",
        ]
        summary = TieredContextEngine._auto_summary(items, max_items=8)
        assert summary.count("formatting check passed") == 1
        assert "no PII detected" in summary

    def test_empty_returns_empty_string(self):
        assert TieredContextEngine._auto_summary([]) == ""

    def test_respects_max_chars(self):
        items = ["item content " * 20 for _ in range(20)]
        result = TieredContextEngine._auto_summary(items, max_chars=300)
        assert len(result) <= 300

    def test_keeps_most_recent_items(self):
        items = [f"event_{i}" for i in range(20)]
        summary = TieredContextEngine._auto_summary(items, max_items=3)
        # Should include the last 3 unique items
        assert "event_19" in summary
        assert "event_18" in summary
        assert "event_17" in summary
        assert "event_0" not in summary


# ---------------------------------------------------------------------------
# Context collapse (Tier 4)
# ---------------------------------------------------------------------------

class TestContextCollapse:
    def test_proportional_caps_scale_with_char_cap(self):
        sections = {
            "ObjectiveNow": "o" * 2000,
            "NonNegotiables": "n" * 4000,
            "WhatChanged": "w" * 2000,
            "Evidence": "e" * 8000,
            "KnownFailures": "k" * 2000,
        }
        collapsed_32k, _, _ = TieredContextEngine._context_collapse(sections, char_cap=32000)
        collapsed_8k, _, _ = TieredContextEngine._context_collapse(sections, char_cap=8000)
        # At 32K the evidence cap should be ~4x that of 8K
        assert len(collapsed_32k["Evidence"]) > len(collapsed_8k["Evidence"])

    def test_output_within_hard_cap(self):
        sections = {
            "ObjectiveNow": "o" * 3000,
            "NonNegotiables": "n" * 5000,
            "WhatChanged": "w" * 4000,
            "Evidence": "e" * 10000,
            "KnownFailures": "k" * 3000,
        }
        char_cap = 8000
        collapsed, applied, _ = TieredContextEngine._context_collapse(sections, char_cap=char_cap)
        assembled = (
            f"## ObjectiveNow\n{collapsed['ObjectiveNow']}\n\n"
            f"## NonNegotiables\n{collapsed['NonNegotiables']}\n\n"
            f"## WhatChanged\n{collapsed['WhatChanged']}\n\n"
            f"## Evidence\n{collapsed['Evidence']}\n\n"
            f"## KnownFailures\n{collapsed['KnownFailures']}"
        )
        hard_cap = max(2000, int(char_cap * 0.55))
        assert len(assembled) <= hard_cap + 200  # small slack for section headers
        assert applied is True

    def test_always_returns_applied_true(self):
        _, applied, _ = TieredContextEngine._context_collapse(
            {"ObjectiveNow": "x", "NonNegotiables": "y", "WhatChanged": "z", "Evidence": "e", "KnownFailures": "k"},
            char_cap=32000,
        )
        assert applied is True


# ---------------------------------------------------------------------------
# assemble_v2
# ---------------------------------------------------------------------------

class TestAssembleV2:
    def test_budget_respected(self):
        engine = TieredContextEngine()
        bundle = engine.assemble_v2(
            None,
            "instruction",
            run_memory_events=[
                {"event_type": "qa_outcome", "payload": {"summary": "x" * 200}}
                for _ in range(300)
            ],
            char_cap=8000,
        )
        assert len(bundle.text) <= 8000

    def test_deterministic_output(self):
        engine = TieredContextEngine()
        events = [{"event_type": "artifact_summary", "payload": {"summary": "Generated SOP narrative"}}]
        profile = {"non_negotiables": ["Use approved template"]}
        b1 = engine.assemble_v2(None, "Build SOP", run_memory_events=events, project_profile=profile, char_cap=4000)
        b2 = engine.assemble_v2(None, "Build SOP", run_memory_events=events, project_profile=profile, char_cap=4000)
        assert b1.text == b2.text

    def test_metadata_has_required_keys(self):
        engine = TieredContextEngine()
        bundle = engine.assemble_v2(None, "test instruction", char_cap=4000)
        assert bundle.metadata is not None
        for key in ("dropped_items", "compaction_tiers_applied", "context_provenance", "section_sizes"):
            assert key in bundle.metadata

    def test_non_negotiables_appear_before_ltm(self):
        engine = TieredContextEngine()
        bundle = engine.assemble_v2(
            None,
            "test",
            project_profile={
                "non_negotiables": ["MANDATORY_CONSTRAINT_ALPHA"],
                "long_term_items": ["fact:key=OPTIONAL_FACT_BETA"],
            },
            char_cap=16000,
        )
        assert "MANDATORY_CONSTRAINT_ALPHA" in bundle.text
        nonneg_pos = bundle.text.find("MANDATORY_CONSTRAINT_ALPHA")
        ltm_pos = bundle.text.find("OPTIONAL_FACT_BETA")
        # Non-negotiables section comes before LTM in the assembled text
        assert nonneg_pos < ltm_pos or ltm_pos == -1

    def test_ltm_gets_space_after_compact_non_negs(self):
        """Long-term items should still fit when non_negotiables are small."""
        engine = TieredContextEngine()
        bundle = engine.assemble_v2(
            None,
            "instruction",
            project_profile={
                "non_negotiables": ["Short constraint."],
                "long_term_items": ["fact:important_key=CURATED_VALUE"],
            },
            char_cap=8000,
        )
        assert "CURATED_VALUE" in bundle.text

    def test_user_preference_lines_included(self):
        engine = TieredContextEngine()
        bundle = engine.assemble_v2(
            None,
            "Write an SOP",
            project_profile={"user_preference_lines": ["USE_UK_SPELLING"]},
            char_cap=8000,
        )
        assert "USE_UK_SPELLING" in bundle.text

    def test_event_types_populate_what_changed(self):
        engine = TieredContextEngine()
        bundle = engine.assemble_v2(
            None,
            "x",
            run_memory_events=[
                {"event_type": "artifact_summary", "payload": {"summary": "ARTIFACT_MARKER"}},
            ],
            char_cap=8000,
        )
        assert "ARTIFACT_MARKER" in bundle.text


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

class TestMemoryConsent:
    def test_allowed_default(self):
        from app.services.memory_consent import memory_item_allowed_for_use

        class Item:
            consent_state = "allowed"
            principal_id = None

        ok, reason = memory_item_allowed_for_use(None, "p1", Item(), respect_consent=True, enforce_consent_ledger=False)
        assert ok is True
        assert reason == ""

    def test_denied_consent_field(self):
        from app.services.memory_consent import memory_item_allowed_for_use

        class Item:
            consent_state = "denied"
            principal_id = None

        ok, reason = memory_item_allowed_for_use(None, "p1", Item(), respect_consent=True, enforce_consent_ledger=False)
        assert ok is False
        assert reason == "consent_field"

    def test_restricted_consent_field(self):
        from app.services.memory_consent import memory_item_allowed_for_use

        class Item:
            consent_state = "restricted"
            principal_id = None

        ok, reason = memory_item_allowed_for_use(None, "p1", Item(), respect_consent=True, enforce_consent_ledger=False)
        assert ok is False
        assert reason == "consent_field"

    def test_denied_bypassed_when_respect_consent_false(self):
        from app.services.memory_consent import memory_item_allowed_for_use

        class Item:
            consent_state = "denied"
            principal_id = None

        ok, _ = memory_item_allowed_for_use(None, "p1", Item(), respect_consent=False, enforce_consent_ledger=False)
        assert ok is True

    def test_empty_consent_state_treated_as_allowed(self):
        from app.services.memory_consent import memory_item_allowed_for_use

        class Item:
            consent_state = ""
            principal_id = None

        ok, _ = memory_item_allowed_for_use(None, "p1", Item(), respect_consent=True, enforce_consent_ledger=False)
        assert ok is True


# ---------------------------------------------------------------------------
# merge_long_term_items_into_profile
# ---------------------------------------------------------------------------

class TestMergeProfile:
    def test_replaces_stale_profile_items(self):
        from app.services.memory_context import merge_long_term_items_into_profile

        profile: dict = {"long_term_items": ["stale:old=bad_value"]}

        class Row:
            memory_type = "fact"
            key = "fresh_key"
            value = "fresh_value"
            consent_state = "allowed"

        inj, skip, lskip = merge_long_term_items_into_profile(profile, [Row()], respect_consent=True)
        assert inj == 1
        assert skip == 0
        assert profile["long_term_items"] == ["fact:fresh_key=fresh_value"]

    def test_clears_stale_when_all_denied(self):
        from app.services.memory_context import merge_long_term_items_into_profile

        profile: dict = {"long_term_items": ["stale:key=val"]}

        class Denied:
            memory_type = "fact"
            key = "k"
            value = "v"
            consent_state = "denied"

        inj, skip, _ = merge_long_term_items_into_profile(profile, [Denied()], respect_consent=True)
        assert inj == 0
        assert skip == 1
        assert "long_term_items" not in profile

    def test_clears_stale_when_empty_rows(self):
        from app.services.memory_context import merge_long_term_items_into_profile

        profile: dict = {"long_term_items": ["stale:key=val"]}
        inj, skip, _ = merge_long_term_items_into_profile(profile, [], respect_consent=True)
        assert inj == 0
        assert "long_term_items" not in profile

    def test_formats_as_type_key_value(self):
        from app.services.memory_context import merge_long_term_items_into_profile

        profile: dict = {}

        class Row:
            memory_type = "constraint"
            key = "audience"
            value = "c_suite"
            consent_state = "allowed"

        merge_long_term_items_into_profile(profile, [Row()], respect_consent=True)
        assert profile["long_term_items"] == ["constraint:audience=c_suite"]
