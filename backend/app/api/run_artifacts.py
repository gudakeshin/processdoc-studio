import json
import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.db.models import MemoryEvent, Project, ProjectMemoryProfile, Run, RunEvent, User
from app.db.session import get_db
from app.services.storage import workspace_path

router = APIRouter()


class RunArtifactsResponse(BaseModel):
    run_id: str
    project_id: str
    status: str
    instruction: str
    output_types: list[str]
    custom_output_types: list[str]
    output_type_representations: dict[str, str]
    artifacts: dict[str, object | None]


def _read_text(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _read_json(path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def _read_base64(path) -> str:
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except FileNotFoundError:
        return ""


def _tokenize_filename(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "Unknown"
    filtered = "".join(ch if ch.isalnum() else " " for ch in text)
    parts = [p for p in filtered.split() if p]
    if not parts:
        return "Unknown"
    return "".join(part.capitalize() for part in parts)


def _latest_run_event_payload(db: Session, run_id: str, event_type: str) -> object | None:
    ev = db.scalar(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.event_type == event_type)
        .order_by(RunEvent.id.desc())
        .limit(1)
    )
    if not ev:
        return None

    try:
        return json.loads(ev.payload)
    except json.JSONDecodeError:
        return ev.payload


@router.get("/{project_id}/{run_id}/artifacts", response_model=RunArtifactsResponse)
def get_run_artifacts(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunArtifactsResponse:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)

    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        output_types = json.loads(run.output_types) if run.output_types else []
        if not isinstance(output_types, list):
            output_types = []
    except json.JSONDecodeError:
        output_types = []
    custom_output_types: list[str] = []
    output_type_representations: dict[str, str] = {}
    if run.plan_payload:
        try:
            plan_payload = json.loads(run.plan_payload)
            if isinstance(plan_payload, dict):
                custom = plan_payload.get("custom_output_types")
                if isinstance(custom, list):
                    custom_output_types = [str(item) for item in custom if str(item).strip()]
                if isinstance(plan_payload.get("output_type_representations"), dict):
                    output_type_representations = {
                        str(k): str(v)
                        for k, v in plan_payload.get("output_type_representations", {}).items()
                    }
        except json.JSONDecodeError:
            custom_output_types = []

    run_dir = workspace_path(project_id) / "runs" / run_id

    process_model_payload = _read_json(run_dir / "process_model.json")
    source_trace = []
    if isinstance(process_model_payload, dict):
        metadata = process_model_payload.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("source_trace"), list):
            source_trace = [str(x) for x in metadata.get("source_trace", []) if str(x).strip()]

    artifacts: dict[str, object | None] = {
        "drawio_xml": _read_text(run_dir / "drawio.xml"),
        "process_map_mermaid": _read_text(run_dir / "process_map.mmd"),
        "raci_html": _read_text(run_dir / "raci.html"),
        "raci_markdown": _read_text(run_dir / "raci.md"),
        "raci_xlsx_base64": _read_base64(run_dir / "raci.xlsx"),
        "xlsx_base64": _read_base64(run_dir / "output.xlsx"),
        "pdf_base64": _read_base64(run_dir / "output.pdf"),
        "docx_base64": _read_base64(run_dir / "output.docx"),
        "pptx_base64": _read_base64(run_dir / "output.pptx"),
        "sop_markdown": _read_text(run_dir / "sop.md"),
        "narrative_md": _read_text(run_dir / "narrative.md"),
        "assembled_context": _read_text(run_dir / "assembled_context.txt"),
        "context_references": source_trace,
        "process_model": process_model_payload,
        "typed_outputs": _read_json(run_dir / "artifacts_typed.json"),
        "visual_qa_report": _read_json(run_dir / "visual_qa_report.json"),
        "dpdp_report_json": _read_json(run_dir / "dpdp_report.json"),
        "qa_report": _read_json(run_dir / "qa_report.json") or _latest_run_event_payload(db, run_id, "qa_report"),
        "guardrail_report": _read_json(run_dir / "guardrail_report.json")
        or _latest_run_event_payload(db, run_id, "guardrail_report"),
        "evaluator_pipeline": _latest_run_event_payload(db, run_id, "evaluator_pipeline"),
    }
    try:
        plan_payload_obj = json.loads(run.plan_payload) if run.plan_payload else {}
    except json.JSONDecodeError:
        plan_payload_obj = {}
    artifacts["plan_payload"] = plan_payload_obj if isinstance(plan_payload_obj, dict) else {}
    memory_events = db.scalars(
        select(MemoryEvent)
        .where(MemoryEvent.project_id == project_id, MemoryEvent.run_id == run_id)
        .order_by(MemoryEvent.id.desc())
        .limit(20)
    ).all()
    recent_changes: list[object] = []
    for ev in reversed(memory_events):
        if ev.event_type not in {"user_intent_updated", "qa_outcome", "qa_remediation", "guardrail_outcome"}:
            continue
        try:
            payload = json.loads(ev.payload)
        except json.JSONDecodeError:
            payload = {"summary": ev.payload}
        recent_changes.append({"event_type": ev.event_type, "payload": payload})
    profile = db.scalar(select(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == project_id))
    profile_payload: dict[str, object] = {}
    if profile and profile.summary_json:
        try:
            parsed = json.loads(profile.summary_json)
            if isinstance(parsed, dict):
                profile_payload = parsed
        except json.JSONDecodeError:
            profile_payload = {}
    artifacts["memory_summary"] = {
        "summary": profile_payload,
        "non_negotiables": profile_payload.get("non_negotiables", []),
        "recent_changes": recent_changes[-5:],
    }
    artifacts["non_negotiables"] = profile_payload.get("non_negotiables", [])
    artifacts["recent_changes"] = recent_changes[-5:]
    ready_downloads: list[str] = []
    if artifacts.get("docx_base64"):
        ready_downloads.append("docx")
    if artifacts.get("pptx_base64"):
        ready_downloads.append("pptx")
    if artifacts.get("xlsx_base64"):
        ready_downloads.append("xlsx")
    if artifacts.get("pdf_base64"):
        ready_downloads.append("pdf")
    if artifacts.get("drawio_xml"):
        ready_downloads.append("process_map_drawio")
    if artifacts.get("process_map_mermaid"):
        ready_downloads.append("process_map_mermaid")
    if artifacts.get("raci_html"):
        ready_downloads.append("raci_html")
    if artifacts.get("raci_markdown"):
        ready_downloads.append("raci_markdown")
    if artifacts.get("raci_xlsx_base64"):
        ready_downloads.append("raci_xlsx")
    if artifacts.get("sop_markdown"):
        ready_downloads.append("sop_markdown")
    if artifacts.get("narrative_md"):
        ready_downloads.append("narrative_md")
    artifacts["ready_downloads"] = ready_downloads
    project = db.scalar(select(Project).where(Project.id == project_id))
    project_name = str(project.name or "").strip() if project else ""
    process_meta = process_model_payload.get("metadata") if isinstance(process_model_payload, dict) else {}
    client_hint = str((process_meta or {}).get("client_name") or "").strip() if isinstance(process_meta, dict) else ""
    client_name = _tokenize_filename(client_hint or project_name or "Client")
    run_date = (run.created_at.date().strftime("%Y%m%d") if run.created_at else "UnknownDate")

    def _name(deliverable_type: str, extension: str) -> str:
        dtype = _tokenize_filename(deliverable_type)
        return f"{client_name}_{dtype}_{run_date}.{extension}"

    artifacts["output_filenames"] = {
        "docx": _name("ProcessNarrative", "docx"),
        "pptx": _name("ExecutiveDeck", "pptx"),
        "xlsx": _name("AnalysisModel", "xlsx"),
        "pdf": _name("ExecutiveReport", "pdf"),
        "raci_xlsx": _name("RaciMatrix", "xlsx"),
        "process_map_drawio": _name("ProcessMap", "drawio.xml"),
        "process_map_mermaid": _name("ProcessMap", "mmd"),
        "raci_html": _name("RaciMatrix", "html"),
        "raci_markdown": _name("RaciMatrix", "md"),
        "sop_markdown": _name("ProcessSop", "md"),
        "narrative_md": _name("ProcessNarrative", "md"),
        "qa_report": _name("QaReport", "json"),
        "guardrail_report": _name("GuardrailReport", "json"),
        "visual_qa_report": _name("VisualQaReport", "json"),
    }

    return RunArtifactsResponse(
        run_id=run_id,
        project_id=project_id,
        status=run.status,
        instruction=run.instruction,
        output_types=output_types,
        custom_output_types=custom_output_types,
        output_type_representations=output_type_representations,
        artifacts=artifacts,
    )

