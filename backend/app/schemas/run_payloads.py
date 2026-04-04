"""Validated shapes for persisted / coordinator JSON blobs (soft contracts)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanPayloadDoc(BaseModel):
    """Minimal structure for persisted plan JSON; extra keys preserved."""

    model_config = ConfigDict(extra="allow")

    output_type_representations: dict[str, str] = Field(default_factory=dict)
    run_contract: dict[str, Any] | None = None
    content_skill_targets: dict[str, str] | None = None


class QaReportDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    passed: bool = False
    scores: dict[str, Any] = Field(default_factory=dict)


class GuardrailReportDoc(BaseModel):
    model_config = ConfigDict(extra="allow")

    overall_passed: bool | None = None
