from typing import Literal, TypedDict


class ProcessStep(TypedDict):
    id: str
    name: str
    role: str
    inputs: list[str]
    outputs: list[str]
    tools: list[str]
    duration_estimate: str
    notes: str


class DecisionBranch(TypedDict):
    id: str
    condition: str
    true_path: list[str]
    false_path: list[str]


class ProcessModel(TypedDict):
    process_name: str
    roles: list[str]
    steps: list[ProcessStep]
    decisions: list[DecisionBranch]
    swimlanes: dict[str, list[str]]
    metrics: list[dict[str, str]]  # [{stat, label, source}] — quantified facts extracted from context
    metadata: dict[str, str]


class ProcessDocState(TypedDict, total=False):
    raw_text: str
    user_instruction: str
    user_intent_original: str  # Immutable — clean user intent extracted once at init; never appended to
    requested_outputs: list[str]
    process_model: ProcessModel
    style_profile: dict[str, str]
    assembled_context: str
    drawio_xml: str
    raci_html: str
    sop_markdown: str
    narrative_md: str
    skill_card: dict
    plan_payload: dict
    lp_snippets: list[dict]
    web_search_results: list[dict]
    qa_report: dict
    guardrail_report: dict
    dpdp_flags: dict
    run_id: str
    project_id: str
    user_id: str
    workspace_path: str
    retry_count: int
    compaction_snapshot: dict
    memory_summary: dict
    coordinator_execution_plan: dict
    run_todos: list[dict]
    _emit_run_event: object


SSEEventType = Literal[
    "plan_ready",
    "step",
    "output_chunk",
    "qa_report",
    "guardrail_event",
    "done",
]
