"""Database engine and session factory. SQLite for local/test, PostgreSQL in Docker and production."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite"):
            path = url.replace("sqlite:///", "")
            if path and path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            _engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)

            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _):  # SQLite enforces FKs only when asked
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
        else:
            _engine = create_engine(url, pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    """Used by tests to point at a fresh database after changing the URL."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    get_settings.cache_clear()


def session_factory() -> sessionmaker:
    get_engine()
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


def create_all() -> None:
    from . import models  # noqa: F401  (register tables)

    eng = get_engine()
    Base.metadata.create_all(eng)
    _migrate(eng)


def _migrate(eng) -> None:
    """Additive migrations for databases created by earlier versions (Alembic comes with the production stack)."""
    from sqlalchemy import inspect, text
    insp = inspect(eng)
    adds = {"ops_prediction": [("mode_pred", "VARCHAR(32)"), ("window_lo", "INTEGER"), ("window_hi", "INTEGER"), ("tier", "VARCHAR(16)"), ("cof", "JSON")],
            "ops_list_item": [("tier", "VARCHAR(16)"), ("route", "INTEGER"), ("seq", "INTEGER"), ("grouped", "BOOLEAN DEFAULT 0"), ("safe_window", "VARCHAR(128)")],
            "ops_work_order": [("item_id", "VARCHAR(32)"), ("details", "JSON")]}
    for table, columns in adds.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for name, typ in columns:
            if name not in have:
                with eng.begin() as con:
                    con.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
    cols = {c["name"] for c in insp.get_columns("ops_asset")}
    if "category" not in cols:
        with eng.begin() as con:
            con.execute(text("ALTER TABLE ops_asset ADD COLUMN category VARCHAR(16) DEFAULT 'lighting'"))
            con.execute(text("UPDATE ops_asset SET category = CASE WHEN asset_type IN ('PMP','PNL','VLV') THEN 'pumping' "
                             "WHEN asset_type IN ('ELV','ESC','LFT') THEN 'elevators' WHEN asset_type IN ('PAV','RMP','CRS') THEN 'pavement' ELSE 'lighting' END"))
