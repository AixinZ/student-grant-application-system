# Student Grant Application System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local English Flask application that creates immutable student grant applications, assigns each valid submission one random approval probability, and provides searchable read-only history and details pages backed by SQLite.

**Architecture:** A Flask application factory wires together Jinja routes, Flask-WTF validation and CSRF, a replaceable approval engine, an application service, a small repository, and a SQLAlchemy SQLite model. The creation service evaluates and persists one complete record, while all later requests only read the stored probability and decision.

**Tech Stack:** Python 3.13.7, Flask 3.1.3, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.51, Flask-WTF 1.3.0, Jinja, vanilla JavaScript, CSS, SQLite, pytest 9.1.1.

## Global Constraints

- Use the existing `/Users/zhengaixin/Desktop/project/.venv`; never install project packages into global Python.
- Bind the local server to `127.0.0.1` by default.
- The UI is English; keep user-visible text out of business logic so French can be added later.
- There is no login, employee identity, update route, delete route, reevaluation route, export, report, upload, Docker, or cloud deployment in this MVP.
- Every valid application generates one probability in `[0, 1)`; `> 0.5` is `APPROVED` and `<= 0.5` is `NOT_APPROVED`.
- Persist the original probability, final decision, `random-v1`, and UTC submission time in the same complete record.
- Province/territory codes are normalized, stored, and shown in uppercase.
- History is newest first, supports case-insensitive partial-name search and decision filtering, and shows 20 records per page.
- Application records are append-only through the web and repository interfaces.
- Currency uses exact decimal values; probability display rounds to two percentage decimals without changing the saved decision.
- Automated tests use a separate temporary SQLite database and deterministic injected probability generators.
- Git commit commands in this plan require Apple Command Line Tools; the current machine cannot run `git` until those tools are installed.

---

## File Structure

Create these focused units:

```text
grant_app/
  __init__.py              application factory and extension wiring
  config.py                environment-backed Flask configuration
  constants.py             allowed select values and decision values
  domain.py                typed input and approval outcome values
  extensions.py            SQLAlchemy and CSRF extension instances
  models.py                immutable Application persistence model
  forms.py                 normalization and server-side form validation
  approval.py              approval protocol and random-v1 implementation
  repository.py            create/read/history database operations
  services.py              one-shot approval-and-persist workflow
  formatters.py            probability, CAD, and Vancouver-time presentation
  routes.py                create, history, details, and error HTTP behavior
  logging_config.py        privacy-conscious rotating local logging
  templates/
    base.html
    applications/new.html
    applications/history.html
    applications/detail.html
    errors/400.html
    errors/404.html
    errors/413.html
    errors/500.html
  static/css/app.css
  static/js/application-form.js
tests/
  conftest.py
  test_app_factory.py
  test_models.py
  test_forms.py
  test_approval.py
  test_services.py
  test_application_routes.py
  test_history_routes.py
  test_security_accessibility.py
docs/manual-test-checklist.md
.env.example
.gitignore
pyproject.toml
requirements.txt
requirements-dev.txt
README.md
```

## Task 1: Reproducible Flask Foundation

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `grant_app/__init__.py`
- Create: `grant_app/config.py`
- Create: `grant_app/extensions.py`
- Create: `tests/conftest.py`
- Create: `tests/test_app_factory.py`

**Interfaces:**
- Produces: `grant_app.create_app(test_config: dict[str, object] | None = None) -> Flask`
- Produces: shared `grant_app.extensions.db` and `grant_app.extensions.csrf`
- Produces: pytest fixtures `app` and `client`

- [ ] **Step 1: Declare exact direct dependencies and pytest configuration**

Create `requirements.txt`:

```text
Flask[dotenv]==3.1.3
Flask-SQLAlchemy==3.1.1
Flask-WTF==1.3.0
SQLAlchemy==2.0.51
```

Create `requirements-dev.txt`:

```text
-r requirements.txt
pytest==9.1.1
```

