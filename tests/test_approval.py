from decimal import Decimal

import pytest

from grant_app.approval import ApprovalEngineError, RandomApprovalEngine
from grant_app.constants import Decision
from grant_app.domain import ApplicationInput


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


def test_probability_at_threshold_is_not_approved(valid_input):
    outcome = RandomApprovalEngine(lambda: 0.5).evaluate(valid_input)

    assert outcome.probability == Decimal("0.5")
    assert outcome.decision is Decision.NOT_APPROVED
    assert outcome.engine_version == "random-v1"


def test_probability_above_threshold_is_approved(valid_input):
    outcome = RandomApprovalEngine(lambda: 0.5001).evaluate(valid_input)

    assert outcome.decision is Decision.APPROVED


@pytest.mark.parametrize("value", [-0.0001, 1, 1.0])
def test_probability_outside_half_open_unit_interval_is_rejected(valid_input, value):
    with pytest.raises(ApprovalEngineError):
        RandomApprovalEngine(lambda: value).evaluate(valid_input)
