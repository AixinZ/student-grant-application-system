"""Define immutable data objects exchanged between forms, services, and approval engines."""

from dataclasses import dataclass
from decimal import Decimal

from .constants import Decision


@dataclass(frozen=True, slots=True)
class ApplicationInput:
    name: str
    annual_income_cad: Decimal
    address: str
    age: int
    education_level: str
    marital_status: str
    dependents: int
    province: str


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    probability: Decimal
    decision: Decision
    engine_version: str