Create `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

Create `.gitignore` with `.venv/`, `.env`, `instance/`, `*.sqlite`, `*.sqlite3`, `*.log`, `__pycache__/`, `.pytest_cache/`, and `.DS_Store`.

- [ ] **Step 2: Install dependencies only in the existing environment**

Run:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```

Expected: installation succeeds and `.venv/bin/python -c "import flask, flask_sqlalchemy, flask_wtf, pytest"` exits 0.

- [ ] **Step 3: Write the failing factory test and shared fixture**

Create `tests/test_app_factory.py`:

```python
from grant_app import create_app


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
    assert app.config["MAX_CONTENT_LENGTH"] == 16 * 1024
    assert app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False
```

Create `tests/conftest.py` with `app(tmp_path)` calling the same factory configuration, yielding the app, then calling `db.session.remove()` and `db.drop_all()` inside an app context. Add `client(app)` returning `app.test_client()`.

- [ ] **Step 4: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app_factory.py -v`

Expected: FAIL because `grant_app` does not exist.

- [ ] **Step 5: Implement configuration, extensions, and the factory**

Create `grant_app/extensions.py`:

```python
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
csrf = CSRFProtect()
```

Create `grant_app/config.py`:

```python
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///student_grants.sqlite"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024
```

Create `grant_app/__init__.py`:

```python
from pathlib import Path

from flask import Flask

from .config import Config
from .extensions import csrf, db


def create_app(test_config: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)
    with app.app_context():
        db.create_all()
    return app
```

- [ ] **Step 6: Run the foundation test**

Run: `.venv/bin/python -m pytest tests/test_app_factory.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the independently working foundation**

```bash
git add requirements.txt requirements-dev.txt pyproject.toml .gitignore grant_app tests
git commit -m "chore: establish Flask application foundation"
```

## Task 2: Domain Values and Database Integrity

**Files:**
- Create: `grant_app/constants.py`
- Create: `grant_app/domain.py`
- Create: `grant_app/models.py`
- Modify: `grant_app/__init__.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `Decision`, `EDUCATION_CHOICES`, `MARITAL_STATUS_CHOICES`, and `PROVINCE_CHOICES`
- Produces: immutable `ApplicationInput` and `ApprovalOutcome` dataclasses
- Produces: SQLAlchemy model `Application`

- [ ] **Step 1: Write failing persistence and constraint tests**

Create tests that build a valid `Application` using `Decimal("45000.00")`, `Decimal("0.734218")`, `Decision.APPROVED.value`, `BC`, and `random-v1`; commit it and assert every value round-trips. Add a second test that changes `province` to lowercase `bc`, expects `sqlalchemy.exc.IntegrityError` on commit, and rolls the session back.

Use this assertion set:

```python
saved = db.session.get(Application, application.id)
assert saved.annual_income_cad == Decimal("45000.00")
assert saved.province == "BC"
assert saved.approval_probability == Decimal("0.734218")
assert saved.decision == "APPROVED"
assert saved.approval_engine == "random-v1"
```

- [ ] **Step 2: Run model tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`

Expected: FAIL because constants, domain values, and `Application` are undefined.

- [ ] **Step 3: Implement exact choice constants and domain dataclasses**

Use these exact constants so form values, model constraints, filters, and templates share one vocabulary:

