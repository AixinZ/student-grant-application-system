from .approval import ApprovalEngine
from .domain import ApplicationInput
from .models import Application
from .repository import ApplicationRepository


def create_application(
    data: ApplicationInput,
    engine: ApprovalEngine,
    repository: ApplicationRepository | None = None,
) -> Application:
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
