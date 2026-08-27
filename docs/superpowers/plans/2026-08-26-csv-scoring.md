# CSV Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local Flask CSV scoring workflow that validates 100,000–250,000-row CSVs, lets an operator choose output columns and one pre-trained model, produces a UTF-8-BOM CSV with a normalized six-decimal `SCORE`, and exposes a testable browser page.

**Architecture:** Use staged HTTP endpoints backed by protected temporary files and JSON manifests, with a single-worker in-process executor for chunked scoring. Keep CSV parsing, task storage, model adapters, calibration, and export independent from Flask routes; register the existing Isolation Forest artifact as an explicitly experimental model and leave the A/B/D artifacts for later registration.

**Tech Stack:** Python 3.13, Flask 3.1, Flask-WTF, standard-library `csv`/`tempfile`/`json`/`concurrent.futures`, the existing Isolation Forest stack (`numpy`, `scikit-learn`, `joblib`) behind an optional model dependency, pytest, Jinja templates, and vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-26-csv-scoring-design.md`

## Global Constraints

- Models are pre-trained artifacts; upload requests never train models.
- One scoring task selects exactly one model.
- Column selection controls output columns only; a model still receives its fixed required input columns.
- Output is UTF-8 with BOM, preserves source row order, and contains selected original columns followed by `SCORE`.
- `SCORE` is six-decimal `0..1`; `0` is lowest risk and `1` is highest risk.
- A source header named `SCORE` is rejected.
- Input is comma-delimited CSV, first row is a header, UTF-8 or UTF-8 BOM.
- Header matching trims surrounding whitespace and ignores case; normalized duplicates are rejected.
- Every data row has the same field count as the header.
- Data-row count is 100,000 through 250,000 inclusive; request/file size is at most 100 MB.
- Uploaded sources, manifests, and results are outside SQLite and expire after one hour.
- Processing is all-or-nothing; no partial result is downloadable.
- Errors and logs never expose cell values, complete rows, filesystem paths, model stack traces, or exception messages.
- Existing application-entry/history behaviour and tests remain unchanged.

---

### Task 1: Dependencies, configuration, and module boundaries

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements-dev.txt`
- Modify: `grant_app/config.py`
- Modify: `grant_app/__init__.py`
- Create: `grant_app/csv_scoring/__init__.py`
- Create: `grant_app/csv_scoring/errors.py`
- Test: `tests/test_csv_scoring_config.py`

**Interfaces:**
- Produces config values `CSV_SCORING_MAX_BYTES`, `CSV_SCORING_MIN_ROWS`, `CSV_SCORING_MAX_ROWS`, `CSV_SCORING_CHUNK_SIZE`, `CSV_SCORING_TTL_SECONDS`, and `CSV_SCORING_TEMP_DIR`.
- Produces stable exception classes `CsvValidationError`, `UploadNotFoundError`, `JobNotFoundError`, `ModelUnavailableError`, and `ScoringError`.
- Depends on no Flask routes or database models.

- [ ] **Step 1: Write failing configuration tests**

```python
def test_csv_scoring_defaults_are_explicit(app):
    assert app.config["CSV_SCORING_MAX_BYTES"] == 100 * 1024 * 1024
    assert app.config["CSV_SCORING_MIN_ROWS"] == 100_000
    assert app.config["CSV_SCORING_MAX_ROWS"] == 250_000
    assert app.config["CSV_SCORING_CHUNK_SIZE"] == 5_000
    assert app.config["CSV_SCORING_TTL_SECONDS"] == 3_600
```

- [ ] **Step 2: Run the focused test and observe the failure**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_config.py -q`

Expected: FAIL because the new configuration keys do not exist.

- [ ] **Step 3: Add optional ML dependencies and configuration defaults**

Add pinned `numpy`, `scikit-learn`, and `joblib` versions compatible with the
existing `work_iforest` environment. Keep them in the runtime requirements so
the configured Isolation Forest can load. Add a 100 MB `MAX_CONTENT_LENGTH`,
the CSV-specific row/chunk/TTL values, and an optional
`CSV_SCORING_MODEL_DIR` environment-backed path. Create the package and error
classes with no route imports.

- [ ] **Step 4: Run the focused tests and the existing suite**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_config.py tests/test_app_factory.py -q`

Expected: PASS, with existing application-factory behaviour unchanged.

- [ ] **Step 5: Commit the configuration boundary**

```bash
git add requirements.txt requirements-dev.txt grant_app/config.py grant_app/__init__.py grant_app/csv_scoring tests/test_csv_scoring_config.py
git commit -m "feat: add CSV scoring configuration boundary"
```

