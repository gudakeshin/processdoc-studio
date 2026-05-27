from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base

DATABASE_URL = settings.database_url

if DATABASE_URL.startswith("sqlite"):
    # SQLite can briefly lock on concurrent writes (API + background workers).
    # Increase busy timeout so transient contention does not fail requests.
    _sqlite_args = {"check_same_thread": False, "timeout": 30}
    if ":memory:" in DATABASE_URL:
        engine = create_engine(
            DATABASE_URL,
            future=True,
            connect_args=_sqlite_args,
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(DATABASE_URL, future=True, connect_args=_sqlite_args)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        # Improve concurrent read/write behavior for local-dev SQLite.
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
        finally:
            cursor.close()
else:
    engine = create_engine(
        DATABASE_URL,
        future=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=settings.database_pool_pre_ping,
        pool_recycle=settings.database_pool_recycle,
        pool_timeout=settings.database_pool_timeout,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
_initialized = False


def _migrate_db() -> None:
    """Apply additive column additions to existing DBs. Idempotent — skips columns that exist."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    _additions = [
        ("runs", "tokens_input", "INTEGER"),
        ("runs", "tokens_output", "INTEGER"),
        ("runs", "tokens_cache_read", "INTEGER"),
        ("runs", "tokens_cache_creation", "INTEGER"),
        ("runs", "cost_usd", "REAL"),
    ]
    with engine.connect() as conn:
        existing_tables = set(inspector.get_table_names())
        for table, col, col_type in _additions:
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            if col not in existing_cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
        conn.commit()


def init_db() -> None:
    global _initialized
    from app.db import models as _models  # noqa: F401 — register ORM tables on Base.metadata

    Base.metadata.create_all(bind=engine)
    _migrate_db()
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
