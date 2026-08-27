from grant_app import create_app
from grant_app.csv_scoring.errors import (
    CsvValidationError,
    JobNotFoundError,
    ModelUnavailableError,
    ScoringError,
    UploadNotFoundError,
)


def test_csv_scoring_defaults_are_explicit(app):
    assert app.config["CSV_SCORING_MAX_BYTES"] == 100 * 1024 * 1024
    assert app.config["CSV_SCORING_MIN_ROWS"] == 100_000
    assert app.config["CSV_SCORING_MAX_ROWS"] == 250_000
    assert app.config["CSV_SCORING_CHUNK_SIZE"] == 5_000
    assert app.config["CSV_SCORING_TTL_SECONDS"] == 3_600
    assert app.config["MAX_CONTENT_LENGTH"] == 100 * 1024 * 1024


def test_csv_scoring_model_and_temp_paths_are_environment_backed(monkeypatch):
    monkeypatch.setenv("CSV_SCORING_MODEL_DIR", "/models/iforest")
    monkeypatch.setenv("CSV_SCORING_TEMP_DIR", "/tmp/csv-scoring")
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )

    assert app.config["CSV_SCORING_MODEL_DIR"] == "/models/iforest"
    assert app.config["CSV_SCORING_TEMP_DIR"] == "/tmp/csv-scoring"


def test_csv_scoring_errors_have_stable_hierarchy():
    assert issubclass(CsvValidationError, ScoringError)
    assert issubclass(UploadNotFoundError, ScoringError)
    assert issubclass(JobNotFoundError, ScoringError)
    assert issubclass(ModelUnavailableError, ScoringError)
