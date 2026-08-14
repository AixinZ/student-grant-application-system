from pathlib import Path

from flask import Flask, render_template
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


def _validate_sqlite_database_uri(database_uri: object) -> None:
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
    @app.errorhandler(CSRFError)
    @app.errorhandler(400)
    def bad_request(_error):
        return render_template("errors/400.html"), 400

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        return render_template("errors/413.html"), 413

    @app.errorhandler(500)
    def internal_server_error(error):
        db.session.rollback()
        original_error = getattr(error, "original_exception", None) or error
        log_exception_context(
            app.logger, "unexpected_server_error", original_error
        )
        return render_template("errors/500.html"), 500

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        db.session.rollback()
        log_exception_context(app.logger, "unexpected_server_error", error)
        return render_template("errors/500.html"), 500


def create_app(test_config: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
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
    csrf.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401

        db.create_all()

    from .routes import web

    app.register_blueprint(web)
    app.add_template_filter(probability_percent)
    app.add_template_filter(cad_currency)
    app.add_template_filter(vancouver_datetime)
    _register_error_handlers(app)
    return app
