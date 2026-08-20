"""Define approval engines and the current random-probability decision logic."""

import random
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from .constants import Decision
from .domain import ApplicationInput, ApprovalOutcome


class ApprovalEngineError(ValueError):
    """Raised when an approval engine produces an invalid outcome."""


class ApprovalEngine(Protocol):
    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome: ...


class RandomApprovalEngine:
    def __init__(self, random_source: Callable[[], float] = random.random) -> None:
        self.random_source = random_source

    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        probability = Decimal(str(self.random_source()))
        if (
            not probability.is_finite()
            or probability < Decimal("0")
            or probability >= Decimal("1")
        ):
            raise ApprovalEngineError("random source must return a value in [0, 1)")

        decision = (
            Decision.APPROVED
            if probability > Decimal("0.5")
            else Decision.NOT_APPROVED
        )
        return ApprovalOutcome(
            probability=probability,
            decision=decision,
            engine_version="random-v1",
        )