```python
from enum import StrEnum


class Decision(StrEnum):
    APPROVED = "APPROVED"
    NOT_APPROVED = "NOT_APPROVED"


EDUCATION_CHOICES = (
    ("HIGH_SCHOOL_OR_BELOW", "High School or Below"),
    ("COLLEGE_DIPLOMA", "College / Diploma"),
    ("BACHELORS_DEGREE", "Bachelor's Degree"),
    ("MASTERS_DEGREE", "Master's Degree"),
    ("DOCTORATE", "Doctorate"),
)

MARITAL_STATUS_CHOICES = (
    ("SINGLE", "Single"),
    ("MARRIED", "Married"),
    ("COMMON_LAW", "Common-law"),
    ("DIVORCED", "Divorced"),
    ("SEPARATED", "Separated"),
    ("WIDOWED", "Widowed"),
)

PROVINCE_CHOICES = (
    ("AB", "Alberta (AB)"),
    ("BC", "British Columbia (BC)"),
    ("MB", "Manitoba (MB)"),
    ("NB", "New Brunswick (NB)"),
    ("NL", "Newfoundland and Labrador (NL)"),
    ("NS", "Nova Scotia (NS)"),
    ("NT", "Northwest Territories (NT)"),
    ("NU", "Nunavut (NU)"),
    ("ON", "Ontario (ON)"),
    ("PE", "Prince Edward Island (PE)"),
    ("QC", "Quebec (QC)"),
    ("SK", "Saskatchewan (SK)"),
    ("YT", "Yukon (YT)"),
)
```

Create `ApplicationInput` with these typed fields:

```python
@dataclass(frozen=True, slots=True)
class ApplicationInput:
    name: str
    annual_income_cad: Decimal
    address: str
    age: int
    education_level: str
    marital_status: str
    dependents: int
    province: str


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    probability: Decimal
    decision: Decision
    engine_version: str
```

- [ ] **Step 4: Implement the model and database checks**

Create `Application` with typed SQLAlchemy mappings, `Numeric(11, 2)` for income, `Numeric(18, 17)` for probability, `DateTime(timezone=True)` with `datetime.now(timezone.utc)` default, and named `CheckConstraint` entries for age, income, dependents, probability, decision, education, marital status, and province.

Add indexes to `name`, `decision`, and `submitted_at`. Do not add model methods that update or delete records.

Modify the factory before `db.create_all()`:

```python
from . import models  # noqa: F401
```

- [ ] **Step 5: Run model tests**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`

Expected: all persistence and constraint tests PASS.

- [ ] **Step 6: Commit domain persistence**

```bash
git add grant_app tests/test_models.py
git commit -m "feat: define immutable application records"
```

## Task 3: Normalization and Form Validation

**Files:**
- Create: `grant_app/forms.py`
- Create: `tests/test_forms.py`

**Interfaces:**
- Consumes: choice constants and `ApplicationInput`
- Produces: `StudentApplicationForm.to_domain() -> ApplicationInput`

- [ ] **Step 1: Write parameterized failing form tests**

Define one valid form payload and parameterize invalid cases for blank text, name length, digits/control characters in names, address length/control characters, age `15`, `101`, and `18.5`, income `-1`, `1000000000`, and `1.999`, dependents `-1`, `21`, and `1.5`, invalid select values, and invalid province codes.

Include these normalization assertions:

```python
form = StudentApplicationForm(
    data={
        **valid_payload,
        "name": "  Marie-Claire O’Neil  ",
        "province": "bc",
    }
)
assert form.validate()
domain = form.to_domain()
assert domain.name == "Marie-Claire O’Neil"
assert domain.province == "BC"
assert domain.annual_income_cad == Decimal("42000.50")
```

- [ ] **Step 2: Run form tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_forms.py -v`

Expected: FAIL because `StudentApplicationForm` is undefined.

- [ ] **Step 3: Implement custom validators and form fields**

Implement:

```python
def trim_text(value: str | None) -> str | None:
    return unicodedata.normalize("NFC", value.strip()) if isinstance(value, str) else value


def normalize_province(value: str | None) -> str | None:
    return trim_text(value).upper() if isinstance(value, str) else value


def validate_name(_form, field) -> None:
    allowed_marks = {" ", "-", "'", "’"}
    if any(not (char.isalpha() or char in allowed_marks) for char in field.data):
        raise ValidationError(
            "Name may contain letters, spaces, apostrophes, and hyphens only."
        )


def reject_control_characters(_form, field) -> None:
    if any(unicodedata.category(char).startswith("C") for char in field.data):
        raise ValidationError("This field contains unsupported characters.")
```

