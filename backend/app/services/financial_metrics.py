from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.services.financial_calculations import calculate_financial_metrics

log = logging.getLogger(__name__)


def _load_meta(model_dir: Path) -> dict[str, Any]:
    meta_path = model_dir / "model.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Failed to parse model.json at %s; returning empty metadata", meta_path, exc_info=True)
        return {}


def _float(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


def _opt_float(d: dict[str, Any], key: str) -> float | None:
    """Return float or None — never a fake default."""
    val = d.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# Ordered list of (keyword_fragment, field_name). First match wins per row.
_BALANCE_SHEET_KEYWORDS: list[tuple[str, str]] = [
    ("current asset", "current_assets"),
    ("current liabilit", "current_liabilities"),
    ("total asset", "total_assets"),
    ("shareholders equity", "shareholders_equity"),
    ("stockholders equity", "shareholders_equity"),
    ("owners equity", "shareholders_equity"),
    ("total equity", "shareholders_equity"),
    ("long-term debt", "total_debt"),
    ("long term debt", "total_debt"),
    ("notes payable", "total_debt"),
    ("total debt", "total_debt"),
    ("cash and cash", "cash"),
    ("cash equivalents", "cash"),
    ("ebitda", "ebitda"),
    ("inventory", "inventory"),
]

_NUMERIC_SEMANTIC_TYPES = {"currency", "number", "percentage"}


def _extract_balance_sheet_from_snapshot(excel_dir: Path) -> dict[str, float | None]:
    """
    Parse the most recent xlsx snapshot to extract balance sheet line items.
    Returns a dict with keys like current_assets, current_liabilities, etc.
    Values are floats if found, absent if not found.
    Never fills in fake constants.
    """
    snapshots_dir = excel_dir / "snapshots"
    if not snapshots_dir.exists():
        return {}

    files = sorted(snapshots_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {}

    try:
        snapshot = json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        log.warning("Failed to parse balance-sheet snapshot %s; returning empty", files[0], exc_info=True)
        return {}

    # Group cells by (sheet_index, row_number) so we can pair labels with values
    row_map: dict[tuple[int, int], list[tuple[str, Any, str]]] = {}
    for si, sheet in enumerate(snapshot.get("sheets", [])):
        for cell in sheet.get("cells", []):
            ref = cell.get("a1_ref", "")
            value = cell.get("value")
            sem_type = str(cell.get("inference", {}).get("semantic_type", ""))
            m = re.match(r"[A-Z]+(\d+)$", str(ref))
            if m:
                row_num = int(m.group(1))
                row_map.setdefault((si, row_num), []).append((ref, value, sem_type))

    result: dict[str, float] = {}

    for row_cells in row_map.values():
        labels = [
            str(v).lower().strip()
            for _, v, _ in row_cells
            if isinstance(v, str) and v.strip()
        ]
        numbers = [
            float(v)
            for _, v, st in row_cells
            if st in _NUMERIC_SEMANTIC_TYPES and isinstance(v, (int, float))
        ]

        if not labels or not numbers:
            continue

        label_text = " ".join(labels)
        for keyword, field_name in _BALANCE_SHEET_KEYWORDS:
            if keyword in label_text and field_name not in result:
                result[field_name] = numbers[0]
                break

    return result


def compute_consolidated_metrics(model_dir: Path) -> dict[str, Any]:
    meta = _load_meta(model_dir)
    assumptions: dict[str, Any] = meta.get("assumptions", {})

    # --- Try to extract real balance sheet data from the latest xlsx snapshot ---
    bs = _extract_balance_sheet_from_snapshot(model_dir / "excel")
    has_snapshot = bool(bs)
    data_source = "snapshot" if has_snapshot else "assumptions"

    # --- Income statement inputs (from assumptions or snapshot) ---
    gross_margin = _float(assumptions, "grossMargin", 0.40)
    operating_margin = _float(assumptions, "operatingMargin", 0.15)
    tax_rate = _float(assumptions, "taxRate", 0.25)
    revenue = _float(assumptions, "revenue", 1_000_000)
    revenue_growth = _float(assumptions, "revenueGrowth", 0.10)
    capex_percent = _float(assumptions, "capexPercent", 0.03)
    working_capital_percent = _float(assumptions, "workingCapitalPercent", 0.08)
    da_percent = _float(assumptions, "daPercent", 0.03)
    interest_rate = _float(assumptions, "interestRate", 0.05)

    cogs_margin = max(0.0, 1 - gross_margin)
    opex_margin = max(0.0, gross_margin - operating_margin)
    cogs = revenue * cogs_margin
    gross_profit = revenue * gross_margin
    opex_val = revenue * opex_margin
    ebit = revenue * operating_margin
    da_approx = revenue * da_percent  # D&A add-back (configurable via daPercent assumption)
    ebitda = ebit + da_approx

    # --- Balance sheet items: prefer snapshot, fall back to assumptions ---
    total_assets = bs.get("total_assets") or _opt_float(assumptions, "totalAssets")
    shareholders_equity = bs.get("shareholders_equity") or _opt_float(assumptions, "shareholdersEquity")
    total_debt = bs.get("total_debt") or _opt_float(assumptions, "totalDebt")
    cash = bs.get("cash") or _opt_float(assumptions, "cash") or 0.0
    current_assets = bs.get("current_assets") or _opt_float(assumptions, "currentAssets")
    current_liabilities = bs.get("current_liabilities") or _opt_float(assumptions, "currentLiabilities")
    inventory = bs.get("inventory") or _opt_float(assumptions, "inventory") or 0.0
    bs_ebitda = bs.get("ebitda")  # explicit EBITDA from snapshot if present

    # Use snapshot EBITDA if available, otherwise compute from income statement
    ebitda_used = bs_ebitda if bs_ebitda and bs_ebitda > 0 else ebitda

    # --- Delegate to the real calculation engine ---
    real_metrics = calculate_financial_metrics(
        revenue=revenue,
        cogs=cogs,
        gross_profit=gross_profit,
        opex=opex_val,
        ebit=ebit,
        tax_rate=tax_rate,
        total_assets=total_assets,
        shareholders_equity=shareholders_equity,
        total_debt=total_debt,
        cash=cash,
    )

    net_margin = real_metrics.get("net_margin_pct", operating_margin * (1 - tax_rate) * 100) / 100
    net_income = real_metrics.get("net_income", ebit * (1 - tax_rate))
    roe_pct = real_metrics.get("roe_pct")  # None when shareholders_equity unavailable
    roa_pct = real_metrics.get("roa_pct")  # None when total_assets unavailable

    # ROIC = NOPAT / invested_capital; invested_capital = total_assets - current_liabilities
    roic: float | None = None
    if total_assets is not None and current_liabilities is not None and total_assets > current_liabilities:
        nopat = ebit * (1 - tax_rate)
        invested_capital = total_assets - current_liabilities
        if invested_capital > 0:
            roic = round(nopat / invested_capital, 4)

    # Liquidity ratios: None if balance sheet data is unavailable
    current_ratio: float | None = None
    if current_assets is not None and current_liabilities is not None and current_liabilities > 0:
        current_ratio = round(current_assets / current_liabilities, 2)

    quick_ratio: float | None = None
    if current_assets is not None and current_liabilities is not None and current_liabilities > 0:
        quick_ratio = round((current_assets - inventory) / current_liabilities, 2)

    # Leverage ratios
    debt_to_equity: float | None = real_metrics.get("debt_to_equity")
    net_debt_to_ebitda: float | None = None
    if total_debt is not None and ebitda_used and ebitda_used > 0:
        net_debt_to_ebitda = round((total_debt - cash) / ebitda_used, 2)

    interest_coverage: float | None = None
    if ebitda_used and ebitda_used > 0 and total_debt and total_debt > 0:
        # Interest expense estimated from the configurable interestRate assumption.
        interest = total_debt * interest_rate
        interest_coverage = round(ebitda_used / interest, 1) if interest > 0 else None

    # --- 5-year forecast (computed first so growth metrics are derived from it, not fabricated) ---
    forecasts = []
    fcf_series: list[float] = []
    prev_rev = revenue
    for i in range(1, 6):
        proj_rev = revenue * ((1 + revenue_growth) ** i)
        proj_ebitda = proj_rev * (ebitda / revenue) if revenue > 0 else 0.0
        proj_ebit = proj_rev * operating_margin
        proj_taxes = max(0.0, proj_ebit * tax_rate)
        proj_ni = proj_ebit - proj_taxes
        # Unlevered FCF proxy: EBITDA − taxes − capex − ΔWorking capital
        proj_fcf = (
            proj_ebitda - proj_taxes - capex_percent * proj_rev - working_capital_percent * (proj_rev - prev_rev)
        )
        fcf_series.append(proj_fcf)
        forecasts.append(
            {
                "period": i,
                "revenue": round(proj_rev, 2),
                "margin": round(operating_margin, 4),
                "ebit": round(proj_ebit, 2),
                "ebitda": round(proj_ebitda, 2),
                "netIncome": round(proj_ni, 2),
                "confidence": round(max(0.5, 0.95 - i * 0.08), 2),
            }
        )
        prev_rev = proj_rev

    def _cagr(first: float, last: float, periods: int) -> float | None:
        if periods <= 0 or first <= 0 or last <= 0:
            return None
        return (last / first) ** (1 / periods) - 1

    # EBITDA compounds with revenue (constant margin); FCF diverges via the working-capital drag.
    # Derive both from the forecast; fall back to the revenue-growth assumption when undefined.
    ebitda_growth = _cagr(forecasts[0]["ebitda"], forecasts[-1]["ebitda"], len(forecasts) - 1)
    fcf_growth = _cagr(fcf_series[0], fcf_series[-1], len(fcf_series) - 1)
    if ebitda_growth is None:
        ebitda_growth = revenue_growth
    if fcf_growth is None:
        fcf_growth = revenue_growth

    metrics = {
        "profitability": {
            "grossMargin": round(gross_margin, 4),
            "operatingMargin": round(operating_margin, 4),
            "netMargin": round(net_margin, 4),
            "roe": round(roe_pct / 100, 4) if roe_pct is not None else None,
            "roa": round(roa_pct / 100, 4) if roa_pct is not None else None,
            "roic": roic,
        },
        "liquidity": {
            "currentRatio": current_ratio,
            "quickRatio": quick_ratio,
            "cashConversionCycle": None,  # requires days-sales and payables data not yet extracted
        },
        "leverage": {
            "debtToEquity": debt_to_equity,
            "interestCoverage": interest_coverage,
            "netDebtToEbitda": net_debt_to_ebitda,
        },
        "growth": {
            "revenueGrowth": round(revenue_growth, 4),
            "ebitdaGrowth": round(ebitda_growth, 4),
            "fcfGrowth": round(fcf_growth, 4),
            "cagr": round(revenue_growth, 4),
        },
    }

    # Income statement (one base period from assumptions)
    taxes = max(0.0, ebit * tax_rate)
    statements = {
        "name": "Base Case",
        "periods": ["Year 0"],
        "revenue": [round(revenue, 2)],
        "cogs": [round(cogs, 2)],
        "grossProfit": [round(gross_profit, 2)],
        "opex": [round(opex_val, 2)],
        "ebitda": [round(ebitda, 2)],
        "ebit": [round(ebit, 2)],
        "taxes": [round(taxes, 2)],
        "netIncome": [round(net_income, 2)],
    }

    return {
        "metrics": metrics,
        "statements": statements,
        "variances": [],
        "forecasts": forecasts,
        "assumptions": {
            **{k: v for k, v in assumptions.items() if isinstance(v, (int, float))},
            "capexPercent": capex_percent,
            "workingCapitalPercent": working_capital_percent,
            "daPercent": da_percent,
            "interestRate": interest_rate,
        },
        "data_source": data_source,
    }
