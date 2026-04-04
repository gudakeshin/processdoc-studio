import uuid
import json
import shutil
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
from app.db.models import (
    ConsentLedger,
    Conversation,
    ConversationMessage,
    DPDPRightsRequest,
    Membership,
    MemoryEvent,
    MemoryItem,
    Project,
    ProjectMemoryProfile,
    Run,
    RunEvent,
    ScheduledTask,
    ScheduledTaskRun,
    User,
    UserProjectPreference,
)
from app.db.session import get_db
from app.services.storage import ensure_workspace, workspace_path
from app.services.proposal_policy import derive_proposal_skill_targets
from app.api.formats import _load_output_types
from app.api.runs import _recommend_output_types
from app.services.run_worker import append_run_event
from app.schemas.common import ProjectSummary

router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str


class UpdateProjectSettingsRequest(BaseModel):
    qa_threshold: float | None = None
    max_qa_loops: int | None = None
    hard_gate_enabled: bool | None = None


class ConversationMessageRequest(BaseModel):
    content: str


class DecisionAnswer(BaseModel):
    prompt_id: str
    selected_values: list[str]
    free_text: str | None = None


class ConversationDecisionRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None
    answers: list[DecisionAnswer]


class ConversationConfirmRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None


class UserProjectPreferencesBody(BaseModel):
    """Lines merged into coordinator NonNegotiables (assemble_v2) for this user+project."""

    context_lines: list[str] | None = None
    # Optional counters for future behavioral-learning (v4 §5.1.1); stored opaque in JSON.
    learning_signals: dict[str, int] | None = None


class ScheduledTaskCreateBody(BaseModel):
    name: str
    instruction: str
    output_types: list[str] = []
    custom_output_types: list[str] = []
    output_type_representations: dict[str, str] = {}
    trigger_type: str = "interval"
    cadence_minutes: int = 60
    run_at: str | None = None
    timezone: str = "UTC"
    retry_limit: int = 3


class ScheduledTaskUpdateBody(BaseModel):
    name: str | None = None
    instruction: str | None = None
    output_types: list[str] | None = None
    custom_output_types: list[str] | None = None
    output_type_representations: dict[str, str] | None = None
    trigger_type: str | None = None
    cadence_minutes: int | None = None
    run_at: str | None = None
    timezone: str | None = None
    retry_limit: int | None = None
    status: str | None = None


def _detail(code: str, message: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _build_plan_hash(
    *,
    instruction: str,
    template_ids: list[str],
    custom_output_types: list[str],
    reps: dict[str, str],
    content_skill_targets: dict[str, str] | None = None,
    regeneration_directive: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "instruction": instruction.strip(),
            "template_output_types": template_ids,
            "custom_output_types": custom_output_types,
            "output_type_representations": reps,
            "content_skill_targets": content_skill_targets or {},
            "regeneration_directive": (regeneration_directive or "").strip(),
        },
        sort_keys=True,
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, payload).hex


def _latest_assistant_plan_metadata(messages: list[dict]) -> dict | None:
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        metadata = msg.get("metadata")
        if isinstance(metadata, dict) and metadata.get("plan_hash"):
            return metadata
    return None