Use `InputRequired` for numeric fields so zero remains valid, `Length`, `NumberRange`, `SelectField(validate_choice=True)`, and a decimal-place validator based on `field.data.as_tuple().exponent < -2`. Give every rule an explicit English error.

Implement `to_domain()` by constructing `ApplicationInput` only after successful validation.

- [ ] **Step 4: Run validation tests**

Run: `.venv/bin/python -m pytest tests/test_forms.py -v`

Expected: all normalization, option, and boundary tests PASS.

- [ ] **Step 5: Commit validation**

```bash
git add grant_app/forms.py tests/test_forms.py
git commit -m "feat: validate student application input"
```

## Task 4: Replaceable Approval Engine and Transactional Creation

**Files:**
- Create: `grant_app/approval.py`
- Create: `grant_app/repository.py`
- Create: `grant_app/services.py`
- Create: `tests/test_approval.py`
- Create: `tests/test_services.py`

**Interfaces:**
- Produces: `ApprovalEngine.evaluate(data: ApplicationInput) -> ApprovalOutcome`
- Produces: `RandomApprovalEngine(random_source: Callable[[], float] = random.random)`
- Produces: `ApplicationRepository.create(application: Application) -> Application`
- Produces: `ApplicationRepository.get(application_id: int) -> Application | None`
- Produces: `create_application(data, engine, repository=None) -> Application`

- [ ] **Step 1: Write failing approval boundary tests**

```python
def test_probability_at_threshold_is_not_approved(valid_input):
    outcome = RandomApprovalEngine(lambda: 0.5).evaluate(valid_input)
    assert outcome.probability == Decimal("0.5")
    assert outcome.decision is Decision.NOT_APPROVED
    assert outcome.engine_version == "random-v1"


def test_probability_above_threshold_is_approved(valid_input):
    outcome = RandomApprovalEngine(lambda: 0.5001).evaluate(valid_input)
    assert outcome.decision is Decision.APPROVED
```

Also assert values below 0 or at/above 1 raise `ApprovalEngineError`.

- [ ] **Step 2: Write failing service atomicity tests**

Use a counting fake engine to prove one call creates one complete record. Use a raising fake engine to prove no row is created. Monkeypatch `db.session.commit` to raise `SQLAlchemyError("database unavailable")`, then assert the repository rolls back and the table remains empty.

- [ ] **Step 3: Run the new tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_approval.py tests/test_services.py -v`

Expected: FAIL because the approval, repository, and service modules do not exist.

- [ ] **Step 4: Implement the approval contract**

Use a `Protocol` for `ApprovalEngine`. In `RandomApprovalEngine.evaluate`, convert with `Decimal(str(self.random_source()))`, reject values outside `[0, 1)`, choose the strict threshold, and return `ApprovalOutcome(..., engine_version="random-v1")`.

- [ ] **Step 5: Implement repository create/get and the service**

The repository create method must have this transaction boundary:

```python
def create(self, application: Application) -> Application:
    try:
        db.session.add(application)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return application
