import uuid
from datetime import datetime, timedelta
from app.core.tz import IST

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Membership, RefreshToken, User
from app.db.session import get_db
from app.services.cache import cache_service

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str) -> str:
    expiry = datetime.now(IST) + timedelta(minutes=settings.jwt_access_exp_minutes)
    payload = {"sub": subject, "exp": expiry, "typ": "access", "jti": str(uuid.uuid4())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str, db: Session, user_id: str) -> str:
    jti = str(uuid.uuid4())
    expiry = datetime.now(IST) + timedelta(days=settings.jwt_refresh_exp_days)
    row = RefreshToken(id=jti, user_id=user_id, expires_at=expiry)
    db.add(row)
    db.commit()
    payload = {"sub": subject, "exp": expiry, "typ": "refresh", "jti": jti}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def rotate_refresh_token(db: Session, refresh_token: str) -> tuple[User, str]:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate refresh token",
    )
    try:
        payload = jwt.decode(refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise credentials_exc from exc
    if payload.get("typ") != "refresh":
        raise credentials_exc
    jti = payload.get("jti")
    email = payload.get("sub")
    if not jti or not email or not isinstance(email, str):
        raise credentials_exc
    now = datetime.now(IST)
    row = db.scalar(select(RefreshToken).where(RefreshToken.id == str(jti)))
    if row is None or row.revoked_at is not None:
        raise credentials_exc
    exp_at = row.expires_at
    if exp_at.tzinfo is None:
        exp_at = exp_at.replace(tzinfo=IST)
    if exp_at < now:
        raise credentials_exc
    user = db.scalar(select(User).where(User.email == email))
    if not user or user.id != row.user_id:
        raise credentials_exc
    new_jti = str(uuid.uuid4())
    new_exp = now + timedelta(days=settings.jwt_refresh_exp_days)
    new_row = RefreshToken(id=new_jti, user_id=user.id, expires_at=new_exp)
    row.revoked_at = now
    row.replaced_by_jti = new_jti
    db.add(new_row)
    db.commit()
    return user, jwt.encode(
        {"sub": email, "exp": new_exp, "typ": "refresh", "jti": new_jti},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_sse_token(subject: str, *, run_id: str | None = None) -> str:
    exp = datetime.now(IST) + timedelta(seconds=max(30, int(settings.jwt_sse_exp_seconds)))
    pl: dict = {"sub": subject, "exp": exp, "typ": "sse"}
    if run_id:
        pl["run_id"] = str(run_id)
    return jwt.encode(pl, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _reject_if_non_access_bearer(payload: dict) -> None:
    typ = payload.get("typ")
    if typ is not None and typ != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type for this endpoint",
        )


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        _reject_if_non_access_bearer(payload)
        email = payload.get("sub")
        if not email or not isinstance(email, str):
            raise credentials_exc
    except JWTError as exc:
        raise credentials_exc from exc

    cached = cache_service.get(f"user_jwt:{email}")
    if cached:
        return User(**cached)

    user = db.scalar(select(User).where(User.email == email))
    if not user:
        raise credentials_exc
    cache_service.set(
        f"user_jwt:{email}",
        {"id": user.id, "email": user.email, "hashed_password": user.hashed_password},
        ttl_seconds=300,
    )
    return user


def get_current_user_sse(
    db: Session = Depends(get_db),
    token: str | None = Query(None, description="JWT for EventSource (no Authorization header in browsers)"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> User:
    """Authenticate SSE clients: `?token=` query and `Authorization: Bearer` both supported."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    raw = token
    if not raw and authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw = parts[1].strip()
    if not raw:
        raise credentials_exc
    try:
        payload = jwt.decode(raw, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        typ = payload.get("typ")
        if typ == "refresh":
            raise credentials_exc
        if typ == "sse":
            email = payload.get("sub")
        else:
            _reject_if_non_access_bearer(payload)
            email = payload.get("sub")
        if not email:
            raise credentials_exc
    except JWTError as exc:
        raise credentials_exc from exc
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        raise credentials_exc
    return user


def require_project_role(project_id: str, allowed_roles: set[str], user: User, db: Session) -> None:
    cache_key = f"project_role:{user.id}:{project_id}"
    cached_role = cache_service.get(cache_key)
    if cached_role:
        role = cached_role.get("role", "")
    else:
        member = db.scalar(
            select(Membership).where(Membership.project_id == project_id, Membership.user_id == user.id)
        )
        role = member.role if member else ""
        cache_service.set(cache_key, {"role": role}, ttl_seconds=60)
    if not role or role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient project permissions")


def ensure_user(email: str, password: str, db: Session) -> User:
    """Authenticate or provision a user.

    When self-signup is disabled, unknown emails receive the same 401 as wrong passwords
    to avoid account enumeration.
    """
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        if not verify_password(password, existing.hashed_password):
            raise invalid
        return existing
    if not settings.auth_allow_self_signup:
        raise invalid
    created = User(id=f"u_{uuid.uuid4().hex[:10]}", email=email, hashed_password=get_password_hash(password))
    db.add(created)
    db.commit()
    db.refresh(created)
    return created
