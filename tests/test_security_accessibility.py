import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from logging.handlers import RotatingFileHandler

import pytest

from grant_app import create_app
from grant_app.constants import Decision
from grant_app.domain import ApplicationInput, ApprovalOutcome
from grant_app.extensions import db
from grant_app.models import Application


VALID_PAYLOAD = {
    "name": "Private Student",
    "annual_income_cad": "42000.50",
    "address": "987 Confidential Avenue",
    "age": "24",
    "education_level": "BACHELORS_DEGREE",
    "marital_status": "SINGLE",
    "dependents": "0",
    "province": "BC",
}


class FixedEngine:
    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        return ApprovalOutcome(
            probability=Decimal("0.75"),
            decision=Decision.APPROVED,
            engine_version="test-v1",
        )


class UnexpectedEngine:
    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        db.session.add(
            Application(
                name="Pending Row",
                annual_income_cad=Decimal("1.00"),
                address="Pending Address",
                age=24,
                education_level="BACHELORS_DEGREE",
                marital_status="SINGLE",
                dependents=0,
                province="BC",
                approval_probability=Decimal("0.75"),
                decision=Decision.APPROVED.value,
                approval_engine="test-v1",
            )
        )
        raise RuntimeError(
            "approval service unavailable: "
            f"{data.name} {data.address} {data.annual_income_cad}"
        ) from ValueError("private nested cause")


@pytest.fixture
def production_style_app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "PROPAGATE_EXCEPTIONS": False,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'csrf.sqlite'}",
        }
    )
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def production_style_client(production_style_app):
    return production_style_app.test_client()


def add_application(app, decision: Decision) -> int:
    with app.app_context():
        record = Application(
            name=f"{decision.value.title()} Student",
            annual_income_cad=Decimal("42000.00"),
            address="123 Test Street",
            age=24,
            education_level="BACHELORS_DEGREE",
            marital_status="SINGLE",
            dependents=0,
            province="BC",
            approval_probability=(
                Decimal("0.75")
                if decision is Decision.APPROVED
                else Decimal("0.50")
            ),
            decision=decision.value,
            approval_engine="test-v1",
            submitted_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
        )
        db.session.add(record)
        db.session.commit()
        return record.id


def test_missing_csrf_token_returns_safe_english_400_page(production_style_client):
    response = production_style_client.post("/applications/new", data=VALID_PAYLOAD)

    assert response.status_code == 400
    assert b"We could not submit the application" in response.data
    assert b"CSRF token is missing" not in response.data
    assert b"Private Student" not in response.data
    assert b'href="/applications/new"' in response.data


def test_request_body_over_16_kib_returns_safe_413_page(production_style_client):
    response = production_style_client.post(
        "/applications/new", data={"name": "A" * (17 * 1024)}
    )

    assert response.status_code == 413
    assert b"The submitted request was too large" in response.data
    assert b'href="/applications/new"' in response.data


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_details_rejects_mutation_methods_without_changing_the_row(
    app, client, method
):
    application_id = add_application(app, Decision.APPROVED)

    response = getattr(client, method)(f"/applications/{application_id}")

    assert response.status_code == 405
    with app.app_context():
        record = db.session.get(Application, application_id)
        assert record is not None
        assert record.name == "Approved Student"
        assert db.session.query(Application).count() == 1


def test_unknown_page_uses_safe_custom_404(client):
    response = client.get("/page-that-does-not-exist")

    assert response.status_code == 404
    assert b"We could not find that page" in response.data
    assert b'href="/applications/new"' in response.data


def test_rendered_pages_have_landmarks_linked_assets_and_decision_text(app, client):
    approved_id = add_application(app, Decision.APPROVED)
    rejected_id = add_application(app, Decision.NOT_APPROVED)

    new_page = client.get("/applications/new")
    history = client.get("/applications")
    approved_detail = client.get(f"/applications/{approved_id}")
    rejected_detail = client.get(f"/applications/{rejected_id}")

    for response in (new_page, history, approved_detail, rejected_detail):
        assert b'<html lang="en">' in response.data
        assert b'href="#main-content"' in response.data
        assert b'<nav aria-label="Primary navigation">' in response.data
        assert b'href="/static/css/app.css"' in response.data
    assert b'<script src="/static/js/application-form.js" defer></script>' in new_page.data
    assert b'id="application-form"' in new_page.data
    assert b'class="table-scroll"' in history.data
    assert b'class="status-badge status-approved">Approved</span>' in approved_detail.data
    assert b'class="status-badge status-not-approved">Not Approved</span>' in rejected_detail.data


def test_invalid_form_links_summary_and_errors_to_invalid_control(client):
    response = client.post(
        "/applications/new", data={**VALID_PAYLOAD, "age": "15"}
    )

    assert response.status_code == 422
    assert b'id="error-summary"' in response.data
    assert b'href="#age"' in response.data
    assert b'aria-describedby="age-error"' in response.data
    assert b'id="age-error"' in response.data


