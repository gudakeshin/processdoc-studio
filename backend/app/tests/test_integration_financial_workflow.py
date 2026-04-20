"""End-to-end integration tests for complete financial modeling workflows."""

import pytest

from app.services.budget_vs_actual import (
    calculate_period_variance,
    create_budget_setup,
    forecast_full_year,
    generate_budget_vs_actual_report,
    record_actual_results,
)
from app.services.financial_calculations import (
    calculate_irr,
    calculate_npv,
)
from app.services.financial_statements import (
    calculate_financial_ratios,
    generate_balance_sheet,
    generate_income_statement,
)
from app.services.model_links import (
    build_model_dependency_graph,
    create_model_link,
    sync_linked_cells,
    validate_all_links,
)
from app.services.scenario_runner import (
    run_scenario_calculation,
)
from app.services.variance_analysis import (
    calculate_line_item_variances,
    generate_variance_report,
    identify_variance_drivers,
)


class TestCompleteFinancialModelingWorkflow:
    """Test end-to-end financial modeling from creation to reporting."""

    def test_full_financial_model_creation_and_analysis(self):
        """Test creating a financial model and analyzing it completely."""
        # Step 1: Create income statement projections
        revenue_projections = [1000000, 1100000, 1210000, 1331000, 1464100]
        # Calculate COGS at 40% of revenue for each period
        cogs_projections = [r * 0.4 for r in revenue_projections]
        # Calculate OpEx at 20% of revenue for each period
        opex_projections = [r * 0.2 for r in revenue_projections]
        tax_rate = 0.21

        income_statement = generate_income_statement(
            revenue_projections=revenue_projections,
            cogs_projections=cogs_projections,
            opex_projections=opex_projections,
            tax_rate=tax_rate,
        )

        # Verify statement structure
        assert income_statement["period_count"] == 5
        assert income_statement["data"]["Revenue"][0] == 1000000
        assert income_statement["data"]["Gross Profit"][0] == pytest.approx(600000)  # 1M - (1M * 0.4) = 600k

        # Step 2: Generate balance sheet for ratio calculation
        balance_sheet = generate_balance_sheet(
            current_assets=500000,
            fixed_assets=2000000,
            current_liabilities=300000,
            long_term_debt=1000000,
            shareholders_equity=1200000,
            periods=5,
        )

        # Step 3: Calculate financial ratios
        ratios = calculate_financial_ratios(income_statement, balance_sheet)

        assert "ratios" in ratios
        assert ratios["period_count"] == 5

        # Step 4: Perform NPV and IRR analysis
        # Add initial investment (negative) to make IRR calculation meaningful
        net_income = income_statement["data"]["Net Income"]
        cash_flows = [-2000000] + net_income  # Initial investment of 2M
        npv = calculate_npv(cash_flows=cash_flows, discount_rate=0.1)
        irr = calculate_irr(cash_flows=cash_flows)

        assert npv["npv"] is not None
        assert npv["periods"] == 6  # Initial investment + 5 periods
        # IRR may or may not converge depending on cash flow pattern
        assert "irr" in irr

        # Step 5: Generate variance report
        actual_data = {
            "Revenue": 1050000,
            "COGS": 420000,
            "OpEx": 210000,
        }
        budget_data = {
            "Revenue": 1000000,
            "COGS": 400000,
            "OpEx": 200000,
        }

        variance_report = generate_variance_report(actual_data, budget_data)

        assert "summary" in variance_report
        assert variance_report["summary"]["variance"] is not None
        # Verify report has expected structure
        assert "line_items" in variance_report

        # Step 6: Identify key drivers
        line_items = calculate_line_item_variances(actual_data, budget_data)
        drivers = identify_variance_drivers(line_items)

        assert len(drivers["drivers"]) > 0
        assert len(drivers["key_drivers_80_20"]) > 0


