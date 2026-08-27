"""Create and configure the Flask app, its integrations, and safe error handling."""

from pathlib import Path
import atexit
import json
import os
import time

from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from werkzeug.exceptions import HTTPException

from .approval import RandomApprovalEngine
from .config import Config
from .diagnostics import log_exception_context
from .extensions import csrf, db
from .formatters import cad_currency, probability_percent, vancouver_datetime
from .logging_config import configure_logging
from .migrations import (
    ROLLBACK_FAILURE_STAGE,
    MigrationError,
    ensure_sqlite_schema,
)


def _is_csv_scoring_request() -> bool:
    """Whether the current request targets the CSV scoring API."""
    return request.path.startswith("/csv-scoring/")


def _configured_csv_scoring_registry(model_dir: object):
    """Register the configured experimental artifact without exposing its paths."""
    from .csv_scoring.adapters.isolation_forest import IsolationForestAdapter
    from .csv_scoring.models import ModelSpec
    from .csv_scoring.registry import ModelRegistry

    registry = ModelRegistry()
    if not model_dir:
        return registry
    directory = Path(model_dir)
    manifest_path = directory / "iforest_manifest.json"
    adapter = IsolationForestAdapter.from_artifact(
        directory / "isolation_forest_model.joblib", manifest_path
    )
    if not adapter.required_headers:
        return registry
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_id = payload["model_id"]
        version = payload["version"]
        if model_id != "experimental-iforest" or not isinstance(version, str) or not version:
            return registry
        registry.register(
            ModelSpec(
                model_id=model_id,
                display_name="Experimental Isolation Forest",
                model_type="unsupervised",
                required_columns=adapter.required_headers,
                version=version,
                adapter=adapter,
            )
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return registry
    return registry


def _initialize_csv_scoring(app: Flask) -> None:
    """Create private CSV scoring infrastructure from application config."""
    from .csv_scoring.errors import CsvValidationError
    from .csv_scoring.store import FileStore
    from .csv_scoring.tasks import TaskExecutor

    store = app.config.get("CSV_SCORING_STORE")
    if store is None:
        try:
            store = FileStore(
                Path(app.config["CSV_SCORING_TEMP_DIR"]) / "grant-app-csv-scoring",
                ttl_seconds=app.config["CSV_SCORING_TTL_SECONDS"],
            )
        except CsvValidationError:
            raise RuntimeError("CSV scoring temporary storage is unavailable") from None
    registry = app.config.get("CSV_SCORING_MODEL_REGISTRY")
    if registry is None:
        registry = _configured_csv_scoring_registry(
            app.config["CSV_SCORING_MODEL_DIR"]
        )
    executor = app.config.get("CSV_SCORING_TASK_EXECUTOR")
    owns_executor = executor is None
    if executor is None:
        executor = TaskExecutor(store)

    app.config["CSV_SCORING_STORE"] = store
    app.config["CSV_SCORING_MODEL_REGISTRY"] = registry
    app.config["CSV_SCORING_TASK_EXECUTOR"] = executor
    store.cleanup_expired(time.time())
    if owns_executor:
        atexit.register(executor.shutdown)


def _validate_sqlite_database_uri(database_uri: object) -> None:
    """Require the configured SQLAlchemy URL to identify a SQLite database.

    Args:
        database_uri: The configured SQLAlchemy database URL or URL-like value.

    Raises:
        RuntimeError: If the value is not a valid SQLAlchemy URL or selects a
            database dialect other than SQLite.
    """
    try:
        url = make_url(database_uri)
    except (ArgumentError, TypeError) as error:
        raise RuntimeError(
            "DATABASE_URL must be a valid SQLite SQLAlchemy URL"
        ) from error
    if url.get_backend_name() != "sqlite":
        raise RuntimeError(
            "Only SQLite DATABASE_URL values are supported by this application"
        )


def _register_error_handlers(app: Flask) -> None:
    """Attach privacy-safe HTTP and unexpected-exception handlers to the app.

    Args:
        app: The Flask application receiving the handlers.

    Notes:
        Server-error handlers roll back the database session and log only
        sanitized diagnostic metadata before rendering a safe response page.
    """
    @app.errorhandler(CSRFError)
    @app.errorhandler(400)
    def bad_request(_error):
        """Render the safe response used for invalid and CSRF-failed requests.

        Args:
            _error: The Flask or CSRF error that selected this handler.

        Returns:
            A rendered error page paired with HTTP status 400.
        """
        if _is_csv_scoring_request():
            return jsonify(error="invalid_request"), 400
        return render_template("errors/400.html"), 400

    @app.errorhandler(404)
    def not_found(_error):
        """Render the safe response for missing pages or application records.

        Args:
            _error: The not-found error that selected this handler.

        Returns:
            A rendered error page paired with HTTP status 404.
        """
        if _is_csv_scoring_request():
            return jsonify(error="not_found"), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        """Render the response for requests exceeding the configured size limit.

        Args:
            _error: The request-too-large error that selected this handler.

        Returns:
            A rendered error page paired with HTTP status 413.
        """
        if _is_csv_scoring_request():
            return jsonify(error="file_too_large"), 413
        return render_template("errors/413.html"), 413

    @app.errorhandler(500)
    def internal_server_error(error):
        """Roll back and render a privacy-safe internal-server-error response.

        Args:
            error: The HTTP 500 wrapper or original exception supplied by Flask.

        Returns:
            A rendered error page paired with HTTP status 500.

        Notes:
            The underlying exception is recorded through the sanitized
            diagnostic logger; submitted values and exception messages are not
            logged.
        """
        db.session.rollback()
        original_error = getattr(error, "original_exception", None) or error
        log_exception_context(
            app.logger, "unexpected_server_error", original_error
        )
        if _is_csv_scoring_request():
            return jsonify(error="processing_failed"), 500
        return render_template("errors/500.html"), 500

    @app.errorhandler(Exception)
    def unexpected_error(error):
        """Handle uncaught non-HTTP exceptions without exposing their details.

        Args:
            error: The uncaught exception raised during request processing.

        Returns:
            The original HTTP exception when applicable, otherwise a rendered
            error page paired with HTTP status 500.
        """
        if isinstance(error, HTTPException):
            return error
        db.session.rollback()
        log_exception_context(app.logger, "unexpected_server_error", error)
        if _is_csv_scoring_request():
            return jsonify(error="processing_failed"), 500
        return render_template("errors/500.html"), 500


def create_app(test_config: dict[str, object] | None = None) -> Flask:
    """Build a configured Flask application and prepare its SQLite schema.

    Args:
        test_config: Optional configuration overrides applied after the default
            environment-backed settings.

    Returns:
        A fully initialized Flask application with routes, template filters,
        extensions, logging, error handlers, and database schema registered.

    Raises:
        RuntimeError: If ``SECRET_KEY`` is missing, the database URL is invalid
            or non-SQLite, or schema inspection/migration cannot complete safely.
        OSError: If the instance directory or rotating log file cannot be
            created or opened.
    """
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    # Resolve optional paths at factory time so deployment environment changes
    # are respected even when the Config class was imported earlier.
    if "CSV_SCORING_MODEL_DIR" in os.environ:
        app.config["CSV_SCORING_MODEL_DIR"] = os.environ["CSV_SCORING_MODEL_DIR"]
    if "CSV_SCORING_TEMP_DIR" in os.environ:
        app.config["CSV_SCORING_TEMP_DIR"] = os.environ["CSV_SCORING_TEMP_DIR"]
    if test_config:
        app.config.update(test_config)
    if "APPROVAL_ENGINE" not in app.config:
        app.config["APPROVAL_ENGINE"] = RandomApprovalEngine()
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured")
    _validate_sqlite_database_uri(app.config["SQLALCHEMY_DATABASE_URI"])

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    configure_logging(app)
    db.init_app(app)
    _initialize_csv_scoring(app)
    csrf.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401

        try:
            ensure_sqlite_schema(db.engine)
        except MigrationError as error:
            log_exception_context(
                app.logger,
                f"database_migration_failed stage={error.stage}",
                error,
            )
            if error.stage == ROLLBACK_FAILURE_STAGE:
                raise RuntimeError(
                    "SQLite database migration failed and rollback/data state "
                    "could not be confirmed; stop the application and preserve "
                    "the database and backup"
                ) from None
            raise RuntimeError(
                "SQLite database migration failed; existing data was not changed"
            ) from None

    from .routes import web

    app.register_blueprint(web)
    app.add_template_filter(probability_percent)
    app.add_template_filter(cad_currency)
    app.add_template_filter(vancouver_datetime)
    _register_error_handlers(app)
    return app
