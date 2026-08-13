from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError

from grant_app.approval import ApprovalEngineError
from grant_app.constants import Decision
from grant_app.domain import ApplicationInput, ApprovalOutcome
from grant_app.extensions import db
from grant_app.models import Application


VALID_PAYLOAD = {
    "name": "Alex Student",
    "annual_income_cad": "42000.50",
    "address": "123 Main Street",
    "age": "24",
    "education_level": "BACHELORS_DEGREE",
    "marital_status": "SINGLE",
    "dependents": "0",
    "province": "BC",
}


class FixedEngine:
    def __init__(self, probability: Decimal = Decimal("0.734218")) -> None:
        self.calls = 0
        self.probability = probability

    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        self.calls += 1
        return ApprovalOutcome(
            probability=self.probability,
            decision=Decision.APPROVED,
            engine_version="random-v1",
        )


class FailingEngine:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        self.calls += 1
        raise ApprovalEngineError("engine internals must remain private")


def test_root_redirects_to_new_application(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/applications/new")


def test_get_new_application_renders_all_fields(client):
    response = client.get("/applications/new")

    assert response.status_code == 200
    for label in (
        b"Name",
        b"Annual income (CAD)",
        b"Address",
        b"Age",
        b"Education level",
        b"Marital status",
        b"Dependents",
        b"Province",
    ):
        assert label in response.data
    assert b"Submit Application" in response.data


def test_valid_submission_redirects_and_details_show_the_saved_record(app, client):
    engine = FixedEngine()
    app.config["APPROVAL_ENGINE"] = engine

    response = client.post("/applications/new", data=VALID_PAYLOAD)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/applications/1")
    assert engine.calls == 1

    with app.app_context():
        saved = db.session.get(Application, 1)
        assert saved is not None
        assert saved.approval_probability == Decimal("0.734218")
        assert saved.decision == "APPROVED"

    details = client.get(response.headers["Location"])
    assert details.status_code == 200
    for expected in (
        b"Application #1",
        b"Alex Student",
        b"$42,000.50 CAD",
        b"123 Main Street",
        b"24",
        b"Bachelor&#39;s Degree",
        b"Single",
        b"0",
        b"BC",
        b"73.42%",
        b"Approved",
        b"random-v1",
    ):
        assert expected in details.data
    assert details.data.count(b"<dl") == 1
    assert b"<form" not in details.data
    assert b"Edit application" not in details.data
    assert b"Delete application" not in details.data
    assert b"Reevaluate" not in details.data


def test_invalid_submission_returns_422_without_evaluation_or_database_row(
    app, client
):
    engine = FixedEngine()
    app.config["APPROVAL_ENGINE"] = engine

    response = client.post(
        "/applications/new", data={**VALID_PAYLOAD, "age": "15"}
    )

    assert response.status_code == 422
    assert b"Age must be between 16 and 100." in response.data
    assert b'href="#age"' in response.data
    assert b'id="age-error"' in response.data
    assert engine.calls == 0
    with app.app_context():
        assert db.session.query(Application).count() == 0


@pytest.mark.parametrize(
    ("field_name", "value", "expected_error"),
    [
        ("name", "A", b"Name must be between 2 and 100 characters."),
        ("address", "1234", b"Address must be between 5 and 200 characters."),
    ],
    ids=["short-name", "short-address"],
)
def test_below_minimum_text_returns_422_without_evaluation_or_database_row(
    app, client, field_name, value, expected_error
):
    engine = FixedEngine()
    app.config["APPROVAL_ENGINE"] = engine

    response = client.post(
        "/applications/new", data={**VALID_PAYLOAD, field_name: value}
    )

    assert response.status_code == 422
    assert expected_error in response.data
    assert engine.calls == 0
    with app.app_context():
        assert db.session.query(Application).count() == 0


def test_approval_failure_returns_general_retry_message_without_database_row(
    app, client
):
    engine = FailingEngine()
    app.config["APPROVAL_ENGINE"] = engine

    response = client.post("/applications/new", data=VALID_PAYLOAD)

    assert response.status_code == 503
    assert b"Please try again." in response.data
    assert b"engine internals" not in response.data
    assert engine.calls == 1
    with app.app_context():
        assert db.session.query(Application).count() == 0


def test_database_failure_returns_general_retry_message_without_partial_row(
    app, client, monkeypatch
):
    engine = FixedEngine()
    app.config["APPROVAL_ENGINE"] = engine

    def fail_commit() -> None:
        raise SQLAlchemyError("database internals must remain private")

    monkeypatch.setattr(db.session, "commit", fail_commit)

    response = client.post("/applications/new", data=VALID_PAYLOAD)

    assert response.status_code == 503
    assert b"Please try again." in response.data
    assert b"database internals" not in response.data
    assert engine.calls == 1
    with app.app_context():
        assert db.session.query(Application).count() == 0


def test_unknown_application_returns_404(client):
    response = client.get("/applications/999")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("formatter_name", "value", "expected"),
    [
        ("probability_percent", Decimal("0.734218"), "73.42%"),
        ("cad_currency", Decimal("42000.5"), "$42,000.50 CAD"),
    ],
)
def test_decimal_formatters(formatter_name, value, expected):
    from grant_app import formatters

    formatter = getattr(formatters, formatter_name)
    assert formatter(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2026, 1, 15, 20, 30), "January 15, 2026 at 12:30 PM PST"),
        (
            datetime(2026, 7, 15, 20, 30, tzinfo=timezone.utc),
            "July 15, 2026 at 1:30 PM PDT",
        ),
    ],
)
def test_vancouver_datetime_treats_naive_values_as_utc(value, expected):
    from grant_app.formatters import vancouver_datetime

    assert vancouver_datetime(value) == expected
