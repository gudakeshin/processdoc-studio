"""
Tests for wiki operations with Cowork Tier 1 retry logic.

Tests the exponential backoff formula, retry behavior, transient vs non-transient
error classification, and end-to-end retry scenarios.
"""

from unittest.mock import patch

from app.services.wiki_operations import (
    classify_error,
    exponential_backoff,
    wiki_ingest_with_retry,
    wiki_lint_with_retry,
    wiki_query_with_retry,
)
from app.core.config import settings

# ===== Tier 1: Exponential Backoff Tests (5 tests) =====

class TestExponentialBackoff:
    """Test the exponential backoff formula: min(1.5, 0.25 * 2^attempt)"""

    def test_backoff_attempt_0(self):
        """Attempt 0 should be 0.25s"""
        assert exponential_backoff(0) == 0.25

    def test_backoff_attempt_1(self):
        """Attempt 1 should be 0.5s"""
        assert exponential_backoff(1) == 0.5

    def test_backoff_attempt_2(self):
        """Attempt 2 should be 1.0s"""
        assert exponential_backoff(2) == 1.0

    def test_backoff_attempt_3_capped(self):
        """Attempt 3 should be 1.5s (capped)"""
        assert exponential_backoff(3) == 1.5

    def test_backoff_capped_at_max(self):
        """All attempts >= 3 should be capped at 1.5s"""
        for attempt in range(3, 20):
            assert exponential_backoff(attempt) == 1.5


# ===== Error Classification Tests (4 tests) =====

class TestErrorClassification:
    """Test error classification (transient vs non-transient)"""

    def test_classify_timeout_as_transient(self):
        """TimeoutError should be transient"""
        error = TimeoutError("Request timeout")
        assert classify_error(error) == "transient"

    def test_classify_connection_error_as_transient(self):
        """ConnectionError should be transient"""
        error = ConnectionError("Connection reset")
        assert classify_error(error) == "transient"

    def test_classify_value_error_as_non_transient(self):
        """ValueError should be non-transient"""
        error = ValueError("Invalid data")
        assert classify_error(error) == "non_transient"

    def test_classify_key_error_as_non_transient(self):
        """KeyError should be non-transient"""
        error = KeyError("Missing field")
        assert classify_error(error) == "non_transient"


# ===== Wiki Ingest Retry Tests (5 tests) =====

class TestWikiIngestRetry:
    """Test wiki ingest with retry logic"""

    def test_ingest_success_on_first_attempt(self):
        """Ingest should succeed on first attempt"""
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('app.services.wiki_operations._update_wiki_pages') as mock_update, \
             patch('app.services.wiki_operations._update_wiki_index') as mock_index, \
             patch('app.services.wiki_operations._append_wiki_log') as mock_log:

            mock_parse.return_value = {"title": "Test", "content": "Content"}
            mock_update.return_value = {"created": 1, "updated": 0, "page_ids": ["p1"], "corrections": []}
            mock_index.return_value = {"page_count": 1}
            mock_log.return_value = "log_1"

            result, error = wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "http://example.com"},
                wiki_type="project",
                project_id="proj_1"
            )

            assert error is None
            assert result["pages_created"] == 1
            assert result["log_entry_id"] == "log_1"
            assert mock_parse.call_count == 1

    def test_ingest_fails_immediately_on_validation_error(self):
        """Ingest should fail immediately on ValueError (non-transient)"""
        with patch('app.services.wiki_operations._parse_source') as mock_parse:
            mock_parse.side_effect = ValueError("Invalid source data")

            result, error = wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "invalid"},
                wiki_type="project",
                project_id="proj_1"
            )

            assert result is None
            assert "Invalid source data" in error
            assert mock_parse.call_count == 1  # No retries

    def test_ingest_retries_on_timeout(self):
        """Ingest should retry on TimeoutError"""
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('app.services.wiki_operations._update_wiki_pages') as mock_update, \
             patch('app.services.wiki_operations._update_wiki_index') as mock_index, \
             patch('app.services.wiki_operations._append_wiki_log') as mock_log, \
             patch('time.sleep') as mock_sleep:

            # Fail twice, succeed on third attempt
            mock_parse.side_effect = [
                TimeoutError("First timeout"),
                TimeoutError("Second timeout"),
                {"title": "Test", "content": "Content"},
            ]
            mock_update.return_value = {"created": 1, "updated": 0, "page_ids": ["p1"], "corrections": []}
            mock_index.return_value = {"page_count": 1}
            mock_log.return_value = "log_1"

            result, error = wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "http://example.com"},
                wiki_type="project",
                project_id="proj_1",
                max_retries=3
            )

            assert error is None
            assert result["pages_created"] == 1
            assert mock_parse.call_count == 3
            assert mock_sleep.call_count == 2  # Two retries (after attempt 0 and 1)

    def test_ingest_fails_after_max_retries(self):
        """Ingest should fail after max retries"""
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('time.sleep'):

            mock_parse.side_effect = TimeoutError("Persistent timeout")

            result, error = wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "http://example.com"},
                wiki_type="project",
                project_id="proj_1",
                max_retries=3
            )

            assert result is None
            assert "Persistent timeout" in error
            assert mock_parse.call_count == 3  # All 3 attempts exhausted

    def test_ingest_backoff_timing(self):
        """Ingest should use correct exponential backoff timing"""
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('time.sleep') as mock_sleep:

            mock_parse.side_effect = TimeoutError("Timeout")

            result, error = wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "http://example.com"},
                wiki_type="project",
                project_id="proj_1",
                max_retries=3
            )

            # Should sleep with exponential backoff: 0.25s, 0.5s
            sleep_calls = mock_sleep.call_args_list
            assert len(sleep_calls) == 2
            assert sleep_calls[0][0][0] == 0.25  # First retry: 0.25s
            assert sleep_calls[1][0][0] == 0.5   # Second retry: 0.5s


