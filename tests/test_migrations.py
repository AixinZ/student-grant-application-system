import sqlite3
import traceback
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

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

CURRENT_COLUMNS = (
    "id",
    "name",
    "name_search_key",
    "annual_income_cad",
    "address",
    "age",
    "education_level",
    "marital_status",
    "dependents",
    "province",
    "approval_probability",
    "decision",
    "approval_engine",
    "submitted_at",
)

CURRENT_ROW = (
    61,
    "Current Student",
    "current student",
    4_200_050,
    "61 Current Street",
    24,
    "BACHELORS_DEGREE",
    "SINGLE",
    0,
    "BC",
    "0.31877934532863472",
    "NOT_APPROVED",
    "random-v1",
    "2026-08-15 13:00:00.000000",
)

ROLLBACK_SQL_MARKER = "ROLLBACK PRIVATE SQL 6d82a1"
ROLLBACK_PARAMETER_MARKER = "PII-ROLLBACK-PARAMETER-47c912"
ROLLBACK_ORIGINAL_MARKER = "PII-ROLLBACK-ORIGINAL-cf31e8"


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


def create_current_database(database_path):
    engine = create_engine(f"sqlite:///{database_path}")
    db.metadata.create_all(bind=engine)
    engine.dispose()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"INSERT INTO applications ({', '.join(CURRENT_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in CURRENT_COLUMNS)})",
            CURRENT_ROW,
        )


def rebuild_applications_declaration(database_path, transform):
    with sqlite3.connect(database_path) as connection:
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'applications'"
        ).fetchone()[0]
        index_sql = [
            row[0]
            for row in connection.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'applications' "
                "ORDER BY name"
            ).fetchall()
        ]
        columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_xinfo('applications')"
            ).fetchall()
            if row[6] == 0
        ]
        rows = connection.execute(
            "SELECT * FROM applications ORDER BY id"
        ).fetchall()
        replacement_sql = transform(table_sql)
        assert replacement_sql != table_sql

        connection.execute("DROP TABLE applications")
        connection.execute(replacement_sql)
        connection.executemany(
            f"INSERT INTO applications ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            rows,
        )
        for statement in index_sql:
            connection.execute(statement)


def read_applications_authentication_snapshot(database_path):
    with sqlite3.connect(database_path) as connection:
        return {
            "objects": connection.execute(
                """
                SELECT type, name, tbl_name, sql
                FROM sqlite_master
                WHERE tbl_name = 'applications'
                ORDER BY type, name
                """
            ).fetchall(),
            "xinfo": connection.execute(
                "PRAGMA table_xinfo('applications')"
            ).fetchall(),
            "table_options": connection.execute(
                """
                SELECT type, ncol, wr, strict
                FROM pragma_table_list
                WHERE schema = 'main' AND name = 'applications'
                """
            ).fetchall(),
            "indexes": [
                (
                    index_row,
                    connection.execute(
                        f"PRAGMA index_xinfo('{index_row[1]}')"
                    ).fetchall(),
                )
                for index_row in connection.execute(
                    "PRAGMA index_list('applications')"
                ).fetchall()
            ],
            "rows": connection.execute(
                "SELECT * FROM applications ORDER BY id"
            ).fetchall(),
        }