### Task 2: Streaming CSV parser and upload metadata

**Files:**
- Create: `grant_app/csv_scoring/parser.py`
- Create: `grant_app/csv_scoring/types.py`
- Create: `tests/test_csv_scoring_parser.py`

**Interfaces:**
- Produces `ParsedUpload(upload_id: str, path: Path, headers: tuple[str, ...], canonical_headers: tuple[str, ...], row_count: int, size_bytes: int, expires_at: float)`.
- Produces `parse_upload(stream, destination_dir: Path, *, upload_id: str, max_bytes: int, min_rows: int, max_rows: int, now: float | None = None) -> ParsedUpload`.
- Produces `canonical_header(value: str) -> str` and `validate_selected_headers(headers, selected) -> tuple[str, ...]`.
- Consumes the configuration and error classes from Task 1.

- [ ] **Step 1: Write parser tests before implementation**

Cover UTF-8, UTF-8 BOM, comma parsing, exact header preservation, trimmed/case-folded matching, normalized duplicate rejection, reserved `SCORE`, uneven row rejection, malformed encoding, missing header, row-count lower/upper boundaries, over-limit rows, and byte-limit rejection. Use a helper that creates a stream with `min_rows` rows without storing a full cell grid in the parser.

```python
def test_parse_upload_strips_bom_for_matching_but_preserves_header(tmp_path):
    stream = io.BytesIO(("\ufeffAccount ID, Amount\n" + rows(100_000)).encode())
    parsed = parse_upload(stream, tmp_path, upload_id="u1", max_bytes=100_000_000,
                          min_rows=100_000, max_rows=250_000)
    assert parsed.headers[:2] == ("Account ID", " Amount")
    assert parsed.canonical_headers[:2] == ("account id", "amount")
    assert parsed.row_count == 100_000
```

- [ ] **Step 2: Run the parser tests to confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_parser.py -q`

Expected: FAIL because parser types and functions do not exist.

- [ ] **Step 3: Implement bounded streaming validation**

Use `tempfile` under the supplied destination directory and copy the input in
bounded chunks while enforcing `max_bytes`. Decode with `utf-8-sig`, feed
`csv.reader`, validate the header before rows, count rows as they are read, and
write the validated source to a server-generated file. Delete the temporary
file on every validation exception. Reject `SCORE` after canonicalization and
reject duplicate canonical headers. Never include cell values in exception
messages.

- [ ] **Step 4: Run parser tests and inspect temporary-file cleanup**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_parser.py -q`

Expected: PASS, including no file left behind for each rejected input.

- [ ] **Step 5: Commit the parser**

```bash
git add grant_app/csv_scoring/parser.py grant_app/csv_scoring/types.py tests/test_csv_scoring_parser.py
git commit -m "feat: validate and stage CSV uploads"
```

### Task 3: Model contract, registry, calibration, and Isolation Forest adapter

**Files:**
- Create: `grant_app/csv_scoring/models.py`
- Create: `grant_app/csv_scoring/registry.py`
- Create: `grant_app/csv_scoring/calibration.py`
- Create: `grant_app/csv_scoring/adapters/isolation_forest.py`
- Create: `grant_app/csv_scoring/adapters/__init__.py`
- Create: `tests/test_csv_scoring_models.py`
- Create: `tests/fixtures/csv_scoring/iforest_manifest.json`

**Interfaces:**
- Produces `ModelSpec(model_id: str, display_name: str, model_type: Literal["supervised", "unsupervised"], required_columns: tuple[str, ...], version: str, adapter: ModelAdapter)`.
- Produces protocol `ModelAdapter.score_rows(rows: Sequence[Mapping[str, object]]) -> Sequence[float]`.
- Produces `ModelRegistry.register(spec)`, `ModelRegistry.get(model_id)`, and `ModelRegistry.list_available() -> tuple[ModelSpec, ...]`.
- Produces `normalize_score(raw_score: float, *, low: float, high: float, reverse: bool = False) -> float`.
- Produces `IsolationForestAdapter.from_artifact(artifact_path: Path, manifest_path: Path) -> IsolationForestAdapter`.

- [ ] **Step 1: Write model-contract and calibration tests**

Test registry lookup and unknown IDs, required-column matching against
canonical headers, supervised probability passthrough, unsupervised direction
reversal, fixed-bound normalization, clipping below/above bounds, invalid equal
bounds, and six-decimal formatting. Add an adapter test using a tiny test
double instead of requiring the untracked production artifact.

