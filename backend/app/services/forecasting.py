"""Time-series forecasting service (ARIMA, exponential smoothing, regression)."""

from datetime import UTC, datetime
from typing import Any

import numpy as np
from scipy import stats


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


def calculate_linear_regression(
    historical_data: list[float],
    forecast_periods: int = 5,
) -> dict[str, Any]:
    """
    Forecast using simple linear regression.

    Args:
        historical_data: List of historical values
        forecast_periods: Number of periods to forecast

    Returns:
        Dictionary with:
            - forecasts: Predicted values
            - confidence_intervals: 95% CI bounds
            - r_squared: Model fit quality
            - slope: Regression slope
            - intercept: Regression intercept
    """
    if len(historical_data) < 2:
        raise ValueError("At least 2 data points required for linear regression")

    # Prepare data
    x = np.arange(len(historical_data))
    y = np.array(historical_data, dtype=float)

    # Calculate regression
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

    # Generate forecasts
    future_x = np.arange(len(historical_data), len(historical_data) + forecast_periods)
    forecasts = slope * future_x + intercept

    # Calculate residuals for confidence intervals
    residuals = y - (slope * x + intercept)
    residual_std = np.std(residuals)
    se = residual_std * np.sqrt(1 + 1/len(x) + (future_x - np.mean(x))**2 / np.sum((x - np.mean(x))**2))

    # 95% confidence interval
    z_score = 1.96
    confidence_intervals = [
        {
            "lower": float(forecasts[i] - z_score * se[i]),
            "forecast": float(forecasts[i]),
            "upper": float(forecasts[i] + z_score * se[i]),
        }
        for i in range(forecast_periods)
    ]

    return {
        "method": "Linear Regression",
        "forecasts": [float(round(f, 2)) for f in forecasts],
        "confidence_intervals": confidence_intervals,
        "r_squared": float(round(r_value**2, 4)),
        "slope": float(round(slope, 4)),
        "intercept": float(round(intercept, 2)),
        "p_value": float(round(p_value, 6)),
        "forecast_periods": forecast_periods,
        "calculated_at": _now_iso(),
    }