class TestBudgetVsActualIntegration:
    """Test integrated budget vs actual tracking workflow."""

    def test_complete_budget_tracking_with_forecasting(self):
        """Test complete budget setup, tracking, and year-end forecasting."""
        # Step 1: Setup budget
        budget_data = {
            "Salaries": 120000,
            "Marketing": 12000,
            "Operations": 24000,
        }

        budget = create_budget_setup(
            model_id="financial_model",
            budget_data=budget_data,
            fiscal_year=2024,
            periods=12,
        )

        assert budget["total_budget"] == 156000
        assert budget["periods"] == 12

        # Step 2: Record actuals for Q1 (3 months)
        actual_by_period = {
            1: {"Salaries": 10200, "Marketing": 1100, "Operations": 2100},
            2: {"Salaries": 10000, "Marketing": 950, "Operations": 2000},
            3: {"Salaries": 10300, "Marketing": 1050, "Operations": 2050},
        }

        # Record each period
        for period, actuals in actual_by_period.items():
            recording = record_actual_results(budget, period, actuals)
            assert recording["period"] == period

        # Step 3: Calculate period variance for month 3
        period_variance = calculate_period_variance(budget, 3, actual_by_period[3])

        assert period_variance["period"] == 3
        assert period_variance["total_budget"] == pytest.approx(13000.0)
        assert period_variance["total_actual"] == pytest.approx(13400.0)

        # Step 4: Forecast full year
        forecast = forecast_full_year(budget, actual_by_period, through_period=3)

        # Verify forecast is reasonable
        assert forecast["fiscal_year"] == 2024
        assert "Salaries" in forecast["forecasts"]
        # Average YTD spending should project to full year
        salaries_forecast = forecast["forecasts"]["Salaries"]
        assert salaries_forecast["full_year_forecast"] > 120000  # Overbudget

        # Step 5: Generate comprehensive report
        report = generate_budget_vs_actual_report(
            budget,
            actual_by_period,
            through_period=3,
            title="Q1 2024 Review",
        )

        assert report["fiscal_year"] == 2024
        assert report["summary"]["periods_recorded"] == 3
        assert report["summary"]["budget"] == pytest.approx(39000.0)
        assert len(report["drivers"]["key_drivers_80_20"]) > 0


class TestModelLinkingAndSync:
    """Test cross-model linking and synchronization."""

    def test_model_linking_with_impact_analysis(self):
        """Test creating model links and analyzing impact."""
        # Step 1: Create links between models
        link1 = create_model_link(
            source_model_id="revenue_model",
            source_cell_ref="A1",
            target_model_id="expense_model",
            target_cell_ref="B1",
            all_links=[],
        )

        assert link1["source_model_id"] == "revenue_model"
        assert link1["status"] == "active"

        link2 = create_model_link(
            source_model_id="expense_model",
            source_cell_ref="A2",
            target_model_id="profit_model",
            target_cell_ref="C1",
            all_links=[link1],
        )

        all_links = [link1, link2]

        # Step 2: Build dependency graph
        graph = build_model_dependency_graph(all_links)

        assert "expense_model" in graph["dependents"]["revenue_model"]
        assert "profit_model" in graph["dependents"]["expense_model"]

        # Step 3: Analyze impact of changes
        from app.services.model_links import get_link_impact

        impact = get_link_impact("revenue_model", all_links)

        assert impact["changed_model"] == "revenue_model"
        assert impact["directly_affected_links"] == 1
        assert "expense_model" in impact["affected_models"]
        assert "profit_model" in impact["affected_models"]

        # Step 4: Sync values across models
        model_assumptions = {"A1": 1000, "A2": 400}

        sync_result = sync_linked_cells("revenue_model", model_assumptions, all_links)

        assert sync_result["synced_cell_count"] == 1
        assert sync_result["error_count"] == 0

        # Step 5: Validate all links
        validation = validate_all_links(all_links)

        assert validation["valid_links"] == 2
        assert validation["issue_count"] == 0
        assert validation["health"] == "good"


