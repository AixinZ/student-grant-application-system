# Student Grant Application System Design

**Date:** 2026-08-12

**Status:** Approved for implementation planning

## 1. Purpose

Build a simple local web application that internal employees use to enter student information and receive a preliminary student-grant decision. The first version uses a random approval probability. It preserves every submitted application as a read-only historical record and keeps the approval logic behind a replaceable interface so a rule-based engine or machine-learning model can replace it later.

## 2. Confirmed Scope

The minimum viable product includes:

- An English-language employee-facing web interface.
- A form for creating a student grant application.
- Server-side validation for every submitted field, with matching browser-side guidance.
- A random approval engine that returns a probability and decision.
- A success/details page showing the saved probability and decision.
- A read-only history page with search, decision filtering, and pagination.
- A read-only details page for every saved application.
- Local SQLite persistence.
- Automated tests and local setup documentation.
- A structure that can later support French, rule-based approval, and machine-learning approval.

The first version does not include:

- Employee login, authorization, or employee identity tracking.
- Editing or deleting applications.
- Public or company-network deployment.
- Reports, charts, data export, notifications, or document upload.
- A real grant-eligibility rule set or trained machine-learning model.
- Docker or cloud infrastructure.

## 3. Technology Choice

Use a Flask monolith with Jinja templates, vanilla JavaScript, CSS, SQLAlchemy, and SQLite. One Flask process serves both the HTML interface and Python application logic.

This option keeps local setup and operation simple while preserving clear module boundaries. A separate JavaScript framework and API service are unnecessary for the MVP. All dependencies must be installed and executed through the existing project virtual environment at `.venv`, which currently uses Python 3.13.7.

## 4. Architecture

The application has five responsibilities:

1. **Web/UI layer:** Flask routes and Jinja templates render the form, history, and details pages. Vanilla JavaScript provides immediate form feedback and prevents accidental repeated button clicks.
2. **Validation layer:** Normalizes and validates all untrusted form data on the server. Browser validation improves usability but is never treated as authoritative.
3. **Application service:** Coordinates validation, approval evaluation, and one transactional database insert.
4. **Approval engine:** Exposes a stable contract that returns a probability, decision, and engine version. The MVP implementation is `RandomApprovalEngine`.
5. **Repository/data layer:** Uses SQLAlchemy to create and query immutable application records in SQLite. Routes and templates do not execute SQL directly.

English UI text is kept out of business logic and organized so a French translation can be added without changing validation, persistence, or approval behavior.

## 5. Application Data Flow

1. An employee opens the new-application page.
2. The employee completes the form and submits it.
3. The server normalizes and validates every field.
4. If validation fails, the server does not run the approval engine or write to the database. It redisplays the form with preserved safe values and field-specific English errors.
5. For a valid form, `RandomApprovalEngine` generates one probability in the interval `[0, 1)`.
6. A probability greater than `0.5` produces `APPROVED`; a probability less than or equal to `0.5` produces `NOT_APPROVED`.
7. The normalized student data, original probability, final decision, engine version, and submission time are inserted in one database transaction.
8. After a successful commit, the server redirects to that application's read-only details page.
9. Refreshing or reopening the details page reads the saved values and never evaluates the application again.

The redirect after creation follows the Post/Redirect/Get pattern, preventing a normal page refresh from resubmitting the form.

## 6. Pages and Navigation

All pages use consistent English navigation with links to `New Application` and `Application History`.

### 6.1 New Application

The page contains these fields:

- `Name`
- `Annual Income (CAD)`
- `Address`
- `Age`
- `Education Level`
- `Marital Status`
- `Dependents`
- `Province / Territory`

The primary action is `Submit Application`. Required fields are explicitly marked. Client-side behavior gives immediate validation guidance and temporarily disables the submit button while a submission is in progress. Server-side errors remain authoritative and are shown next to their fields with an error summary.

### 6.2 Application History

The history page defaults to newest-first ordering and shows 20 rows per page. Each row contains:

- Application ID
- Name
- Age
- Province/territory code
- Annual income
- Approval probability
- Decision
- Submission time
- A `View Details` link

Employees can perform a case-insensitive partial-name search and select `All`, `Approved`, or `Not Approved`. Search, filter, and page state remain in the URL so a refresh or copied link preserves the view. Invalid page or filter values fall back safely to page 1 and `All`.

The list has no edit or delete controls.

### 6.3 Application Details

This read-only page shows all submitted student fields plus:

- Application ID
- Approval probability
- Decision
- Approval engine version
- Submission time

It provides links back to history and to create another application. It never contains an edit, delete, or reevaluate action. An unknown application ID returns an English `Application not found` page with HTTP status 404.

## 7. Accepted Input Values and Validation

All text values are trimmed. A value containing only whitespace is empty. Browser controls mirror the rules below, but the server repeats every check.

### 7.1 Name

- Required.
- Between 2 and 100 characters after trimming.
- Supports Unicode letters, accented letters, spaces, apostrophes, and hyphens.
- Rejects line breaks, invisible control characters, digits, and unsupported punctuation.

