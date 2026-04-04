"""Validated inputs for a single coordinator / run execution."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CoordinatorRunInput(BaseModel):
    """Required contract for state entering `Coordinator.coordinate()` / `run()`."""

    raw_text: str = ""
    user_instruction: str = ""
    requested_outputs: list[str] = Field(default_factory=list)
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    plan_payload: dict[str, Any] = Field(default_factory=dict)
    dpdp_flags: dict[str, Any] = Field(default_factory=lambda: {"enabled": True})
    qa_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    max_qa_loops: int = Field(default=2, ge=1, le=5)
    output_type_representations: dict[str, str] = Field(default_factory=dict)
    user_id: str | None = None

    def to_initial_state(self) -> dict[str, Any]:
        """Mutable execution dict; optional fields are added by the coordinator."""
        out: dict[str, Any] = {
            "raw_text": self.raw_text,
            "user_instruction": self.user_instruction,
            "requested_outputs": list(self.requested_outputs),
            "project_id": self.project_id,
            "run_id": self.run_id,
            "plan_payload": dict(self.plan_payload),
            "dpdp_flags": dict(self.dpdp_flags),
            "qa_threshold": self.qa_threshold,
            "max_qa_loops": self.max_qa_loops,
            "output_type_representations": dict(self.output_type_representations),
        }
        if self.user_id:
            out["user_id"] = self.user_id
        return out
