from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    create_sse_token,
    ensure_user,
    get_current_user,
    require_project_role,
    rotate_refresh_token,
)
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models import Run, User
from app.db.session import get_db

router = APIRouter()


def _auth_login_rate_limit() -> str:
    """Evaluated per request so tests and env overrides can change limits without reloading modules."""
    return (settings.auth_login_rate_limit or "30/minute").strip() or "30/minute"


def _auth_refresh_rate_limit() -> str:
    return (settings.auth_refresh_rate_limit or "60/minute").strip() or "60/minute"


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class SseTokenBody(BaseModel):
    run_id: str | None = None


@router.post("/login")
@limiter.limit(_auth_login_rate_limit)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    user = ensure_user(body.email, body.password, db)
    return {
        "access_token": create_access_token(user.email),
        "refresh_token": create_refresh_token(user.email, db, user.id),
        "token_type": "bearer",
    }


@router.post("/refresh")
@limiter.limit(_auth_refresh_rate_limit)
def refresh_session(request: Request, body: RefreshRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    user, new_refresh = rotate_refresh_token(db, body.refresh_token)
    return {
        "access_token": create_access_token(user.email),
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/sse-token")
def issue_sse_token(
    body: SseTokenBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str | int]:
    rid = (body.run_id or "").strip()
    if rid:
        run = db.scalar(select(Run).where(Run.id == rid))
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot issue token for this run",
            )
        try:
            require_project_role(run.project_id, {"Owner", "Editor", "Viewer"}, user, db)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot issue token for this run",
            ) from None
    return {
        "sse_token": create_sse_token(user.email, run_id=rid or None),
        "expires_in": int(settings.jwt_sse_exp_seconds),
    }
