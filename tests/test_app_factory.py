import pytest

from grant_app import create_app


def test_create_app_uses_test_configuration(tmp_path):
    database_path = tmp_path / "factory.sqlite"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )

    assert app.config["TESTING"] is True
    assert app.config["MAX_CONTENT_LENGTH"] == 16 * 1024
    assert app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False


def test_create_app_rejects_non_sqlite_database_before_loading_driver():
    with pytest.raises(RuntimeError, match="SQLite"):
        create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": (
                    "postgresql+psycopg://employee:secret@localhost/grants"
                ),
            }
        )
