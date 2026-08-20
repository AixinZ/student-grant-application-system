"""Coordinate approval evaluation and persistence for a new grant application."""

from .approval import ApprovalEngine
from .domain import ApplicationInput
from .models import Application
from .repository import ApplicationRepository


def create_application(
    data: ApplicationInput,
    engine: ApprovalEngine,
    repository: ApplicationRepository | None = None,
) -> Application:
    """Evaluate, construct, and persist one immutable grant application.

    Args:
        data: Validated student information from the application form.
        engine: The approval engine that produces the probability and decision.
        repository: Optional persistence boundary, primarily injectable for
            alternate implementations and isolated tests.

    Returns:
        The persisted application, including its assigned database identifier.

    Raises:
        ApprovalEngineError: If the approval engine produces an invalid result.
        SQLAlchemyError: If the application cannot be stored in the database.
    """
    outcome = engine.evaluate(data)
    application = Application(
        name=data.name,
        annual_income_cad=data.annual_income_cad,
        address=data.address,
        age=data.age,
        education_level=data.education_level,
        marital_status=data.marital_status,
        dependents=data.dependents,
        province=data.province,
        approval_probability=outcome.probability,
        decision=outcome.decision.value,
        approval_engine=outcome.engine_version,
    )
    return (repository if repository is not None else ApplicationRepository()).create(
        application
    )
