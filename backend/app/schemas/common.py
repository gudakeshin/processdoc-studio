from __future__ import annotations

from pydantic import BaseModel


class ProjectSummary(BaseModel):
    id: str
    name: str


class RunSummary(BaseModel):
    id: str
    status: str
    created_at: str | None = None
    instruction: str
    tokens_input: int | None = None
    tokens_output: int | None = None
    tokens_cache_read: int | None = None
    tokens_cache_creation: int | None = None
    cost_usd: float | None = None

