"""Tests for Excel model composition retry mechanism (Cowork Tier 1)."""

import pytest
from unittest.mock import patch, MagicMock
import time

from app.services.excel_model_composer import (
    _exponential_backoff,
    compose_financial_model_with_retry,
    MAX_RETRY_ATTEMPTS,
)


class TestExponentialBackoff:
    """Test exponential backoff delay calculation."""

    def test_backoff_attempt_0(self):
        """First retry: 0.25 * 2^0 = 0.25 seconds."""
        delay = _exponential_backoff(0)
        assert delay == pytest.approx(0.25, abs=0.01)

    def test_backoff_attempt_1(self):
        """Second retry: min(1.5, 0.25 * 2^1) = 0.5 seconds."""
        delay = _exponential_backoff(1)
        assert delay == pytest.approx(0.5, abs=0.01)

    def test_backoff_attempt_2(self):
        """Third retry: min(1.5, 0.25 * 2^2) = 1.0 seconds."""
        delay = _exponential_backoff(2)
        assert delay == pytest.approx(1.0, abs=0.01)

    def test_backoff_attempt_3_capped(self):
        """Fourth retry: min(1.5, 0.25 * 2^3) = min(1.5, 2.0) = 1.5 seconds (capped)."""
        delay = _exponential_backoff(3)
        assert delay == pytest.approx(1.5, abs=0.01)

    def test_backoff_capped_at_max(self):
        """Backoff never exceeds 1.5 seconds."""
        for attempt in range(10):
            delay = _exponential_backoff(attempt)
            assert delay <= 1.5


class TestComposeFinancialModelWithRetry:
    """Test retry wrapper around compose_financial_model."""

    @patch("app.services.excel_model_composer.compose_financial_model")
    def test_retry_success_on_first_attempt(self, mock_compose):
        """Success on first attempt returns cells with None error."""
        mock_cells = [{"sheet": "Test", "row": 1, "col": 1}]
        mock_compose.return_value = mock_cells

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            periods=5,
        )

        assert cells == mock_cells
        assert error is None
        assert mock_compose.call_count == 1

    @patch("app.services.excel_model_composer.compose_financial_model")
    def test_retry_fails_immediately_on_validation_error(self, mock_compose):
        """ValidationError (non-transient) fails immediately."""
        mock_compose.side_effect = ValueError("Invalid periods: 0")

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            periods=0,
        )

        assert cells is None
        assert "Invalid periods" in error
        assert mock_compose.call_count == 1  # No retries

    @patch("app.services.excel_model_composer.compose_financial_model")
    @patch("time.sleep")
    def test_retry_succeeds_on_second_attempt_after_memory_error(self, mock_sleep, mock_compose):
        """Transient MemoryError triggers retry; succeeds on second attempt."""
        mock_cells = [{"sheet": "Test", "row": 1, "col": 1}]
        mock_compose.side_effect = [
            MemoryError("Out of memory"),
            mock_cells,
        ]

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            periods=5,
        )

        assert cells == mock_cells
        assert error is None
        assert mock_compose.call_count == 2  # First failed, second succeeded
        assert mock_sleep.called  # Backoff delay applied

    @patch("app.services.excel_model_composer.compose_financial_model")
    @patch("time.sleep")
    def test_retry_fails_after_max_attempts(self, mock_sleep, mock_compose):
        """Transient error fails after max retries."""
        mock_compose.side_effect = MemoryError("Out of memory")

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            periods=5,
            max_retries=3,
        )

        assert cells is None
        assert "Out of memory" in error
        assert mock_compose.call_count == 3  # All max retries attempted
        assert mock_sleep.call_count == 2  # Backoff delays between attempts

    @patch("app.services.excel_model_composer.compose_financial_model")
    @patch("time.sleep")
    def test_retry_treats_unknown_exception_as_transient(self, mock_sleep, mock_compose):
        """Unknown exception treated as transient; retries."""
        mock_cells = [{"sheet": "Test", "row": 1, "col": 1}]
        mock_compose.side_effect = [
            RuntimeError("Service timeout"),
            mock_cells,
        ]

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            periods=5,
        )

        assert cells == mock_cells
        assert error is None
        assert mock_compose.call_count == 2
        assert mock_sleep.called

    @patch("app.services.excel_model_composer.compose_financial_model")
    @patch("time.sleep")
    def test_retry_timeout_error_triggers_retry(self, mock_sleep, mock_compose):
        """TimeoutError (transient) triggers retry."""
        mock_cells = [{"sheet": "Test", "row": 1, "col": 1}]
        mock_compose.side_effect = [
            TimeoutError("Request timeout"),
            mock_cells,
        ]

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            periods=5,
        )

        assert cells == mock_cells
        assert error is None
        assert mock_compose.call_count == 2

    @patch("app.services.excel_model_composer.compose_financial_model")
    def test_retry_with_custom_max_retries(self, mock_compose):
        """Custom max_retries parameter respected."""
        mock_compose.side_effect = MemoryError("Out of memory")

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            periods=5,
            max_retries=1,
        )

        assert cells is None
        assert mock_compose.call_count == 1  # Only one attempt

    @patch("app.services.excel_model_composer.compose_financial_model")
    def test_retry_passes_all_parameters_to_compose(self, mock_compose):
        """All parameters passed correctly to compose_financial_model."""
        mock_cells = [{"sheet": "Test"}]
        mock_compose.return_value = mock_cells

        scenarios = [{"name": "Scenario 1"}]
        budget_data = {"Marketing": 10000}
        actuals = {1: {"revenue": 100000}}
        historical = [1.0, 2.0, 3.0]

        cells, error = compose_financial_model_with_retry(
            assumptions={"revenue": 1000000},
            scenarios=scenarios,
            budget_data=budget_data,
            actuals_by_period=actuals,
            historical_data=historical,
            periods=5,
        )

        assert cells == mock_cells
        mock_compose.assert_called_once_with(
            assumptions={"revenue": 1000000},
            scenarios=scenarios,
            budget_data=budget_data,
            actuals_by_period=actuals,
            historical_data=historical,
            periods=5,
        )

    @patch("app.services.excel_model_composer.compose_financial_model")
    @patch("time.sleep")
    def test_retry_backoff_timing_correct(self, mock_sleep, mock_compose):
        """Verify correct backoff delays between retries."""
        mock_compose.side_effect = MemoryError("Out of memory")

        with patch("app.services.excel_model_composer._exponential_backoff") as mock_backoff:
            mock_backoff.side_effect = [0.25, 0.5]

            cells, error = compose_financial_model_with_retry(
                assumptions={"revenue": 1000000},
                periods=5,
                max_retries=3,
            )

            # Verify backoff called for each retry
            assert mock_backoff.call_count == 2
            mock_backoff.assert_any_call(0)  # First retry
            mock_backoff.assert_any_call(1)  # Second retry

            # Verify sleep called with correct delays
            assert mock_sleep.call_count == 2
            mock_sleep.assert_any_call(0.25)
            mock_sleep.assert_any_call(0.5)
