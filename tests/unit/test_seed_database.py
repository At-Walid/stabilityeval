"""A new database starts as a copy of the shipped pilot database (data.database.seed_database)."""
from __future__ import annotations

import sqlite3

import pytest

from stability_eval.data.database import DEFAULT_SEED_DB, SEED_DB_ENV_VAR, seed_database


@pytest.fixture()
def seed_file(tmp_path, monkeypatch):
    path = tmp_path / "seed.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker VALUES ('seeded')")
    conn.close()
    monkeypatch.setenv(SEED_DB_ENV_VAR, str(path))
    return path


def marker(path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        conn.close()


def test_a_missing_database_is_created_from_the_seed(seed_file, tmp_path):
    target = tmp_path / "results" / "stabilityeval.db"
    assert seed_database(f"sqlite:///{target}") is True
    assert marker(target) == "seeded"
    assert list(target.parent.iterdir()) == [target]  # no partial copy left behind


def test_an_existing_database_is_never_touched(seed_file, tmp_path):
    target = tmp_path / "mine.db"
    target.write_bytes(b"")
    assert seed_database(f"sqlite:///{target}") is False
    assert target.read_bytes() == b""


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:", "postgresql://u@h/db"])
def test_only_sqlite_files_are_seeded(seed_file, url):
    assert seed_database(url) is False


def test_an_empty_setting_turns_seeding_off(tmp_path, monkeypatch):
    monkeypatch.setenv(SEED_DB_ENV_VAR, "")
    target = tmp_path / "new.db"
    assert seed_database(f"sqlite:///{target}") is False
    assert not target.exists()


def test_a_missing_seed_file_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv(SEED_DB_ENV_VAR, str(tmp_path / "absent.db"))
    target = tmp_path / "new.db"
    assert seed_database(f"sqlite:///{target}") is False
    assert not target.exists()


def test_the_default_seed_is_the_shipped_pilot_database(monkeypatch):
    monkeypatch.delenv(SEED_DB_ENV_VAR, raising=False)
    assert DEFAULT_SEED_DB.as_posix().endswith("data/pilot/stabilityeval_pilot.db")
    assert DEFAULT_SEED_DB.is_file()
