import unicodedata
from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .constants import (
    Decision,
    EDUCATION_CHOICES,
    MARITAL_STATUS_CHOICES,
    PROVINCE_CHOICES,
)
from .extensions import db


INCOME_MAX_CENTS = 99_999_999_999


class ExactIncome(TypeDecorator[Decimal]):
    """Store a two-decimal CAD amount as exact SQLite integer cents."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> int | None:
        if value is None:
            return None
        if not isinstance(value, Decimal) or not value.is_finite():
            raise ValueError("annual_income_cad must be a finite Decimal")

        cents = value * 100
        if cents != cents.to_integral_value():
            raise ValueError("annual_income_cad supports at most two decimal places")
        if cents < 0 or cents > INCOME_MAX_CENTS:
            raise ValueError("annual_income_cad is outside the supported range")
        return int(cents)

    def process_result_value(self, value: int | None, dialect) -> Decimal | None:
        if value is None:
            return None
        return (Decimal(value) / 100).quantize(Decimal("0.00"))


class ExactProbability(TypeDecorator[Decimal]):
    """Store an arbitrary-precision Decimal probability as canonical text."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> str | None:
        if value is None:
            return None
        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value < Decimal("0")
            or value >= Decimal("1")
        ):
            raise ValueError("approval_probability must be a Decimal in [0, 1)")
        return format(value, "f")

    def process_result_value(self, value: str | None, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)


def _allowed_values(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def make_name_search_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


class Application(db.Model):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("age >= 16 AND age <= 100", name="ck_applications_age_range"),
        CheckConstraint(
            f"typeof(annual_income_cad) = 'integer' "
            f"AND annual_income_cad >= 0 AND annual_income_cad <= {INCOME_MAX_CENTS}",
            name="ck_applications_income_range",
        ),
        CheckConstraint(
            "dependents >= 0 AND dependents <= 20",
            name="ck_applications_dependents_range",
        ),
        CheckConstraint(
            "typeof(approval_probability) = 'text' AND ("
            "approval_probability = '0' OR ("
            "substr(approval_probability, 1, 2) = '0.' "
            "AND length(approval_probability) > 2 "
            "AND substr(approval_probability, 3) NOT GLOB '*[^0-9]*'))",
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
    name_search_key: Mapped[str] = mapped_column(
        String(300), nullable=False, index=True
    )
    annual_income_cad: Mapped[Decimal] = mapped_column(ExactIncome(), nullable=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    education_level: Mapped[str] = mapped_column(String(30), nullable=False)
    marital_status: Mapped[str] = mapped_column(String(20), nullable=False)
    dependents: Mapped[int] = mapped_column(Integer, nullable=False)
    province: Mapped[str] = mapped_column(String(2), nullable=False)
    approval_probability: Mapped[Decimal] = mapped_column(
        ExactProbability(), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    approval_engine: Mapped[str] = mapped_column(String(50), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


@event.listens_for(Application, "before_insert")
def _set_name_search_key(_mapper, _connection, target: Application) -> None:
    target.name_search_key = make_name_search_key(target.name)
