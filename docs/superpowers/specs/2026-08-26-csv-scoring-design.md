# CSV Scoring Upload Design

## Purpose

Add a CSV upload, model-selection, scoring, and download workflow to the
existing local Flask application. An operator uploads a CSV, reviews its
columns, chooses which original columns to keep in the result, selects one
server-side pre-trained model, and downloads a CSV containing the selected
columns followed by a normalized `SCORE` column.

The first registered model is the existing Isolation Forest prototype as an
experimental model. Supervised models A and B and unsupervised model D will be
added later through the same model-registration contract.

## Scope and fixed decisions

- The existing student-grant application and SQLite history behaviour remain
  unchanged.
- Models are pre-trained artifacts. Upload requests never train models.
- One scoring task selects exactly one model.
- Column selection controls output columns only; a model still receives its
  fixed required input columns.
- Output is CSV encoded as UTF-8 with BOM, with the original row order
  preserved.
- Output columns are the selected original columns followed by exactly one
  final column named `SCORE`.
- `SCORE` is formatted with six decimal places and means low risk at `0` and
  high risk at `1`.
- A source CSV that already contains `SCORE` is rejected to avoid collisions.
- Scores use model-specific, training-time calibration metadata. Per-upload
  Min-Max normalization is not used.
- The supported input is a comma-delimited CSV whose first row is a header,
  encoded as UTF-8 or UTF-8 with BOM.
- Header matching ignores surrounding whitespace and case. Duplicate headers
  after normalization are rejected; original spelling is retained for output.
- Every data row must have the same number of fields as the header.
- A file must contain 100,000 through 250,000 data rows and be no larger than
  100 MB.
- Uploaded sources and generated results are stored outside SQLite in a
  protected temporary directory and expire after one hour.
- Errors are all-or-nothing: no partial result is offered for download.

## Architecture

The feature is a separate CSV Scoring module and does not alter application
submission or history routes. It exposes a staged HTTP API and a small Flask
test page that will later serve as the foundation for the Figma-designed
frontend.

### HTTP API

- `POST /csv-scoring/uploads` accepts a multipart CSV upload and returns an
  `upload_id`, normalized/original field metadata, row count, and byte size.
- `GET /csv-scoring/uploads/<upload_id>` returns metadata and the selectable
  fields for a valid, non-expired upload.
- `POST /csv-scoring/jobs` accepts `upload_id`, a list of output fields, and one
  `model_id`; it validates the model schema and creates a `job_id`.
- `GET /csv-scoring/jobs/<job_id>` returns `queued`, `running`, `completed`, or
  `failed`, plus safe progress metadata.
- `GET /csv-scoring/jobs/<job_id>/download` returns the completed CSV only.

The page uses these same interfaces. It provides drag-and-drop/file selection,
field checkboxes, a single model selector, progress/status display, and a
download action. It does not contain model inference logic.

### Internal components

1. **CSV parser** validates encoding, delimiter, header uniqueness, row width,
   row count, and file size while writing the upload to a server-generated
   temporary path.
2. **Upload/task manager** owns random `upload_id` and `job_id` values,
   manifest files, task status, progress, expiry, and atomic cleanup. SQLite is
   not used for uploaded data or task state.
3. **Model registry and adapters** expose a stable contract containing model
   ID, display name, type, artifact path, required columns, preprocessing,
   score direction, fixed calibration parameters, and version.
4. **Chunked scorer** reads approximately 5,000–10,000 rows at a time, calls an
   adapter, normalizes scores to `0..1`, and passes rows to the exporter.
5. **CSV exporter** writes selected source fields and `SCORE` to a temporary
   result file. The result is renamed into its completed state only after the
   entire task succeeds.

The recommended execution mechanism is a single-worker in-process background
executor. It avoids introducing Redis/Celery for the current local, trusted,
single-user application while preventing a 250,000-row operation from blocking
the request that creates it.

## Data flow

1. The upload endpoint streams the request into a random temporary file and
   validates the CSV contract.
2. It records source metadata and returns `upload_id` plus field information;
   source contents are not returned to the browser.
3. The user selects output fields and one registered model.
4. The job endpoint verifies that selected fields belong to the source and that
   all model-required fields exist in the source. It then creates a job.
5. The background scorer reads the source in chunks, applies the model's
   preprocessing and inference, and converts each raw score with fixed
   training-time calibration.
6. The exporter writes selected original values followed by the six-decimal
   `SCORE`, preserving row order.
7. On success, the result becomes downloadable and remains available until
   expiry. On failure, the incomplete result is deleted and the job becomes
   `failed`.

For supervised models, a calibrated positive-class probability is used when
available. For unsupervised models, the adapter first orients the raw score so
that larger values mean higher risk, then applies stored lower/upper training
calibration bounds and clips to `[0, 1]`:

```text
SCORE = clip((raw_score - training_low) /
             (training_high - training_low), 0, 1)
```

The existing Isolation Forest artifact will be registered with its exact
required headers and a sidecar calibration manifest. It is explicitly marked
experimental until replaced by the final model C artifact.

## Validation, errors, and privacy

- Unsupported file type, encoding, delimiter, empty/duplicate header, row-width
  mismatch, invalid row count, size overflow, or an existing `SCORE` header
  prevents upload completion.
- Missing model-required columns prevents job creation.
- Empty cells are handled only when the selected model's preprocessing supports
  them. Unsupported missing values, invalid numeric values, preprocessing
  failures, model-load failures, and export failures fail the whole job.
- Responses expose only safe error categories, field names, row numbers, and
  retry guidance. They never echo cell values, full rows, local paths, model
  stack traces, or exception messages.
- Existing CSRF protection applies to browser-facing state-changing requests.
- Upload and job IDs are random and unguessable; user-controlled filenames and
  paths are never used for storage or download.
- Temporary files are private to the process user. Expired files are cleaned on
  requests and at application startup; successful and failed jobs are both
  cleaned after one hour.
- Logs contain only stable event names, IDs, sizes/counts, status, model ID,
  model version, and sanitized exception metadata consistent with the existing
  diagnostic logger.

## Testing and acceptance criteria

### Parser and model unit tests

- Validate UTF-8/BOM, header normalization, duplicates, row widths, size and
  row-count boundaries, and the reserved `SCORE` name.
- Verify model registration, required-column checks, score direction, fixed
  calibration, clipping, and six-decimal formatting.
- Verify supported missing-value handling and rejection of invalid values.

### Task and export integration tests

- Upload metadata is correct and source rows remain in order.
- Chunked scoring produces exactly selected fields plus final `SCORE`.
- No partial output survives a failed task.
- Expiry cleanup removes source, manifests, and results.
- A 250,000-row, 20-column run stays bounded in memory.
- The Isolation Forest artifact can be loaded and scored in a smoke test when
  its configured path is available; test doubles cover the adapter contract for
  models not yet supplied.

### Flask and page tests

- Cover upload, metadata, job creation, status, download, CSRF, 413, invalid
  IDs, unavailable models, safe failures, and navigation/page rendering.
- Browser acceptance covers drag-and-drop, field selection, model selection,
  status changes, successful download, and validation/error display.
- The complete existing test suite continues to pass unchanged.

## Not in this phase

- Training or retraining models from uploaded data.
- Comparing multiple models in one task.
- User accounts, multi-tenant isolation, cloud storage, or external worker
  infrastructure.
- Final Figma visual design or production frontend polish.
- Adding the missing formal model artifacts A, B, and D; those are follow-up
  registrations against the defined adapter contract.
