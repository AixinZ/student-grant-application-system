# Final CSV scoring fix report

## Findings addressed

- Cleanup now removes stale parser staging remnants directly below the private
  store root and upload/job directories whose manifests are missing, malformed,
  or unreadable. Orphans use the configured TTL as an mtime grace period, so
  recent in-progress work is retained. Every deletion remains root-confined;
  deletion and scan failures emit stable sanitized log events without paths or
  exception messages.
- Parser validation now checks the sampled CSV dialect and accepts only commas.
  Quoted commas remain valid CSV data; semicolon, tab, and pipe-delimited input
  is rejected.
- Upload parsing receives `CSV_SCORING_TTL_SECONDS` from the route. Parsed
  upload expiry and `FileStore` cleanup therefore use the same configured TTL.
- The scorer now sends adapters a projection containing exactly
  `ModelSpec.required_columns`, never selected-output or other source columns.

## TDD evidence

The focused regression tests were added before implementation and initially
failed as expected: non-comma input was accepted, the TTL parameter was absent,
stale incomplete directories were skipped, cleanup did not report a failed
deletion, and the adapter received extra columns. The route TTL integration test
also failed while the route intentionally omitted the new argument, then passed
when the configured argument was restored.

## Verification

- `.venv/bin/python -m pytest -q tests/test_csv_scoring_parser.py tests/test_csv_scoring_store.py tests/test_csv_scoring_scorer.py tests/test_csv_scoring_routes.py` — 44 passed.
- `.venv/bin/python -m pytest -q` — 182 passed in 10.22s.
- `git diff --check` — passed before commit.

## Scope

Only the CSV-scoring parser, store, scorer, upload route, focused tests, and
this report are included. No files in `test.txt`, `work_iforest/`, or `outputs/`
were changed.
