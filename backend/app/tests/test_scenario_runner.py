"""Test suite for scenario analysis engine."""

import pytest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.scenario_runner import (
    run_scenario_calculation,
    compare_scenarios,
    save_scenario_results,
    load_scenario_results,
    load_all_scenario_results,
    refresh_all_scenario_results,
    get_scenario_rankings,
)


@pytest.fixture
def temp_excel_dir():
    """Create a temporary directory for excel files."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestScenarioCalculation:
    """Test scenario calculation."""

    def test_run_scenario_basic(self):
        """Test basic scenario calculation."""
        base_assumptions = {
            "revenue": 1000,
            "cogs": 400,
            "opex": 200,
            "tax_rate": 0.21,
        }
        scenario = {
            "id": "scn_1",
            "name": "Conservative",
            "assumption_overrides": {"revenue": 900},
        }

        result = run_scenario_calculation(scenario, base_assumptions)

        assert result["scenario_id"] == "scn_1"
        assert result["scenario_name"] == "Conservative"
        assert result["assumptions"]["revenue"] == 900
        assert result["assumptions"]["opex"] == 200  # From base
        assert "metrics" in result
        assert "calculated_at" in result

    def test_scenario_merges_assumptions(self):
        """Test that scenario overrides merge with base assumptions."""
        base_assumptions = {
            "revenue": 1000,
            "cogs": 400,
            "opex": 200,
            "growth_rate": 0.1,
        }
        scenario = {
            "id": "scn_opt",
            "name": "Optimistic",
            "assumption_overrides": {
                "revenue": 1200,
                "growth_rate": 0.15,
            },
        }

        result = run_scenario_calculation(scenario, base_assumptions)

        # Check merged assumptions
        assert result["assumptions"]["revenue"] == 1200  # Overridden
        assert result["assumptions"]["growth_rate"] == 0.15  # Overridden
        assert result["assumptions"]["cogs"] == 400  # From base
        assert result["assumptions"]["opex"] == 200  # From base

    def test_scenario_calculates_metrics(self):
        """Test that scenario calculation generates metrics."""
        base_assumptions = {
            "revenue": 1000,
            "cogs": 400,
            "opex": 200,
            "tax_rate": 0.21,
        }
        scenario = {
            "id": "scn_1",
            "name": "Scenario 1",
            "assumption_overrides": {},
        }

        result = run_scenario_calculation(scenario, base_assumptions)

        metrics = result.get("metrics", {})
        assert "gross_margin_pct" in metrics
        assert "operating_margin_pct" in metrics
        assert "net_margin_pct" in metrics

    def test_scenario_calculates_npv(self):
        """Test that scenario calculation includes NPV if applicable."""
        base_assumptions = {
            "cash_flows": "-100,50,50,50",
            "discount_rate": 0.10,
        }
        scenario = {
            "id": "scn_1",
            "name": "Scenario 1",
            "assumption_overrides": {},
        }

        result = run_scenario_calculation(scenario, base_assumptions)

        assert result["npv"] is not None
        assert result["npv"]["npv"] is not None


class TestScenarioComparison:
    """Test scenario comparison."""

    def test_compare_scenarios_metrics(self):
        """Test comparing metrics between scenarios."""
        baseline = {
            "scenario_id": "base",
            "scenario_name": "Baseline",
            "metrics": {
                "gross_margin_pct": 60.0,
                "net_margin_pct": 30.0,
            },
        }
        other = {
            "scenario_id": "opt",
            "scenario_name": "Optimistic",
            "metrics": {
                "gross_margin_pct": 65.0,
                "net_margin_pct": 35.0,
            },
        }

        comparison = compare_scenarios(baseline, other)

        assert comparison["scenario_id"] == "opt"
        assert comparison["baseline_scenario"] == "Baseline"
        assert "gross_margin_pct" in comparison["metrics_variance"]
        assert comparison["metrics_variance"]["gross_margin_pct"]["variance"] == pytest.approx(5.0)

    def test_compare_scenarios_npv(self):
        """Test comparing NPV between scenarios."""
        baseline = {
            "scenario_id": "base",
            "scenario_name": "Baseline",
            "npv": {"npv": 100.0},
        }
        other = {
            "scenario_id": "opt",
            "scenario_name": "Optimistic",
            "npv": {"npv": 150.0},
        }

        comparison = compare_scenarios(baseline, other)

        assert comparison["npv_variance"] is not None
        assert comparison["npv_variance"]["variance"] == pytest.approx(50.0)


class TestScenarioStorage:
    """Test scenario result storage and retrieval."""

    def test_save_and_load_scenario_results(self, temp_excel_dir):
        """Test saving and loading scenario results."""
        result = {
            "scenario_id": "scn_1",
            "scenario_name": "Test",
            "metrics": {"gross_margin_pct": 60.0},
        }

        # Save
        saved = save_scenario_results(temp_excel_dir, "scn_1", result)
        assert "saved_at" in saved

        # Load
        loaded = load_scenario_results(temp_excel_dir, "scn_1")
        assert loaded is not None
        assert loaded["scenario_id"] == "scn_1"
        assert loaded["metrics"]["gross_margin_pct"] == 60.0

    def test_load_all_scenario_results(self, temp_excel_dir):
        """Test loading all scenario results."""
        results_dir = temp_excel_dir / "scenario_results"
        results_dir.mkdir(parents=True, exist_ok=True)

        # Create multiple result files
        for i in range(3):
            result = {
                "scenario_id": f"scn_{i}",
                "scenario_name": f"Scenario {i}",
                "metrics": {"gross_margin_pct": 60.0 + i},
            }
            result_path = results_dir / f"scn_{i}.json"
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

        # Load all
        all_results = load_all_scenario_results(temp_excel_dir)

        assert len(all_results) == 3
        assert all_results[0]["scenario_id"] == "scn_0"

    def test_load_scenario_results_not_found(self, temp_excel_dir):
        """Test loading non-existent scenario results."""
        result = load_scenario_results(temp_excel_dir, "nonexistent")
        assert result is None


class TestScenarioRefresh:
    """Test refreshing scenario calculations."""

    def test_refresh_all_scenario_results(self, temp_excel_dir):
        """Test recalculating all scenario results."""
        model_meta = {
            "id": "model_1",
            "assumptions": {
                "revenue": 1000,
                "cogs": 400,
                "opex": 200,
                "tax_rate": 0.21,
            },
        }
        scenarios = [
            {
                "id": "scn_1",
                "name": "Conservative",
                "assumption_overrides": {"revenue": 900},
            },
            {
                "id": "scn_2",
                "name": "Optimistic",
                "assumption_overrides": {"revenue": 1200},
            },
        ]

        results = refresh_all_scenario_results(temp_excel_dir, model_meta, scenarios)

        assert len(results) == 2
        assert results[0]["scenario_id"] == "scn_1"
        assert results[1]["scenario_id"] == "scn_2"

        # Verify they were saved
        loaded_1 = load_scenario_results(temp_excel_dir, "scn_1")
        assert loaded_1 is not None
        assert loaded_1["assumptions"]["revenue"] == 900


class TestScenarioRanking:
    """Test scenario ranking."""

    def test_rank_scenarios_by_metric(self):
        """Test ranking scenarios by a metric."""
        results = [
            {
                "scenario_id": "scn_1",
                "scenario_name": "Conservative",
                "metrics": {"gross_margin_pct": 55.0},
            },
            {
                "scenario_id": "scn_2",
                "scenario_name": "Baseline",
                "metrics": {"gross_margin_pct": 60.0},
            },
            {
                "scenario_id": "scn_3",
                "scenario_name": "Optimistic",
                "metrics": {"gross_margin_pct": 65.0},
            },
        ]

        rankings = get_scenario_rankings(results, "gross_margin_pct", ascending=False)

        assert len(rankings) == 3
        assert rankings[0]["scenario_name"] == "Optimistic"
        assert rankings[0]["metric_value"] == 65.0
        assert rankings[2]["scenario_name"] == "Conservative"

    def test_rank_scenarios_ascending(self):
        """Test ranking scenarios in ascending order."""
        results = [
            {
                "scenario_id": "scn_1",
                "scenario_name": "High Cost",
                "metrics": {"opex_ratio": 0.35},
            },
            {
                "scenario_id": "scn_2",
                "scenario_name": "Low Cost",
                "metrics": {"opex_ratio": 0.20},
            },
        ]

        rankings = get_scenario_rankings(results, "opex_ratio", ascending=True)

        assert rankings[0]["scenario_name"] == "Low Cost"
        assert rankings[1]["scenario_name"] == "High Cost"


class TestIntegration:
    """Integration tests for scenario analysis."""

    def test_full_scenario_workflow(self, temp_excel_dir):
        """Test complete scenario analysis workflow."""
        # Setup
        model_meta = {
            "id": "model_1",
            "assumptions": {
                "revenue": 1000,
                "cogs": 400,
                "opex": 200,
                "tax_rate": 0.21,
            },
        }
        scenarios = [
            {
                "id": "base",
                "name": "Baseline",
                "assumption_overrides": {},
            },
            {
                "id": "opt",
                "name": "Optimistic",
                "assumption_overrides": {"revenue": 1200, "opex": 180},
            },
        ]

        # Refresh all scenarios
        results = refresh_all_scenario_results(temp_excel_dir, model_meta, scenarios)
        assert len(results) == 2

        # Load all and verify
        all_loaded = load_all_scenario_results(temp_excel_dir)
        assert len(all_loaded) == 2

        # Compare scenarios
        baseline_result = load_scenario_results(temp_excel_dir, "base")
        opt_result = load_scenario_results(temp_excel_dir, "opt")

        comparison = compare_scenarios(baseline_result, opt_result)
        assert comparison["scenario_id"] == "opt"
        assert "metrics_variance" in comparison

        # Rank by metric
        rankings = get_scenario_rankings(all_loaded, "gross_margin_pct")
        assert len(rankings) == 2
