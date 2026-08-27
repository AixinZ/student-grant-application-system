"""Load runtime security, database, and request-size settings from the environment."""

import os
import tempfile


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///student_grants.sqlite"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024
    CSV_SCORING_MAX_BYTES = 100 * 1024 * 1024
    CSV_SCORING_MIN_ROWS = 100_000
    CSV_SCORING_MAX_ROWS = 250_000
    CSV_SCORING_CHUNK_SIZE = 5_000
    CSV_SCORING_TTL_SECONDS = 3_600
    CSV_SCORING_MODEL_DIR = os.environ.get("CSV_SCORING_MODEL_DIR")
    CSV_SCORING_TEMP_DIR = os.environ.get(
        "CSV_SCORING_TEMP_DIR", tempfile.gettempdir()
    )