def _sanitize_decision_answers(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        values = [str(x).strip() for x in (v if isinstance(v, list) else []) if str(x).strip()]
        out[key] = values[:5]
    return out


def _build_decision_prompts(
    *,
    content: str,
    template_ids: list[str],
    custom_output_types: list[str],
    current_answers: dict[str, list[str]],
) -> tuple[list[dict], list[str], list[str], list[str]]:
    """Return (decision_prompts, unresolved_ids, blocking_questions, soft_hints).

    ``blocking_questions`` are tied 1-to-1 with ``unresolved_ids`` and gate
    confirmation.  ``soft_hints`` are advisory messages shown to the user but
    they never prevent plan confirmation.
    """
    if not settings.instruction_decision_prompts_enabled:
        return [], [], [], []
    prompts: list[dict] = []
    unresolved: list[str] = []
    open_questions: list[str] = []
    soft_hints: list[str] = []
    deliverable_opts = [
        {"value": "proposal", "label": "Proposal"},
        {"value": "report", "label": "Report"},
        {"value": "sop", "label": "SOP"},
        {"value": "deck", "label": "Deck / presentation"},
    ]
    selected_primary = current_answers.get("primary_deliverable", [])
    prompts.append(
        {
            "id": "primary_deliverable",
            "label": "Select the primary deliverable type",
            "mode": "single_select",
            "required": True,
            "options": deliverable_opts,
            "selected_values": selected_primary[:1],
        }
    )
    if not selected_primary:
        unresolved.append("primary_deliverable")
        open_questions.append(
            "Please confirm the primary deliverable type (for example proposal, report, SOP, or deck)."
        )

    if not template_ids and not custom_output_types:
        format_opts = [
            {"value": "process_map", "label": "Process map"},
            {"value": "docx", "label": "Word (DOCX)"},
            {"value": "pptx", "label": "Slides (PPTX)"},
            {"value": "xlsx", "label": "Spreadsheet (XLSX)"},
            {"value": "pdf", "label": "PDF"},
        ]
        selected_formats = current_answers.get("preferred_outputs", [])
        prompts.append(
            {
                "id": "preferred_outputs",
                "label": "Select one or more preferred outputs",
                "mode": "multi_select",
                "required": True,
                "options": format_opts,
                "selected_values": selected_formats[:5],
                "min_select": 1,
            }
        )
        if not selected_formats:
            unresolved.append("preferred_outputs")
            open_questions.append("Which output formats should be prioritized for this run?")

    if len(content.split()) < 8:
        soft_hints.append("Could you add more detail on deliverable scope, audience, and level of depth?")

    return prompts, unresolved, open_questions, soft_hints


def _instruction_may_warrant_strategy_options(text: str) -> bool:
    s = (text or "").strip()
    if len(s.split()) < 8:
        return False
    t = s.lower()
    keys = (
        "analy",
        "dataset",
        "excel",
        "csv",
        "spreadsheet",
        "client data",
        "approach",
        "tradeoff",
        "evaluate",
        "hypothesis",
        "segment",
        "scenario",
    )
    return any(k in t for k in keys)


def _is_redo_followup(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    keys = ("redo", "regenerate", "rework", "rewrite", "revise", "try again", "again")
    return any(k in t for k in keys)


def _derive_content_skill_targets(
    *,
    instruction: str,
    template_ids: list[str],
    prior_plan_meta: dict | None = None,
) -> dict[str, str]:
    targets = derive_proposal_skill_targets(instruction=instruction, output_types=template_ids, base_targets=None)
    if prior_plan_meta and _is_redo_followup(instruction):
        prior_targets = prior_plan_meta.get("content_skill_targets")
        if isinstance(prior_targets, dict):
            for out in template_ids:
                prev = str(prior_targets.get(out) or "").strip()
                if prev:
                    targets[out] = prev
    return targets


def _build_regeneration_directive(content: str) -> str:
    if not _is_redo_followup(content):
        return ""
    return (
        "Regeneration directive: produce a materially different draft while preserving factual consistency. "
        "Change at least three dimensions: (1) storyline framing, (2) value-case structure and levers, "
        "(3) risk/mitigation articulation. Avoid near-verbatim reuse of prior section wording."
    )


def _persist_assistant_plan_message(
    *,
    db: Session,
    conv: Conversation,
    content: str,
    instruction: str,
    template_ids: list[str],
    custom_output_types: list[str],
    output_type_representations: dict[str, str],
    rationale: str,
    decision_answers: dict[str, list[str]] | None = None,
    content_skill_targets: dict[str, str] | None = None,
    regeneration_directive: str | None = None,
) -> dict:
    decision_answers = decision_answers or {}
    content_skill_targets = {
        str(k).strip(): str(v).strip()
        for k, v in (content_skill_targets or {}).items()
        if str(k).strip() and str(v).strip()
    }
    regeneration_directive = (regeneration_directive or "").strip()
    decision_prompts, unresolved_prompt_ids, open_questions, soft_hints = _build_decision_prompts(
        content=content,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        current_answers=decision_answers,
    )
    strategy_dossier: dict | None = None
    if settings.strategy_options_planning_enabled and _instruction_may_warrant_strategy_options(instruction):
        try:
            from app.services.strategy_plan import generate_strategy_options

            strategy_dossier = generate_strategy_options(instruction=instruction)
        except Exception:
            strategy_dossier = None
        opts = strategy_dossier.get("options") if isinstance(strategy_dossier, dict) else None
        if isinstance(opts, list) and len(opts) >= 2:
            strat_prompt = {
                "id": "execution_strategy",
                "label": "Choose an execution approach",
                "mode": "single_select",
                "required": True,
                "options": [
                    {"value": str(o["id"]), "label": str(o["title"])[:280]}
                    for o in opts
                    if isinstance(o, dict) and str(o.get("id") or "").strip() and str(o.get("title") or "").strip()
                ],
                "selected_values": (decision_answers.get("execution_strategy") or [])[:1],
            }
            if strat_prompt["options"]:
                decision_prompts = [strat_prompt] + decision_prompts
                if not decision_answers.get("execution_strategy"):
                    unresolved_prompt_ids = ["execution_strategy"] + unresolved_prompt_ids
                    open_questions = [
                        "Select one of the proposed execution approaches (see Approaches below).",
                    ] + open_questions
    ready_for_confirmation = len(unresolved_prompt_ids) == 0
    display_open_questions = open_questions + soft_hints
    plan_hash = _build_plan_hash(
        instruction=instruction,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        reps=output_type_representations,
        content_skill_targets=content_skill_targets,
        regeneration_directive=regeneration_directive,
    )
    approval_reason = "Plan is ready for confirmation." if ready_for_confirmation else "Clarification required before confirmation."
    plan_summary = (
        f"Draft plan: {rationale} | outputs={', '.join(template_ids) if template_ids else 'none'} | "
        f"custom={', '.join(custom_output_types) if custom_output_types else 'none'}"
    )
    strategy_md = ""
    if isinstance(strategy_dossier, dict) and strategy_dossier.get("options"):
        from app.services.strategy_plan import format_strategy_dossier_markdown

        strategy_md = "\n\n" + format_strategy_dossier_markdown(strategy_dossier)
    assistant_content = (
        f"{plan_summary}\n"
        f"Template outputs: {', '.join(template_ids) if template_ids else 'none'}\n"
        f"Custom outputs: {', '.join(custom_output_types) if custom_output_types else 'none'}\n"
        f"Proposed representations: {json.dumps(output_type_representations)}\n"
        + (
            "Open questions:\n- " + "\n- ".join(display_open_questions)
            if display_open_questions
            else "No open questions. Confirm plan to continue to execution."
        )
        + strategy_md
    )
    metadata_obj = {
        "template_output_types": template_ids,
        "custom_output_types": custom_output_types,
        "output_type_representations": output_type_representations,
        "content_skill_targets": content_skill_targets,
        "regeneration_directive": regeneration_directive,
        "requires_output_type_confirmation": True,
        "requires_user_approval": True,
        "ready_to_run": False,
        "approval_reason": approval_reason,
        "rationale": rationale,
        "instruction": instruction,
        "plan_summary": plan_summary,
        "open_questions": display_open_questions,
        "soft_hints": soft_hints,
        "decision_prompts": decision_prompts,
        "decision_answers": decision_answers,
        "unresolved_prompt_ids": unresolved_prompt_ids,
        "ready_for_confirmation": ready_for_confirmation,
        "requires_confirmation": True,
        "plan_hash": plan_hash,
        "strategy_dossier": strategy_dossier,
    }
    assistant_msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=assistant_content,
        metadata_json=json.dumps(metadata_obj),
    )
    db.add(assistant_msg)
    conv.updated_at = datetime.utcnow()
    db.commit()
    return {
        "conversation_id": conv.id,
        "template_output_types": template_ids,
        "custom_output_types": custom_output_types,
        "output_type_representations": output_type_representations,
        "content_skill_targets": content_skill_targets,
        "regeneration_directive": regeneration_directive,
        "requires_output_type_confirmation": True,
        "requires_user_approval": True,
        "ready_to_run": False,
        "approval_reason": approval_reason,
        "rationale": rationale,
        "plan_summary": plan_summary,
        "open_questions": display_open_questions,
        "soft_hints": soft_hints,
        "decision_prompts": decision_prompts,
        "decision_answers": decision_answers,
        "unresolved_prompt_ids": unresolved_prompt_ids,
        "ready_for_confirmation": ready_for_confirmation,
        "requires_confirmation": True,
        "plan_hash": plan_hash,
        "messages": _serialize_messages(db, conv.id),
    }


def _get_or_create_conversation(db: Session, *, pid: str, user_id: str) -> Conversation:
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.project_id == pid, Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    if conv:
        return conv
    conv = Conversation(
        id=f"conv_{uuid.uuid4().hex[:10]}",
        project_id=pid,
        user_id=user_id,
        title="Cowork Session",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _serialize_messages(db: Session, conversation_id: str) -> list[dict]:
    rows = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.id.asc())
    ).all()
    out: list[dict] = []
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json) if row.metadata_json else {}
            if not isinstance(metadata, dict):
                metadata = {}
        except Exception:
            metadata = {}
        out.append(
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "metadata": metadata,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out


def _ensure_workspace_safe(project_id: str) -> None:
    try:
        ensure_workspace(project_id)
    except Exception:
        # Workspace creation is retried by downstream endpoints that require it.
        pass


@router.get("", response_model=dict[str, list[ProjectSummary]])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(Project).join(Membership, Membership.project_id == Project.id).where(Membership.user_id == user.id)
    ).all()
    return {"items": [{"id": p.id, "name": p.name} for p in rows]}


