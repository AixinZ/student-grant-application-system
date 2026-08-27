# Student Grant Applications

Local English-language application for recording student grant applications and
viewing their read-only history. It is intended for one trusted local computer;
do not expose it on a network or use it for public deployment.

## Prerequisites

Use the existing Python virtual environment in `.venv`. Install the development
and runtime dependencies with:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```

## Local secret and configuration

The application requires a local `SECRET_KEY`. Generate one with:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
```

Copy `.env.example` to `.env`, replace the example value with the generated
secret, and keep `.env` untracked. The repository `.gitignore` already excludes
this file. Do not reuse a secret from another environment or commit it.

`DATABASE_URL` is SQLite-only. By default the application uses
`sqlite:///student_grants.sqlite`, which Flask resolves in the local `instance/`
directory, so the default configured database file is
`instance/student_grants.sqlite`. To use a different local SQLite file,
uncomment `DATABASE_URL` in `.env` and set another SQLite SQLAlchemy URL. For
example, `sqlite:////absolute/path/to/student_grants.sqlite` identifies the
configured database file `/absolute/path/to/student_grants.sqlite`. Before any
backup or restore, read the effective `DATABASE_URL` and identify that file; all
database operations below refer to this configured database file. The
application rejects non-SQLite database dialects at startup because its exact
Decimal storage and database constraints are currently implemented specifically
for SQLite.

## Start and stop

Start the server from the repository root:

```bash
.venv/bin/flask --app grant_app:create_app run --host 127.0.0.1
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in a browser. The initial
startup creates the database and tables if they are not already present. Before
accepting requests, startup also automatically migrates the known legacy schema.
Repeated startup is safe and does not reconvert records that were already
migrated. To stop the server, return to its terminal and press `Ctrl-C`.

## Generate synthetic screening data

Open **Data Generator** from the header navigation. Enter a whole-number row
count from **10,000** through **250,000**, then select **Generate Excel File** to
download the XLSX. The browser downloads an Excel workbook containing the
requested number of synthetic student-grant records.

The final **Fraud Label** column contains `Yes` when at least one supported
screening rule matches that synthetic record and `No` when none match. A `Yes`
value is a screening signal for review; it is not a finding or confirmation of
fraud. Use the generated data only for testing and demonstration, not for
decisions about real applicants.

## Test

Run the automated test suite with:

```bash
.venv/bin/python -m pytest -q
```

The tests use isolated temporary SQLite databases and do not change the local
operator database. For browser acceptance testing, follow
[`docs/manual-test-checklist.md`](docs/manual-test-checklist.md).

## Local data and logs

The default database is `instance/student_grants.sqlite`. It contains the
read-only application history. The local application log is
`instance/student_grants.log`; it is a rotating log and is excluded from version
control. Treat both files as private operational data.

## Backup

Before the first startup of this revision, stop the server and create a
protected backup of the database:

1. Stop the server with `Ctrl-C` so no writes are in progress.
2. Identify the configured database file from `DATABASE_URL` as described above.
3. Copy that configured database file to a protected, timestamped location. For
   example, use a location managed by the operator's approved backup policy.
4. Restart the server using the command above.
5. After startup, verify Application History and open one Details page before
   accepting new applications.

Do not make a live filesystem copy while the server is accepting submissions.

## Restore and recovery

If startup reports a database migration failure, keep both the database and its
backup untouched. Do not delete or recreate the database. Restore the previous
application revision, then investigate the privacy-safe
`database_migration_failed` log event before attempting another upgrade.

1. Stop the server with `Ctrl-C`.
2. Identify the configured database file from `DATABASE_URL` as described above.
3. Preserve the current configured database file separately before replacing it.
4. Copy the selected backup over that same configured database file.
5. Restart the server using the command above.
6. Open Application History and verify the expected records before accepting new
   applications.

The web interface intentionally does not provide edit, delete, or restore
operations. File-system access to backups and the database must be restricted to
authorized local operators.
