from pathlib import Path

from flask import Flask

from .approval import RandomApprovalEngine
from .config import Config
from .extensions import csrf, db
from .formatters import cad_currency, probability_percent, vancouver_datetime


def create_app(test_config: dict[str, object] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if "APPROVAL_ENGINE" not in app.config:
        app.config["APPROVAL_ENGINE"] = RandomApprovalEngine()
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be configured")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
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
    return app
