import contextlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.upload_validation import validate_icon_upload
from app.db.models import User
from app.db.session import get_db
from app.services.skill_document import (
    BUILTIN_SKILLS_ROOT,
    load_builtin_skills,
    load_custom_skills_from_workspace,
    skill_dict_from_markdown_text,
    write_skill_md,
)
from app.services.storage import workspace_path

router = APIRouter()

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _custom_skills_dir(project_id: str) -> Path:
    return workspace_path(project_id) / "custom_skills"


def _merged_skill_registry(project_id: str) -> list[dict[str, Any]]:
    builtins = load_builtin_skills()
    custom = load_custom_skills_from_workspace(_custom_skills_dir(project_id))
    return [*builtins, *custom]


def _public_skill(skill: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in skill.items() if not str(k).startswith("_")}


def _skill_lookup(project_id: str, sid: str, version: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    for item in _merged_skill_registry(project_id):
        if str(item.get("id")) != sid:
            continue
        if version is not None and str(item.get("version", "")) != version:
            continue
        source = "custom" if bool(item.get("custom")) else "builtin"
        return item, source
    return None, None


def _validate_custom_skill_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ["id", "domain", "display_name", "output_types", "tools", "prompt_instructions", "version", "description", "sample_instruction"]
    for k in required:
        if k not in payload:
            errors.append(f"missing:{k}")
        elif k == "prompt_instructions" and not str(payload.get(k) or "").strip():
            errors.append("missing:prompt_instructions")
    if "output_types" in payload and not isinstance(payload["output_types"], list):
        errors.append("output_types must be an array")
    if "tools" in payload and not isinstance(payload["tools"], list):
        errors.append("tools must be an array")
    if "quality_thresholds" in payload and not isinstance(payload["quality_thresholds"], dict):
        errors.append("quality_thresholds must be an object if provided")
    return errors


def _companion_file_allowlist(skill: dict[str, Any]) -> list[Path]:
    paths = skill.get("companion_files")
    if not isinstance(paths, list):
        return []
    out: list[Path] = []
    md_path = skill.get("_skill_md_path")
    skill_dir = Path(md_path).parent if isinstance(md_path, str) and md_path else None
    root_resolved = _PROJECT_ROOT.resolve()
    for item in paths:
        if not isinstance(item, str) or not item.strip():
            continue
        rel = item.strip()
        candidates: list[Path] = [(root_resolved / rel).resolve()]
        if skill_dir and rel.startswith("./"):
            candidates.insert(0, (skill_dir / rel[2:]).resolve())
        for resolved in candidates:
            try:
                resolved.relative_to(root_resolved)
            except ValueError:
                continue
            if resolved.is_file():
                out.append(resolved)
                break
    return out


def _parse_skill_create_body(*, skill_json: str | None, skill_md: str | None) -> dict[str, Any]:
    if skill_md and skill_md.strip():
        payload = skill_dict_from_markdown_text(skill_md, custom=True)
        if payload is None:
            raise HTTPException(status_code=400, detail="skill_md could not be parsed as SKILL.md (YAML frontmatter + body)")
        return payload
    if skill_json and skill_json.strip():
        try:
            payload = json.loads(skill_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="skill_json must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="skill_json must be a JSON object")
        return payload
    raise HTTPException(status_code=400, detail="Provide skill_md (SKILL.md) or skill_json")


@router.get("")
def list_skills(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    domain: str | None = None,
    custom: bool | None = None,
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    items = [_public_skill(it) for it in _merged_skill_registry(pid)]
    if domain:
        items = [it for it in items if it.get("domain") == domain]
    if custom is True:
        items = [it for it in items if bool(it.get("custom")) is True]
    if custom is False:
        items = [it for it in items if bool(it.get("custom")) is False]

    return {"project_id": pid, "items": items}


@router.post("")
async def create_skill(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skill_md: str | None = Form(None),
    skill_json: str | None = Form(None),
    icon: UploadFile | None = File(None),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    if icon is not None and (icon.filename or "").strip():
        icon_bytes = await icon.read()
        validate_icon_upload(icon.filename or "icon.bin", icon_bytes)

    payload = _parse_skill_create_body(skill_json=skill_json, skill_md=skill_md)
    errors = _validate_custom_skill_payload(payload)
    if errors:
        return {"project_id": pid, "status": "validation_failed", "errors": errors}

    skill_id = str(payload["id"])
    version = str(payload["version"])

    stored: dict[str, Any] = {
        **payload,
        "custom": True,
        "created_by": user.email,
    }
    stored.setdefault("quality_thresholds", {"narrative": 0.8})

    out_dir = _custom_skills_dir(pid) / skill_id
    out_dir.mkdir(parents=True, exist_ok=True)
    write_skill_md(out_dir / "SKILL.md", stored)

    return {"project_id": pid, "skill_id": skill_id, "version": version, "status": "validated"}


@router.get("/{sid}/companions")
def get_skill_companions(
    pid: str,
    sid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    version: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    skill, _source = _skill_lookup(pid, sid, version)
    if skill is None:
        raise HTTPException(status_code=404, detail="skill not found")

    allowlisted = _companion_file_allowlist(skill)
    listed = [str(p.relative_to(_PROJECT_ROOT)) for p in allowlisted]

    if not file_path:
        return {"project_id": pid, "skill_id": sid, "version": skill.get("version"), "files": listed}

    requested = (_PROJECT_ROOT / file_path).resolve()
    if requested not in allowlisted:
        raise HTTPException(status_code=403, detail="file is not registered as a companion")
    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="companion file not found")

    content = requested.read_text(encoding="utf-8")
    return {
        "project_id": pid,
        "skill_id": sid,
        "version": skill.get("version"),
        "file_path": str(requested.relative_to(_PROJECT_ROOT)),
        "content": content,
    }


@router.delete("/{sid}")
def delete_skill(
    pid: str,
    sid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    base_dir = _custom_skills_dir(pid) / sid
    if not base_dir.exists():
        return {"project_id": pid, "skill_id": sid, "status": "not_found"}

    for p in base_dir.rglob("*"):
        if p.is_file():
            p.unlink(missing_ok=True)
    for p in sorted(base_dir.rglob("*"), reverse=True):
        if p.is_dir():
            p.rmdir()
    with contextlib.suppress(Exception):
        base_dir.rmdir()

    return {"project_id": pid, "skill_id": sid, "status": "deleted"}


@router.put("/{sid}")
async def update_skill(
    pid: str,
    sid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skill_md: str | None = Form(None),
    skill_json: str | None = Form(None),
    version: str | None = Form(None),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    payload = _parse_skill_create_body(skill_json=skill_json, skill_md=skill_md)
    errors = _validate_custom_skill_payload(payload)
    if errors:
        return {"project_id": pid, "status": "validation_failed", "errors": errors}

    if str(payload.get("id")) != sid:
        raise HTTPException(status_code=400, detail="payload id must match route sid")

    target_version = version or str(payload.get("version") or "")
    if not target_version:
        raise HTTPException(status_code=400, detail="version is required")

    existing, source = _skill_lookup(pid, sid, target_version)
    if existing is None or source is None:
        raise HTTPException(status_code=404, detail="skill not found")

    if source == "custom":
        stored: dict[str, Any] = {
            **payload,
            "custom": True,
            "created_by": existing.get("created_by", user.email),
        }
        stored.setdefault("quality_thresholds", {"narrative": 0.8})
        out_dir = _custom_skills_dir(pid) / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        write_skill_md(out_dir / "SKILL.md", stored)
    else:
        replacement = {**payload, "custom": False}
        replacement.pop("_skill_md_path", None)
        md_path = BUILTIN_SKILLS_ROOT / sid / "SKILL.md"
        if not md_path.parent.is_dir():
            raise HTTPException(status_code=404, detail="built-in skill has no SKILL.md directory")
        write_skill_md(md_path, replacement)

    return {"project_id": pid, "skill_id": sid, "version": target_version, "status": "updated"}