def assert_unknown_lookalike_is_unchanged_and_unversioned(database_path):
    before = read_applications_authentication_snapshot(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with pytest.raises(MigrationError) as captured:
            ensure_sqlite_schema(engine)
    finally:
        engine.dispose()

    assert captured.value.stage == "inspect-schema"
    assert read_applications_authentication_snapshot(database_path) == before
    with sqlite3.connect(database_path) as connection:
        object_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "schema_migrations" not in object_names
    assert "applications_migrating_v2" not in object_names


def create_sensitive_invalid_legacy_database(database_path):
    sensitive_row = (
        52,
        "PII-NAME-4f821a",
        42000.50,
        "PII-ADDRESS-91b072",
        15,
        "BACHELORS_DEGREE",
        "SINGLE",
        0,
        "BC",
        31877934532863472,
        "NOT_APPROVED",
        "random-v1",
        "2026-08-15 12:00:00.000000",
    )
    create_legacy_database(
        database_path,
        rows=(sensitive_row,),
        ignore_check_constraints=True,
    )


def inject_dbapi_rollback_failure(monkeypatch):
    def fail_rollback(_connection):
        raise DBAPIError(
            ROLLBACK_SQL_MARKER,
            {"applicant": ROLLBACK_PARAMETER_MARKER},
            sqlite3.OperationalError(ROLLBACK_ORIGINAL_MARKER),
        )

    monkeypatch.setattr(Connection, "rollback", fail_rollback)


# Protected mutation: removing or weakening any current CHECK declaration while
# leaving every visible column unchanged must not be adopted or version-stamped.
@pytest.mark.parametrize(
    "transform",
    [
        lambda sql: sql.replace(
            ", \n\tCONSTRAINT ck_applications_age_range "
            "CHECK (age >= 16 AND age <= 100)",
            "",
            1,
        ),
        lambda sql: sql.replace("age <= 100", "age <= 101", 1),
    ],
    ids=("missing-check", "altered-check"),
)
def test_current_constraint_lookalike_is_rejected_without_modification(
    tmp_path, transform
):
    database_path = tmp_path / "current-constraint-lookalike.sqlite"
    create_current_database(database_path)
    rebuild_applications_declaration(database_path, transform)

    assert_unknown_lookalike_is_unchanged_and_unversioned(database_path)


# Protected mutation: relying on table_info alone would miss the generated
# column, while ignoring table options would adopt the WITHOUT ROWID variant.
@pytest.mark.parametrize(
    "transform",
    [
        lambda sql: sql.replace(
            "\tsubmitted_at DATETIME NOT NULL, ",
            "\tsubmitted_at DATETIME NOT NULL, \n"
            "\tshadow TEXT GENERATED ALWAYS AS (name) VIRTUAL, ",
            1,
        ),
        lambda sql: f"{sql} WITHOUT ROWID",
    ],
    ids=("hidden-generated-column", "without-rowid"),
)
def test_current_xinfo_or_table_option_lookalike_is_rejected_without_modification(
    tmp_path, transform
):
    database_path = tmp_path / "current-table-option-lookalike.sqlite"
    create_current_database(database_path)
    rebuild_applications_declaration(database_path, transform)

    assert_unknown_lookalike_is_unchanged_and_unversioned(database_path)


# Protected mutations: omitting, changing, or adding an index must make the
# complete schema unsupported even though all application columns still match.
@pytest.mark.parametrize(
    "statements",
    [
        ("DROP INDEX ix_applications_name",),
        (
            "DROP INDEX ix_applications_decision",
            "CREATE UNIQUE INDEX ix_applications_decision "
            "ON applications (address)",
        ),
        (
            "CREATE INDEX ix_applications_address "
            "ON applications (address)",
        ),
    ],
    ids=("missing-index", "altered-index", "extra-index"),
)
def test_current_index_lookalike_is_rejected_without_modification(
    tmp_path, statements
):
    database_path = tmp_path / "current-index-lookalike.sqlite"
    create_current_database(database_path)
    with sqlite3.connect(database_path) as connection:
        for statement in statements:
            connection.execute(statement)

    assert_unknown_lookalike_is_unchanged_and_unversioned(database_path)


# Protected mutation: an application trigger is not part of either supported
# schema and must remain byte-for-byte intact when startup rejects the file.
def test_current_schema_with_unexpected_trigger_is_rejected_without_modification(
    tmp_path,
):
    database_path = tmp_path / "current-trigger-lookalike.sqlite"
    create_current_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER unexpected_applications_trigger
            AFTER INSERT ON applications
            BEGIN
                UPDATE applications
                SET name_search_key = lower(NEW.name)
                WHERE id = NEW.id;
            END
            """
        )

    assert_unknown_lookalike_is_unchanged_and_unversioned(database_path)


# Protected mutation: the exact legacy declaration also requires its original
# indexes; a same-column legacy look-alike must not be guessed or rebuilt.
def test_legacy_index_lookalike_is_rejected_without_modification(tmp_path):
    database_path = tmp_path / "legacy-index-lookalike.sqlite"
    create_legacy_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX ix_applications_name")

    assert_unknown_lookalike_is_unchanged_and_unversioned(database_path)


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


# Protected mutation: rejecting a legacy-consistent v1 marker or failing to
# advance it to v2 must fail this preservation test.
def test_legacy_database_with_v1_marker_migrates_and_advances_marker(tmp_path):
    database_path = tmp_path / "legacy-v1.sqlite"
    create_legacy_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO schema_migrations (id, version) VALUES (1, 1)"
        )

    engine = create_engine(f"sqlite:///{database_path}")
    ensure_sqlite_schema(engine)
    engine.dispose()

    with sqlite3.connect(database_path) as connection:
        migrated_rows = connection.execute(
            """
            SELECT id, name, address, annual_income_cad, approval_probability
            FROM applications
            ORDER BY id
            """
        ).fetchall()
        marker = connection.execute(
            "SELECT id, version FROM schema_migrations"
        ).fetchall()
    assert migrated_rows == [
        (
            7,
            "E\u0301LODIE Grant",
            "24 Accent Street",
            4_200_050,
            "0.31877934532863472",
        ),
        (
            23,
            "Jordan Lee",
            "99 Boundary Road",
            99_999_999_999,
            "0.75",
        ),
    ]
    assert marker == [(1, 2)]


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


# Protected mutation: chaining the original constraint exception must expose the
# sensitive row, SQL, or parameters in the rendered migration traceback.
def test_constraint_failure_surfaces_only_sanitized_migration_error(tmp_path):
    database_path = tmp_path / "sensitive-constraint-error.sqlite"
    sensitive_name = "PII-NAME-4f821a"
    sensitive_address = "PII-ADDRESS-91b072"
    constraint_violating_row = (
        52,
        sensitive_name,
        42000.50,
        sensitive_address,
        15,
        "BACHELORS_DEGREE",
        "SINGLE",
        0,
        "BC",
        31877934532863472,
        "NOT_APPROVED",
        "random-v1",
        "2026-08-15 12:00:00.000000",
    )
    create_legacy_database(
        database_path,
        rows=(constraint_violating_row,),
        ignore_check_constraints=True,
    )

    engine = create_engine(f"sqlite:///{database_path}")
    with pytest.raises(MigrationError) as captured:
        ensure_sqlite_schema(engine)
    engine.dispose()
    rendered = "".join(
        traceback.format_exception(captured.type, captured.value, captured.tb)
    )

    assert captured.type is MigrationError
    assert captured.value.stage == "apply-schema"
    assert captured.value.__cause__ is None
    assert "MigrationError" in rendered
    assert "apply-schema" in rendered
    assert sensitive_name not in rendered
    assert sensitive_address not in rendered
    assert "INSERT INTO" not in rendered
    assert "[parameters:" not in rendered
    assert "sqlalchemy.exc.IntegrityError" not in rendered


# Protected mutation: allowing rollback's DBAPIError to replace the migration
# error would expose SQL/parameters and falsely imply that rollback succeeded.
def test_rollback_dbapi_failure_raises_sanitized_unconfirmed_stage(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "rollback-dbapi-failure.sqlite"
    create_sensitive_invalid_legacy_database(database_path)
    inject_dbapi_rollback_failure(monkeypatch)

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with pytest.raises(MigrationError) as captured:
            ensure_sqlite_schema(engine)
    finally:
        engine.dispose()
    rendered = "".join(
        traceback.format_exception(captured.type, captured.value, captured.tb)
    )

    assert captured.type is MigrationError
    assert captured.value.stage == "rollback-unconfirmed"
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    assert "rollback-unconfirmed" in rendered
    for forbidden in (
        "PII-NAME-4f821a",
        "PII-ADDRESS-91b072",
        ROLLBACK_SQL_MARKER,
        ROLLBACK_PARAMETER_MARKER,
        ROLLBACK_ORIGINAL_MARKER,
        "INSERT INTO",
        "[parameters:",
        "sqlalchemy.exc.DBAPIError",
        "sqlalchemy.exc.IntegrityError",
    ):
        assert forbidden not in rendered


# Guardrail: the rollback guard is deliberately limited to DBAPI failures;
# programming defects at the injection seam must remain visible to developers.
def test_non_dbapi_rollback_programming_error_is_not_silenced(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "rollback-programming-error.sqlite"
    create_sensitive_invalid_legacy_database(database_path)

    def fail_rollback(_connection):
        raise AssertionError("rollback programming sentinel")

    monkeypatch.setattr(Connection, "rollback", fail_rollback)
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with pytest.raises(AssertionError, match="rollback programming sentinel"):
            ensure_sqlite_schema(engine)
    finally:
        engine.dispose()
