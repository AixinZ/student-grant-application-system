"""Model contracts for pre-trained CSV scoring artifacts."""

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence

from .parser import canonical_header


class ModelAdapter(Protocol):
    """Adapter implemented by a pre-trained scoring model."""

    def score_rows(self, rows: Sequence[Mapping[str, object]]) -> Sequence[float]:
        """Return one normalized risk score for every input row."""


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Metadata and adapter for one selectable pre-trained model."""

    model_id: str
    display_name: str
    model_type: Literal["supervised", "unsupervised"]
    required_columns: tuple[str, ...]
    version: str
    adapter: ModelAdapter

    def __post_init__(self) -> None:
        canonical = tuple(canonical_header(column) for column in self.required_columns)
        if (
            not self.model_id
            or not self.display_name
            or not self.version
            or self.model_type not in ("supervised", "unsupervised")
            or not canonical
            or any(not column for column in canonical)
            or len(canonical) != len(set(canonical))
        ):
            raise ValueError("Invalid model specification")
        object.__setattr__(self, "required_columns", canonical)

    def matches_headers(self, headers: Sequence[str]) -> bool:
        """Whether the source headers include every required model feature."""
        available = {canonical_header(header) for header in headers}
        return all(column in available for column in self.required_columns)