def calculate_exponential_smoothing(
    historical_data: list[float],
    forecast_periods: int = 5,
    alpha: float = 0.3,
    beta: float = 0.1,
) -> dict[str, Any]:
    """
    Forecast using exponential smoothing (Holt-Winters style).

    Args:
        historical_data: List of historical values
        forecast_periods: Number of periods to forecast
        alpha: Smoothing factor for level (0-1)
        beta: Smoothing factor for trend (0-1)

    Returns:
        Dictionary with:
            - forecasts: Predicted values
            - smoothed_values: Smoothed historical values
            - trend: Estimated trend
            - mape: Mean Absolute Percentage Error
    """
    if len(historical_data) < 2:
        raise ValueError("At least 2 data points required for exponential smoothing")

    data = np.array(historical_data, dtype=float)
    n = len(data)

    # Initialize
    level = data[0]
    trend = data[1] - data[0]
    smoothed_values = [level]

    # Smooth historical data
    for i in range(1, n):
        prev_level = level
        level = alpha * data[i] + (1 - alpha) * (prev_level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
        smoothed_values.append(level)

    # Generate forecasts
    forecasts = []
    for i in range(1, forecast_periods + 1):
        forecast = level + i * trend
        forecasts.append(forecast)

    # Calculate MAPE (Mean Absolute Percentage Error)
    errors = []
    for i in range(n):
        if data[i] != 0:
            error = abs((data[i] - smoothed_values[i]) / data[i]) * 100
            errors.append(error)

    mape = np.mean(errors) if errors else 0.0

    return {
        "method": "Exponential Smoothing",
        "forecasts": [float(round(f, 2)) for f in forecasts],
        "smoothed_values": [float(round(v, 2)) for v in smoothed_values],
        "level": float(round(level, 2)),
        "trend": float(round(trend, 2)),
        "mape": float(round(mape, 2)),
        "alpha": alpha,
        "beta": beta,
        "forecast_periods": forecast_periods,
        "calculated_at": _now_iso(),
    }


def calculate_moving_average(
    historical_data: list[float],
    window_size: int = 3,
    forecast_periods: int = 5,
) -> dict[str, Any]:
    """
    Forecast using moving average.

    Args:
        historical_data: List of historical values
        window_size: Number of periods for moving average
        forecast_periods: Number of periods to forecast

    Returns:
        Dictionary with:
            - forecasts: Predicted values (constant at last MA)
            - moving_averages: Calculated moving averages
            - window_size: Size of window used
    """
    if len(historical_data) < window_size:
        raise ValueError(f"Need at least {window_size} data points for {window_size}-period MA")

    data = np.array(historical_data, dtype=float)

    # Calculate moving averages
    moving_averages = []
    for i in range(window_size - 1, len(data)):
        ma = np.mean(data[i - window_size + 1 : i + 1])
        moving_averages.append(ma)

    # Forecast (constant at last MA)
    last_ma = moving_averages[-1]
    forecasts = [float(last_ma)] * forecast_periods

    return {
        "method": "Moving Average",
        "forecasts": [float(round(f, 2)) for f in forecasts],
        "moving_averages": [float(round(ma, 2)) for ma in moving_averages],
        "window_size": window_size,
        "last_moving_average": float(round(last_ma, 2)),
        "forecast_periods": forecast_periods,
        "calculated_at": _now_iso(),
    }


def calculate_arima_simple(
    historical_data: list[float],
    forecast_periods: int = 5,
) -> dict[str, Any]:
    """
    Simple ARIMA-style forecasting using differencing and AR model.

    This is a simplified ARIMA(1,1,0) implementation:
    - Differencing (d=1) to make data stationary
    - AR(1) autoregressive model on differenced data

    Args:
        historical_data: List of historical values
        forecast_periods: Number of periods to forecast

    Returns:
        Dictionary with:
            - forecasts: Predicted values
            - differenced_data: First differences
            - ar_coefficient: Autoregressive coefficient
            - stationarity_test: ADF-like test result
    """
    if len(historical_data) < 3:
        raise ValueError("At least 3 data points required for ARIMA")

    data = np.array(historical_data, dtype=float)

    # First difference to make stationary
    differenced = np.diff(data)

    # Calculate autocorrelation at lag 1
    if len(differenced) > 1:
        mean_diff = np.mean(differenced)
        c0 = np.sum((differenced - mean_diff) ** 2) / len(differenced)
        c1 = np.sum((differenced[:-1] - mean_diff) * (differenced[1:] - mean_diff)) / len(differenced)
        ar_coef = c1 / c0 if c0 != 0 else 0.0
    else:
        ar_coef = 0.0

    # Generate forecasts
    forecasts = []
    last_value = data[-1]
    last_diff = differenced[-1]

    for _ in range(forecast_periods):
        # Forecast difference
        next_diff = ar_coef * last_diff
        # Forecast value
        next_value = last_value + next_diff
        forecasts.append(next_value)

        last_value = next_value
        last_diff = next_diff

    # Simple stationarity check (range test)
    data_range = np.max(data) - np.min(data)
    diff_range = np.max(differenced) - np.min(differenced) if len(differenced) > 0 else 0
    is_stationary = diff_range < data_range if data_range > 0 else True

    return {
        "method": "ARIMA(1,1,0)",
        "forecasts": [float(round(f, 2)) for f in forecasts],
        "ar_coefficient": float(round(ar_coef, 4)),
        "stationary": is_stationary,
        "differenced_data": [float(round(d, 2)) for d in differenced],
        "forecast_periods": forecast_periods,
        "calculated_at": _now_iso(),
    }


def compare_forecast_methods(
    historical_data: list[float],
    forecast_periods: int = 5,
) -> dict[str, Any]:
    """
    Compare multiple forecasting methods and rank by fit quality.

    Args:
        historical_data: List of historical values
        forecast_periods: Number of periods to forecast

    Returns:
        Dictionary with all methods' results and rankings
    """
    results = {}

    # Try each method
    try:
        results["linear_regression"] = calculate_linear_regression(historical_data, forecast_periods)
    except Exception as e:
        results["linear_regression"] = {"error": str(e)}

    try:
        results["exponential_smoothing"] = calculate_exponential_smoothing(
            historical_data, forecast_periods, alpha=0.3, beta=0.1
        )
    except Exception as e:
        results["exponential_smoothing"] = {"error": str(e)}

    try:
        results["moving_average_3"] = calculate_moving_average(historical_data, window_size=3, forecast_periods=forecast_periods)
    except Exception as e:
        results["moving_average_3"] = {"error": str(e)}

    try:
        results["arima"] = calculate_arima_simple(historical_data, forecast_periods)
    except Exception as e:
        results["arima"] = {"error": str(e)}

    # Rank by fit quality (R-squared for regression, MAPE for others)
    rankings = []

    if "r_squared" in results.get("linear_regression", {}):
        rankings.append({
            "method": "Linear Regression",
            "fit_quality": results["linear_regression"]["r_squared"],
            "metric": "R²",
        })

    if "mape" in results.get("exponential_smoothing", {}):
        # Lower MAPE is better, invert for ranking
        mape = results["exponential_smoothing"]["mape"]
        fit_quality = 100 - min(mape, 100)  # 0-100 scale where higher is better
        rankings.append({
            "method": "Exponential Smoothing",
            "fit_quality": fit_quality,
            "metric": f"1 - MAPE/100 ({mape:.1f}%)",
        })

    # Sort by fit quality
    rankings.sort(key=lambda x: x["fit_quality"], reverse=True)

    return {
        "forecast_period_length": forecast_periods,
        "historical_data_points": len(historical_data),
        "forecasts": results,
        "rankings": rankings,
        "recommended_method": rankings[0]["method"] if rankings else None,
        "calculated_at": _now_iso(),
    }


def forecast_with_confidence(
    historical_data: list[float],
    forecast_periods: int = 5,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """
    Generate forecasts with confidence intervals using multiple methods.

    Args:
        historical_data: List of historical values
        forecast_periods: Number of periods to forecast
        confidence_level: Confidence level for intervals (0.90, 0.95, 0.99)

    Returns:
        Dictionary with ensemble forecast and confidence intervals
    """
    # Get multiple forecasts
    lr_result = calculate_linear_regression(historical_data, forecast_periods)
    es_result = calculate_exponential_smoothing(historical_data, forecast_periods)
    ma_result = calculate_moving_average(historical_data, window_size=3, forecast_periods=forecast_periods)

    # Ensemble: average the forecasts
    lr_forecasts = np.array(lr_result["forecasts"])
    es_forecasts = np.array(es_result["forecasts"])
    ma_forecasts = np.array(ma_result["forecasts"])

    ensemble_forecasts = (lr_forecasts + es_forecasts + ma_forecasts) / 3

    # Calculate ensemble confidence intervals
    all_forecasts = np.array([lr_forecasts, es_forecasts, ma_forecasts])
    forecast_std = np.std(all_forecasts, axis=0)

    # z-score for confidence level
    z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_scores.get(confidence_level, 1.96)

    ensemble_ci = [
        {
            "forecast": float(round(ensemble_forecasts[i], 2)),
            "lower": float(round(max(0, ensemble_forecasts[i] - z * forecast_std[i]), 2)),
            "upper": float(round(ensemble_forecasts[i] + z * forecast_std[i], 2)),
            "std_dev": float(round(forecast_std[i], 2)),
        }
        for i in range(forecast_periods)
    ]

    return {
        "method": "Ensemble (LR + ES + MA)",
        "confidence_level": confidence_level,
        "forecasts": [float(round(f, 2)) for f in ensemble_forecasts],
        "confidence_intervals": ensemble_ci,
        "ensemble_component_forecasts": {
            "linear_regression": [float(round(f, 2)) for f in lr_forecasts],
            "exponential_smoothing": [float(round(f, 2)) for f in es_forecasts],
            "moving_average_3": [float(round(f, 2)) for f in ma_forecasts],
        },
        "forecast_periods": forecast_periods,
        "calculated_at": _now_iso(),
    }