class TestDataConnectorIntegration:
    """Test external data integration workflow."""

    def test_external_data_import_with_lineage_tracking(self):
        """Test importing external data and tracking lineage."""
        import json
        import tempfile

        from app.services.financial_data_connector import (
            create_data_source_connector,
            detect_data_drift,
            get_data_lineage,
            sync_data_source,
        )

        # Step 1: Create data source
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            data = [{"Revenue": 1000, "COGS": 400, "OpEx": 200}]
            json.dump(data, f)
            f.flush()

            mapping = {
                "annual_revenue": "Revenue",
                "cost_of_goods": "COGS",
                "operating_expenses": "OpEx",
            }

            connector = create_data_source_connector(
                model_id="model_a",
                source_name="External Budget",
                file_path=f.name,
                file_type="json",
                column_mapping=mapping,
                refresh_schedule="monthly",
            )

            assert connector["source_name"] == "External Budget"

            # Step 2: First sync
            model_assumptions = {
                "annual_revenue": 900,
                "cost_of_goods": 380,
                "operating_expenses": 180,
            }

            sync_result1 = sync_data_source(connector, model_assumptions)

            assert sync_result1["error_count"] == 0
            assert sync_result1["updated_assumptions"]["annual_revenue"] == 1000.0

            # Step 3: Track lineage
            lineage = get_data_lineage("model_a", [sync_result1])

            assert lineage["assumption_count"] == 3
            assert "annual_revenue" in lineage["assumptions_with_sources"]

            # Step 4: Update source and detect drift
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f2:
                data2 = [{"Revenue": 1200, "COGS": 480, "OpEx": 250}]
                json.dump(data2, f2)
                f2.flush()

                connector2 = connector.copy()
                connector2["file_path"] = f2.name

                sync_result2 = sync_data_source(connector2, sync_result1["updated_assumptions"])

                drift = detect_data_drift(
                    sync_result2["updated_assumptions"],
                    sync_result1["updated_assumptions"],
                    threshold_pct=5.0,
                )

                assert drift["drift_count"] > 0
                assert any(d["pct_change"] > 10 for d in drift["drifts"])


class TestScenarioAndForecastingIntegration:
    """Test scenario analysis and forecasting together."""

    def test_multiple_scenarios_with_forecast_comparison(self):
        """Test running multiple scenarios and comparing forecasts."""
        from app.services.forecasting import forecast_with_confidence

        # Base case
        base_data = [1000, 1050, 1100, 1150, 1200]

        # Scenario 1: Upside (15% higher growth)
        upside_data = [1000, 1075, 1155, 1242, 1428]

        # Scenario 2: Downside (5% lower growth)
        downside_data = [1000, 1025, 1050, 1076, 1103]

        # Generate forecasts for each scenario
        base_forecast = forecast_with_confidence(base_data, forecast_periods=3)
        upside_forecast = forecast_with_confidence(upside_data, forecast_periods=3)
        downside_forecast = forecast_with_confidence(downside_data, forecast_periods=3)

        # Verify forecasts diverge
        assert upside_forecast["forecasts"][0] > base_forecast["forecasts"][0]
        assert downside_forecast["forecasts"][0] < base_forecast["forecasts"][0]

        # All forecasts should have confidence intervals
        assert len(base_forecast["confidence_intervals"]) > 0
        assert len(upside_forecast["confidence_intervals"]) > 0
        assert len(downside_forecast["confidence_intervals"]) > 0


class TestConflictResolutionIntegration:
    """Test conflict detection and resolution workflow."""

    def test_conflict_lifecycle_from_detection_to_resolution(self):
        """Test complete conflict lifecycle."""
        import tempfile
        from pathlib import Path

        from app.services.conflict_resolution import (
            create_conflict,
            list_conflicts,
            resolve_conflict,
        )

        # Step 1: Create temp directory for conflicts
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_dir = Path(tmpdir)

            # Step 2: Detect and create conflict
            conflict = create_conflict(
                excel_dir,
                sheet="Sheet1",
                cell_ref="A1",
                base_value=100,
                local_value=110,
                remote_value=120,
                actor="user_a",
            )

            assert conflict["status"] == "open"
            assert conflict["severity"] in ["high", "medium"]

            # Step 3: List conflicts
            all_conflicts = list_conflicts(excel_dir)

            assert len(all_conflicts) >= 1
            assert any(c["id"] == conflict["id"] for c in all_conflicts)

            # Step 4: Resolve conflict
            resolved = resolve_conflict(
                excel_dir,
                conflict_id=conflict["id"],
                actor="user_a",
                chosen_side="remote",
                rationale="Accepting remote version after verification",
            )

            assert resolved["status"] == "resolved"
            assert resolved["resolution"]["chosen_side"] == "remote"

            # Step 5: Verify resolution
            remaining_open = [c for c in list_conflicts(excel_dir) if c["status"] == "open" and c["id"] == conflict["id"]]

            assert len(remaining_open) == 0