@router.post("")
def create_project(
    body: CreateProjectRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = Project(id=f"p_{uuid.uuid4().hex[:10]}", name=body.name, created_by=user.id)
    db.add(project)
    db.add(Membership(id=f"m_{uuid.uuid4().hex[:10]}", project_id=project.id, user_id=user.id, role="Owner"))
    db.commit()
    background_tasks.add_task(_ensure_workspace_safe, project.id)
    return {"id": project.id, "name": project.name, "roles": ["Owner", "Editor", "Viewer"]}


@router.delete("/{pid}")
def delete_project(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.scalar(select(Project).where(Project.id == pid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    membership = db.scalar(select(Membership).where(Membership.project_id == pid, Membership.user_id == user.id))
    if membership is None or membership.role != "Owner":
        raise HTTPException(status_code=403, detail="Insufficient project permissions")

    run_ids = db.scalars(select(Run.id).where(Run.project_id == pid)).all()
    if run_ids:
        db.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
        db.execute(delete(MemoryEvent).where(MemoryEvent.run_id.in_(run_ids)))
        db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.run_id.in_(run_ids)))

    task_ids = db.scalars(select(ScheduledTask.id).where(ScheduledTask.project_id == pid)).all()
    if task_ids:
        db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.task_id.in_(task_ids)))

    conv_ids = db.scalars(select(Conversation.id).where(Conversation.project_id == pid)).all()
    if conv_ids:
        db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id.in_(conv_ids)))

    db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.project_id == pid))
    db.execute(delete(ScheduledTask).where(ScheduledTask.project_id == pid))
    db.execute(delete(MemoryItem).where(MemoryItem.project_id == pid))
    db.execute(delete(UserProjectPreference).where(UserProjectPreference.project_id == pid))
    db.execute(delete(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == pid))
    db.execute(delete(Conversation).where(Conversation.project_id == pid))
    db.execute(delete(Membership).where(Membership.project_id == pid))
    db.execute(delete(Run).where(Run.project_id == pid))
    db.execute(delete(ConsentLedger).where(ConsentLedger.project_id == pid))
    db.execute(delete(DPDPRightsRequest).where(DPDPRightsRequest.project_id == pid))
    db.execute(delete(Project).where(Project.id == pid))
    db.commit()

    project_workspace = workspace_path(pid)
    if project_workspace.exists():
        shutil.rmtree(project_workspace, ignore_errors=True)
    return {"project_id": pid, "deleted": True}


