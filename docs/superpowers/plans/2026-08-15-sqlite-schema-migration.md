# SQLite Schema Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically and atomically migrate the known pre-`60cda71` SQLite schema so every immutable historical application remains readable under the current exact-storage model.

**Architecture:** A focused `grant_app/migrations.py` module will inspect the SQLite table declaration, distinguish absent/legacy/current/unknown schemas, and execute a versioned table rebuild inside `BEGIN IMMEDIATE`. Startup will call this schema gate instead of `db.create_all()` directly; legacy values are converted with `Decimal`, current SQLAlchemy model types, and the existing Unicode search-key function, followed by row/ID validation before commit.

**Tech Stack:** Python 3.13, Flask 3.1, Flask-SQLAlchemy 3.1, SQLAlchemy 2.0, SQLite, pytest.

## Global Constraints

- SQLite is the only supported database dialect.
- Preserve every legacy application `id`, display value, decision, approval engine, and submission timestamp; never expose edit, delete, or reevaluation behavior.
- Legacy `annual_income_cad` is CAD dollars and becomes exact integer cents in `0..99,999,999,999`.
- Legacy `approval_probability` is a base-10 integer coefficient at scale `10^17` and becomes exact text in `[0, 1)` without rounding.
- `name_search_key` is NFC-normalized Unicode `casefold()` text; `name` remains unchanged.
- The table rebuild, validation, index recreation, and schema-version write must commit or roll back as one SQLite transaction.
- Unknown schemas or invalid rows must fail startup without modifying the existing applications table or leaking PII in logs/errors.
- Repeated startup against a migrated/current database must not reconvert or replace application records.
- Do not add Alembic, Flask-Migrate, non-SQLite support, downgrade support, or a generic migration framework.

---

## File map

- Create `grant_app/migrations.py`: schema fingerprints, migration exception, exact row conversion, transactional rebuild, version tracking, and the public startup schema gate.
- Create `tests/test_migrations.py`: real-file SQLite fixtures and direct migration/rollback/idempotency tests.
- Modify `grant_app/__init__.py`: replace direct `db.create_all()` startup with the migration gate and privacy-safe failure logging.
- Modify `tests/test_app_factory.py`: application-factory integration against a legacy file and safe startup failure coverage.
- Modify `tests/test_history_routes.py`: prove migrated records are readable through history and details without semantic change.
- Modify `README.md`: automatic migration, pre-upgrade backup, verification, and recovery instructions.

---

### Task 1: Transactional SQLite migration engine

**Files:**
- Create: `grant_app/migrations.py`
- Create: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `grant_app.models.Application`, `grant_app.models.INCOME_MAX_CENTS`, `grant_app.models.make_name_search_key`, `grant_app.extensions.db`.
- Produces: `CURRENT_SCHEMA_VERSION: int = 2`, `MigrationError(stage: str)`, and `ensure_sqlite_schema(engine: sqlalchemy.engine.Engine) -> None`.

- [ ] **Step 1: Add a real legacy database fixture and failing preservation test**

Create a helper in `tests/test_migrations.py` that opens a file with `sqlite3`, executes the known legacy table declaration, and inserts literal rows. The legacy declaration must have exactly these columns and declared types:

```python
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
```

The fixture must include:

```python
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
    31877934532863472,  # 0.31877934532863472 at legacy scale 10**17
    "NOT_APPROVED",
    "random-v1",
    "2026-08-12 18:30:00.000000",
)
```

and a second record using income `999999999.99`, probability coefficient `75000000000000000`, an approved decision, and a different primary key/timestamp.

The first test calls the wished-for `ensure_sqlite_schema(create_engine(url))`, then uses raw SQLite queries to assert literal outcomes:

```python
assert row_count == 2
assert primary_keys == [7, 23]
assert typeof_income == "integer"
assert stored_income == 4_200_050
assert typeof_probability == "text"
assert stored_probability == "0.31877934532863472"
assert stored_name == "E\u0301LODIE Grant"
assert stored_search_key == "élodie grant"
assert schema_version == 2
```

Before writing the test body, name the protected mutation: removing exact conversion, changing scale, normalizing the display name, or omitting a row/ID must fail this test.

- [ ] **Step 2: Run the preservation test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_migrations.py::test_known_legacy_database_is_migrated_without_changing_record_meaning -q
```

Expected: FAIL because `grant_app.migrations` / `ensure_sqlite_schema` does not exist.

- [ ] **Step 3: Implement schema recognition and exact conversion helpers**

In `grant_app/migrations.py`, define:

```python
CURRENT_SCHEMA_VERSION = 2
LEGACY_PROBABILITY_SCALE = Decimal(10**17)
MIGRATION_TABLE = "schema_migrations"
TEMP_APPLICATIONS_TABLE = "applications_migrating_v2"

