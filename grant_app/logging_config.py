"""Configure bounded rotating logs for privacy-conscious local diagnostics."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask


def configure_logging(app: Flask) -> None:
    """Configure a bounded local application log without request payloads.

    Args:
        app: The Flask application whose logger and instance directory are
            configured.

    Raises:
        OSError: If the log directory or rotating log file cannot be created.

    Notes:
        Previously installed handlers created by this function are closed and
        replaced. Testing apps skip file logging unless ``LOG_FILE`` is set.
    """
    for existing in list(app.logger.handlers):
        if getattr(existing, "_student_grants_file_handler", False):
            app.logger.removeHandler(existing)
            existing.close()

    configured_path = app.config.get("LOG_FILE")
    if app.testing and configured_path is None:
        return

    log_path = (
        Path(configured_path)
        if configured_path is not None
        else Path(app.instance_path) / "student_grants.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler._student_grants_file_handler = True
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(module)s %(message)s")
    )
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
