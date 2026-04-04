from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    create_sse_token,
    ensure_user,
    get_current_user,
    rotate_refresh_token,
)
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class SseTokenBody(BaseModel):
    run_id: str | None = None


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    user = ensure_user(body.email, body.password, db)
    return {
        "access_token": create_access_token(user.email),
        "refresh_token": create_refresh_token(user.email, db, user.id),
        "token_type": "bearer",
    }


@router.post("/refresh")
def refresh_session(body: RefreshRequest, db: Session = Depends(get_db)) -> dict[str, str]:
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
) -> dict[str, str | int]:
    return {
        "sse_token": create_sse_token(user.email, run_id=body.run_id),
        "expires_in": int(settings.jwt_sse_exp_seconds),
    }
