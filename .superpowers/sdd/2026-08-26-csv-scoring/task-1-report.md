# Task 1 report: CSV scoring configuration boundary

## Files changed

- `grant_app/config.py`: added explicit CSV scoring limits, TTL, chunk size, 100 MB request limit, and environment-backed model/temp paths.
- `grant_app/__init__.py`: resolves optional path environment variables at app-factory time.
- `grant_app/csv_scoring/__init__.py`: package exports.
- `grant_app/csv_scoring/errors.py`: stable scoring exception hierarchy.
- `requirements.txt`: pinned numpy, scikit-learn, and joblib runtime dependencies.
- `tests/test_csv_scoring_config.py`: configuration and error-boundary tests.
- `tests/test_app_factory.py`, `tests/test_security_accessibility.py`: updated old 16 KiB assertions to match the required 100 MB limit.

## Verification

- `.venv/bin/python -m pytest tests/test_csv_scoring_config.py tests/test_app_factory.py -q` — 9 passed.
- `.venv/bin/python -m pytest -q` — 117 passed.

## Commit

`b5bc3430be3094a4e04ddc3b5ea7eae7fc0eb49b` (`feat: add CSV scoring configuration boundary`)

## Concerns

- The existing security test encoded the previous 16 KiB request limit; it was updated to exercise the new required 100 MB limit.
- ML dependency pins were selected for the documented Python 3.13 stack; packages are declared but were not installed in the local virtual environment.
