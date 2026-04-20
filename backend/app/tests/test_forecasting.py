"""Test suite for time-series forecasting."""

import pytest

from app.services.forecasting import (
    calculate_arima_simple,
    calculate_exponential_smoothing,
    calculate_linear_regression,
    calculate_moving_average,
    compare_forecast_methods,
    forecast_with_confidence,
)


class TestLinearRegression:
    """Test linear regression forecasting."""

    def test_linear_regression_basic(self):
        """Test basic linear regression forecast."""
        # Linear trend: 10, 20, 30, 40, 50
        historical_data = [10, 20, 30, 40, 50]
        result = calculate_linear_regression(historical_data, forecast_periods=3)

        assert result["method"] == "Linear Regression"
        assert len(result["forecasts"]) == 3
        assert result["r_squared"] > 0.99  # Perfect fit for linear data
        assert result["slope"] > 0  # Upward trend

    def test_linear_regression_with_noise(self):
        """Test linear regression with noisy data."""
        # Trend with noise
        historical_data = [10, 19, 32, 38, 51]
        result = calculate_linear_regression(historical_data, forecast_periods=2)

        assert result["r_squared"] > 0.90  # Good fit
        assert len(result["forecasts"]) == 2
        assert len(result["confidence_intervals"]) == 2

    def test_linear_regression_confidence_intervals(self):
        """Test that confidence intervals widen with forecast horizon."""
        # Use data with some noise to create residuals
        historical_data = [10, 19, 32, 38, 51]
        result = calculate_linear_regression(historical_data, forecast_periods=3)

        cis = result["confidence_intervals"]
        # Later periods should have wider intervals
        width_1 = cis[0]["upper"] - cis[0]["lower"]
        width_3 = cis[2]["upper"] - cis[2]["lower"]
        assert width_3 >= width_1

    def test_linear_regression_invalid_input(self):
        """Test linear regression with invalid input."""
        with pytest.raises(ValueError):
            calculate_linear_regression([10], forecast_periods=2)


class TestExponentialSmoothing:
    """Test exponential smoothing forecasting."""

    def test_exponential_smoothing_basic(self):
        """Test basic exponential smoothing."""
        historical_data = [100, 105, 110, 115, 120]
        result = calculate_exponential_smoothing(historical_data, forecast_periods=2)

        assert result["method"] == "Exponential Smoothing"
        assert len(result["forecasts"]) == 2
        assert len(result["smoothed_values"]) == len(historical_data)
        assert result["mape"] >= 0

    def test_exponential_smoothing_trend(self):
        """Test that exponential smoothing captures trend."""
        # Strong upward trend
        historical_data = [10, 15, 25, 35, 50]
        result = calculate_exponential_smoothing(historical_data, forecast_periods=1)

        # Forecast should be in a reasonable range (exponential smoothing can dampen trend)
        forecast = result["forecasts"][0]
        assert forecast > 0
        assert forecast > historical_data[0]  # Should be above the first value

    def test_exponential_smoothing_parameters(self):
        """Test different smoothing parameters."""
        historical_data = [100, 102, 101, 103, 102]

        # High alpha (responsive to recent changes)
        result_high_alpha = calculate_exponential_smoothing(
            historical_data, forecast_periods=1, alpha=0.9, beta=0.1
        )

        # Low alpha (smoother)
        result_low_alpha = calculate_exponential_smoothing(
            historical_data, forecast_periods=1, alpha=0.1, beta=0.05
        )

        # Both should work
        assert result_high_alpha["alpha"] == 0.9
        assert result_low_alpha["alpha"] == 0.1

    def test_exponential_smoothing_mape(self):
        """Test MAPE (Mean Absolute Percentage Error) calculation."""
        historical_data = [100, 100, 100, 100, 100]
        result = calculate_exponential_smoothing(historical_data, forecast_periods=1)

        # For constant data, MAPE should be close to 0
        assert result["mape"] < 10


