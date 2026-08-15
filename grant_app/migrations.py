import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import MetaData
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from .extensions import db
from .models import (
    Application,
    INCOME_MAX_CENTS,
    make_name_search_key,
)


CURRENT_SCHEMA_VERSION: int = 2
LEGACY_PROBABILITY_SCALE = Decimal(10**17)
MIGRATION_TABLE = "schema_migrations"
TEMP_APPLICATIONS_TABLE = "applications_migrating_v2"


class MigrationError(RuntimeError):
    def __init__(self, stage: str):
        super().__init__(f"SQLite schema migration failed during {stage}")
        self.stage = stage


_LEGACY_FINGERPRINT = (
    ("id", "INTEGER", True, 1),
    ("name", "VARCHAR(100)", True, 0),
    ("annual_income_cad", "NUMERIC(11,2)", True, 0),
    ("address", "VARCHAR(200)", True, 0),
    ("age", "INTEGER", True, 0),
    ("education_level", "VARCHAR(30)", True, 0),
    ("marital_status", "VARCHAR(20)", True, 0),
    ("dependents", "INTEGER", True, 0),
    ("province", "VARCHAR(2)", True, 0),
    ("approval_probability", "NUMERIC(18,17)", True, 0),
    ("decision", "VARCHAR(20)", True, 0),
    ("approval_engine", "VARCHAR(50)", True, 0),
    ("submitted_at", "DATETIME", True, 0),
)

_CURRENT_FINGERPRINT = (
    ("id", "INTEGER", True, 1),
    ("name", "VARCHAR(100)", True, 0),
    ("name_search_key", "VARCHAR(300)", True, 0),
    ("annual_income_cad", "INTEGER", True, 0),
    ("address", "VARCHAR(200)", True, 0),
    ("age", "INTEGER", True, 0),
    ("education_level", "VARCHAR(30)", True, 0),
    ("marital_status", "VARCHAR(20)", True, 0),
    ("dependents", "INTEGER", True, 0),
    ("province", "VARCHAR(2)", True, 0),
    ("approval_probability", "TEXT", True, 0),
    ("decision", "VARCHAR(20)", True, 0),
    ("approval_engine", "VARCHAR(50)", True, 0),
    ("submitted_at", "DATETIME", True, 0),
)

_MIGRATION_FINGERPRINT = (
    ("id", "INTEGER", True, 1),
    ("version", "INTEGER", True, 0),
)

_APPLICATION_COLUMNS = tuple(column[0] for column in _LEGACY_FINGERPRINT)


def _normalize_declared_type(declared_type: str) -> str:
    return re.sub(r"\s+", "", declared_type).upper()


def _table_fingerprint(connection: Connection, table_name: str):
    rows = connection.exec_driver_sql(f"PRAGMA table_info('{table_name}')").fetchall()
    return tuple(
        (
            row[1],
            _normalize_declared_type(row[2]),
            bool(row[3]),
            row[5],
        )
        for row in rows
    )