### 7.2 Annual Income

- Required.
- Represents the applicant's yearly income in Canadian dollars.
- Must be a decimal amount from `0.00` through `999,999,999.99` CAD.
- Accepts no more than two decimal places.
- Is stored as an exact decimal amount rather than a binary floating-point currency value.

### 7.3 Address

- Required.
- Between 5 and 200 characters after trimming.
- Rejects line breaks and invisible control characters.
- Preserves normal internal spaces and address punctuation.

### 7.4 Age

- Required.
- Must be an integer from 16 through 100, inclusive.
- Decimal values such as `18.5` are invalid.

### 7.5 Education Level

The field is required and accepts only these values and labels:

- `HIGH_SCHOOL_OR_BELOW` — High School or Below
- `COLLEGE_DIPLOMA` — College / Diploma
- `BACHELORS_DEGREE` — Bachelor's Degree
- `MASTERS_DEGREE` — Master's Degree
- `DOCTORATE` — Doctorate

### 7.6 Marital Status

The field is required and accepts only these values and labels:

- `SINGLE` — Single
- `MARRIED` — Married
- `COMMON_LAW` — Common-law
- `DIVORCED` — Divorced
- `SEPARATED` — Separated
- `WIDOWED` — Widowed

### 7.7 Dependents

- Required.
- Must be an integer from 0 through 20, inclusive.
- Decimal and negative values are invalid.

### 7.8 Province or Territory

The form displays the full Canadian province or territory name with its code. The submitted value is normalized to uppercase, validated against the allowed list, and stored and displayed in summaries as an uppercase two-letter code.

Allowed codes are:

- `AB` — Alberta
- `BC` — British Columbia
- `MB` — Manitoba
- `NB` — New Brunswick
- `NL` — Newfoundland and Labrador
- `NS` — Nova Scotia
- `NT` — Northwest Territories
- `NU` — Nunavut
- `ON` — Ontario
- `PE` — Prince Edward Island
- `QC` — Quebec
- `SK` — Saskatchewan
- `YT` — Yukon

## 8. Approval Engine

An approval engine consumes normalized, validated application data and returns exactly three values:

- `probability`: a value in the inclusive/exclusive interval `[0, 1)`
- `decision`: `APPROVED` or `NOT_APPROVED`
- `engine_version`: a stable identifier describing the implementation

The MVP engine identifier is `random-v1`. It generates one value for each valid new application. The decision threshold is evaluated against the generated value before display rounding:

- `probability > 0.5` means `APPROVED`.
- `probability <= 0.5` means `NOT_APPROVED`.

The generator is injectable so automated tests can supply exact values such as `0.5` and `0.5001`. Later `RuleBasedApprovalEngine` or `MLApprovalEngine` implementations can satisfy the same contract without changing page or history behavior.

The database stores both the probability and final decision. Existing applications are never reevaluated when the engine changes.

## 9. Database Design

SQLite contains one `applications` table. Each application is an append-only record at the application layer.

| Column | Storage | Requirement |
|---|---|---|
| `id` | Integer primary key | Automatically incremented application ID |
| `name` | String(100) | Required |
| `annual_income_cad` | Numeric(11,2) | Required, `0.00` to `999,999,999.99` |
| `address` | String(200) | Required |
| `age` | Integer | Required, 16 to 100 |
| `education_level` | String | Required, allowed-value constraint |
| `marital_status` | String | Required, allowed-value constraint |
| `dependents` | Integer | Required, 0 to 20 |
| `province` | String(2) | Required, uppercase allowed-value constraint |
| `approval_probability` | Numeric | Required, 0 through 1 |
| `decision` | String | Required, `APPROVED` or `NOT_APPROVED` |
| `approval_engine` | String | Required; MVP value is `random-v1` |
| `submitted_at` | Time-zone-aware datetime | Required; stored in UTC |

The final decision is calculated once during creation and is not recalculated from a rounded display value. Database checks enforce numeric ranges and allowed categories as a final data-integrity layer. Indexes support name search, decision filtering, and newest-first ordering.

Only create and read operations are exposed by the application. No HTTP update/delete routes and no repository update/delete methods are included. Because this is a local SQLite application without authentication, a person with direct file-system access could still alter the database file; tamper-evident auditing and operating-system access control are outside this MVP.

## 10. Formatting and Time

- Probabilities display as percentages with two decimal places, such as `73.42%`.
- Decisions always display alongside the probability, using the text `Approved` or `Not Approved`; color is supplementary only.
- Threshold evaluation uses the unrounded generated probability. A value such as `0.50001` can therefore display as `50.00%` while correctly retaining an `Approved` result.
- Annual income displays as CAD currency with grouping separators and two decimal places.
- Submission times are saved in UTC and converted to the local display timezone. For this local MVP, the display timezone is `America/Vancouver`.

## 11. Error Handling and Transactions