```

The service calls the engine once, maps the input and outcome to one `Application`, and calls `repository.create`. It does not round the probability and does not expose update, delete, or reevaluate methods.

- [ ] **Step 6: Run engine and service tests**

Run: `.venv/bin/python -m pytest tests/test_approval.py tests/test_services.py -v`

Expected: all tests PASS, including `0.5`, `0.5001`, one-call, and rollback cases.

- [ ] **Step 7: Commit the creation workflow**

```bash
git add grant_app/approval.py grant_app/repository.py grant_app/services.py tests
git commit -m "feat: evaluate and persist grant decisions"
```

## Task 5: New Application and Read-Only Details

**Files:**
- Create: `grant_app/formatters.py`
- Create: `grant_app/routes.py`
- Modify: `grant_app/__init__.py`
- Create: `grant_app/templates/base.html`
- Create: `grant_app/templates/applications/new.html`
- Create: `grant_app/templates/applications/detail.html`
- Create: `tests/test_application_routes.py`

**Interfaces:**
- Produces: `web` blueprint
- Produces routes: `GET /`, `GET|POST /applications/new`, `GET /applications/<int:application_id>`
- Produces Jinja filters: `probability_percent`, `cad_currency`, `vancouver_datetime`

- [ ] **Step 1: Write failing create/detail route tests**

Test that GET new returns 200 with all eight labels. POST a valid payload with a configured fixed engine returning `0.734218`; assert a 302 redirect to `/applications/1`, then assert the details response contains `73.42%`, `Approved`, `random-v1`, `BC`, and all full student fields.

Post invalid age `15` and assert status 422, the English age error, zero engine calls, and zero database rows. GET `/applications/999` must return 404.

- [ ] **Step 2: Run route tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_application_routes.py -v`

Expected: FAIL because routes and templates are missing.

- [ ] **Step 3: Implement presentation formatters**

Implement exact behavior:

```python
def probability_percent(value: Decimal) -> str:
    return f"{value * Decimal('100'):.2f}%"


def cad_currency(value: Decimal) -> str:
    return f"${value:,.2f} CAD"
```

For `vancouver_datetime`, treat a naive database value as UTC, convert with `ZoneInfo("America/Vancouver")`, and render an unambiguous English date/time including `PST` or `PDT`.

- [ ] **Step 4: Implement routes and app wiring**

Configure `APPROVAL_ENGINE` to `RandomApprovalEngine()` unless a test override supplies one. Register the blueprint and three Jinja filters in `create_app`.

The POST route must:

```python
form = StudentApplicationForm()
if form.validate_on_submit():
    application = create_application(
        form.to_domain(), current_app.config["APPROVAL_ENGINE"]
    )
    return redirect(url_for("web.application_detail", application_id=application.id))
status = 422 if request.method == "POST" else 200
return render_template("applications/new.html", form=form), status
```

Catch approval and SQLAlchemy failures separately, log only event context, flash a general retry message, and return the form without saving a partial record.

- [ ] **Step 5: Build semantic base, form, and details templates**

`base.html` must contain `<html lang="en">`, a skip link, `<header>`, `<nav aria-label="Primary navigation">`, `<main id="main-content">`, and flashed-message output.

`new.html` must render `form.hidden_tag()`, a linked error summary, visible labels, required semantics, field-level errors with stable IDs, CAD help text, select choices, and `Submit Application`.

`detail.html` must render one `<dl>` containing the full record and links to history and new application. Do not render forms or edit/delete/reevaluate actions.

- [ ] **Step 6: Run route tests**

Run: `.venv/bin/python -m pytest tests/test_application_routes.py -v`

Expected: create, validation, redirect, formatting, details, and 404 tests PASS.

- [ ] **Step 7: Commit create and details pages**

```bash
git add grant_app tests/test_application_routes.py
git commit -m "feat: add application submission and details"
```

## Task 6: Searchable, Filtered, Paginated History

**Files:**
- Modify: `grant_app/repository.py`
- Modify: `grant_app/routes.py`
- Create: `grant_app/templates/applications/history.html`
- Create: `tests/test_history_routes.py`

**Interfaces:**
- Produces: `ApplicationRepository.list_page(name_query, decision, page, per_page=20)`
- Produces route: `GET /applications`
- Consumes query parameters: `q`, `decision`, and `page`

- [ ] **Step 1: Write failing history behavior tests**

Create 23 records with controlled UTC timestamps and mixed decisions. Assert:

```python
response = client.get("/applications")
assert response.status_code == 200
assert response.data.count(b'class="history-row"') == 20
assert response.data.index(b"Newest Student") < response.data.index(b"Older Student")
```