@router.get("/{pid}/settings")
def get_project_settings(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    membership = db.scalar(
        select(Project).join(Membership, Membership.project_id == Project.id).where(
            Project.id == pid, Membership.user_id == user.id
        )
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Insufficient project permissions")
    settings_path = workspace_path(pid) / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {"project_id": pid, **data}
        except Exception:
            pass
    return {"project_id": pid, "qa_threshold": 0.8, "max_qa_loops": 2, "hard_gate_enabled": True}


@router.put("/{pid}/settings")
def update_project_settings(
    pid: str,
    body: UpdateProjectSettingsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    # Owner/Editor can edit settings.
    membership = db.scalar(
        select(Membership).where(Membership.project_id == pid, Membership.user_id == user.id)
    )
    if not membership or membership.role not in {"Owner", "Editor"}:
        raise HTTPException(status_code=403, detail="Insufficient project permissions")

    ensure_workspace(pid)
    current = {"qa_threshold": 0.8, "max_qa_loops": 2, "hard_gate_enabled": True}
    settings_path = workspace_path(pid) / "settings.json"
    if settings_path.exists():
        try:
            parsed = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                current.update(parsed)
        except Exception:
            pass
    if body.qa_threshold is not None:
        current["qa_threshold"] = max(0.0, min(1.0, float(body.qa_threshold)))
    if body.max_qa_loops is not None:
        current["max_qa_loops"] = max(1, min(5, int(body.max_qa_loops)))
    if body.hard_gate_enabled is not None:
        current["hard_gate_enabled"] = bool(body.hard_gate_enabled)
    settings_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return {"project_id": pid, **current}


@router.get("/{pid}/conversation")
def get_project_conversation(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id)
    return {"conversation_id": conv.id, "messages": _serialize_messages(db, conv.id)}


@router.post("/{pid}/conversation/messages")
def post_project_conversation_message(
    pid: str,
    body: ConversationMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id)

    user_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content=content[:6000],
        metadata_json="{}",
    )
    db.add(user_msg)
    db.flush()

    available_output_types = [
        item for item in _load_output_types() if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]
    prior_messages = _serialize_messages(db, conv.id)
    prior_plan_meta = _latest_assistant_plan_metadata(prior_messages)
    history_prompt = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-12:]
        if str(m.get("content") or "").strip()
    )
    base_instruction = str((prior_plan_meta or {}).get("instruction") or "").strip()
    if _is_redo_followup(content) and base_instruction:
        combined_instruction = f"{base_instruction}\n\nUser follow-up: {content}".strip()
    else:
        combined_instruction = f"{history_prompt}\nuser: {content}".strip()
    template_ids, custom_output_types, output_type_representations, rationale = _recommend_output_types(
        combined_instruction, available_output_types
    )
    content_skill_targets = _derive_content_skill_targets(
        instruction=combined_instruction,
        template_ids=template_ids,
        prior_plan_meta=prior_plan_meta if isinstance(prior_plan_meta, dict) else None,
    )
    regeneration_directive = _build_regeneration_directive(content)
    response = _persist_assistant_plan_message(
        db=db,
        conv=conv,
        content=content,
        instruction=combined_instruction,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        output_type_representations=output_type_representations,
        rationale=rationale,
        content_skill_targets=content_skill_targets,
        regeneration_directive=regeneration_directive,
    )
    response["memory_quick_add"] = {
        "memory_page_path": "/memory",
        "batch_api_relative": f"/api/memory/{pid}/batch",
        "hint": "Save durable facts to Memory (or batch API after review); they are merged into run context when compaction is enabled.",
    }
    return response