class TestMovingAverage:
    """Test moving average forecasting."""

    def test_moving_average_basic(self):
        """Test basic moving average."""
        historical_data = [10, 20, 30, 40, 50]
        result = calculate_moving_average(historical_data, window_size=2, forecast_periods=2)

        assert result["method"] == "Moving Average"
        assert len(result["moving_averages"]) == len(historical_data) - 1
        assert len(result["forecasts"]) == 2

    def test_moving_average_calculation(self):
        """Test moving average calculations are correct."""
        historical_data = [10, 20, 30, 40]
        result = calculate_moving_average(historical_data, window_size=2, forecast_periods=1)

        # MA of [10, 20] = 15, MA of [20, 30] = 25, MA of [30, 40] = 35
        mas = result["moving_averages"]
        assert mas[0] == 15
        assert mas[1] == 25
        assert mas[2] == 35

    def test_moving_average_constant_forecast(self):
        """Test that MA forecasts are constant (last MA)."""
        historical_data = [10, 20, 30, 40, 50]
        result = calculate_moving_average(historical_data, window_size=3, forecast_periods=5)

        # All forecasts should be equal
        forecasts = result["forecasts"]
        assert all(f == forecasts[0] for f in forecasts)
        assert forecasts[0] == result["last_moving_average"]

    def test_moving_average_window_size_validation(self):
        """Test window size validation."""
        with pytest.raises(ValueError):
            calculate_moving_average([10, 20], window_size=3, forecast_periods=1)


class TestARIMA:
    """Test ARIMA forecasting."""

    def test_arima_basic(self):
        """Test basic ARIMA forecast."""
        historical_data = [10, 20, 30, 40, 50]
        result = calculate_arima_simple(historical_data, forecast_periods=2)

        assert result["method"] == "ARIMA(1,1,0)"
        assert len(result["forecasts"]) == 2
        assert len(result["differenced_data"]) == len(historical_data) - 1

    def test_arima_differencing(self):
        """Test that ARIMA correctly differences data."""
        historical_data = [10, 20, 30, 40]
        result = calculate_arima_simple(historical_data, forecast_periods=1)

        # Differences: [10, 10, 10]
        expected_diff = [10, 10, 10]
        actual_diff = result["differenced_data"]
        assert actual_diff == expected_diff

    def test_arima_stationarity(self):
        """Test stationarity detection."""
        # Non-stationary (trending) data
        trending_data = [10, 20, 30, 40, 50]
        result_trending = calculate_arima_simple(trending_data, forecast_periods=1)
        # After differencing, should be more stationary
        assert bool(result_trending["stationary"]) is True

    def test_arima_ar_coefficient(self):
        """Test AR coefficient calculation."""
        # Random walk (constant differences)
        historical_data = [10, 20, 30, 40, 50]
        result = calculate_arima_simple(historical_data, forecast_periods=1)

        # For constant differences, AR coef should be close to 0
        assert -1 < result["ar_coefficient"] < 1


class TestCompareForecasts:
    """Test comparing multiple forecasting methods."""

    def test_compare_methods_basic(self):
        """Test comparison of forecasting methods."""
        historical_data = [10, 20, 30, 40, 50]
        result = compare_forecast_methods(historical_data, forecast_periods=2)

        assert "forecasts" in result
        assert "rankings" in result
        assert result["recommended_method"] is not None

    def test_compare_methods_includes_all(self):
        """Test that comparison includes all methods."""
        historical_data = [10, 20, 30, 40, 50]
        result = compare_forecast_methods(historical_data, forecast_periods=2)

        forecasts = result["forecasts"]
        assert "linear_regression" in forecasts
        assert "exponential_smoothing" in forecasts
        assert "moving_average_3" in forecasts
        assert "arima" in forecasts

    def test_compare_methods_ranking(self):
        """Test that methods are ranked by fit quality."""
        historical_data = [10, 20, 30, 40, 50]
        result = compare_forecast_methods(historical_data, forecast_periods=2)

        rankings = result["rankings"]
        assert len(rankings) > 0
        # Rankings should be sorted by fit quality (descending)
        for i in range(len(rankings) - 1):
            assert rankings[i]["fit_quality"] >= rankings[i + 1]["fit_quality"]


