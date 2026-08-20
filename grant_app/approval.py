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
    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        """Evaluate an application and return an approval result.

        Args:
            data: Validated student application data.

        Returns:
            The probability, decision, and engine version produced by the
            implementation.

        Raises:
            ApprovalEngineError: If the implementation cannot produce a valid
                outcome.
        """
        ...


class RandomApprovalEngine:
    def __init__(self, random_source: Callable[[], float] = random.random) -> None:
        """Initialize the engine with an injectable source of random values.

        Args:
            random_source: A callable that returns a numeric value in the
                half-open interval ``[0, 1)`` each time it is called.
        """
        self.random_source = random_source

    def evaluate(self, data: ApplicationInput) -> ApprovalOutcome:
        """Make a temporary approval decision from a random probability.

        Args:
            data: Validated application data. The random-v1 engine accepts the
                complete record but does not yet use its fields.

        Returns:
            An outcome approved when the generated probability is greater than
            ``0.5`` and not approved otherwise.

        Raises:
            ApprovalEngineError: If the random source returns a non-finite
                value or a value outside ``[0, 1)``.
            InvalidOperation: If the random source returns a value whose string
                representation cannot be parsed as a decimal number.
        """
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
