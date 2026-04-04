from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any


def _iso_like(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def infer_cell_schema(cell: dict[str, Any]) -> dict[str, Any]:
    value = cell.get("value")
    formula = cell.get("formula")
    number_format = str(cell.get("number_format") or "").lower()

    if formula:
        semantic_type = "formula"
        role = "derived"
        confidence = 0.98
        ambiguity: list[str] = []
    elif isinstance(value, bool):
        semantic_type = "bool"
        role = "metadata"
        confidence = 0.95
        ambiguity = []
    elif isinstance(value, (int, float, Decimal)):
        if "%" in number_format:
            semantic_type = "percent"
        elif "$" in number_format or "usd" in number_format or "eur" in number_format:
            semantic_type = "currency"
        else:
            semantic_type = "number"
        role = "assumption"
        confidence = 0.9
        ambiguity = []
    elif isinstance(value, datetime):
        semantic_type = "date"
        role = "dimension"
        confidence = 0.9
        ambiguity = []
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            semantic_type = "text"
            role = "metadata"
            confidence = 0.6
            ambiguity = ["empty_text"]
        elif _iso_like(stripped):
            semantic_type = "date"
            role = "dimension"
            confidence = 0.8
            ambiguity = ["iso_string_date"]
        elif len(stripped) <= 32 and stripped.replace("_", "").isalnum():
            semantic_type = "id"
            role = "identifier"
            confidence = 0.7
            ambiguity = ["alphanumeric_id_guess"]
        else:
            semantic_type = "text"
            role = "dimension"
            confidence = 0.75
            ambiguity = []
    elif value is None:
        semantic_type = "empty"
        role = "metadata"
        confidence = 0.0
        ambiguity = ["null_value"]
    else:
        semantic_type = "text"
        role = "metadata"
        confidence = 0.4
        ambiguity = ["fallback_type"]

    protected = semantic_type == "formula"
    unit_hint = "percent" if semantic_type == "percent" else None
    currency_hint = "USD" if semantic_type == "currency" else None

    return {
        "semantic_type": semantic_type,
        "role": role,
        "confidence": confidence,
        "ambiguity_flags": ambiguity,
        "unit_hint": unit_hint,
        "currency_hint": currency_hint,
        "protected": protected,
    }

