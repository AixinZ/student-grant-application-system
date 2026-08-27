"""Safe adapter for a configured, pre-trained Isolation Forest pipeline."""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import joblib

from ..calibration import normalize_score
from ..errors import ModelUnavailableError
from ..parser import canonical_header


@dataclass(frozen=True, slots=True)
class IsolationForestAdapter:
    """Score rows with a loaded artifact and immutable training calibration."""

    pipeline: object | None = None
    required_headers: tuple[str, ...] = ()
    low: float = 0.0
    high: float = 1.0
    reverse: bool = False
    chunk_size: int = 5_000

    @classmethod
    def from_artifact(cls, artifact_path: Path, manifest_path: Path) -> "IsolationForestAdapter":
        """Load only a configured artifact and validate its public manifest."""
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            required = tuple(canonical_header(value) for value in manifest["required_headers"])
            calibration = manifest["calibration"]
            direction = manifest["score_direction"]
            if (
                not isinstance(manifest["model_id"], str)
                or not isinstance(manifest["version"], str)
                or not required
                or any(not header for header in required)
                or len(required) != len(set(required))
                or direction not in ("higher_is_higher_risk", "lower_is_higher_risk")
            ):
                raise ValueError
            low = float(calibration["low"])
            high = float(calibration["high"])
            # Validate fixed bounds before admitting an artifact.
            normalize_score(low, low=low, high=high)
        except Exception:
            return cls()

        try:
            pipeline = joblib.load(Path(artifact_path))
            if cls._stored_headers(pipeline) != required:
                raise ValueError
            return cls(
                pipeline=pipeline,
                required_headers=required,
                low=low,
                high=high,
                reverse=direction == "lower_is_higher_risk",
            )
        except Exception:
            return cls(
                required_headers=required,
                low=low,
                high=high,
                reverse=direction == "lower_is_higher_risk",
            )

    def is_available(self) -> bool:
        """Whether this configured artifact loaded successfully."""
        return self.pipeline is not None

    @property
    def availability_reason(self) -> str | None:
        """Expose only a fixed route-safe availability status."""
        return None if self.is_available() else "Model is unavailable"

    @staticmethod
    def _stored_headers(pipeline: object) -> tuple[str, ...]:
        headers = getattr(pipeline, "feature_names_in_", None)
        if headers is None:
            raise ValueError("Artifact lacks feature headers")
        return tuple(canonical_header(str(header)) for header in headers)

    def score_rows(self, rows: Sequence[Mapping[str, object]]) -> Sequence[float]:
        """Return calibrated risk scores in deterministic manifest header order."""
        try:
            if self.pipeline is None:
                raise ModelUnavailableError("Model unavailable")
            scores: list[float] = []
            for start in range(0, len(rows), self.chunk_size):
                chunk = rows[start : start + self.chunk_size]
                values = [self._ordered_values(row) for row in chunk]
                raw_scores = self.pipeline.decision_function(values)
                if len(raw_scores) != len(values):
                    raise ValueError
                for raw in raw_scores:
                    score = normalize_score(raw, low=self.low, high=self.high, reverse=self.reverse)
                    if not math.isfinite(score):
                        raise ValueError
                    scores.append(score)
            return scores
        except ModelUnavailableError:
            raise
        except Exception:
            raise ModelUnavailableError("Model unavailable") from None

    def _ordered_values(self, row: Mapping[str, object]) -> list[object]:
        canonical_row = {canonical_header(str(key)): value for key, value in row.items()}
        if any(header not in canonical_row for header in self.required_headers):
            raise ValueError
        return [canonical_row[header] for header in self.required_headers]