# ===== Wiki Query Retry Tests (3 tests) =====

class TestWikiQueryRetry:
    """Test wiki query with retry logic"""

    def test_query_success_on_first_attempt(self):
        """Query should succeed on first attempt"""
        with patch('app.services.wiki_operations._get_wiki_index') as mock_index, \
             patch('app.services.wiki_operations._search_wiki_pages') as mock_search, \
             patch('app.services.wiki_operations._synthesize_answer') as mock_synth, \
             patch('app.services.wiki_operations._extract_citations') as mock_cite:

            mock_index.return_value = {"pages": []}
            mock_search.return_value = [{"id": "p1", "title": "Page 1"}]
            mock_synth.return_value = "The answer is..."
            mock_cite.return_value = ["p1"]

            result, error = wiki_query_with_retry(
                question="What is X?",
                wiki_type="project",
                project_id="proj_1"
            )

            assert error is None
            assert "answer" in result
            assert result["answer"] == "The answer is..."
            assert mock_search.call_count == 1

    def test_query_fails_immediately_on_missing_index(self):
        """Query should fail immediately if index is missing (non-transient)"""
        with patch('app.services.wiki_operations._get_wiki_index') as mock_index:
            mock_index.return_value = None

            result, error = wiki_query_with_retry(
                question="What is X?",
                wiki_type="project",
                project_id="proj_1"
            )

            assert result is None
            assert "not found" in error.lower()
            assert mock_index.call_count == 1

    def test_query_retries_on_connection_error(self):
        """Query should retry on ConnectionError"""
        with patch('app.services.wiki_operations._get_wiki_index') as mock_index, \
             patch('app.services.wiki_operations._search_wiki_pages') as mock_search, \
             patch('app.services.wiki_operations._synthesize_answer') as mock_synth, \
             patch('app.services.wiki_operations._extract_citations') as mock_cite, \
             patch('time.sleep'):

            mock_index.return_value = {"pages": []}
            mock_search.side_effect = [
                ConnectionError("Lost connection"),
                [{"id": "p1", "title": "Page 1"}],
            ]
            mock_synth.return_value = "The answer is..."
            mock_cite.return_value = ["p1"]

            result, error = wiki_query_with_retry(
                question="What is X?",
                wiki_type="project",
                project_id="proj_1",
                max_retries=2
            )

            assert error is None
            assert mock_search.call_count == 2


# ===== Wiki Lint Retry Tests (2 tests) =====

class TestWikiLintRetry:
    """Test wiki lint with retry logic"""

    def test_lint_success_on_first_attempt(self):
        """Lint should succeed on first attempt"""
        with patch('app.services.wiki_operations._evaluate_wiki_qa') as mock_qa, \
             patch('app.services.wiki_operations._append_wiki_log'):

            mock_qa.return_value = {
                "passed": True,
                "issues": [],
                "suggestions": [],
                "severity": "low",
                "summary": {"broken_links": 0, "orphaned_pages": 0, "missing_entities": 0, "total_issues": 0}
            }

            result, error = wiki_lint_with_retry(
                wiki_type="project",
                project_id="proj_1"
            )

            assert error is None
            assert result["issues_count"] == 0
            assert result["severity"] == "low"
            assert mock_qa.call_count == 1

    def test_lint_retries_on_transient_error(self):
        """Lint should retry on transient errors"""
        with patch('app.services.wiki_operations._evaluate_wiki_qa') as mock_qa, \
             patch('time.sleep'):

            mock_qa.side_effect = [
                TimeoutError("Search timeout"),
                {
                    "passed": True,
                    "issues": [],
                    "suggestions": [],
                    "severity": "low",
                    "summary": {"broken_links": 0, "orphaned_pages": 0, "missing_entities": 0, "total_issues": 0}
                },
            ]

            result, error = wiki_lint_with_retry(
                wiki_type="project",
                project_id="proj_1",
                max_retries=2
            )

            assert error is None
            assert mock_qa.call_count == 2


