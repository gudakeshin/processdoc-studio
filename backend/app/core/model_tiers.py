"""Model-tier resolution for the Deloitte-quality program (Pillar A).

Planning and critique passes use stronger models; bulk slide/section drafting
stays on the configured default model (haiku). Routing is gated by
``settings.model_tiering_enabled`` so a single flag reverts to flat routing.
"""
from __future__ import annotations

from app.core.config import settings


def planning_model() -> str:
    """Model for narrative-spine / outline planning. Falls back to the default."""
    if getattr(settings, "model_tiering_enabled", True):
        m = str(getattr(settings, "anthropic_planning_model", "") or "").strip()
        if m:
            return m
    return settings.anthropic_claude_model


def critique_model() -> str:
    """Model for design-review / critique passes. Falls back to the default."""
    if getattr(settings, "model_tiering_enabled", True):
        m = str(getattr(settings, "anthropic_critique_model", "") or "").strip()
        if m:
            return m
    return settings.anthropic_claude_model
