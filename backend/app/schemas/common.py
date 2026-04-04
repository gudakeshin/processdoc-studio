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

