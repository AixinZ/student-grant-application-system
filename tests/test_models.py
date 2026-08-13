from decimal import Decimal

import pytest
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


def test_application_round_trips_high_precision_probability(app):
    with app.app_context():
        probability = Decimal("0.12345678901234567")
        application = build_application(approval_probability=probability)
        db.session.add(application)
        db.session.commit()
        db.session.expire_all()

        saved = db.session.get(Application, application.id)
        assert saved.approval_probability == probability


def test_application_rejects_lowercase_province(app):
    with app.app_context():
        db.session.add(build_application(province="bc"))

        with pytest.raises(IntegrityError):
            db.session.commit()

        db.session.rollback()
