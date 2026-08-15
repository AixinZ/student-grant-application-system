# SQLite Schema Migration Design

**Date:** 2026-08-13  
**Status:** Approved by user on 2026-08-15

## Purpose

Upgrade databases created before commit `60cda71` without losing or changing
the meaning of immutable application records. The migration must make legacy
records readable by the current history and details pages, remain safe if
startup is repeated, and stop without partially changing the database when an
unexpected schema or invalid legacy value is found.

## Supported database states

Startup recognizes exactly three states:

1. No `applications` table: create the current schema and record the current
   schema version.
2. The known legacy schema: run the legacy-to-current migration in one SQLite
   transaction.
3. The current schema: verify/record the current version and make no data
   changes.

Any other `applications` table shape is unsupported. Startup must fail with a
safe operator-facing error instead of guessing or modifying it.

## Migration architecture

A focused migration module runs during application startup before routes are
registered. It owns schema inspection, version tracking, legacy conversion,
validation, and atomic table replacement. The application remains SQLite-only.

For the known legacy schema, the migration starts an explicit write transaction
and:

1. Inspects the legacy columns and constraints.
2. Creates a temporary table using the current application schema.
3. Reads every legacy record and converts values in Python using `Decimal` and
   Unicode normalization, never binary floating-point arithmetic for business
   values.
4. Inserts converted records with their original primary keys and submission
   timestamps.
5. Confirms the source and destination row counts and primary-key sets match.
6. Replaces the legacy table, recreates current indexes, records the schema
   version, and commits.

SQLite transactional DDL ensures a failure rolls back the temporary table,
replacement, indexes, and version marker together. No web request can run until
startup migration has completed.

## Exact data conversions

- `annual_income_cad`: interpret the legacy value as CAD dollars with at most
  two decimal places, multiply the exact `Decimal` value by 100, and store the
  resulting integer cents. Valid range remains `0..99,999,999,999` cents.
- `approval_probability`: interpret the legacy raw value as the integer
  coefficient previously stored at scale `10^17`; convert it to exact canonical
  decimal text in `[0, 1)` without rounding.
- `name_search_key`: derive NFC-normalized Unicode `casefold()` text from the
  original name. The original display name is unchanged.
- Every other field, including `id`, decision, engine identifier, and
  `submitted_at`, is copied without semantic transformation.

Any row that cannot satisfy the current constraints aborts the entire migration.
The error and logs must not contain applicant PII or raw record values.

## Idempotency and versioning

A small schema-version table records the current migration version. Structural
inspection remains authoritative for databases that predate version tracking.
After a successful migration, subsequent startups recognize the current schema
and perform no record conversion or table replacement. A current-schema database
without a version marker is adopted by recording the current version only after
its required columns and storage declarations are verified.

## Failure handling and operations

- Unknown schemas and invalid legacy rows fail startup before accepting traffic.
- Migration failure rolls back and leaves the legacy database readable by the
  legacy application version.
- Logs contain only privacy-safe exception type and migration-stage metadata.
- Operators should stop the server and make a protected backup before deploying
  a revision that performs a migration. README instructions will describe the
  backup, automatic migration, verification, and recovery workflow.
- The migration never deletes individual application records and does not add
  edit, delete, or reevaluation capabilities.

## Test strategy

Strict TDD will begin with a real SQLite fixture containing the exact legacy
table definition and representative records, including accented/decomposed
names, boundary income, and precise probabilities. Regression coverage must
prove:

- the current code fails to read the legacy fixture before the fix;
- first startup migrates it and history/details return the preserved records;
- raw current storage uses integer cents, exact probability text, and populated
  search keys;
- record count, primary keys, decisions, timestamps, and display values are
  preserved;
- a second startup is a no-op and remains readable;
- a forced invalid legacy row or unknown schema causes full rollback with no
  partial replacement or version advance;
- fresh databases and already-current databases still initialize normally;
- the focused migration tests and complete project suite pass.

## Out of scope

- Non-SQLite databases.
- Migration from arbitrary or manually modified schemas.
- A general migration framework or downgrade support.
- Editing, deleting, or reevaluating historical applications.
