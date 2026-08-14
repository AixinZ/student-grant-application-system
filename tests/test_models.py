from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from grant_app.constants import Decision
from grant_app.extensions import db
from grant_app.models import Application


def build_application(**changes):
    values = {
        "name": "Alex Student",
        "annual_income_cad": Decimal("45000.00"),
        "address": "123 Main Street",
        "age": 24,
        "education_level": "BACHELORS_DEGREE",
        "marital_status": "SINGLE",
        "dependents": 0,
        "province": "BC",
        "approval_probability": Decimal("0.734218"),
        "decision": Decision.APPROVED.value,
        "approval_engine": "random-v1",
    }
    values.update(changes)
    return Application(**values)


def test_application_round_trips_persisted_domain_values(app):
    with app.app_context():
        application = build_application()
        db.session.add(application)
        db.session.commit()

        saved = db.session.get(Application, application.id)
        assert saved.annual_income_cad == Decimal("45000.00")
        assert saved.province == "BC"
        assert saved.approval_probability == Decimal("0.734218")
        assert saved.decision == "APPROVED"
        assert saved.approval_engine == "random-v1"


def test_application_round_trips_arbitrary_precision_probability_as_text(app):
    with app.app_context():
        probability = Decimal("0.0031877934532863472")
        application = build_application(approval_probability=probability)
        db.session.add(application)
        db.session.commit()
        db.session.expire_all()

        saved = db.session.get(Application, application.id)
        assert saved.approval_probability == probability
        storage_type, stored_value = db.session.execute(
            text(
                "SELECT typeof(approval_probability), approval_probability "
                "FROM applications WHERE id = :application_id"
            ),
            {"application_id": application.id},
        ).one()
        assert storage_type == "text"
        assert stored_value == "0.0031877934532863472"


@pytest.mark.parametrize(
    "invalid_probability",
    ["1", "-0.1", "not-a-number", "0.25 trailing"],
)
def test_probability_raw_storage_rejects_out_of_range_or_malformed_text(
    app, invalid_probability
):
    with app.app_context():
        application = build_application()
        db.session.add(application)
        db.session.commit()

        with pytest.raises(IntegrityError):
            db.session.execute(
                text(
                    "UPDATE applications SET approval_probability = :probability "
                    "WHERE id = :application_id"
                ),
                {
                    "probability": invalid_probability,
                    "application_id": application.id,
                },
            )

        db.session.rollback()


def test_maximum_income_round_trips_as_exact_integer_cents(app):
    with app.app_context():
        income = Decimal("999999999.99")
        application = build_application(annual_income_cad=income)
        db.session.add(application)
        db.session.commit()
        db.session.expire_all()

        saved = db.session.get(Application, application.id)
        assert saved.annual_income_cad == income
        storage_type, stored_value = db.session.execute(
            text(
                "SELECT typeof(annual_income_cad), annual_income_cad "
                "FROM applications WHERE id = :application_id"
            ),
            {"application_id": application.id},
        ).one()
        assert storage_type == "integer"
        assert stored_value == 99_999_999_999


def test_income_raw_storage_rejects_cents_above_supported_maximum(app):
    with app.app_context():
        application = build_application()
        db.session.add(application)
        db.session.commit()

        with pytest.raises(IntegrityError):
            db.session.execute(
                text(
                    "UPDATE applications SET annual_income_cad = :income_cents "
                    "WHERE id = :application_id"
                ),
                {
                    "income_cents": 100_000_000_000,
                    "application_id": application.id,
                },
            )

        db.session.rollback()


def test_application_rejects_lowercase_province(app):
    with app.app_context():
        db.session.add(build_application(province="bc"))

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()