```python
def test_normalize_score_clips_to_fixed_training_bounds():
    assert normalize_score(-2.0, low=-1.0, high=1.0) == 0.0
    assert normalize_score(0.0, low=-1.0, high=1.0) == 0.5
    assert normalize_score(2.0, low=-1.0, high=1.0) == 1.0
```

- [ ] **Step 2: Run the model tests to observe failure**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_models.py -q`

Expected: FAIL because the registry, adapters, and calibration functions do not exist.

- [ ] **Step 3: Implement the model protocol and registry**

Represent required columns canonically while retaining display metadata. Keep
artifact paths and manifest paths configuration-derived, never request-derived.
Make `list_available()` omit artifacts that cannot be loaded and expose a safe
availability reason to the route without exposing paths or exception text.

- [ ] **Step 4: Implement fixed calibration and the Isolation Forest adapter**

Load the existing joblib pipeline only through the adapter. Validate that the
manifest header order matches the artifact's stored headers. Normalize rows into
that exact order, call `predict`/`decision_function` in chunks, orient the raw
score so larger means higher risk, and apply the manifest's training-time
`low`/`high` bounds. The sidecar manifest must include model ID, version,
required headers, score direction, and calibration values. Do not add the
untracked binary to Git; configure its path with `CSV_SCORING_MODEL_DIR`.

- [ ] **Step 5: Run tests and an optional configured-artifact smoke test**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_models.py -q`

Expected: PASS. When `CSV_SCORING_MODEL_DIR` points at `work_iforest`, run the
separate smoke test and verify finite scores in `[0, 1]`; when it is absent,
the registry reports the experimental model as unavailable without failing app
startup.

- [ ] **Step 6: Commit the model boundary**

```bash
git add grant_app/csv_scoring/models.py grant_app/csv_scoring/registry.py grant_app/csv_scoring/calibration.py grant_app/csv_scoring/adapters tests/test_csv_scoring_models.py tests/fixtures/csv_scoring/iforest_manifest.json
git commit -m "feat: add pluggable CSV scoring model adapters"
```

### Task 4: Temporary upload/task store and background executor

**Files:**
- Create: `grant_app/csv_scoring/store.py`
- Create: `grant_app/csv_scoring/tasks.py`
- Create: `tests/test_csv_scoring_store.py`
- Create: `tests/test_csv_scoring_tasks.py`

**Interfaces:**
- Produces `FileStore(root: Path, ttl_seconds: int)` with exact methods `save_upload(parsed: ParsedUpload) -> None`, `get_upload(upload_id: str) -> UploadManifest`, `create_job(upload_id: str, model_id: str, selected_headers: tuple[str, ...], now: float) -> JobManifest`, `get_job(job_id: str) -> JobManifest`, `update_job(job_id: str, *, status: JobStatus, progress_rows: int, error_code: str | None = None) -> JobManifest`, `result_path(job_id: str) -> Path`, and `cleanup_expired(now: float) -> int`.
- Produces immutable `UploadManifest` and `JobManifest` values. Job status is one of `queued`, `running`, `completed`, or `failed`; progress is an integer row count.
- Produces `TaskExecutor.submit(job_id, callable) -> None` and `TaskExecutor.shutdown() -> None`.

- [ ] **Step 1: Write store/task tests**

Test random IDs, JSON manifest atomic writes, upload/job lookup, expired
manifest removal, no SQLite usage, status transitions, monotonic progress, and
failed-job result deletion. Test executor exceptions become `failed` status and
only one job runs at a time.

- [ ] **Step 2: Run focused tests and observe failure**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_store.py tests/test_csv_scoring_tasks.py -q`

Expected: FAIL because the store and executor do not exist.

- [ ] **Step 3: Implement the protected file store**

Create a root directory with restrictive permissions when possible. Store each
upload/job in a random-ID directory. Write manifests to a temporary sibling and
atomically rename them. Resolve IDs to children of the configured root and
reject traversal or missing manifests. Store only metadata, never CSV rows, in
manifests.

- [ ] **Step 4: Implement the single-worker executor and cleanup**

Use `ThreadPoolExecutor(max_workers=1)`. Update job manifests atomically before
and after work, catch all worker exceptions, log only sanitized context through
`log_exception_context`, and delete incomplete result files. Call cleanup at
application startup and from CSV-scoring requests.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_store.py tests/test_csv_scoring_tasks.py -q`

Expected: PASS.

