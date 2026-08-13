from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError

from grant_app.constants import Decision
from grant_app.domain import ApplicationInput, ApprovalOutcome
from grant_app.extensions import db
from grant_app.models import Application
from grant_app.repository import ApplicationRepository
from grant_app.services import create_application


@pytest.fixture
def valid_input():
    return ApplicationInput(
        name="Alex Student",
        annual_income_cad=Decimal("45000.00"),
        address="123 Main Street",
        age=24,
        education_level="BACHELORS_DEGREE",
        marital_status="SINGLE",
        dependents=0,
        province="BC",
    )


class CountingEngine:
    def __init__(self):
        self.calls = 0

    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        self.calls += 1
        return ApprovalOutcome(
            probability=Decimal("0.5001"),
            decision=Decision.APPROVED,
            engine_version="counting-v1",
        )


class RaisingEngine:
    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        raise RuntimeError("approval unavailable")


def test_create_application_evaluates_once_and_persists_complete_record(app, valid_input):
    with app.app_context():
        engine = CountingEngine()

        saved = create_application(valid_input, engine)

        assert engine.calls == 1
        assert saved.id is not None
        persisted = ApplicationRepository().get(saved.id)
        assert persisted is not None
        assert persisted.name == "Alex Student"
        assert persisted.annual_income_cad == Decimal("45000.00")
        assert persisted.province == "BC"
        assert persisted.approval_probability == Decimal("0.5001")
        assert persisted.decision == Decision.APPROVED.value
        assert persisted.approval_engine == "counting-v1"


def test_create_application_does_not_persist_when_evaluation_fails(app, valid_input):
    with app.app_context():
        with pytest.raises(RuntimeError, match="approval unavailable"):
            create_application(valid_input, RaisingEngine())

        assert Application.query.count() == 0


def test_repository_rolls_back_when_commit_fails(app, valid_input, monkeypatch):
    with app.app_context():
        application = Application(
            name=valid_input.name,
            annual_income_cad=valid_input.annual_income_cad,
            address=valid_input.address,
            age=valid_input.age,
            education_level=valid_input.education_level,
            marital_status=valid_input.marital_status,
            dependents=valid_input.dependents,
            province=valid_input.province,
            approval_probability=Decimal("0.5001"),
            decision=Decision.APPROVED.value,
            approval_engine="random-v1",
        )

        def fail_commit():
            raise SQLAlchemyError("database unavailable")

        monkeypatch.setattr(db.session, "commit", fail_commit)

        with pytest.raises(SQLAlchemyError, match="database unavailable"):
            ApplicationRepository().create(application)

        assert Application.query.count() == 0
