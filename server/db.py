# db.py -- engine, session factory, and the two URL facts that bite in prod.
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.config import Settings, get_settings

_PG_DRIVER = "postgresql+psycopg"


def normalise_database_url(url: str) -> str:
    """Force psycopg 3 on every spelling of a Postgres URL.

    `postgres://` is what Render, Heroku and Fly hand out and SQLAlchemy 2
    rejects it outright -- loud, and therefore harmless. `postgresql://` is the
    dangerous one: it resolves to the psycopg2 dialect, which this project does
    not install because it pins psycopg 3, so it imports fine, passes every test
    that uses SQLite, and dies at the first connection in production. Both
    spellings become `postgresql+psycopg://` here, once, at the only place a URL
    enters the process.

    A driver the caller named explicitly is left alone. `postgresql+asyncpg://`
    is somebody's deliberate decision and overriding it would be this function
    guessing over a human.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = _PG_DRIVER + "://" + url[len("postgresql://"):]
    return url


def _engine_kwargs(url: str) -> dict[str, Any]:
    if url.startswith("sqlite"):
        kw: dict[str, Any] = {
            # SQLite-only DBAPI argument, and passing it to any other driver is
            # a TypeError at connect. FastAPI serves requests from a thread pool
            # and a pooled connection outlives the thread that opened it, so the
            # default same-thread assertion fires on perfectly correct code.
            "connect_args": {"check_same_thread": False},
        }
        if ":memory:" in url or url.endswith("sqlite://"):
            # Every pooled connection to :memory: gets its OWN empty database.
            # StaticPool keeps one connection, which is the only way an
            # in-memory schema survives being handed to a second session.
            kw["poolclass"] = StaticPool
        return kw
    # pool_pre_ping costs a round trip and buys nothing on a local file; on a
    # managed Postgres it is the difference between a redeploy and a 500.
    return {"pool_pre_ping": True, "pool_recycle": 1800}


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    """SQLite ships with foreign keys OFF.

    Every ON DELETE CASCADE in models.py -- including the one that makes ARCH
    3.12's stop-and-delete actually delete a session's captures -- is inert
    without this pragma. Dev would then behave differently from Postgres in
    exactly the area the consent story depends on.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    # WAL lets the rack UI read while a session writes. Silently ignored by
    # :memory:, which reports journal_mode=memory and carries on.
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def make_engine(url: str | None = None, *, echo: bool | None = None,
                settings: Settings | None = None) -> Engine:
    """Build an engine for an explicit URL. Tests point this at a temp file."""
    st = settings or get_settings()
    dsn = normalise_database_url(url if url is not None else st.database_url)
    return create_engine(
        dsn,
        echo=st.sql_echo if echo is None else echo,
        **_engine_kwargs(dsn),
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine()


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[SASession]:
    # expire_on_commit=False: the request handler routinely reads ids and
    # counters off a Capture after committing it, and the default would issue a
    # fresh SELECT for each attribute on a row nobody changed.
    return sessionmaker(bind=get_engine(), expire_on_commit=False, class_=SASession)


def create_all(engine: Engine | None = None) -> None:
    """Create the schema, including the audit append-only triggers.

    Imported here rather than at module scope so that db.py stays importable by
    models.py's future callers without a cycle.
    """
    from server.models import Base

    eng = engine or get_engine()
    _set_aside_unscoped_catalogue(eng)
    Base.metadata.create_all(eng)


def _set_aside_unscoped_catalogue(eng: Engine) -> None:
    """A `catalogue_part` table from before catalogues belonged to an
    organisation has no `organisation_id`, and `create_all` never alters an
    existing table -- so every read would fail on the missing column. Rename it
    aside instead of dropping it: its rows had no owner then and cannot be
    given one now, but a person may still want to look at them.

    Idempotent. The one schema change this project has made without a
    migration tool, and it is here, next to create_all, so it is not a second
    place anybody has to remember.
    """
    from sqlalchemy import inspect

    names = inspect(eng).get_table_names()
    if "catalogue_part" not in names:
        return
    columns = {c["name"] for c in inspect(eng).get_columns("catalogue_part")}
    if "organisation_id" in columns:
        return
    legacy, n = "catalogue_part_unscoped_legacy", 1
    while legacy in names:            # never overwrite an earlier set-aside
        n += 1
        legacy = f"catalogue_part_unscoped_legacy_{n}"
    with eng.begin() as conn:
        conn.exec_driver_sql(f"ALTER TABLE catalogue_part RENAME TO {legacy}")
        # SQLite keeps the old index name on the renamed table, and the new
        # table wants the same name.
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_catalogue_rhyme")


def drop_all(engine: Engine | None = None) -> None:
    """Tests and dev only. Deliberately not exported to any HTTP path."""
    from server.models import Base

    eng = engine or get_engine()
    if eng.dialect.name == "sqlite":
        # The append-only triggers reference audit_event and SQLite refuses to
        # drop a table out from under its own trigger.
        with eng.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_event_no_update")
            conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_event_no_delete")
    Base.metadata.drop_all(eng)


@contextmanager
def session_scope(factory: sessionmaker[SASession] | None = None) -> Iterator[SASession]:
    """Transaction boundary for background work: the meter, the purge job.

    Commits on success, rolls back on anything else. audit.record() flushes but
    never commits, so an audit row lands in the same transaction as the fact it
    describes -- either both are true or neither is.
    """
    session = (factory or get_sessionmaker())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[SASession]:
    """FastAPI dependency. One session per request, committed by the caller."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
