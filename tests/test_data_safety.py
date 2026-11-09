import os
import sqlite3
from pathlib import Path

import pytest

from backend import database
from backend.config import get_settings


def test_pytest_uses_isolated_database_and_retrieval_paths():
    repository_root = Path(__file__).resolve().parents[1]
    settings = get_settings()

    database_path = Path(os.environ["DATABASE_PATH"]).resolve()
    retrieval_path = settings["vector_index_path"].resolve()

    assert database.DB.resolve() == database_path
    assert not database_path.is_relative_to(repository_root)
    assert not retrieval_path.is_relative_to(repository_root)


def test_pytest_release_configuration_fails_closed():
    settings = get_settings()

    assert settings["clinical_data_approved"] is False
    assert settings["analysis_gate_reasons"]


def test_init_db_refuses_ambiguous_legacy_settings_without_changing_them(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "ambiguous-settings.sqlite"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "CREATE TABLE legacy_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO settings VALUES('review_threshold', '80');"
        "INSERT INTO legacy_settings VALUES('team', 'Coding Unit');"
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(database, "DB", database_path)

    with pytest.raises(RuntimeError, match="Refusing database initialization"):
        database.init_db()

    connection = sqlite3.connect(database_path)
    settings = connection.execute(
        "SELECT key, value FROM settings"
    ).fetchall()
    legacy_settings = connection.execute(
        "SELECT key, value FROM legacy_settings"
    ).fetchall()
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    connection.close()

    assert settings == [("review_threshold", "80")]
    assert legacy_settings == [("team", "Coding Unit")]
    assert tables == {"settings", "legacy_settings"}