- A validation error does not run the approval engine and does not create a record.
- Approval-engine failure does not create a record and shows a general retry message.
- Approval evaluation and the application insert are coordinated so the database contains either one complete record or no record.
- A database exception rolls back the transaction and shows a general error without exposing SQL, paths, stack traces, or configuration secrets.
- Technical details are written to a local application log for diagnosis.
- Logs may contain application IDs, event types, and error context, but must not contain full names, addresses, or full submitted form payloads.
- Unknown records return HTTP 404.
- Unsafe or malformed query parameters use documented safe defaults instead of crashing the page.

## 12. Security and Data Protection

Although the application runs locally and has no login, it uses standard protections appropriate to form data:

- Bind the development server to `127.0.0.1` by default rather than exposing it to the network.
- Protect state-changing form submissions with a CSRF token.
- Escape rendered user data through Jinja's default HTML escaping.
- Use SQLAlchemy parameter binding rather than constructing SQL from form or query text.
- Set a conservative request-body limit because the application accepts no file uploads.
- Load the Flask secret key from local configuration rather than committing it.
- Exclude the SQLite database, local secrets, caches, and logs from version control.

This MVP's lack of authentication is acceptable only for the confirmed single-computer local use case. Authentication and authorization must be designed before network or public deployment.

## 13. Language and Accessibility

The MVP user interface is English. User-visible strings are kept separate from business rules so French labels and messages can be introduced later.

Basic accessibility requirements are:

- Set the document language to `en`.
- Give every form control a visible, programmatically associated label.
- Identify required inputs in text or semantics, not by color alone.
- Associate field errors with their controls and direct focus to the error summary or first invalid control after a failed submission.
- Support complete form and navigation operation by keyboard with a logical focus order and visible focus state.
- Use semantic landmarks, headings, forms, buttons, links, and table headers.
- Give record-specific links accessible names, such as `View details for application 102`.
- Display decision text in addition to status color.
- Maintain readable color contrast.
- Allow the history table to scroll safely on narrow displays.

## 14. Test Strategy

Use `pytest` with an isolated temporary SQLite database. Tests never read or modify the employee's real local database. Use Flask's test client for request/response integration and inject fixed approval probabilities for deterministic approval tests.

Coverage includes:

- Valid, missing, malformed, and boundary values for every input.
- Unicode and accented names, text trimming, control-character rejection, and uppercase province normalization.
- Exact currency parsing and maximum two-decimal precision.
- Allowed education, marital-status, and province values.
- `0.5` producing `NOT_APPROVED` and a value above `0.5` producing `APPROVED`.
- Exactly one engine evaluation and one complete record for a valid submission.
- No record for validation, engine, or database failures.
- Transaction rollback after database failure.
- Newest-first history, case-insensitive partial-name search, decision filtering, and 20-row pagination.
- Full details rendering and HTTP 404 for an unknown ID.
- Absence of application update and delete endpoints.
- Percentage and CAD formatting, important English copy, semantic labels, error associations, and decision text.
- CSRF behavior in production-style configuration, while allowing a controlled test configuration.

Manual browser verification complements automated tests for keyboard flow, visible focus, responsive layout, color contrast, and clear error/result presentation.

## 15. Local Operation

- Use `.venv/bin/python`, `.venv/bin/pip`, and the Flask executable from the existing `.venv`.
- Provide one documented Flask startup command.
- Create the SQLite database and initial table automatically on first local startup.
- Store runtime data in Flask's instance directory, outside tracked source files.
- Provide `.env.example` or equivalent configuration guidance without a real secret.
- Provide an English `README.md` explaining dependency installation, startup, testing, database location, stopping the server, and manual database backup.
- A backup consists of stopping writes and copying the SQLite database file to a protected location. Restoration is a deliberate manual operation and is not exposed in the UI.

## 16. Future Evolution

The approved boundaries support these later changes without redesigning the current pages:

- Replace `random-v1` with a versioned rule-based approval engine.
- Add a versioned machine-learning approval engine and model metadata.
- Add French translations and a language selector.
- Add employee authentication and a `submitted_by` audit relationship.
- Move from SQLite to PostgreSQL before multi-user network deployment.
- Introduce database migrations when schema evolution begins.

Changing to a real eligibility model requires a separate design covering explainability, fairness, privacy, model/rule versioning, validation data, human review, and decision appeal requirements.

## 17. Acceptance Criteria

The MVP is accepted when:

1. An employee can submit all confirmed student fields from an English browser form.
2. Invalid data is rejected with clear field errors and creates no application.
3. A valid submission generates exactly one probability and saves one complete record.
4. The saved result uses the strict `> 0.5` approval rule and displays the probability as a percentage.
5. The history page supports newest-first ordering, name search, decision filtering, and 20-row pagination.
6. `View Details` opens a read-only page containing the full application and saved approval metadata.
7. The application provides no edit or delete capability.
8. Province/territory codes are stored and displayed in uppercase.
9. The application runs locally through the existing Python virtual environment and persists data in SQLite.
10. Automated tests pass against an isolated test database, and the documented manual browser checks pass.

