import sqlite3

import pytest

from grant_app import create_app
from tests.test_migrations import (
    ROLLBACK_ORIGINAL_MARKER,
    ROLLBACK_PARAMETER_MARKER,
    ROLLBACK_SQL_MARKER,
    create_legacy_database,
    create_sensitive_invalid_legacy_database,
    inject_dbapi_rollback_failure,
)


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
    assert app.config["MAX_CONTENT_LENGTH"] == 100 * 1024 * 1024
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


def test_create_app_sanitizes_corrupt_sqlite_startup_failure(tmp_path, caplog):
    database_path = tmp_path / "corrupt-factory.sqlite"
    sensitive_marker = "PII-CORRUPT-4f821a"
    original_bytes = f"{sensitive_marker} invalid SQLite bytes".encode()
    database_path.write_bytes(original_bytes)

    with pytest.raises(
        RuntimeError,
        match="existing data was not changed",
    ) as captured:
        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )

    assert str(captured.value) == (
        "SQLite database migration failed; existing data was not changed"
    )
    assert "database_migration_failed stage=begin-transaction" in caplog.text
    assert "BEGIN IMMEDIATE" not in caplog.text
    assert "parameters" not in caplog.text
    assert "file is not a database" not in caplog.text
    assert sensitive_marker not in caplog.text
    assert database_path.read_bytes() == original_bytes


# Protected mutation: a failed rollback makes the persisted data state unknown,
# so startup must give fixed stop/preserve guidance rather than claim no change.
def test_create_app_reports_unconfirmed_rollback_without_leaking_details(
    tmp_path, monkeypatch, caplog
):
    database_path = tmp_path / "rollback-factory.sqlite"
    create_sensitive_invalid_legacy_database(database_path)
    inject_dbapi_rollback_failure(monkeypatch)

    with pytest.raises(RuntimeError) as captured:
        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )

    assert str(captured.value) == (
        "SQLite database migration failed and rollback/data state could not be "
        "confirmed; stop the application and preserve the database and backup"
    )
    assert "existing data was not changed" not in str(captured.value)
    assert "database_migration_failed stage=rollback-unconfirmed" in caplog.text
    assert "exception_type=MigrationError" in caplog.text
    for forbidden in (
        "PII-NAME-4f821a",
        "PII-ADDRESS-91b072",
        ROLLBACK_SQL_MARKER,
        ROLLBACK_PARAMETER_MARKER,
        ROLLBACK_ORIGINAL_MARKER,
        "INSERT INTO",
        "parameters",
    ):
        assert forbidden not in caplog.text
