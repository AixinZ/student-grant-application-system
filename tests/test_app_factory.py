import sqlite3

import pytest

from grant_app import create_app
from tests.test_migrations import create_legacy_database


def test_create_app_uses_test_configuration(tmp_path):
    database_path = tmp_path / "factory.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )

    assert app.config["TESTING"] is True
    assert app.config["MAX_CONTENT_LENGTH"] == 16 * 1024
    assert app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False


def test_create_app_rejects_non_sqlite_database_before_loading_driver():
    with pytest.raises(RuntimeError, match="SQLite"):
        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": (
                    "postgresql+psycopg://employee:secret@localhost/grants"
                ),
            }
        )


def test_create_app_migrates_known_legacy_database_before_serving(tmp_path):
    database_path = tmp_path / "legacy-factory.sqlite"
    create_legacy_database(database_path)

    create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )

    with sqlite3.connect(database_path) as connection:
        schema_version = connection.execute(
            "SELECT version FROM schema_migrations WHERE id = 1"
        ).fetchone()[0]
        stored = connection.execute(
            """
            SELECT typeof(annual_income_cad),
                   typeof(approval_probability),
                   name_search_key
            FROM applications
            WHERE id = 7
            """
        ).fetchone()

    assert schema_version == 2
    assert stored == ("integer", "text", "élodie grant")


def test_create_app_rejects_unknown_schema_without_changing_database(
    tmp_path, caplog
):
    database_path = tmp_path / "unknown-factory.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE applications (id INTEGER PRIMARY KEY, unexpected TEXT)"
        )
        connection.execute(
            "INSERT INTO applications (id, unexpected) VALUES (41, 'literal')"
        )
        sql_before = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'applications'"
        ).fetchone()[0]
        rows_before = connection.execute("SELECT * FROM applications").fetchall()

    with pytest.raises(
        RuntimeError,
        match="existing data was not changed",
    ):
        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )

    assert "unexpected" not in caplog.text
    assert "database_migration_failed stage=inspect-schema" in caplog.text
    with sqlite3.connect(database_path) as connection:
        sql_after = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'applications'"
        ).fetchone()[0]
        rows_after = connection.execute("SELECT * FROM applications").fetchall()

    assert sql_after == sql_before
    assert rows_after == rows_before
