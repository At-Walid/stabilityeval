from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from stability_eval.config.settings import settings
from stability_eval.data.models import Base

DATABASE_URL = settings.DATABASE_URL

# A new database starts as a copy of the shipped pilot database (the bundled SWE-bench Lite issues
# and the ICSE pilot experiment), so the dashboard and the CLI can replay the pilot right away.
# STABILITYEVAL_SEED_DB names another seed file; set it to an empty string to start empty.
SEED_DB_ENV_VAR = "STABILITYEVAL_SEED_DB"
DEFAULT_SEED_DB = Path(__file__).resolve().parents[2] / "data" / "pilot" / "stabilityeval_pilot.db"


def _configure_sqlite(engine: Engine) -> None:
    """Enable WAL mode and foreign-key enforcement for SQLite connections."""
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def build_engine(url: str = DATABASE_URL):
    engine = create_engine(url, echo=False)
    _configure_sqlite(engine)
    return engine


_engine = build_engine()
_SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def seed_database(url: str = DATABASE_URL) -> bool:
    """Copy the seed database to ``url``'s SQLite file when that file does not exist yet.

    Only file-based SQLite URLs are seeded; an existing database is never touched. Returns True
    when a copy was made.
    """
    seed = os.environ.get(SEED_DB_ENV_VAR)
    seed_path = DEFAULT_SEED_DB if seed is None else Path(seed) if seed else None
    parsed = make_url(url)
    target = parsed.database
    if (
        seed_path is None
        or not seed_path.is_file()
        or parsed.get_backend_name() != "sqlite"
        or not target
        or target == ":memory:"
        or target.startswith("file:")
    ):
        return False
    target_path = Path(target)
    if target_path.exists():
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    partial = target_path.with_name(f"{target_path.name}.{os.getpid()}.partial")
    shutil.copyfile(seed_path, partial)
    os.replace(partial, target_path)
    return True


def create_all(engine=None) -> None:
    """Create all tables if they do not already exist, and upgrade an older schema in place.

    With no ``engine`` (the configured database), a database that does not exist yet is first
    created as a copy of the seed database (``seed_database``).
    """
    from stability_eval.data.migrations import upgrade

    if engine is None:
        seed_database()
    engine = engine or _engine
    Base.metadata.create_all(engine)
    upgrade(engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a database session and commit on success, roll back on error."""
    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
