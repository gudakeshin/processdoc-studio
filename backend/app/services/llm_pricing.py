"""LLM token cost calculation based on per-MTok pricing."""
from __future__ import annotations

from app.core.config import settings


def calculate_run_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> float:
    p_in = getattr(settings, "llm_price_input_per_mtok", 3.00)
    p_out = getattr(settings, "llm_price_output_per_mtok", 15.00)
    p_cr = getattr(settings, "llm_price_cache_read_per_mtok", 0.30)
    p_cc = getattr(settings, "llm_price_cache_creation_per_mtok", 3.75)
    return round(
        input_tokens * p_in / 1_000_000
        + output_tokens * p_out / 1_000_000
        + cache_read_tokens * p_cr / 1_000_000
        + cache_creation_tokens * p_cc / 1_000_000,
        6,
    )