# ===== Integration Tests (5 tests) =====

class TestWikiRetryIntegration:
    """Integration tests for retry scenarios"""

    def test_retry_with_custom_max_attempts(self):
        """Should respect custom max_retries parameter"""
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('time.sleep'):

            mock_parse.side_effect = TimeoutError("Timeout")

            result, error = wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "http://example.com"},
                wiki_type="project",
                project_id="proj_1",
                max_retries=5
            )

            assert mock_parse.call_count == 5

    def test_retry_passes_all_parameters(self):
        """Retry should pass all parameters through to helper functions"""
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('app.services.wiki_operations._update_wiki_pages') as mock_update, \
             patch('app.services.wiki_operations._update_wiki_index') as mock_index, \
             patch('app.services.wiki_operations._append_wiki_log') as mock_log:

            mock_parse.return_value = {"title": "Test", "content": "Content"}
            mock_update.return_value = {"created": 1, "updated": 0, "page_ids": ["p1"], "corrections": []}
            mock_index.return_value = {"page_count": 1}
            mock_log.return_value = "log_1"

            wiki_ingest_with_retry(
                source_type="document",
                source_data={"filename": "test.pdf", "content": "..."},
                wiki_type="leading_practice",
                project_id=None,  # LP wiki
                max_retries=2
            )

            # Verify _append_wiki_log was called with correct parameters
            mock_log.assert_called_once()
            call_args = mock_log.call_args
            assert call_args[0][0] == "leading_practice"
            assert call_args[0][1] is None  # No project_id for LP
            assert call_args[0][2] == "ingest"

    def test_transient_classification_includes_message_matching(self):
        """classify_error should detect transient errors by message content"""
        error = Exception("Service unavailable")
        assert classify_error(error) == "transient"

        error = Exception("Rate limit exceeded")
        assert classify_error(error) == "transient"

    def test_non_transient_classification_includes_message_matching(self):
        """classify_error should detect non-transient errors by message content"""
        error = Exception("Validation failed")
        assert classify_error(error) == "non_transient"

        error = Exception("Schema mismatch")
        assert classify_error(error) == "non_transient"

    def test_retry_logs_attempts(self):
        """Retry operations should log each attempt (at least for warnings/errors)"""
        # This is tested implicitly by other tests, but we verify the logging calls
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('app.services.wiki_operations.logger') as mock_logger, \
             patch('time.sleep'):

            mock_parse.side_effect = [
                TimeoutError("First"),
                TimeoutError("Second"),
            ]

            wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "http://example.com"},
                max_retries=2
            )

            # Should have logged at least one warning about retry
            warning_calls = [c for c in mock_logger.warning.call_args_list if c]
            assert len(warning_calls) >= 1


class TestWikiEventedRebuild:
    def test_ingest_evented_rebuild_emits_event_and_skips_sync_when_fallback_off(self, monkeypatch):
        monkeypatch.setattr(settings, "wiki_evented_graph_rebuild_enabled", True)
        monkeypatch.setattr(settings, "wiki_evented_graph_rebuild_fallback_sync_enabled", False)
        with patch('app.services.wiki_operations._parse_source') as mock_parse, \
             patch('app.services.wiki_operations._update_wiki_pages') as mock_update, \
             patch('app.services.wiki_operations._append_wiki_log') as mock_log, \
             patch('app.services.wiki_ingest.emit_wiki_change_event') as mock_emit, \
             patch('app.services.wiki_graph.build_relationships_incremental') as mock_build:
            mock_parse.return_value = {"title": "Test", "content": "Content"}
            mock_update.return_value = {"created": 1, "updated": 0, "page_ids": ["p1"], "corrections": []}
            mock_log.return_value = "log_1"
            result, error = wiki_ingest_with_retry(
                source_type="url",
                source_data={"url": "http://example.com"},
                wiki_type="project",
                project_id="proj_1",
            )
            assert error is None
            assert result is not None
            mock_emit.assert_called_once()
            mock_build.assert_not_called()