@router.post("/{pid}/conversation/decisions")
def post_project_conversation_decisions(
    pid: str,
    body: ConversationDecisionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id)
    if body.conversation_id and body.conversation_id != conv.id:
        raise HTTPException(
            status_code=400,
            detail=_detail("conversation_id_mismatch", "conversation_id does not match current conversation"),
        )
    messages = _serialize_messages(db, conv.id)
    plan_meta = _latest_assistant_plan_metadata(messages)
    if not plan_meta:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_missing", "No assistant plan is available for decision updates"),
        )
    latest_plan_hash = str(plan_meta.get("plan_hash") or "")
    if body.plan_hash and body.plan_hash != latest_plan_hash:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_changed", "Plan changed. Please resolve decisions on the latest plan"),
        )
    answers_map: dict[str, list[str]] = {}
    for ans in body.answers:
        key = (ans.prompt_id or "").strip()
        if not key:
            continue
        values = [str(v).strip() for v in (ans.selected_values or []) if str(v).strip()]
        if ans.free_text and ans.free_text.strip():
            values.append(ans.free_text.strip())
        answers_map[key] = values[:5]
    if not answers_map:
        raise HTTPException(
            status_code=400,
            detail=_detail("answers_missing", "answers must include at least one selected value"),
        )

    prior_answers = _sanitize_decision_answers(plan_meta.get("decision_answers"))
    merged_answers = {**prior_answers, **answers_map}
    assistant_instruction = str(plan_meta.get("instruction") or "").strip()
    if not assistant_instruction:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_instruction_missing", "Latest plan is missing instruction context"),
        )
    decision_lines = []
    for k, vals in merged_answers.items():
        if vals:
            decision_lines.append(f"{k}: {', '.join(vals)}")
    enriched_instruction = assistant_instruction
    if decision_lines:
        enriched_instruction = (
            f"{assistant_instruction}\n\nUser-confirmed decisions:\n- " + "\n- ".join(decision_lines)
        )
    available_output_types = [
        item for item in _load_output_types() if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]
    template_ids, custom_output_types, output_type_representations, rationale = _recommend_output_types(
        enriched_instruction, available_output_types
    )

    user_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content=(
            "Decision update: "
            + "; ".join([f"{k}={','.join(v)}" for k, v in merged_answers.items() if v])[:5000]
        ),
        metadata_json=json.dumps({"decision_answers": merged_answers, "plan_hash": latest_plan_hash}),
    )
    db.add(user_msg)
    db.flush()

    return _persist_assistant_plan_message(
        db=db,
        conv=conv,
        content=enriched_instruction,
        instruction=assistant_instruction,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        output_type_representations=output_type_representations,
        rationale=rationale,
        decision_answers=merged_answers,
        content_skill_targets=plan_meta.get("content_skill_targets")
        if isinstance(plan_meta.get("content_skill_targets"), dict)
        else {},
        regeneration_directive=str(plan_meta.get("regeneration_directive") or ""),
    )