Add tests for case-insensitive partial query `?q=mar`, `?decision=APPROVED`, page 2, combined filters, and preserved query parameters in pagination links. Assert `?page=abc`, `?page=-2`, and an unsupported decision safely use page 1 and All.

- [ ] **Step 2: Run history tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_history_routes.py -v`

Expected: FAIL because the history route and list query are missing.

- [ ] **Step 3: Implement repository history query**

Build a SQLAlchemy `select(Application)` ordered by `submitted_at.desc(), id.desc()`. Apply `func.lower(Application.name).contains(name_query.lower())` only for a non-empty trimmed query of at most 100 characters. Apply decision filtering only for a valid `Decision` value. Paginate with `per_page=20` and `error_out=False`; if a requested page is outside the available range, rerun page 1.

- [ ] **Step 4: Implement history route and template**

Parse a positive integer page with a small helper that returns 1 on malformed input. Render a GET filter form and a semantic table with the approved columns. Each details link must include an accessible name like `View details for application 102`. Use `url_for` with `q`, `decision`, and target `page` for Previous/Next links.

Do not add update or delete controls.

- [ ] **Step 5: Run history tests**

Run: `.venv/bin/python -m pytest tests/test_history_routes.py -v`

Expected: ordering, 20-row pagination, search, filter, combined state, and invalid-query tests PASS.

- [ ] **Step 6: Commit history**

```bash
git add grant_app/repository.py grant_app/routes.py grant_app/templates/applications/history.html tests/test_history_routes.py
git commit -m "feat: add searchable application history"
```

## Task 7: Security, Error Pages, Logging, and Accessible Frontend Behavior

**Files:**
- Create: `grant_app/logging_config.py`
- Modify: `grant_app/__init__.py`
- Modify: `grant_app/routes.py`
- Create: `grant_app/templates/errors/400.html`
- Create: `grant_app/templates/errors/404.html`
- Create: `grant_app/templates/errors/413.html`
- Create: `grant_app/templates/errors/500.html`
- Create: `grant_app/static/css/app.css`
- Create: `grant_app/static/js/application-form.js`
- Modify: `grant_app/templates/base.html`
- Modify: `grant_app/templates/applications/new.html`
- Modify: `grant_app/templates/applications/history.html`
- Modify: `grant_app/templates/applications/detail.html`
- Create: `tests/test_security_accessibility.py`

**Interfaces:**
- Produces: `configure_logging(app: Flask) -> None`
- Produces: error responses for CSRF/400, 404, 413, and 500
- Produces: keyboard-visible, responsive English UI behavior

- [ ] **Step 1: Write failing security and accessibility tests**

Create a CSRF-enabled test app, POST without a token, and assert HTTP 400 with a safe English message. POST a body above 16 KiB and assert 413. Assert PUT, PATCH, and DELETE against an existing details URL return 405 and leave the row unchanged.

For rendered pages, assert:

```python
assert b'<html lang="en">' in response.data
assert b'href="#main-content"' in response.data
assert b'<nav aria-label="Primary navigation">' in response.data
assert b"Approved" in approved_detail.data
assert b"Not Approved" in rejected_detail.data
```

Post an invalid form and assert its error summary links to the invalid control and the control uses `aria-describedby`. Trigger a service error using a fake engine and use `caplog` to assert the log does not contain the submitted full name or address.

- [ ] **Step 2: Run security/accessibility tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_security_accessibility.py -v`

Expected: FAIL until handlers, logging, semantics, CSS, and JavaScript are complete.

- [ ] **Step 3: Add privacy-conscious rotating logging**

Create a `RotatingFileHandler` at `instance/student_grants.log` with `maxBytes=1_000_000`, `backupCount=3`, UTF-8 encoding, timestamps, severity, module, and event message. Do not log form dictionaries, names, addresses, secrets, or SQL parameters. Skip file logging during tests unless a test path is explicitly configured.

- [ ] **Step 4: Add safe error handlers**

