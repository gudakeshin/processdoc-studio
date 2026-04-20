"""Guarded Claude turn with optional Anthropic Bash/Text Editor tools (Owner/Editor only)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db
from app.services.bash_rate_limit import check_rate_limit
from app.services.claude import is_claude_enabled
from app.services.claude_tools import run_claude_tools_loop

router = APIRouter()


class BashCapableTurnRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)
    allow_bash: bool = False
    allow_text_editor: bool = False
    allow_write: bool = False
    system: str | None = Field(default=None, max_length=24000)
    session_id: str | None = Field(default=None, description="Reuse prior bash session within project")
    messages: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional prior turns: [{'role':'user'|'assistant','content': str|list}]",
    )


@router.post("/{pid}/agent/bash-capable-turn")
def bash_capable_turn(
    pid: str,
    body: BashCapableTurnRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    if not is_claude_enabled():
        raise HTTPException(status_code=503, detail="Claude is not configured (ANTHROPIC_API_KEY)")

    if body.allow_bash and not settings.bash_tool_enabled:
        raise HTTPException(
            status_code=403,
            detail="Bash tool is disabled on this server (set BASH_TOOL_ENABLED=true after hardening).",
        )
    if body.allow_text_editor and not settings.text_editor_tool_enabled:
        raise HTTPException(
            status_code=403,
            detail="Text editor tool is disabled on this server (set TEXT_EDITOR_TOOL_ENABLED=true after hardening).",
        )

    ok, reason = check_rate_limit(f"agent_tool_turn:{user.id}")
    if not ok:
        raise HTTPException(status_code=429, detail=reason)

    correlation_id = str(uuid.uuid4())
    default_system = (
        "You are a careful assistant for ProcessDoc Studio. "
        "When tools are available, use them only when necessary and stay within project workspace boundaries. "
        "Do not request credentials or exfiltrate secrets. "
        "Text editor writes are only allowed when the caller sets allow_write=true."
    )
    system = (body.system or default_system).strip()

    prior = body.messages or []
    msg_history: list[dict[str, Any]] = list(prior)
    msg_history.append({"role": "user", "content": body.message.strip()})

    try:
        result = run_claude_tools_loop(
            system=system,
            messages=msg_history,
            project_id=pid,
            allow_bash=body.allow_bash,
            allow_text_editor=body.allow_text_editor,
            allow_write=body.allow_write,
            user_id=str(user.id),
            session_id=body.session_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "project_id": pid,
        "correlation_id": correlation_id,
        "text": result.get("text", ""),
        "session_id": result.get("session_id"),
        "tool_trace": result.get("tool_trace", []),
        "model": result.get("model"),
        "rounds": result.get("rounds"),
        "allow_bash": body.allow_bash,
        "allow_text_editor": body.allow_text_editor,
        "allow_write": body.allow_write,
    }
