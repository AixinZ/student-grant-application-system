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

By default the application uses its local SQLite database. To override the
connection for a local development purpose, uncomment and change `DATABASE_URL`
in `.env`.

## Start and stop

Start the server from the repository root:

```bash
.venv/bin/flask --app grant_app:create_app run --host 127.0.0.1
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in a browser. The initial
startup creates the database and tables if they are not already present. To stop
the server, return to its terminal and press `Ctrl-C`.

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

1. Stop the server with `Ctrl-C` so no writes are in progress.
2. Copy `instance/student_grants.sqlite` to a protected, timestamped location.
   For example, use a location managed by the operator's approved backup policy.
3. Restart the server using the command above.

Do not make a live filesystem copy while the server is accepting submissions.

## Restore and recovery

1. Stop the server with `Ctrl-C`.
2. Preserve the current `instance/student_grants.sqlite` separately before
   replacing it.
3. Copy the selected backup into `instance/student_grants.sqlite`.
4. Restart the server using the command above.
5. Open Application History and verify the expected records before accepting new
   applications.

The web interface intentionally does not provide edit, delete, or restore
operations. File-system access to backups and the database must be restricted to
authorized local operators.