```bash
git add grant_app/csv_scoring/store.py grant_app/csv_scoring/tasks.py tests/test_csv_scoring_store.py tests/test_csv_scoring_tasks.py
git commit -m "feat: manage expiring CSV scoring tasks"
```

### Task 5: Chunked scorer and atomic CSV exporter

**Files:**
- Create: `grant_app/csv_scoring/scorer.py`
- Create: `grant_app/csv_scoring/exporter.py`
- Create: `tests/test_csv_scoring_scorer.py`
- Create: `tests/test_csv_scoring_exporter.py`

**Interfaces:**
- Produces `score_job(source_path: Path, result_temp_path: Path, *, selected_headers: tuple[str, ...], model: ModelSpec, chunk_size: int, progress: Callable[[int], None]) -> int`.
- Produces `write_scored_csv(rows: Iterable[Mapping[str, object]], output_path: Path, *, selected_headers: tuple[str, ...], scores: Iterable[float]) -> None`.

- [ ] **Step 1: Write failing scorer/exporter tests**

Use a deterministic adapter and a 10-row fixture for fast tests. Verify source
row order, selected-field order, final `SCORE`, UTF-8 BOM, six decimals,
quoting, chunk boundaries, progress counts, all-or-nothing result creation, and
failure cleanup. Add a generated 250,000-row/20-column performance fixture that
asserts bounded memory using a streaming source rather than retaining all rows.

- [ ] **Step 2: Run the focused tests and observe failure**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_scorer.py tests/test_csv_scoring_exporter.py -q`

Expected: FAIL because the scorer and exporter do not exist.

- [ ] **Step 3: Implement chunked reading and model invocation**

Read the validated CSV with `csv.DictReader`, map canonical source headers to
original headers, and feed exactly `chunk_size` mappings to the adapter. Verify
the adapter returns one finite score per input row in `[0, 1]`; otherwise raise
`ScoringError` without exposing values. Pass selected original values and
formatted scores to the exporter while preserving order.

- [ ] **Step 4: Implement atomic UTF-8-BOM export**

Write to a task-specific temporary result path using `newline=""`,
`encoding="utf-8-sig"`, and `csv.writer`. Write the selected headers followed
by `SCORE`; flush and close before renaming to the completed result name. Never
reuse an input filename and never offer the temporary path to callers.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_scorer.py tests/test_csv_scoring_exporter.py -q`

Expected: PASS, including the bounded-memory performance case.

```bash
git add grant_app/csv_scoring/scorer.py grant_app/csv_scoring/exporter.py tests/test_csv_scoring_scorer.py tests/test_csv_scoring_exporter.py
git commit -m "feat: score CSVs in chunks and export normalized results"
```

### Task 6: Flask API routes and application wiring

**Files:**
- Modify: `grant_app/routes.py`
- Modify: `grant_app/__init__.py`
- Create: `tests/test_csv_scoring_routes.py`

**Interfaces:**
- Adds the five endpoints from the spec under the existing `web` blueprint:
  `POST /csv-scoring/uploads`, `GET /csv-scoring/uploads/<upload_id>`,
  `POST /csv-scoring/jobs`, `GET /csv-scoring/jobs/<job_id>`, and
  `GET /csv-scoring/jobs/<job_id>/download`.
- Produces JSON for upload/metadata/job/status errors and `send_file` only for
  completed downloads.

- [ ] **Step 1: Write route tests before implementation**

Test a valid upload with a small config override (`MIN_ROWS=2`), metadata
response, selected-field/model job creation, queued-to-completed status,
download headers/body, invalid CSV, missing required columns, unknown IDs,
unavailable models, CSRF failure, 100 MB/413 handling, and privacy-safe error
and log content. Use a deterministic test registry injected through app config.

- [ ] **Step 2: Run route tests to observe failure**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_routes.py -q`

Expected: FAIL because the endpoints are not registered.

- [ ] **Step 3: Implement upload and metadata routes**

Require a multipart field named `file`, invoke the parser/store, call cleanup,
and return only metadata plus fields. Convert parser errors to stable 400/413
responses. Do not trust or return the client filename.

- [ ] **Step 4: Implement job/status/download routes**

Validate `upload_id`, selected fields, exactly one model ID, and required model
columns. Create a queued manifest and submit the scorer to the single-worker
executor. Return progress and safe failure categories. Set download
`Content-Disposition` to a server-generated name such as
`scored_<job_id>.csv` and set `text/csv; charset=utf-8`.

- [ ] **Step 5: Wire startup initialization and error handling**

Create the store, registry, and executor during app creation from config; clean
expired files before serving requests; shut down the executor when the process
exits. Keep existing 400/413/500 handlers and sanitized diagnostics intact.

- [ ] **Step 6: Run route tests and the complete suite**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_routes.py tests -q`

