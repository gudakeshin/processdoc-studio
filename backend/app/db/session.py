from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base

DATABASE_URL = settings.database_url

if DATABASE_URL.startswith("sqlite"):
    _sqlite_args = {"check_same_thread": False}
    if ":memory:" in DATABASE_URL:
        engine = create_engine(
            DATABASE_URL,
            future=True,
            connect_args=_sqlite_args,
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(DATABASE_URL, future=True, connect_args=_sqlite_args)
else:
    engine = create_engine(
        DATABASE_URL,
        future=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=settings.database_pool_pre_ping,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
_initialized = False


def init_db() -> None:
    global _initialized
    from app.db import models as _models  # noqa: F401 — register ORM tables on Base.metadata

    Base.metadata.create_all(bind=engine)
    _initialized = True


def get_db() -> Generator[Session, None, None]:
    if not _initialized:
        init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Multi-step unit of work with explicit commit/rollback (use outside FastAPI Depends)."""
    if not _initialized:
        init_db()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
