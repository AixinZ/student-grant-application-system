import pytest

from grant_app import create_app
from grant_app.extensions import db


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "test.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