@router.delete("/{pid}/conversation")
def clear_project_conversation(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.project_id == pid, Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    if conv is None:
        return {"cleared": False}
    db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id == conv.id))
    db.execute(delete(Conversation).where(Conversation.id == conv.id))
    db.commit()
    return {"cleared": True}


@router.post("/{pid}/conversation/confirm")
def confirm_project_conversation_plan(
    pid: str,
    body: ConversationConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id)
    if body.conversation_id and body.conversation_id != conv.id:
        raise HTTPException(
            status_code=400,
            detail=_detail("conversation_id_mismatch", "conversation_id does not match current conversation"),
        )
    messages = _serialize_messages(db, conv.id)
    plan_meta = _latest_assistant_plan_metadata(messages)
    if not plan_meta:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_missing", "No assistant plan is available to confirm"),
        )
    if not bool(plan_meta.get("ready_for_confirmation")):
        raise HTTPException(
            status_code=409,
            detail=_detail(
                "plan_open_questions",
                "Plan still has open questions and cannot be confirmed",
                unresolved_prompt_ids=plan_meta.get("unresolved_prompt_ids") or [],
                open_questions=plan_meta.get("open_questions") or [],
            ),
        )
    plan_hash = str(plan_meta.get("plan_hash") or "")
    if body.plan_hash and body.plan_hash != plan_hash:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_changed", "Plan changed. Please reconfirm the latest plan", latest_plan_hash=plan_hash),
        )
    da = _sanitize_decision_answers(plan_meta.get("decision_answers"))
    dossier = plan_meta.get("strategy_dossier") if isinstance(plan_meta.get("strategy_dossier"), dict) else None
    from app.services.strategy_plan import resolve_selected_strategy

    selected_strategy = resolve_selected_strategy(dossier, da)
    confirm_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content="Confirmed plan for execution.",
        metadata_json=json.dumps(
            {
                "plan_confirmed": True,
                "plan_hash": plan_hash,
                "instruction": str(plan_meta.get("instruction") or ""),
                "template_output_types": plan_meta.get("template_output_types") or [],
                "custom_output_types": plan_meta.get("custom_output_types") or [],
                "output_type_representations": plan_meta.get("output_type_representations") or {},
                "content_skill_targets": plan_meta.get("content_skill_targets")
                if isinstance(plan_meta.get("content_skill_targets"), dict)
                else {},
                "regeneration_directive": str(plan_meta.get("regeneration_directive") or ""),
                "confirmed_at": datetime.utcnow().isoformat(),
                "decision_answers": da,
                "strategy_dossier": dossier,
                "selected_strategy": selected_strategy,
            }
        ),
    )
    db.add(confirm_msg)
    conv.updated_at = datetime.utcnow()
    db.commit()
    return {
        "conversation_id": conv.id,
        "confirmed": True,
        "plan_hash": plan_hash,
        "instruction": str(plan_meta.get("instruction") or ""),
        "template_output_types": plan_meta.get("template_output_types") or [],
        "custom_output_types": plan_meta.get("custom_output_types") or [],
        "output_type_representations": plan_meta.get("output_type_representations") or {},
        "content_skill_targets": plan_meta.get("content_skill_targets")
        if isinstance(plan_meta.get("content_skill_targets"), dict)
        else {},
        "regeneration_directive": str(plan_meta.get("regeneration_directive") or ""),
    }