Register handlers for `CSRFError`, 404, 413, and unexpected 500 errors. Roll back `db.session` in the 500 handler. Render English pages that state what happened and link back to a safe page; never render exception text or stack traces.

- [ ] **Step 5: Add responsive and accessible CSS**

Define shared color tokens with adequate contrast, a visible `:focus-visible` outline, readable form spacing, explicit error and status styles, a two-column desktop form that becomes one column below 720px, and `.table-scroll { overflow-x: auto; }`. Decision badges must include text; color is supplementary.

- [ ] **Step 6: Add minimal form JavaScript**

Load the script with `defer`. On `submit`, call `form.checkValidity()`; only for a valid form set the submit button's `disabled` property and text to `Submitting…`. On a page with server errors, focus the error summary. Do not calculate approval probability in JavaScript.

- [ ] **Step 7: Run security/accessibility tests and full regression**

Run:

```bash
.venv/bin/python -m pytest tests/test_security_accessibility.py -v
.venv/bin/python -m pytest -q
```

Expected: all tests PASS with no update/delete capability and no sensitive submitted values in logs.

- [ ] **Step 8: Commit security and frontend completion**

```bash
git add grant_app tests/test_security_accessibility.py
git commit -m "feat: harden and polish employee web interface"
```

## Task 8: Operator Documentation and End-to-End Verification

**Files:**
- Create: `.env.example`
- Create: `README.md`
- Create: `docs/manual-test-checklist.md`
- Modify: any previously created file only when verification exposes a documented defect

**Interfaces:**
- Produces: exact setup, start, stop, test, database, log, backup, and recovery instructions
- Produces: a repeatable manual acceptance checklist

- [ ] **Step 1: Write `.env.example` without a real secret**

```dotenv
SECRET_KEY=replace-with-a-random-local-secret
# DATABASE_URL=sqlite:///student_grants.sqlite
```

- [ ] **Step 2: Write the English operator README**

Document these exact commands:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
.venv/bin/flask --app grant_app:create_app run --host 127.0.0.1
.venv/bin/python -m pytest -q
```

Explain that the generated secret must be pasted into an untracked `.env`, the browser URL is `http://127.0.0.1:5000`, Ctrl-C stops the server, the database is `instance/student_grants.sqlite`, and the log is `instance/student_grants.log`.

Document backup as: stop the server, copy `instance/student_grants.sqlite` to a protected timestamped location, then restart. Document restoration as: stop the server, preserve the current file separately, copy the selected backup into the instance path, restart, and verify history before accepting new applications.

- [ ] **Step 3: Write the manual browser acceptance checklist**

Include checked procedures for valid submission, all validation boundaries, `0.5` and above-threshold injected development checks, refresh without resubmission, history ordering/search/filter/pagination, full details, missing record, absence of edit/delete UI and endpoints, uppercase province display, keyboard-only completion, visible focus, error focus, 320px-wide layout, contrast, decision text without color, and log privacy.

- [ ] **Step 4: Run clean automated verification**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all collected tests PASS with zero failures and zero errors.

- [ ] **Step 5: Run local smoke verification**

With a configured `.env`, run:

```bash
.venv/bin/flask --app grant_app:create_app run --host 127.0.0.1
```

Expected: the server reports `http://127.0.0.1:5000`; complete the manual checklist in a browser, stop with Ctrl-C, and confirm `instance/student_grants.sqlite` persists the created history.

- [ ] **Step 6: Commit documentation after verification**

```bash
git add .env.example README.md docs/manual-test-checklist.md
git commit -m "docs: add local operation and acceptance guide"
```

- [ ] **Step 7: Record final evidence**

Capture the final pytest summary, manual-checklist result, Python version from `.venv/bin/python --version`, and installed direct package versions from `.venv/bin/python -m pip show Flask Flask-SQLAlchemy Flask-WTF SQLAlchemy pytest` in the implementation handoff. Do not claim completion unless each required automated and manual check has evidence.