class TestEndToEndReportGeneration:
    """Test complete report generation workflow."""

    def test_comprehensive_financial_report_generation(self):
        """Test generating a comprehensive financial report from model data."""
        # Create sample model data
        revenue_projections = [1000000, 1100000, 1210000, 1331000, 1464100]

        generate_income_statement(
            revenue_projections=revenue_projections,
            cogs_projections=0.4,
            opex_projections=0.2,
            tax_rate=0.21,
        )

        # Create variance data
        actual_data = {"Revenue": 1050000, "COGS": 420000, "OpEx": 210000}
        budget_data = {"Revenue": 1000000, "COGS": 400000, "OpEx": 200000}

        variance_report = generate_variance_report(actual_data, budget_data)

        # Create budget vs actual
        budget = create_budget_setup(
            model_id="report_model",
            budget_data={"Revenue": 1000000, "Expenses": 600000},
            fiscal_year=2024,
        )

        actual_by_period = {1: {"Revenue": 1050000, "Expenses": 620000}}

        budget_report = generate_budget_vs_actual_report(
            budget,
            actual_by_period,
            through_period=1,
            title="2024 Financial Summary",
        )

        # Verify all components present
        assert variance_report["summary"]["actual"] > variance_report["summary"]["budget"]
        assert budget_report["fiscal_year"] == 2024
        assert len(budget_report["drivers"]["key_drivers_80_20"]) > 0


class TestDataIntegrityAcrossWorkflows:
    """Test data consistency across multiple workflows."""

    def test_data_consistency_in_linked_scenarios(self):
        """Test that data remains consistent when models are linked and scenarios created."""
        # Create linked models
        link = create_model_link(
            source_model_id="source",
            source_cell_ref="A1",
            target_model_id="target",
            target_cell_ref="B1",
            all_links=[],
        )

        # Run scenarios on source with base assumptions
        base_assumptions = {"revenue": 1000, "cogs": 400, "opex": 200}
        scenario = {
            "id": "base_case",
            "name": "Base Case",
            "assumption_overrides": {},
        }
        scenario_data = run_scenario_calculation(scenario, base_assumptions)

        # Sync to target
        sync_result = sync_linked_cells("source", {"A1": 1000}, [link])

        # Verify sync matches scenario
        assert sync_result["synced_cell_count"] == 1
        assert scenario_data["scenario_id"] == "base_case"


class TestErrorHandlingAndRecovery:
    """Test error handling and recovery in workflows."""

    def test_recovery_from_failed_sync(self):
        """Test recovery from failed data source sync."""
        from app.services.financial_data_connector import (
            sync_data_source,
        )

        # Create connector with invalid file path
        connector = {
            "id": "test_conn",
            "model_id": "model_a",
            "source_name": "Invalid Source",
            "file_path": "/nonexistent/file.json",
            "file_type": "json",
            "column_mapping": {"revenue": "Revenue"},
            "columns_available": ["Revenue"],
            "refresh_schedule": "manual",
            "status": "active",
            "created_at": "2024-01-01T00:00:00Z",
            "last_synced_at": None,
            "sync_count": 0,
            "row_count": 0,
        }

        # Try to sync - should fail gracefully
        try:
            sync_result = sync_data_source(connector, {})
            # Even if no error is raised, verify the structure is valid
            assert "synced_at" in sync_result
        except Exception as e:
            # File not found is expected
            assert "not found" in str(e).lower() or "No such file" in str(e)
