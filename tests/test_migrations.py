import sqlite3
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from grant_app.extensions import db
from grant_app.migrations import MigrationError, ensure_sqlite_schema
from grant_app.models import Application


LEGACY_COLUMNS = {
    "id": "INTEGER",
    "name": "VARCHAR(100)",
    "annual_income_cad": "NUMERIC(11, 2)",
    "address": "VARCHAR(200)",
    "age": "INTEGER",
    "education_level": "VARCHAR(30)",
    "marital_status": "VARCHAR(20)",
    "dependents": "INTEGER",
    "province": "VARCHAR(2)",
    "approval_probability": "NUMERIC(18, 17)",
    "decision": "VARCHAR(20)",
    "approval_engine": "VARCHAR(50)",
    "submitted_at": "DATETIME",
}

LEGACY_APPLICATIONS_SQL = """
CREATE TABLE applications (
    id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    annual_income_cad NUMERIC(11, 2) NOT NULL,
    address VARCHAR(200) NOT NULL,
    age INTEGER NOT NULL,
    education_level VARCHAR(30) NOT NULL,
    marital_status VARCHAR(20) NOT NULL,
    dependents INTEGER NOT NULL,
    province VARCHAR(2) NOT NULL,
    approval_probability NUMERIC(18, 17) NOT NULL,
    decision VARCHAR(20) NOT NULL,
    approval_engine VARCHAR(50) NOT NULL,
    submitted_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_applications_age_range CHECK (age >= 16 AND age <= 100),
    CONSTRAINT ck_applications_income_range
        CHECK (annual_income_cad >= 0 AND annual_income_cad <= 999999999.99),
    CONSTRAINT ck_applications_dependents_range
        CHECK (dependents >= 0 AND dependents <= 20),
    CONSTRAINT ck_applications_probability_range
        CHECK (approval_probability >= 0
            AND approval_probability <= 100000000000000000),
    CONSTRAINT ck_applications_decision_allowed
        CHECK (decision IN ('APPROVED', 'NOT_APPROVED')),
    CONSTRAINT ck_applications_education_level_allowed
        CHECK (education_level IN ('HIGH_SCHOOL_OR_BELOW', 'COLLEGE_DIPLOMA',
            'BACHELORS_DEGREE', 'MASTERS_DEGREE', 'DOCTORATE')),
    CONSTRAINT ck_applications_marital_status_allowed
        CHECK (marital_status IN ('SINGLE', 'MARRIED', 'COMMON_LAW', 'DIVORCED',
            'SEPARATED', 'WIDOWED')),
    CONSTRAINT ck_applications_province_allowed
        CHECK (province IN ('AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU',
            'ON', 'PE', 'QC', 'SK', 'YT'))
)
"""

LEGACY_ROWS = (
    (
        7,
        "E\u0301LODIE Grant",
        42000.50,
        "24 Accent Street",
        24,
        "BACHELORS_DEGREE",
        "SINGLE",
        0,
        "BC",
        31877934532863472,
        "NOT_APPROVED",
        "random-v1",
        "2026-08-12 18:30:00.000000",
    ),
    (
        23,
        "Jordan Lee",
        999999999.99,
        "99 Boundary Road",
        45,
        "MASTERS_DEGREE",
        "MARRIED",
        2,
        "ON",
        75000000000000000,
        "APPROVED",
        "random-v1",
        "2026-08-13 09:15:30.000000",
    ),
)


def create_legacy_database(
    database_path, rows=LEGACY_ROWS, *, ignore_check_constraints=False
):
    with sqlite3.connect(database_path) as connection:
        if ignore_check_constraints:
            connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(LEGACY_APPLICATIONS_SQL)
        for indexed_column in ("name", "decision", "submitted_at"):
            connection.execute(
                f"CREATE INDEX ix_applications_{indexed_column} "
                f"ON applications ({indexed_column})"
            )
        connection.executemany(
            f"INSERT INTO applications ({', '.join(LEGACY_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in LEGACY_COLUMNS)})",
            rows,
        )


# Protected mutations: removing exact conversion, changing the probability scale,
# normalizing the display name, or omitting a source row/ID must fail this test.
def test_known_legacy_database_is_migrated_without_changing_record_meaning(tmp_path):
    database_path = tmp_path / "legacy.sqlite"
    create_legacy_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")

    ensure_sqlite_schema(engine)
    engine.dispose()

    with sqlite3.connect(database_path) as connection:
        row_count = connection.execute("SELECT count(*) FROM applications").fetchone()[
            0
        ]
        primary_keys = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM applications ORDER BY id"
            ).fetchall()
        ]
        migrated = connection.execute(
            """
            SELECT typeof(annual_income_cad), annual_income_cad,
                   typeof(approval_probability), approval_probability,
                   name, name_search_key
            FROM applications
            WHERE id = 7
            """
        ).fetchone()
        schema_version = connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchone()[0]
        index_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }

    assert row_count == 2
    assert primary_keys == [7, 23]
    assert migrated[0] == "integer"
    assert migrated[1] == 4_200_050
    assert migrated[2] == "text"
    assert migrated[3] == "0.31877934532863472"
    assert migrated[4] == "E\u0301LODIE Grant"
    assert migrated[5] == "élodie grant"
    assert schema_version == 2
    assert index_names == {
        "ix_applications_decision",
        "ix_applications_name",
        "ix_applications_name_search_key",
        "ix_applications_submitted_at",
    }


