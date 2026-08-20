"""Authenticate SQLite schemas and transactionally migrate supported legacy records."""

import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import MetaData
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.schema import CreateTable

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
ROLLBACK_FAILURE_STAGE = "rollback-unconfirmed"


class MigrationError(RuntimeError):
    def __init__(self, stage: str):
        """Create a sanitized migration failure for a specific processing stage.

        Args:
            stage: A stable operator-facing stage identifier that contains no
                SQL, parameters, record values, or raw database error message.
        """
        super().__init__(f"SQLite schema migration failed during {stage}")
        self.stage = stage


_LEGACY_COLUMNS = (
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

_CURRENT_COLUMNS = (
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

_MIGRATION_COLUMNS = (
    ("id", "INTEGER", True, 1),
    ("version", "INTEGER", True, 0),
)

_LEGACY_TABLE_SQL = """
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

_MIGRATION_TABLE_SQL = """
CREATE TABLE schema_migrations (
    id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
)
"""

_APPLICATION_COLUMNS = tuple(column[0] for column in _LEGACY_COLUMNS)


def _expected_xinfo(columns):
    """Build the expected ``pragma_table_xinfo`` fingerprint for known columns.

    Args:
        columns: Ordered column specifications containing name, declared type,
            nullability, and primary-key position.

    Returns:
        A tuple matching SQLite's normalized extended column metadata shape.
    """
    return tuple(
        (position, name, declared_type, not_null, None, primary_key, 0)
        for position, (name, declared_type, not_null, primary_key) in enumerate(
            columns
        )
    )


_LEGACY_XINFO = _expected_xinfo(_LEGACY_COLUMNS)
_CURRENT_XINFO = _expected_xinfo(_CURRENT_COLUMNS)
_MIGRATION_XINFO = _expected_xinfo(_MIGRATION_COLUMNS)


def _expected_index(column_id: int, column_name: str):
    """Build the expected fingerprint for one ordinary single-column index.

    Args:
        column_id: The zero-based SQLite column identifier indexed by the key.
        column_name: The corresponding database column name.

    Returns:
        A normalized index descriptor matching ``pragma_index_list`` and
        ``pragma_index_xinfo`` output.
    """
    return (False, "c", False, ((0, column_id, column_name, False, "BINARY"),))


_LEGACY_INDEXES = {
    "ix_applications_name": _expected_index(1, "name"),
    "ix_applications_decision": _expected_index(10, "decision"),
    "ix_applications_submitted_at": _expected_index(12, "submitted_at"),
}

_CURRENT_INDEXES = {
    "ix_applications_name": _expected_index(1, "name"),
    "ix_applications_name_search_key": _expected_index(2, "name_search_key"),
    "ix_applications_decision": _expected_index(11, "decision"),
    "ix_applications_submitted_at": _expected_index(13, "submitted_at"),
}


def _normalize_declared_type(declared_type: str) -> str:
    """Normalize SQLite declared types for stable schema comparison.

    Args:
        declared_type: The type text reported by SQLite schema metadata.

    Returns:
        Uppercase type text with insignificant whitespace removed.
    """
    return re.sub(r"\s+", "", declared_type).upper()


def _normalize_sql_fragment(fragment: str | None) -> str | None:
    """Remove insignificant SQL whitespace while preserving quoted content.

    Args:
        fragment: A SQL declaration fragment, or ``None`` for a missing default.

    Returns:
        A lowercase, whitespace-free representation outside quoted strings, or
        ``None`` when the input is ``None``.

    Raises:
        ValueError: If a quoted SQL identifier or string is not terminated.
    """
    if fragment is None:
        return None

    normalized: list[str] = []
    quote: str | None = None
    position = 0
    while position < len(fragment):
        character = fragment[position]
        if quote is not None:
            normalized.append(character)
            if character == quote:
                if position + 1 < len(fragment) and fragment[position + 1] == quote:
                    normalized.append(fragment[position + 1])
                    position += 1
                else:
                    quote = None
        elif character in ("'", '"', "`"):
            quote = character
            normalized.append(character)
        elif not character.isspace():
            normalized.append(character.lower())
        position += 1
    if quote is not None:
        raise ValueError
    return "".join(normalized)


def _table_declaration_fingerprint(table_sql: str):
    """Parse table SQL into comparable columns, constraints, and options.

    Args:
        table_sql: A complete SQLite ``CREATE TABLE`` statement.

    Returns:
        A three-part fingerprint containing ordered column declarations,
        order-independent constraints, and normalized table options.

    Raises:
        ValueError: If the declaration has unbalanced parentheses, unterminated
            quotes, or no table-body opening parenthesis.
    """
    opening_parenthesis = table_sql.find("(")
    if opening_parenthesis < 0:
        raise ValueError

    parts: list[str] = []
    current: list[str] = []
    depth = 1
    quote: str | None = None
    position = opening_parenthesis + 1
    closing_parenthesis: int | None = None
    while position < len(table_sql):
        character = table_sql[position]
        if quote is not None:
            current.append(character)
            if character == quote:
                if position + 1 < len(table_sql) and table_sql[position + 1] == quote:
                    current.append(table_sql[position + 1])
                    position += 1
                else:
                    quote = None
        elif character in ("'", '"', "`"):
            quote = character
            current.append(character)
        elif character == "(":
            depth += 1
            current.append(character)
        elif character == ")":
            depth -= 1
            if depth == 0:
                parts.append("".join(current))
                closing_parenthesis = position
                break
            current.append(character)
        elif character == "," and depth == 1:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
        position += 1

    if quote is not None or closing_parenthesis is None:
        raise ValueError

    normalized_parts = tuple(_normalize_sql_fragment(part) for part in parts)
    constraint_prefixes = (
        "check(",
        "constraint",
        "foreignkey(",
        "primarykey(",
        "unique(",
    )
    columns = tuple(
        part
        for part in normalized_parts
        if not part.startswith(constraint_prefixes)
    )
    constraints = tuple(
        sorted(
            part
            for part in normalized_parts
            if part.startswith(constraint_prefixes)
        )
    )
    options = _normalize_sql_fragment(
        table_sql[closing_parenthesis + 1 :].rstrip().removesuffix(";")
    )
    return columns, constraints, options


def _table_xinfo(connection: Connection, table_name: str):
    """Read and normalize extended SQLite column metadata for one table.

    Args:
        connection: The connection holding the active migration transaction.
        table_name: The trusted table name to inspect through a bound parameter.

    Returns:
        A tuple describing column order, names, types, nullability, defaults,
        primary-key positions, and hidden/generated-column status.
    """
    rows = connection.exec_driver_sql(
        "SELECT * FROM pragma_table_xinfo(?)",
        (table_name,),
    ).fetchall()
    return tuple(
        (
            row[0],
            row[1],
            _normalize_declared_type(row[2]),
            bool(row[3]),
            _normalize_sql_fragment(row[4]),
            row[5],
            row[6],
        )
        for row in rows
    )


def _table_options(connection: Connection, table_name: str):
    """Read SQLite table kind, column count, rowid mode, and strict mode.

    Args:
        connection: The connection holding the active migration transaction.
        table_name: The trusted table name to inspect.

    Returns:
        A normalized table-options tuple, or ``None`` when exactly one matching
        main-schema table is not present.
    """
    rows = connection.exec_driver_sql(
        """
        SELECT type, ncol, wr, strict
        FROM pragma_table_list
        WHERE schema = 'main' AND name = ?
        """,
        (table_name,),
    ).fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    return row[0], row[1], bool(row[2]), bool(row[3])


def _table_sql(connection: Connection, table_name: str) -> str | None:
    """Return the canonical CREATE statement stored for a SQLite table.

    Args:
        connection: The connection holding the active migration transaction.
        table_name: The trusted table name to locate in ``sqlite_master``.

    Returns:
        The stored ``CREATE TABLE`` SQL, or ``None`` when the table is missing,
        duplicated, or does not have textual SQL.
    """
    rows = connection.exec_driver_sql(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ? AND tbl_name = ?
        """,
        (table_name, table_name),
    ).fetchall()
    if len(rows) != 1 or not isinstance(rows[0][0], str):
        return None
    return rows[0][0]


def _index_fingerprints(connection: Connection, table_name: str):
    """Collect normalized definitions for every index associated with a table.

    Args:
        connection: The connection holding the active migration transaction.
        table_name: The trusted table name whose indexes are inspected.

    Returns:
        A mapping from index name to uniqueness, origin, partial-index status,
        and ordered key-column metadata.
    """
    indexes = {}
    for row in connection.exec_driver_sql(
        "SELECT * FROM pragma_index_list(?)",
        (table_name,),
    ).fetchall():
        index_name = row[1]
        key_columns = tuple(
            (
                index_row[0],
                index_row[1],
                index_row[2],
                bool(index_row[3]),
                index_row[4],
            )
            for index_row in connection.exec_driver_sql(
                "SELECT * FROM pragma_index_xinfo(?)",
                (index_name,),
            ).fetchall()
            if bool(index_row[5])
        )
        indexes[index_name] = (
            bool(row[2]),
            row[3],
            bool(row[4]),
            key_columns,
        )
    return indexes


def _related_objects(connection: Connection, table_name: str):
    """List non-internal SQLite objects attached to a table.

    Args:
        connection: The connection holding the active migration transaction.
        table_name: The trusted table name whose objects are inspected.

    Returns:
        A set of ``(type, name, table_name)`` tuples covering the table, indexes,
        triggers, and any other related non-internal objects.
    """
    return {
        (row[0], row[1], row[2])
        for row in connection.exec_driver_sql(
            """
            SELECT type, name, tbl_name
            FROM sqlite_master
            WHERE tbl_name = ? AND name NOT LIKE 'sqlite_%'
            """,
            (table_name,),
        ).fetchall()
    }


def _matches_supported_table(
    connection: Connection,
    table_name: str,
    *,
    expected_sql: str,
    expected_xinfo,
    expected_indexes,
) -> bool:
    """Authenticate a live SQLite table against an exact supported fingerprint.

    Args:
        connection: The connection holding the active migration transaction.
        table_name: The trusted table name to authenticate.
        expected_sql: The supported ``CREATE TABLE`` declaration.
        expected_xinfo: The expected extended column metadata.
        expected_indexes: The complete expected index fingerprint mapping.

    Returns:
        ``True`` only when declaration contents, column metadata, table options,
        indexes, and related object inventory all match the supported schema.
    """
    table_sql = _table_sql(connection, table_name)
    if table_sql is None:
        return False
    try:
        declaration_matches = _table_declaration_fingerprint(
            table_sql
        ) == _table_declaration_fingerprint(expected_sql)
    except ValueError:
        return False

    expected_objects = {
        ("table", table_name, table_name),
        *(("index", index_name, table_name) for index_name in expected_indexes),
    }
    return (
        declaration_matches
        and _table_xinfo(connection, table_name) == expected_xinfo
        and _table_options(connection, table_name)
        == ("table", len(expected_xinfo), False, False)
        and _index_fingerprints(connection, table_name) == expected_indexes
        and _related_objects(connection, table_name) == expected_objects
    )


def _existing_tables(connection: Connection) -> set[str]:
    """Return every table name currently registered in the SQLite database.

    Args:
        connection: The connection holding the active migration transaction.

    Returns:
        A set containing table names from ``sqlite_master``.
    """
    return {
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _read_schema_version(connection: Connection, tables: set[str]) -> int | None:
    """Validate and read the single supported schema-version marker.

    Args:
        connection: The connection holding the active migration transaction.
        tables: The complete set of currently existing table names.

    Returns:
        The recorded integer schema version, or ``None`` when the version table
        does not exist.

    Raises:
        MigrationError: If the version table, its row, or its version value does
            not exactly match a supported state.
    """
    if MIGRATION_TABLE not in tables:
        return None
    if not _matches_supported_table(
        connection,
        MIGRATION_TABLE,
        expected_sql=_MIGRATION_TABLE_SQL,
        expected_xinfo=_MIGRATION_XINFO,
        expected_indexes={},
    ):
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
    """Classify the database as absent, legacy, current, or unknown.

    Args:
        connection: The connection holding the active migration transaction.

    Returns:
        ``"absent"``, ``"legacy"``, ``"current"``, or ``"unknown"`` after
        authenticating tables, constraints, indexes, objects, and version state.

    Raises:
        MigrationError: If a leftover temporary table or contradictory version
            marker makes the database unsafe to classify.
    """
    tables = _existing_tables(connection)
    if TEMP_APPLICATIONS_TABLE in tables:
        raise MigrationError("inspect-schema")

    version = _read_schema_version(connection, tables)
    if "applications" not in tables:
        if version is not None:
            raise MigrationError("inspect-schema")
        return "absent"

    if _matches_supported_table(
        connection,
        "applications",
        expected_sql=_LEGACY_TABLE_SQL,
        expected_xinfo=_LEGACY_XINFO,
        expected_indexes=_LEGACY_INDEXES,
    ):
        if version not in (None, 1):
            raise MigrationError("inspect-schema")
        return "legacy"
    current_table_sql = str(
        CreateTable(Application.__table__).compile(dialect=connection.dialect)
    )
    if _matches_supported_table(
        connection,
        "applications",
        expected_sql=current_table_sql,
        expected_xinfo=_CURRENT_XINFO,
        expected_indexes=_CURRENT_INDEXES,
    ):
        if version not in (None, CURRENT_SCHEMA_VERSION):
            raise MigrationError("inspect-schema")
        return "current"
    return "unknown"


def _convert_income(raw_income) -> Decimal:
    """Validate a legacy income value for exact integer-cent storage.

    Args:
        raw_income: The numeric value read from a supported legacy row.

    Returns:
        A finite ``Decimal`` representing a supported non-negative CAD amount.

    Raises:
        ValueError: If the value is non-finite, exceeds two decimal places, or
            falls outside the current model's supported range.
        InvalidOperation: If the legacy value cannot be parsed as a decimal.
    """
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
    """Convert a scaled legacy probability integer to an exact decimal.

    Args:
        raw_coefficient: The integer coefficient stored by the legacy SQLite
            numeric representation.

    Returns:
        The exact probability obtained by dividing by the legacy scale.

    Raises:
        ValueError: If the value is boolean, non-integer, negative, or at least
            the full legacy probability scale.
    """
    if (
        isinstance(raw_coefficient, bool)
        or not isinstance(raw_coefficient, int)
        or raw_coefficient < 0
        or raw_coefficient >= int(LEGACY_PROBABILITY_SCALE)
    ):
        raise ValueError
    return Decimal(raw_coefficient) / LEGACY_PROBABILITY_SCALE


def _convert_legacy_row(row) -> dict:
    """Translate one authenticated legacy row into current model values.

    Args:
        row: A SQLAlchemy mapping containing every legacy application column.

    Returns:
        A dictionary ready for insertion into the current applications table,
        including exact income, exact probability, and normalized name key.

    Raises:
        ValueError: If the timestamp or any converted numeric value is not in a
            supported legacy representation.
    """
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


def _index_name(index):
    """Return an index name for deterministic recreation order.

    Args:
        index: A named SQLAlchemy index belonging to the applications table.

    Returns:
        The index's stable database name.
    """
    return index.name


def _migrate_legacy_applications(connection: Connection) -> None:
    """Rebuild the legacy applications table without losing immutable records.

    Args:
        connection: The connection holding the exclusive migration transaction.

    Raises:
        MigrationError: If the rebuilt table does not contain exactly the same
            record count and primary-key set as the legacy source.
        ValueError: If any supported legacy row cannot be converted safely.

    Notes:
        The function creates a constrained temporary current-schema table,
        converts every row, validates identity preservation, replaces the legacy
        table, and recreates all current indexes. Its caller owns commit and
        rollback.
    """
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
    for index in sorted(Application.__table__.indexes, key=_index_name):
        index.create(bind=connection)


def _record_schema_version(connection: Connection, version: int) -> None:
    """Create or update the single-row schema-version marker.

    Args:
        connection: The connection holding the active migration transaction.
        version: The current supported schema version to persist.

    Notes:
        This operation remains inside the caller's transaction and is idempotent
        for repeated application startups.
    """
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
    """Authenticate, create, or migrate the SQLite schema in one transaction.

    Args:
        engine: The configured SQLite SQLAlchemy engine.

    Raises:
        MigrationError: If the connection or exclusive transaction cannot begin,
            the schema is unsupported, row conversion or validation fails, or
            rollback cannot be confirmed. The ``stage`` attribute identifies a
            sanitized failure boundary for operators.

    Notes:
        Startup acquires ``BEGIN IMMEDIATE`` before inspection. Fresh databases
        are created, exact legacy schemas are migrated, current schemas are
        adopted idempotently, and unknown lookalikes are rejected. Any failure
        is rolled back; a connection whose rollback fails is invalidated so the
        pool cannot retry and leak the raw database error.
    """
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
            try:
                connection.rollback()
            except DBAPIError:
                connection.invalidate()
                raise MigrationError(ROLLBACK_FAILURE_STAGE) from None
            if isinstance(error, MigrationError):
                raise
            raise MigrationError("apply-schema") from None