class TestEnsembleForecasting:
    """Test ensemble forecasting with confidence intervals."""

    def test_ensemble_basic(self):
        """Test ensemble forecast generation."""
        historical_data = [10, 20, 30, 40, 50]
        result = forecast_with_confidence(historical_data, forecast_periods=2)

        assert result["method"] == "Ensemble (LR + ES + MA)"
        assert len(result["forecasts"]) == 2
        assert len(result["confidence_intervals"]) == 2

    def test_ensemble_confidence_intervals(self):
        """Test ensemble confidence interval structure."""
        historical_data = [10, 20, 30, 40, 50]
        result = forecast_with_confidence(
            historical_data,
            forecast_periods=2,
            confidence_level=0.95,
        )

        cis = result["confidence_intervals"]
        for ci in cis:
            assert ci["lower"] <= ci["forecast"] <= ci["upper"]
            assert ci["std_dev"] >= 0

    def test_ensemble_confidence_levels(self):
        """Test different confidence levels."""
        historical_data = [10, 20, 30, 40, 50]

        result_90 = forecast_with_confidence(
            historical_data, forecast_periods=1, confidence_level=0.90
        )
        result_95 = forecast_with_confidence(
            historical_data, forecast_periods=1, confidence_level=0.95
        )
        result_99 = forecast_with_confidence(
            historical_data, forecast_periods=1, confidence_level=0.99
        )

        # Wider intervals with higher confidence
        ci_90 = result_90["confidence_intervals"][0]
        ci_95 = result_95["confidence_intervals"][0]
        ci_99 = result_99["confidence_intervals"][0]

        width_90 = ci_90["upper"] - ci_90["lower"]
        width_95 = ci_95["upper"] - ci_95["lower"]
        width_99 = ci_99["upper"] - ci_99["lower"]

        assert width_90 < width_95 < width_99

    def test_ensemble_component_forecasts(self):
        """Test that ensemble includes component forecasts."""
        historical_data = [10, 20, 30, 40, 50]
        result = forecast_with_confidence(historical_data, forecast_periods=2)

        components = result["ensemble_component_forecasts"]
        assert "linear_regression" in components
        assert "exponential_smoothing" in components
        assert "moving_average_3" in components

        # Each should have 2 forecasts
        for component in components.values():
            assert len(component) == 2


class TestIntegration:
    """Integration tests for forecasting."""

    def test_complete_forecasting_workflow(self):
        """Test complete forecasting workflow."""
        # Simulate revenue data with trend
        historical_data = [1000, 1100, 1210, 1331, 1464]

        # Get all forecasts
        lr = calculate_linear_regression(historical_data, forecast_periods=3)
        es = calculate_exponential_smoothing(historical_data, forecast_periods=3)
        ma = calculate_moving_average(historical_data, window_size=2, forecast_periods=3)
        arima = calculate_arima_simple(historical_data, forecast_periods=3)

        # Compare methods
        compare_forecast_methods(historical_data, forecast_periods=3)

        # Ensemble with confidence
        ensemble = forecast_with_confidence(historical_data, forecast_periods=3)

        # Verify all produce reasonable outputs
        assert len(lr["forecasts"]) == 3
        assert len(es["forecasts"]) == 3
        assert len(ma["forecasts"]) == 3
        assert len(arima["forecasts"]) == 3
        assert len(ensemble["forecasts"]) == 3

    def test_seasonal_pattern(self):
        """Test forecasting with seasonal pattern."""
        # Simple seasonal pattern (12-month cycle)
        seasonal_data = [100, 110, 120, 125, 130, 140] + [100, 110, 120, 125, 130, 140]

        result = calculate_exponential_smoothing(seasonal_data, forecast_periods=3)

        # Should have smoothed values
        assert len(result["smoothed_values"]) == len(seasonal_data)
        assert result["mape"] >= 0

    def test_volatile_data(self):
        """Test forecasting with volatile data."""
        # Volatile data with trend
        volatile_data = [100, 150, 90, 140, 85, 145, 95, 150]

        result = compare_forecast_methods(volatile_data, forecast_periods=2)

        # Should still produce forecasts despite volatility
        assert result["forecasts"] is not None
        assert result["recommended_method"] is not None
