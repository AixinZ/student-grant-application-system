from pathlib import Path

from flask import Flask

from .config import Config
from .extensions import csrf, db


def create_app(test_config: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)
    with app.app_context():
        from . import models  # noqa: F401

        db.create_all()
    return app
