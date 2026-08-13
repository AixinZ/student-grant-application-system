from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import Mapped, mapped_column

from .constants import (
    Decision,
    EDUCATION_CHOICES,
    MARITAL_STATUS_CHOICES,
    PROVINCE_CHOICES,
)
from .extensions import db


class ExactNumeric(Numeric):
    """Preserve SQLite numeric values without exposing binary float tails."""

    cache_ok = True

    def result_processor(self, dialect: Dialect, coltype: object):
        if self.asdecimal and not dialect.supports_native_decimal:
            return lambda value: Decimal(str(value)) if value is not None else None
        return super().result_processor(dialect, coltype)


def _allowed_values(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Application(db.Model):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("age >= 16 AND age <= 100", name="ck_applications_age_range"),
        CheckConstraint(
            "annual_income_cad >= 0 AND annual_income_cad <= 999999999.99",
            name="ck_applications_income_range",
        ),
        CheckConstraint(
            "dependents >= 0 AND dependents <= 20",
            name="ck_applications_dependents_range",
        ),
        CheckConstraint(
            "approval_probability >= 0 AND approval_probability <= 1",
            name="ck_applications_probability_range",
        ),
        CheckConstraint(
            f"decision IN ({_allowed_values(decision.value for decision in Decision)})",
            name="ck_applications_decision_allowed",
        ),
        CheckConstraint(
            f"education_level IN ({_allowed_values(value for value, _ in EDUCATION_CHOICES)})",
            name="ck_applications_education_level_allowed",
        ),
        CheckConstraint(
            f"marital_status IN ({_allowed_values(value for value, _ in MARITAL_STATUS_CHOICES)})",
            name="ck_applications_marital_status_allowed",
        ),
        CheckConstraint(
            f"province IN ({_allowed_values(value for value, _ in PROVINCE_CHOICES)})",
            name="ck_applications_province_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    annual_income_cad: Mapped[Decimal] = mapped_column(Numeric(11, 2), nullable=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    education_level: Mapped[str] = mapped_column(String(30), nullable=False)
    marital_status: Mapped[str] = mapped_column(String(20), nullable=False)
    dependents: Mapped[int] = mapped_column(Integer, nullable=False)
    province: Mapped[str] = mapped_column(String(2), nullable=False)
    approval_probability: Mapped[Decimal] = mapped_column(ExactNumeric(18, 17), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    approval_engine: Mapped[str] = mapped_column(String(50), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True
    )