@router.get("/{pid}/me/preferences")
def get_my_project_preferences(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    row = db.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user.id,
            UserProjectPreference.project_id == pid,
        )
    )
    if row is None:
        return {"project_id": pid, "context_lines": [], "learning_signals": {}, "updated_at": None}
    try:
        data = json.loads(row.preferences_json) if row.preferences_json else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    lines = data.get("context_lines")
    ls = data.get("learning_signals")
    return {
        "project_id": pid,
        "context_lines": lines if isinstance(lines, list) else [],
        "learning_signals": ls if isinstance(ls, dict) else {},
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.patch("/{pid}/me/preferences")
def patch_my_project_preferences(
    pid: str,
    body: UserProjectPreferencesBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user.id,
            UserProjectPreference.project_id == pid,
        )
    )
    base: dict = {}
    if row is not None:
        try:
            parsed = json.loads(row.preferences_json) if row.preferences_json else {}
            if isinstance(parsed, dict):
                base = parsed
        except Exception:
            base = {}
    if body.context_lines is not None:
        base["context_lines"] = [str(x).strip() for x in body.context_lines if str(x).strip()][:50]
    if body.learning_signals is not None:
        prev = base.get("learning_signals")
        merged = dict(prev) if isinstance(prev, dict) else {}
        for k, v in body.learning_signals.items():
            if not k or len(str(k)) > 64:
                continue
            try:
                merged[str(k)[:64]] = int(v)
            except (TypeError, ValueError):
                continue
        base["learning_signals"] = merged
    payload = json.dumps(base, sort_keys=True)
    now = datetime.utcnow()
    if row is None:
        row = UserProjectPreference(user_id=user.id, project_id=pid, preferences_json=payload, updated_at=now)
        db.add(row)
    else:
        row.preferences_json = payload
        row.updated_at = now
    db.commit()
    return get_my_project_preferences(pid, user, db)


@router.get("/{pid}/admin/team-personalization")
def get_team_personalization_summary(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner"}, user, db)
    total_items = int(
        db.scalar(
            select(func.count())
            .select_from(MemoryItem)
            .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        )
        or 0
    )
    by_type_rows = db.execute(
        select(MemoryItem.memory_type, func.count())
        .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        .group_by(MemoryItem.memory_type)
    ).all()
    by_source_rows = db.execute(
        select(MemoryItem.source, func.count())
        .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        .group_by(MemoryItem.source)
    ).all()
    pref_users = int(
        db.scalar(select(func.count()).select_from(UserProjectPreference).where(UserProjectPreference.project_id == pid))
        or 0
    )
    return {
        "project_id": pid,
        "memory_items_total": total_items,
        "memory_items_by_type": {str(r[0]): int(r[1]) for r in by_type_rows},
        "memory_items_by_source": {str(r[0]): int(r[1]) for r in by_source_rows},
        "users_with_saved_preferences": pref_users,
    }


@router.get("/{pid}/scheduled-tasks")
def list_scheduled_tasks(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    rows = db.scalars(select(ScheduledTask).where(ScheduledTask.project_id == pid).order_by(ScheduledTask.created_at.desc())).all()
    items: list[dict] = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "instruction": row.instruction,
                "status": row.status,
                "trigger_type": row.trigger_type,
                "cadence_minutes": row.cadence_minutes,
                "run_at": row.run_at.isoformat() if row.run_at else None,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
                "last_run_status": row.last_run_status,
                "output_types": json.loads(row.output_types_json or "[]"),
                "custom_output_types": json.loads(row.custom_output_types_json or "[]"),
                "output_type_representations": json.loads(row.output_type_representations_json or "{}"),
            }
        )
    return {"project_id": pid, "items": items}