class MigrationError(RuntimeError):
    def __init__(self, stage: str):
        super().__init__(f"SQLite schema migration failed during {stage}")
        self.stage = stage
```

Implement private helpers that:

- read `PRAGMA table_info('applications')` and compare normalized declared
  types, column names, nullability, and primary-key position against literal
  legacy/current fingerprints;
- reject a migration marker newer than `CURRENT_SCHEMA_VERSION` or inconsistent
  with the detected table shape;
- convert income using `Decimal(str(raw_income)) * 100`, require an integral
  result and the current cents range;
- require the raw legacy probability coefficient to be an integer in
  `0 <= coefficient < 10**17`, then compute
  `Decimal(coefficient) / LEGACY_PROBABILITY_SCALE`;
- parse the legacy ISO timestamp to `datetime`, preserve every other literal
  field, and derive only `name_search_key` with `make_name_search_key(name)`.

Do not include raw values, names, addresses, SQL text, or exception messages in
`MigrationError`.

- [ ] **Step 4: Implement the minimal transactional rebuild**

Implement `ensure_sqlite_schema(engine)` with this control flow:

```python
with engine.connect() as connection:
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        state = inspect_schema(connection)
        if state == "absent":
            db.metadata.create_all(bind=connection)
        elif state == "legacy":
            migrate_legacy_applications(connection)
        elif state != "current":
            raise MigrationError("inspect-schema")
        record_schema_version(connection, CURRENT_SCHEMA_VERSION)
        connection.commit()
    except Exception as error:
        connection.rollback()
        if isinstance(error, MigrationError):
            raise
        raise MigrationError("apply-schema") from error
```

For the legacy branch:

- clone `Application.__table__` to a temporary `MetaData` with name
  `applications_migrating_v2`;
- remove cloned indexes before creating the temporary table so global SQLite
  index names do not conflict with the legacy table;
- insert converted rows through the cloned SQLAlchemy table so `ExactIncome`
  and `ExactProbability` bind processors produce current raw storage;
- compare source/destination counts and sorted primary-key lists;
- drop the legacy table, rename the temporary table to `applications`, and
  create every index declared by `Application.__table__.indexes`;
- create/update a singleton `schema_migrations` row with version `2` in the same
  transaction.

- [ ] **Step 5: Run the preservation test and verify GREEN**

Run the same focused command from Step 2. Expected: `1 passed` with raw integer
cents, exact probability text, original display name, populated search key, and
both primary keys preserved.

- [ ] **Step 6: Add failing idempotency, adoption, unknown-schema, and rollback tests**

Add four behavior tests:

```python
def test_second_migration_run_is_a_no_op_for_current_database(tmp_path):
    # Migrate once, capture rows, sqlite_master table SQL/rootpage and version.
    # Run ensure_sqlite_schema again and assert every captured value is unchanged.

def test_current_schema_without_version_marker_is_adopted_without_rebuild(tmp_path):
    # Create Application metadata directly, insert a current row, capture rootpage,
    # run the gate, then assert only schema version 2 was added.

def test_unknown_applications_schema_is_rejected_without_modification(tmp_path):
    # CREATE TABLE applications (id INTEGER PRIMARY KEY, unexpected TEXT);
    # assert MigrationError.stage == "inspect-schema" and sqlite_master SQL/rows
    # are byte-for-byte unchanged with no migration marker/temp table.

def test_invalid_legacy_row_rolls_back_table_rebuild_and_version(tmp_path):
    # Use PRAGMA ignore_check_constraints=ON to insert coefficient 10**17 into
    # the exact legacy table; assert failure leaves the legacy declaration,
    # all original rows, no temp table, and no version row.
```

Each test must exercise a real file-backed SQLite engine and assert persisted
database state after disposing the engine. Do not mock transactions or SQL.

- [ ] **Step 7: Run the four new tests and verify RED for the missing safeguards**

Run:

```bash
.venv/bin/python -m pytest tests/test_migrations.py -q
```

Expected before completing the safeguards: at least one failure showing a
missing schema-state, idempotency, or rollback behavior; the failure must be an
assertion about persisted state, not a fixture or import error.

- [ ] **Step 8: Complete the minimal safeguards and verify GREEN**

Implement only the branches required by Step 6, keeping schema fingerprints
literal and rejecting rather than guessing. Run:

```bash
.venv/bin/python -m pytest tests/test_migrations.py -q
```

Expected: all migration-engine tests pass.

- [ ] **Step 9: Run focused regression and commit Task 1**

Run:

```bash
.venv/bin/python -m pytest tests/test_models.py tests/test_migrations.py -q
.venv/bin/python -m compileall -q grant_app tests
git diff --check
```

Commit only Task 1 files:

```bash
git add grant_app/migrations.py tests/test_migrations.py
git commit -m "feat: migrate legacy SQLite application records"
```

---

### Task 2: Startup integration, route regression, and operator guidance

**Files:**
- Modify: `grant_app/__init__.py`
- Modify: `tests/test_app_factory.py`
- Modify: `tests/test_history_routes.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `ensure_sqlite_schema(engine) -> None` and `MigrationError.stage` from Task 1; existing `log_exception_context(logger, event, error)`.
- Produces: application startup that creates, adopts, or migrates SQLite safely before registering routes.

