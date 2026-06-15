import base64
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.handoff_bundle import build_handoff_bundle
from app.db.models import MemoryEvent, Project, ProjectMemoryProfile, Run, RunEvent, User
from app.db.session import get_db
from app.services.artifact_integrity import pptx_base64_from_file, verify_pptx_on_disk
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

    pptx_b64, pptx_integrity = pptx_base64_from_file(run_dir)

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
        "pptx_base64": pptx_b64,
        "pptx_integrity": pptx_integrity,
        "deck_html": _read_text(run_dir / "deck.html"),
        "deck_pdf_base64": _read_base64(run_dir / "deck.pdf"),
        "sop_markdown": _read_text(run_dir / "sop.md"),
        "narrative_md": _read_text(run_dir / "narrative.md"),
        "assembled_context": _read_text(run_dir / "assembled_context.txt"),
        "context_references": source_trace,
        "process_model": process_model_payload,
        "typed_outputs": _read_json(run_dir / "artifacts_typed.json"),
        "pptx_slides": _read_json(run_dir / "pptx_slides.json"),
        "visual_qa_report": _read_json(run_dir / "visual_qa_report.json"),
        "dpdp_report_json": _read_json(run_dir / "dpdp_report.json"),
        "qa_report": _read_json(run_dir / "qa_report.json") or _latest_run_event_payload(db, run_id, "qa_report"),
        "guardrail_report": _read_json(run_dir / "guardrail_report.json")
        or _latest_run_event_payload(db, run_id, "guardrail_report"),
        "evaluator_pipeline": _latest_run_event_payload(db, run_id, "evaluator_pipeline"),
        "final_artifact_qa": _read_json(run_dir / "final_artifact_qa.json"),
    }
    qa_report_obj = artifacts.get("qa_report") if isinstance(artifacts.get("qa_report"), dict) else {}
    guardrail_obj = artifacts.get("guardrail_report") if isinstance(artifacts.get("guardrail_report"), dict) else {}
    final_qa_obj = artifacts.get("final_artifact_qa") if isinstance(artifacts.get("final_artifact_qa"), dict) else {}
    evaluator_obj = artifacts.get("evaluator_pipeline") if isinstance(artifacts.get("evaluator_pipeline"), dict) else {}
    guardrail_failure_event = db.scalar(
        select(RunEvent).where(
            RunEvent.run_id == run_id,
            RunEvent.event_type == "completed_with_guardrail_failures",
        )
    )
    if guardrail_failure_event:
        artifacts["quality_status"] = "completed_with_guardrail_failures"
    elif evaluator_obj.get("status") == "fail":
        artifacts["quality_status"] = "evaluator_failed"
    elif final_qa_obj.get("status") == "fail":
        artifacts["quality_status"] = "final_artifact_qa_failed"
    elif qa_report_obj.get("passed") and str(guardrail_obj.get("status") or "").lower() == "pass":
        artifacts["quality_status"] = "passed"
    else:
        artifacts["quality_status"] = "review_recommended"
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
    if artifacts.get("deck_html"):
        ready_downloads.append("deck_html")
    if artifacts.get("deck_pdf_base64"):
        ready_downloads.append("deck_pdf")
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
    artifacts["handoff_bundle_available"] = bool(run_dir.exists())
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
        "deck_html": _name("ExecutiveDeck", "html"),
        "deck_pdf": _name("ExecutiveDeck", "pdf"),
        "handoff_bundle": _name("HandoffBundle", "zip"),
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


CANVAS_ARTIFACT_FILES: dict[str, str] = {
    "narrative_md": "narrative.md",
    "sop_markdown": "sop.md",
    "raci_markdown": "raci.md",
    "process_map_mermaid": "process_map.mmd",
}


class CanvasSaveRequest(BaseModel):
    artifact_key: str
    content: str


@router.patch("/{project_id}/{run_id}/canvas")
def save_canvas_artifact(
    project_id: str,
    run_id: str,
    body: CanvasSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    if body.artifact_key not in CANVAS_ARTIFACT_FILES:
        raise HTTPException(status_code=400, detail=f"Unknown artifact key: {body.artifact_key}")
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run_dir = workspace_path(project_id) / "runs" / run_id
    (run_dir / CANVAS_ARTIFACT_FILES[body.artifact_key]).write_text(body.content, encoding="utf-8")
    return {"ok": True, "artifact_key": body.artifact_key}


@router.get("/{project_id}/{run_id}/artifacts/pptx/download")
def download_run_pptx(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream output.pptx directly from the run workspace (canonical on-disk artifact)."""
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = workspace_path(project_id) / "runs" / run_id
    pptx_path = run_dir / "output.pptx"
    if not pptx_path.is_file():
        raise HTTPException(status_code=404, detail="PPTX output not found for this run")

    check = verify_pptx_on_disk(run_dir)
    if not check.get("ok"):
        raise HTTPException(status_code=404, detail="PPTX output not available")

    process_meta = {}
    pm = _read_json(run_dir / "process_model.json")
    if isinstance(pm, dict) and isinstance(pm.get("metadata"), dict):
        process_meta = pm["metadata"]
    project = db.scalar(select(Project).where(Project.id == project_id))
    project_name = str(project.name or "").strip() if project else ""
    client_hint = str(process_meta.get("client_name") or "").strip()
    client_name = _tokenize_filename(client_hint or project_name or "Client")
    run_date = run.created_at.date().strftime("%Y%m%d") if run.created_at else "UnknownDate"
    filename = f"{client_name}_ExecutiveDeck_{run_date}.pptx"

    return FileResponse(
        path=str(pptx_path),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )


@router.get("/{project_id}/{run_id}/handoff_bundle")
def get_run_handoff_bundle(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Build (if needed) and stream the Claude Code handoff bundle zip."""

    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = workspace_path(project_id) / "runs" / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail="Run workspace not found")

    try:
        output_types = json.loads(run.output_types) if run.output_types else []
    except json.JSONDecodeError:
        output_types = []

    plan_hash = ""
    if run.plan_payload:
        try:
            plan_payload = json.loads(run.plan_payload)
            if isinstance(plan_payload, dict):
                plan_hash = str(plan_payload.get("plan_hash") or "")
        except json.JSONDecodeError:
            plan_hash = ""

    project = db.scalar(select(Project).where(Project.id == project_id))
    project_name = str(project.name or "").strip() if project else ""
    run_date = run.created_at.date().strftime("%Y%m%d") if run.created_at else "UnknownDate"
    filename = f"{_tokenize_filename(project_name or 'Project')}_HandoffBundle_{run_date}.zip"

    result = build_handoff_bundle(
        run_dir,
        metadata={
            "project_id": project_id,
            "run_id": run_id,
            "status": run.status,
            "instruction": run.instruction,
            "output_types": output_types if isinstance(output_types, list) else [],
            "plan_hash": plan_hash,
        },
    )
    if not result.zip_path or not result.zip_path.exists():
        raise HTTPException(status_code=500, detail="Handoff bundle unavailable")

    return FileResponse(
        path=str(result.zip_path),
        media_type="application/zip",
        filename=filename,
    )