@router.post("/{pid}/scheduled-tasks")
def create_scheduled_task(
    pid: str,
    body: ScheduledTaskCreateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    run_at_dt = None
    if body.run_at:
        try:
            run_at_dt = datetime.fromisoformat(body.run_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid run_at ISO timestamp")
    task = ScheduledTask(
        id=f"task_{uuid.uuid4().hex[:10]}",
        project_id=pid,
        created_by=user.id,
        name=(body.name or "").strip()[:255],
        instruction=(body.instruction or "").strip()[:6000],
        output_types_json=json.dumps(list(dict.fromkeys(body.output_types or []))),
        custom_output_types_json=json.dumps(body.custom_output_types or []),
        output_type_representations_json=json.dumps(body.output_type_representations or {}),
        trigger_type=body.trigger_type if body.trigger_type in {"interval", "once"} else "interval",
        cadence_minutes=max(1, int(body.cadence_minutes or 60)),
        run_at=run_at_dt,
        timezone=(body.timezone or "UTC").strip()[:64],
        retry_limit=max(0, int(body.retry_limit or 3)),
        status="active",
    )
    task.next_run_at = task.run_at if task.trigger_type == "once" else (datetime.utcnow() + timedelta(minutes=task.cadence_minutes))
    db.add(task)
    db.commit()
    return {"project_id": pid, "task_id": task.id, "status": "created"}


@router.patch("/{pid}/scheduled-tasks/{task_id}")
def update_scheduled_task(
    pid: str,
    task_id: str,
    body: ScheduledTaskUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if body.name is not None:
        row.name = body.name.strip()[:255]
    if body.instruction is not None:
        row.instruction = body.instruction.strip()[:6000]
    if body.output_types is not None:
        row.output_types_json = json.dumps(list(dict.fromkeys(body.output_types)))
    if body.custom_output_types is not None:
        row.custom_output_types_json = json.dumps(body.custom_output_types)
    if body.output_type_representations is not None:
        row.output_type_representations_json = json.dumps(body.output_type_representations)
    if body.trigger_type in {"interval", "once"}:
        row.trigger_type = body.trigger_type
    if body.cadence_minutes is not None:
        row.cadence_minutes = max(1, int(body.cadence_minutes))
    if body.timezone is not None:
        row.timezone = body.timezone.strip()[:64]
    if body.retry_limit is not None:
        row.retry_limit = max(0, int(body.retry_limit))
    if body.status in {"active", "paused", "archived"}:
        row.status = body.status
    if body.run_at is not None:
        row.run_at = datetime.fromisoformat(body.run_at.replace("Z", "+00:00")).replace(tzinfo=None) if body.run_at else None
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.utcnow() + timedelta(minutes=row.cadence_minutes))
    if row.status != "active":
        row.next_run_at = None
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "updated"}


@router.post("/{pid}/scheduled-tasks/{task_id}/pause")
def pause_scheduled_task(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "paused"
    row.next_run_at = None
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "paused"}


@router.post("/{pid}/scheduled-tasks/{task_id}/resume")
def resume_scheduled_task(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "active"
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.utcnow() + timedelta(minutes=row.cadence_minutes))
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "active"}


@router.post("/{pid}/scheduled-tasks/{task_id}/run-now")
def run_scheduled_task_now(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    plan = {
        "skill_card": "auto_selected",
        "sub_agents": json.loads(row.output_types_json or "[]"),
        "custom_output_types": json.loads(row.custom_output_types_json or "[]"),
        "output_type_representations": json.loads(row.output_type_representations_json or "{}"),
        "scheduled_task_id": row.id,
    }
    run = Run(
        id=run_id,
        project_id=pid,
        status="plan_ready",
        output_types=row.output_types_json,
        instruction=row.instruction,
        plan_payload=json.dumps(plan),
    )
    db.add(run)
    append_run_event(db, run_id, "scheduled_task.run_started", {"task_id": row.id, "project_id": pid})
    append_run_event(db, run_id, "plan_ready", plan)
    append_run_event(db, run_id, "step", {"status": "awaiting_hitl_approval", "source": "scheduled_task"})
    db.add(
        ScheduledTaskRun(
            id=f"str_{uuid.uuid4().hex[:10]}",
            task_id=row.id,
            project_id=pid,
            run_id=run_id,
            status="plan_ready",
            message="Run-now created and awaiting approval",
        )
    )
    row.last_run_at = datetime.utcnow()
    row.last_run_status = "queued"
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": pid, "task_id": task_id, "run_id": run_id, "status": "plan_ready"}