- [ ] **Step 1: Add a failing application-factory legacy migration test**

Use the real legacy fixture helper to create a database before calling
`create_app()` with its file URL. Assert factory startup succeeds and raw storage
already has schema version `2`, integer income, text probability, and search key.

Run:

```bash
.venv/bin/python -m pytest tests/test_app_factory.py::test_create_app_migrates_known_legacy_database_before_serving -q
```

Expected: FAIL because startup still calls `db.create_all()` and leaves the
legacy table unchanged.

- [ ] **Step 2: Replace direct create-all startup with the migration gate**

In `create_app`, keep model import before schema work and replace
`db.create_all()` with:

```python
try:
    ensure_sqlite_schema(db.engine)
except MigrationError as error:
    log_exception_context(
        app.logger,
        f"database_migration_failed stage={error.stage}",
        error,
    )
    raise RuntimeError(
        "SQLite database migration failed; existing data was not changed"
    ) from None
```

The operator exception and log event must not contain legacy row values or PII.

- [ ] **Step 3: Run the factory test and verify GREEN**

Run the Step 1 command. Expected: `1 passed`.

- [ ] **Step 4: Add failing history/details and repeated-startup regressions**

Create the exact legacy database, start the application twice in sequence, and
assert through real test-client requests:

```python
history = client.get("/applications?q=élodie")
details = client.get("/applications/7")
assert history.status_code == 200
assert details.status_code == 200
assert "E\u0301LODIE Grant".encode() in history.data
assert b"$42,000.50 CAD" in details.data
assert b"31.88%" in details.data
assert b"Not approved" in details.data
```

After the second startup, assert there are still exactly two records with IDs
`7` and `23` and unchanged `submitted_at`, decisions, and approval engines.

Run the new focused tests before any further production change. Expected against
the old startup path: history/details return `500` or the raw schema assertions
fail.

- [ ] **Step 5: Add safe unknown-schema startup regression**

Create `applications(id INTEGER PRIMARY KEY, unexpected TEXT)`, call
`create_app()`, and assert:

```python
with pytest.raises(
    RuntimeError,
    match="existing data was not changed",
):
    create_app(config)
assert "unexpected" not in caplog.text
assert "database_migration_failed stage=inspect-schema" in caplog.text
```

Reopen the file and assert the original table SQL and rows remain unchanged.

- [ ] **Step 6: Make only the integration corrections needed for GREEN**

Resolve session/engine cleanup needed for two sequential factories without
weakening transaction boundaries or logging raw exceptions. Run:

```bash
.venv/bin/python -m pytest tests/test_app_factory.py tests/test_history_routes.py tests/test_security_accessibility.py -q
```

Expected: all focused startup, history, and privacy tests pass.

- [ ] **Step 7: Document automatic migration operations**

Update README startup/backup/recovery sections with these exact operator facts:

- startup automatically migrates the known legacy schema before accepting
  requests;
- stop the server and create a protected database backup before first startup
  of this revision;
- after startup, verify Application History and one Details page;
- if startup reports migration failure, keep the database and backup untouched,
  do not delete/recreate it, restore the previous application revision, and
  investigate the privacy-safe log event;
- repeated startup is safe and does not reconvert migrated records.

- [ ] **Step 8: Run final verification and commit Task 2**

Run fresh commands on the exact final tree:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q grant_app tests
git diff --check
git status --short --branch
```

Expected: the complete suite passes, compilation and diff checks exit `0`, and
only Task 2 files are pending before commit.

Commit:

```bash
git add grant_app/__init__.py tests/test_app_factory.py tests/test_history_routes.py README.md
git commit -m "fix: migrate existing SQLite history on startup"
```

After both task reviews are clean, run one final full suite on committed `HEAD`,
reproduce history/details against the preserved local legacy database without
deleting it, and request one scoped whole-fix review before declaring the P1
resolved or moving to another task.