def test_data_generator_page_has_accessible_form_and_navigation(client):
    response = client.get("/data-generator")

    assert response.status_code == 200
    assert b'href="/data-generator"' in response.data
    assert b'id="data-generator-form"' in response.data
    assert b'id="row-count-help"' in response.data
    assert b'min="10000"' in response.data
    assert b'max="250000"' in response.data
    assert b'step="1"' in response.data
    assert b'<script src="/static/js/data-generator-form.js" defer></script>' in response.data


def test_invalid_generator_form_links_summary_to_row_count(client):
    response = client.post("/data-generator", data={"row_count": "9999"})

    assert response.status_code == 422
    assert b'id="error-summary"' in response.data
    assert b'href="#row_count"' in response.data
    assert b'aria-describedby="row-count-help row_count-error"' in response.data
    assert b'id="row_count-error"' in response.data


def test_unexpected_service_error_rolls_back_and_logs_no_submitted_pii(
    production_style_app, production_style_client, caplog
):
    production_style_app.config["WTF_CSRF_ENABLED"] = False
    production_style_app.config["APPROVAL_ENGINE"] = UnexpectedEngine()

    with caplog.at_level(logging.ERROR, logger=production_style_app.logger.name):
        response = production_style_client.post(
            "/applications/new", data=VALID_PAYLOAD
        )

    assert response.status_code == 500
    assert b"Something went wrong" in response.data
    assert b"approval service unavailable" not in response.data
    assert "unexpected_server_error" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "cause_type=ValueError" in caplog.text
    assert re.search(
        r"traceback=test_security_accessibility\.py:evaluate:\d+", caplog.text
    )
    assert "approval service unavailable" not in caplog.text
    assert "private nested cause" not in caplog.text
    assert VALID_PAYLOAD["name"] not in caplog.text
    assert VALID_PAYLOAD["address"] not in caplog.text
    assert VALID_PAYLOAD["annual_income_cad"] not in caplog.text
    with production_style_app.app_context():
        assert db.session.query(Application).count() == 0


def test_explicit_test_log_uses_privacy_safe_rotating_handler(tmp_path):
    log_path = tmp_path / "logs" / "student_grants.log"
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'logging.sqlite'}",
            "LOG_FILE": log_path,
        }
    )

    rotating_handlers = [
        handler
        for handler in application.logger.handlers
        if isinstance(handler, RotatingFileHandler)
    ]
    assert len(rotating_handlers) == 1
    handler = rotating_handlers[0]
    assert handler.maxBytes == 1_000_000
    assert handler.backupCount == 3

    application.logger.warning("application_processing_delayed")
    handler.flush()
    contents = log_path.read_text(encoding="utf-8")
    assert "WARNING" in contents
    assert "application_processing_delayed" in contents

    with application.app_context():
        db.session.remove()
        db.drop_all()
    handler.close()
    application.logger.removeHandler(handler)


def test_unconfigured_testing_app_removes_shared_file_handler_and_stops_writes(
    tmp_path,
):
    log_path = tmp_path / "logs" / "student_grants.log"
    logging_app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'first.sqlite'}",
            "LOG_FILE": log_path,
        }
    )
    created_apps = [logging_app]

    try:
        logging_app.logger.warning("first_app_event")
        for handler in logging_app.logger.handlers:
            if getattr(handler, "_student_grants_file_handler", False):
                handler.flush()
        contents_after_first_app = log_path.read_text(encoding="utf-8")

        unconfigured_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'second.sqlite'}",
            }
        )
        created_apps.append(unconfigured_app)
        unconfigured_app.logger.warning("testing_event_must_not_reach_file")
        for handler in unconfigured_app.logger.handlers:
            if getattr(handler, "_student_grants_file_handler", False):
                handler.flush()

        assert log_path.read_text(encoding="utf-8") == contents_after_first_app
        assert not any(
            getattr(handler, "_student_grants_file_handler", False)
            for handler in unconfigured_app.logger.handlers
        )
    finally:
        for handler in list(logging_app.logger.handlers):
            if getattr(handler, "_student_grants_file_handler", False):
                logging_app.logger.removeHandler(handler)
                handler.close()
        for application in created_apps:
            with application.app_context():
                db.session.remove()
                db.drop_all()


def test_header_keyboard_focus_uses_high_contrast_override(client):
    response = client.get("/static/css/app.css")

    assert response.status_code == 200
    assert b"--color-header-background: #0b3578;" in response.data
    assert b"--color-header-focus: #ffffff;" in response.data
    assert b":focus-visible {\n  outline: 3px solid var(--color-focus);" in response.data
    assert (
        b".site-header :focus-visible {\n"
        b"  outline-color: var(--color-header-focus);\n"
        b"}" in response.data
    )
