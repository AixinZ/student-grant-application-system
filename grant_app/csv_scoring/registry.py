"""Registry for selectable pre-trained CSV scoring models."""

from typing import Iterable

from .errors import ModelUnavailableError
from .models import ModelSpec


class ModelRegistry:
    """Store model specifications without loading request-provided artifacts."""

    def __init__(self, specs: Iterable[ModelSpec] = ()) -> None:
        self._specs: dict[str, ModelSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ModelSpec) -> None:
        if not isinstance(spec, ModelSpec) or spec.model_id in self._specs:
            raise ValueError("Invalid model registration")
        self._specs[spec.model_id] = spec

    def get(self, model_id: str) -> ModelSpec:
        try:
            spec = self._specs[model_id]
        except (KeyError, TypeError):
            raise ModelUnavailableError("Model unavailable") from None
        if not self._is_available(spec):
            raise ModelUnavailableError("Model unavailable")
        return spec

    def list_available(self) -> tuple[ModelSpec, ...]:
        return tuple(spec for spec in self._specs.values() if self._is_available(spec))

    def availability_reason(self, model_id: str) -> str | None:
        """Return a route-safe reason without artifact or exception details."""
        try:
            spec = self._specs[model_id]
        except (KeyError, TypeError):
            return "Model is unavailable"
        return None if self._is_available(spec) else "Model is unavailable"

    @staticmethod
    def _is_available(spec: ModelSpec) -> bool:
        checker = getattr(spec.adapter, "is_available", None)
        try:
            if callable(checker):
                return bool(checker())
            return not bool(getattr(spec.adapter, "availability_reason", None))
        except Exception:
            return False