Expected: PASS with no regression in existing routes.

- [ ] **Step 7: Commit the API integration**

```bash
git add grant_app/routes.py grant_app/__init__.py tests/test_csv_scoring_routes.py
git commit -m "feat: expose CSV scoring API"
```

### Task 7: Browser test page

**Files:**
- Create: `grant_app/templates/csv_scoring/new.html`
- Create: `grant_app/static/js/csv-scoring-form.js`
- Modify: `grant_app/templates/base.html`
- Modify: `grant_app/routes.py`
- Create: `tests/test_csv_scoring_page.py`

**Interfaces:**
- Adds `GET /csv-scoring` rendering the test page.
- The page consumes the five API endpoints and uses the existing site shell,
  focus styles, flash/error conventions, and CSRF token strategy.

- [ ] **Step 1: Write page-rendering tests**

Assert the page has a file input and drop zone, accessible field-selection
container, one-model selector, submit/status/download controls, CSRF token,
navigation link, and text explaining that `SCORE` is `0..1` risk evidence.

- [ ] **Step 2: Run page tests to observe failure**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_page.py -q`

Expected: FAIL because the page route/template do not exist.

- [ ] **Step 3: Implement the minimal functional template and route**

Render an empty state before upload, show available models from the registry,
and provide stable IDs/labels for keyboard and screen-reader use. Keep visual
styling consistent with the current app; do not add Figma-specific assets.

- [ ] **Step 4: Implement vanilla JavaScript flow**

Handle drag/drop and file selection, upload via `fetch` with CSRF, render the
returned fields as checked checkboxes, require at least one output field, submit
one model, poll status with a bounded interval, disable duplicate submissions,
and expose the download link only when completed. Show server-provided safe
error categories without displaying raw CSV values.

- [ ] **Step 5: Run page/API tests and commit**

Run: `.venv/bin/python -m pytest tests/test_csv_scoring_page.py tests/test_csv_scoring_routes.py -q`

Expected: PASS.

```bash
git add grant_app/templates/csv_scoring/new.html grant_app/static/js/csv-scoring-form.js grant_app/templates/base.html grant_app/routes.py tests/test_csv_scoring_page.py
git commit -m "feat: add CSV scoring test page"
```

### Task 8: Documentation, verification, and acceptance run

**Files:**
- Modify: `README.md`
- Modify: `docs/manual-test-checklist.md`
- Modify: `tests/test_readme.py`
- Modify: `tests/test_security_accessibility.py`

- [ ] **Step 1: Write documentation tests/checklist assertions**

Require the README to document the local page, CSV limits, `SCORE` meaning,
temporary one-hour retention, experimental Isolation Forest status, and the
fact that labels/scores are not proof of fraud. Require the manual checklist
to cover keyboard navigation, invalid limits, a representative large CSV,
download/opening in Excel, exact output columns, and cleanup.

- [ ] **Step 2: Update operator documentation**

Document how to set `CSV_SCORING_MODEL_DIR` for the untracked experimental
artifact, how to start the local app, how to test the full page, and how to
register future A/B/D artifacts without exposing model paths to users.

- [ ] **Step 3: Run the full verification suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS for the complete suite, including accessibility/privacy checks.

- [ ] **Step 4: Run configured Isolation Forest smoke verification**

Point `CSV_SCORING_MODEL_DIR` at the existing `work_iforest` directory, upload
a CSV with the artifact's exact required headers and 100,000–250,000 rows,
score it through the page/API, verify finite six-decimal scores in `[0, 1]`,
and confirm output order and selected-column projection. Do not commit the
existing binary or generated outputs.

- [ ] **Step 5: Run the 250,000-row performance acceptance check**

Generate a temporary 20-column CSV with 250,000 rows, run one scoring job,
record elapsed time and peak memory, verify no partial output on a forced
failure, then confirm source/result cleanup after TTL using an injected clock.

- [ ] **Step 6: Review the final worktree and commit documentation**

Run: `git status --short` and `git diff --check`

Expected: only intended feature files are changed; pre-existing `test.txt`,
`work_iforest/`, and `outputs/` remain untouched and untracked.

```bash
git add README.md docs/manual-test-checklist.md tests/test_readme.py tests/test_security_accessibility.py
git commit -m "docs: document CSV scoring workflow"
```
