from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutionMilestone(BaseModel):
    output_type: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=300)


class CoordinatorPlanResponse(BaseModel):
    rationale: str = Field(default="", max_length=2000)
    ordered_output_types: list[str] = Field(default_factory=list)
    per_output_notes: dict[str, str] = Field(default_factory=dict)
    execution_milestones: list[ExecutionMilestone] = Field(default_factory=list)

