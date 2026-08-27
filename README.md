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

## Test

Run the automated test suite with:

```bash
.venv/bin/python -m pytest -q
```

The tests use isolated temporary SQLite databases and do not change the local
operator database. For browser acceptance testing, follow
[`docs/manual-test-checklist.md`](docs/manual-test-checklist.md).

## CSV scoring

CSV scoring is a separate local workflow. After starting the server, open
[http://127.0.0.1:5000/csv-scoring](http://127.0.0.1:5000/csv-scoring), choose a
comma-delimited UTF-8 CSV (UTF-8 with BOM is also accepted), select one or more
original columns for the download, choose an available model, then wait for the
download link. Test the full page using the CSV Scoring section of
[`docs/manual-test-checklist.md`](docs/manual-test-checklist.md), including the
keyboard-only and Excel-open checks.

The input file must have one header row, contain 100,000 through 250,000 data
rows, and be no larger than 100 MB. It must not already include a `SCORE`
header. A successful result is UTF-8 with BOM CSV, preserves source row order,
and contains the selected original columns followed by exactly one final
`SCORE` column. `SCORE` uses six decimal places and is fixed risk evidence from
`0` to `1`: low risk at `0` and high risk at `1`. Labels and scores are
screening evidence, not proof of fraud; operators must use appropriate review
and any required decision process rather than treating a score as a finding.

Uploads and generated results are private temporary files, outside SQLite, and
are removed after one hour. Do not upload production data to an instance whose
temporary directory is not appropriately access-restricted. A failed scoring
job provides no partial download.

### Experimental Isolation Forest artifact

The only currently supported artifact is the **Experimental Isolation Forest**.
It is not a production fraud decision model. To make a locally approved
artifact available to the server, set `CSV_SCORING_MODEL_DIR` to the directory
that contains both `isolation_forest_model.joblib` and `iforest_manifest.json`,
then start the app:

```bash
export CSV_SCORING_MODEL_DIR=/absolute/path/to/approved-iforest-artifact
.venv/bin/flask --app grant_app:create_app run --host 127.0.0.1
```

Keep the artifact directory private. If it is unavailable or invalid, the page
shows no available model and no artifact location is exposed to the browser.
When registering future supervised A/B or unsupervised D artifacts, add their
server-side `ModelSpec` and adapter/manifest validation with a stable model ID,
operator-facing display name, required-column contract, score direction, and
training-time calibration. Configure their paths only on the server; API and
page responses must expose only the stable ID, display name, version, and
required columns—never filesystem paths, manifest contents, or raw model
errors.

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
