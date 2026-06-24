import json
import shutil
import uuid
from dataclasses import asdict

from fastapi import BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.projects._router import router  # shared: see _router.py
from app.core.auth import get_current_user, require_project_role
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
from app.schemas.common import ProjectSummary
from app.services.branding_service import BrandingService
from app.services.storage import ensure_workspace, workspace_path


class CreateProjectRequest(BaseModel):
    name: str


class UpdateProjectSettingsRequest(BaseModel):
    qa_threshold: float | None = None
    max_qa_loops: int | None = None
    hard_gate_enabled: bool | None = None
    web_search_provider: str | None = None
    tavily_enabled: bool | None = None
    tavily_api_key: str | None = None


def _ensure_workspace_safe(project_id: str) -> None:
    try:
        ensure_workspace(project_id)
    except Exception:  # noqa: S110 — best-effort, non-fatal
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
    response = {"project_id": pid, "qa_threshold": 0.8, "max_qa_loops": 2, "hard_gate_enabled": True}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                response.update(data)
        except Exception:  # noqa: S110 — best-effort, non-fatal
            pass
    if response.get("tavily_api_key"):
        response["tavily_configured"] = True
        del response["tavily_api_key"]
    return response


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
        except Exception:  # noqa: S110 — best-effort, non-fatal
            pass
    if body.qa_threshold is not None:
        current["qa_threshold"] = max(0.0, min(1.0, float(body.qa_threshold)))
    if body.max_qa_loops is not None:
        current["max_qa_loops"] = max(1, min(5, int(body.max_qa_loops)))
    if body.hard_gate_enabled is not None:
        current["hard_gate_enabled"] = bool(body.hard_gate_enabled)
    if body.web_search_provider is not None:
        provider = body.web_search_provider.strip().lower() if body.web_search_provider else ""
        if provider in {"brave", "google", "tavily", ""}:
            current["web_search_provider"] = provider if provider else None
        else:
            raise HTTPException(status_code=400, detail="Invalid web_search_provider")
    if body.tavily_enabled is not None:
        current["tavily_enabled"] = bool(body.tavily_enabled)
    if body.tavily_api_key is not None:
        current["tavily_api_key"] = body.tavily_api_key.strip() if body.tavily_api_key else ""
    settings_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    response = {"project_id": pid}
    response.update({k: v for k, v in current.items() if k != "tavily_api_key"})
    if current.get("tavily_api_key"):
        response["tavily_configured"] = True
    return response


@router.get("/{pid}/token-usage")
def get_project_token_usage(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return accumulated token counts and estimated cost for this project session."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    from app.services.llm_pricing import calculate_run_cost_usd
    from app.services.run_budget import get_project_usage
    usage = get_project_usage(pid)
    cost = calculate_run_cost_usd(**usage)
    return {
        "project_id": pid,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read_tokens": usage["cache_read_tokens"],
        "cache_creation_tokens": usage["cache_creation_tokens"],
        "cost_usd": cost,
    }


@router.get("/{pid}/branding")
def get_project_branding(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve the project's branding (color palette, fonts, logo) for the UI.

    Returns the same BrandingContext the deliverable renderers consume, so the
    frontend can honor a project's custom brand instead of static defaults.
    """
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    ctx = BrandingService(db).get_branding_for_run(str(pid))
    return {"project_id": pid, **asdict(ctx)}
