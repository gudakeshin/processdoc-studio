from pydantic import BaseModel, Field


class SkillCard(BaseModel):
    id: str
    domain: str
    display_name: str
    output_types: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    prompt_instructions: str = ""
    quality_thresholds: dict[str, float] = Field(default_factory=dict)
    custom: bool = False


class RunManifest(BaseModel):
    run_id: str
    project_id: str
    status: str
    output_types: list[str] = Field(default_factory=list)
    qa_scores: dict[str, float] = Field(default_factory=dict)
    guardrail_results: dict[str, str] = Field(default_factory=dict)