def _existing_tables(connection: Connection) -> set[str]:
    return {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _read_schema_version(connection: Connection, tables: set[str]) -> int | None:
    if MIGRATION_TABLE not in tables:
        return None
    if _table_fingerprint(connection, MIGRATION_TABLE) != _MIGRATION_FINGERPRINT:
        raise MigrationError("inspect-schema")

    rows = connection.exec_driver_sql(
        "SELECT id, typeof(version), version FROM schema_migrations"
    ).fetchall()
    if len(rows) != 1 or rows[0][0] != 1 or rows[0][1] != "integer":
        raise MigrationError("inspect-schema")

    version = rows[0][2]
    if not isinstance(version, int) or version > CURRENT_SCHEMA_VERSION:
        raise MigrationError("inspect-schema")
    return version


def _inspect_schema(connection: Connection) -> str:
    tables = _existing_tables(connection)
    if TEMP_APPLICATIONS_TABLE in tables:
        raise MigrationError("inspect-schema")

    version = _read_schema_version(connection, tables)
    if "applications" not in tables:
        if version is not None:
            raise MigrationError("inspect-schema")
        return "absent"

    fingerprint = _table_fingerprint(connection, "applications")
    if fingerprint == _LEGACY_FINGERPRINT:
        if version not in (None, 1):
            raise MigrationError("inspect-schema")
        return "legacy"
    if fingerprint == _CURRENT_FINGERPRINT:
        if version not in (None, CURRENT_SCHEMA_VERSION):
            raise MigrationError("inspect-schema")
        return "current"
    return "unknown"


def _convert_income(raw_income) -> Decimal:
    income = Decimal(str(raw_income))
    cents = income * 100
    if (
        not income.is_finite()
        or cents != cents.to_integral_value()
        or cents < 0
        or cents > INCOME_MAX_CENTS
    ):
        raise ValueError
    return income


def _convert_probability(raw_coefficient) -> Decimal:
    if (
        isinstance(raw_coefficient, bool)
        or not isinstance(raw_coefficient, int)
        or raw_coefficient < 0
        or raw_coefficient >= int(LEGACY_PROBABILITY_SCALE)
    ):
        raise ValueError
    return Decimal(raw_coefficient) / LEGACY_PROBABILITY_SCALE


def _convert_legacy_row(row) -> dict:
    raw_timestamp = row["submitted_at"]
    if not isinstance(raw_timestamp, str):
        raise ValueError
    submitted_at = datetime.fromisoformat(raw_timestamp)

    return {
        "id": row["id"],
        "name": row["name"],
        "name_search_key": make_name_search_key(row["name"]),
        "annual_income_cad": _convert_income(row["annual_income_cad"]),
        "address": row["address"],
        "age": row["age"],
        "education_level": row["education_level"],
        "marital_status": row["marital_status"],
        "dependents": row["dependents"],
        "province": row["province"],
        "approval_probability": _convert_probability(row["approval_probability"]),
        "decision": row["decision"],
        "approval_engine": row["approval_engine"],
        "submitted_at": submitted_at,
    }


def _migrate_legacy_applications(connection: Connection) -> None:
    columns_sql = ", ".join(_APPLICATION_COLUMNS)
    source_rows = connection.exec_driver_sql(
        f"SELECT {columns_sql} FROM applications ORDER BY id"
    ).mappings().all()
    source_ids = sorted(row["id"] for row in source_rows)

    temporary_metadata = MetaData()
    temporary_table = Application.__table__.to_metadata(
        temporary_metadata, name=TEMP_APPLICATIONS_TABLE
    )
    temporary_table.indexes.clear()
    temporary_table.create(bind=connection)

    for source_row in source_rows:
        connection.execute(
            temporary_table.insert(), _convert_legacy_row(source_row)
        )

    destination_ids = sorted(
        row[0]
        for row in connection.exec_driver_sql(
            f"SELECT id FROM {TEMP_APPLICATIONS_TABLE} ORDER BY id"
        ).fetchall()
    )
    destination_count = connection.exec_driver_sql(
        f"SELECT count(*) FROM {TEMP_APPLICATIONS_TABLE}"
    ).scalar_one()
    if destination_count != len(source_rows) or destination_ids != source_ids:
        raise MigrationError("validate-records")

    connection.exec_driver_sql("DROP TABLE applications")
    connection.exec_driver_sql(
        f"ALTER TABLE {TEMP_APPLICATIONS_TABLE} RENAME TO applications"
    )
    for index in sorted(Application.__table__.indexes, key=lambda item: item.name):
        index.create(bind=connection)


def _record_schema_version(connection: Connection, version: int) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO schema_migrations (id, version) VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET version = excluded.version
        """,
        (version,),
    )


def ensure_sqlite_schema(engine: Engine) -> None:
    try:
        connection = engine.connect()
    except DBAPIError:
        raise MigrationError("begin-transaction") from None

    with connection:
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        except DBAPIError:
            try:
                connection.rollback()
            except DBAPIError:
                pass
            raise MigrationError("begin-transaction") from None
        try:
            state = _inspect_schema(connection)
            if state == "absent":
                db.metadata.create_all(bind=connection)
            elif state == "legacy":
                _migrate_legacy_applications(connection)
            elif state != "current":
                raise MigrationError("inspect-schema")
            _record_schema_version(connection, CURRENT_SCHEMA_VERSION)
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error, MigrationError):
                raise
            raise MigrationError("apply-schema") from None
