"""Define the application ORM model, exact SQLite value types, and search-key updates."""

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
        """Convert a CAD decimal to exact integer cents before SQLite storage.

        Args:
            value: A finite, non-negative decimal amount with at most two
                fractional places, or ``None`` for a nullable conversion.
            dialect: The active SQLAlchemy dialect supplied to the type hook.

        Returns:
            The amount as integer cents, or ``None`` when no value was supplied.

        Raises:
            ValueError: If the value is not a finite ``Decimal``, has excessive
                precision, or falls outside the supported income range.
        """
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
        """Convert stored integer cents back to an exact two-place decimal.

        Args:
            value: The integer-cent value read from SQLite, or ``None``.
            dialect: The active SQLAlchemy dialect supplied to the type hook.

        Returns:
            The equivalent CAD ``Decimal`` quantized to two places, or ``None``.
        """
        if value is None:
            return None
        return (Decimal(value) / 100).quantize(Decimal("0.00"))


class ExactProbability(TypeDecorator[Decimal]):
    """Store an arbitrary-precision Decimal probability as canonical text."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> str | None:
        """Convert a probability to canonical decimal text for exact storage.

        Args:
            value: A finite ``Decimal`` in the half-open interval ``[0, 1)``, or
                ``None`` for a nullable conversion.
            dialect: The active SQLAlchemy dialect supplied to the type hook.

        Returns:
            A non-exponential decimal string preserving all supplied digits, or
            ``None`` when no value was supplied.

        Raises:
            ValueError: If the value is not a finite ``Decimal`` in ``[0, 1)``.
        """
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
        """Restore an exact probability from its canonical SQLite text.

        Args:
            value: The canonical decimal string read from SQLite, or ``None``.
            dialect: The active SQLAlchemy dialect supplied to the type hook.

        Returns:
            The exact probability as a ``Decimal``, or ``None``.
        """
        if value is None:
            return None
        return Decimal(value)


def _allowed_values(values: Iterable[str]) -> str:
    """Render trusted enum values for inclusion in model CHECK constraints.

    Args:
        values: Internal constant values that define an allowed database domain.

    Returns:
        A comma-separated sequence of single-quoted SQL string literals.

    Notes:
        Callers pass only application-owned constants; this helper must not be
        used with user-supplied input.
    """
    return ", ".join(f"'{value}'" for value in values)


def make_name_search_key(value: str) -> str:
    """Create the persisted Unicode-insensitive key used for name searches.

    Args:
        value: A normalized student name or search fragment.

    Returns:
        The NFC-normalized, case-folded search representation.
    """
    return unicodedata.normalize("NFC", value).casefold()


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp for a new record.

    Returns:
        The current time with ``timezone.utc`` attached.
    """
    return datetime.now(timezone.utc)


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
        default=_utc_now,
        index=True,
    )


@event.listens_for(Application, "before_insert")
def _set_name_search_key(_mapper, _connection, target: Application) -> None:
    """Populate the normalized name-search key immediately before insertion.

    Args:
        _mapper: SQLAlchemy mapper metadata supplied to the event hook.
        _connection: The active SQLAlchemy connection supplied to the hook.
        target: The application about to be inserted.

    Notes:
        This mutates only ``target.name_search_key`` so searches can use a
        persisted, indexed Unicode case-folded value.
    """
    target.name_search_key = make_name_search_key(target.name)