def read_current_snapshot(database_path):
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM applications ORDER BY id"
        ).fetchall()
        table_sql, rootpage = connection.execute(
            """
            SELECT sql, rootpage
            FROM sqlite_master
            WHERE type = 'table' AND name = 'applications'
            """
        ).fetchone()
        version = connection.execute(
            "SELECT version FROM schema_migrations WHERE id = 1"
        ).fetchone()[0]
    return rows, table_sql, rootpage, version


# Protected mutation: rebuilding or reconverting an already-current table must
# change this persisted snapshot and fail the test.
def test_second_migration_run_is_a_no_op_for_current_database(tmp_path):
    database_path = tmp_path / "idempotent.sqlite"
    create_legacy_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    ensure_sqlite_schema(engine)
    engine.dispose()
    before = read_current_snapshot(database_path)

    engine = create_engine(f"sqlite:///{database_path}")
    ensure_sqlite_schema(engine)
    engine.dispose()

    assert read_current_snapshot(database_path) == before


# Protected mutation: rebuilding an unmarked current table or changing its row
# while adopting it must fail the persisted-row/rootpage assertions.
def test_current_schema_without_version_marker_is_adopted_without_rebuild(tmp_path):
    database_path = tmp_path / "current-without-marker.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    db.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            Application.__table__.insert(),
            {
                "id": 31,
                "name": "Current Student",
                "name_search_key": "current student",
                "annual_income_cad": Decimal("52000.75"),
                "address": "31 Current Way",
                "age": 31,
                "education_level": "COLLEGE_DIPLOMA",
                "marital_status": "COMMON_LAW",
                "dependents": 1,
                "province": "AB",
                "approval_probability": Decimal("0.625"),
                "decision": "APPROVED",
                "approval_engine": "random-v1",
                "submitted_at": datetime.fromisoformat(
                    "2026-08-14 11:45:00.000000"
                ),
            },
        )
    engine.dispose()
    with sqlite3.connect(database_path) as connection:
        row_before = connection.execute(
            "SELECT * FROM applications WHERE id = 31"
        ).fetchone()
        rootpage_before = connection.execute(
            "SELECT rootpage FROM sqlite_master WHERE name = 'applications'"
        ).fetchone()[0]
        objects_before = connection.execute(
            """
            SELECT type, name, tbl_name, rootpage, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()

    engine = create_engine(f"sqlite:///{database_path}")
    ensure_sqlite_schema(engine)
    engine.dispose()

    with sqlite3.connect(database_path) as connection:
        row_after = connection.execute(
            "SELECT * FROM applications WHERE id = 31"
        ).fetchone()
        rootpage_after = connection.execute(
            "SELECT rootpage FROM sqlite_master WHERE name = 'applications'"
        ).fetchone()[0]
        version = connection.execute(
            "SELECT version FROM schema_migrations WHERE id = 1"
        ).fetchone()[0]
        objects_after = connection.execute(
            """
            SELECT type, name, tbl_name, rootpage, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%' AND tbl_name != 'schema_migrations'
            ORDER BY type, name
            """
        ).fetchall()
    assert row_after == row_before
    assert rootpage_after == rootpage_before
    assert objects_after == objects_before
    assert version == 2


# Protected mutation: guessing an unknown schema or persisting migration artifacts
# must change the byte-for-byte schema/row snapshot and fail this test.
def test_unknown_applications_schema_is_rejected_without_modification(tmp_path):
    database_path = tmp_path / "unknown.sqlite"
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

    engine = create_engine(f"sqlite:///{database_path}")
    with pytest.raises(MigrationError) as captured:
        ensure_sqlite_schema(engine)
    engine.dispose()

    with sqlite3.connect(database_path) as connection:
        sql_after = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'applications'"
        ).fetchone()[0]
        rows_after = connection.execute("SELECT * FROM applications").fetchall()
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert captured.value.stage == "inspect-schema"
    assert sql_after == sql_before
    assert rows_after == rows_before
    assert "schema_migrations" not in table_names
    assert "applications_migrating_v2" not in table_names


# Protected mutation: accepting the upper probability bound or committing a
# partial rebuild/version must fail these persisted rollback assertions.
def test_invalid_legacy_row_rolls_back_table_rebuild_and_version(tmp_path):
    database_path = tmp_path / "invalid-legacy.sqlite"
    invalid_row = (
        *LEGACY_ROWS[0][:9],
        10**17,
        *LEGACY_ROWS[0][10:],
    )
    create_legacy_database(
        database_path,
        rows=(invalid_row,),
        ignore_check_constraints=True,
    )
    with sqlite3.connect(database_path) as connection:
        sql_before = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'applications'"
        ).fetchone()[0]
        rows_before = connection.execute("SELECT * FROM applications").fetchall()

    engine = create_engine(f"sqlite:///{database_path}")
    with pytest.raises(MigrationError) as captured:
        ensure_sqlite_schema(engine)
    engine.dispose()

    with sqlite3.connect(database_path) as connection:
        sql_after = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'applications'"
        ).fetchone()[0]
        rows_after = connection.execute("SELECT * FROM applications").fetchall()
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert captured.value.stage == "apply-schema"
    assert sql_after == sql_before
    assert rows_after == rows_before
    assert "applications_migrating_v2" not in table_names
    assert "schema_migrations" not in table_names
