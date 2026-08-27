"""Bounded-memory execution of pre-trained CSV scoring models."""

from __future__ import annotations

import csv
import math
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path

from .errors import ScoringError
from .exporter import write_scored_csv
from .models import ModelSpec
from .parser import canonical_header


def _failed() -> ScoringError:
    return ScoringError("CSV scoring failed")


def _validated_scores(scores: Sequence[float], expected_count: int) -> tuple[float, ...]:
    try:
        values = tuple(scores)
    except (TypeError, ValueError, OverflowError):
        raise _failed() from None
    if len(values) != expected_count:
        raise _failed()
    try:
        converted = tuple(float(score) for score in values)
    except (TypeError, ValueError, OverflowError):
        raise _failed() from None
    if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in converted):
        raise _failed()
    return converted


def score_job(
    source_path: Path,
    result_temp_path: Path,
    *,
    selected_headers: tuple[str, ...],
    model: ModelSpec,
    chunk_size: int,
    progress: Callable[[int], None],
) -> int:
    """Score a validated staged CSV in chunks and atomically create its result."""
    source = Path(source_path)
    result = Path(result_temp_path)
    if chunk_size <= 0:
        raise _failed()
    try:
        if source.resolve() == result.resolve():
            raise _failed()
    except OSError:
        raise _failed() from None

    total = 0
    scores: deque[float] = deque()

    def selected_rows() -> Iterator[Mapping[str, object]]:
        nonlocal total
        try:
            with source.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, strict=True)
                if not reader.fieldnames:
                    raise _failed()
                canonical_to_original = {
                    canonical_header(header): header for header in reader.fieldnames if header is not None
                }
                if len(canonical_to_original) != len(reader.fieldnames):
                    raise _failed()
                selected_original = tuple(
                    canonical_to_original[canonical_header(header)] for header in selected_headers
                )
                if not selected_original:
                    raise _failed()
                batch: list[dict[str, object]] = []
                output_batch: list[dict[str, object]] = []
                for source_row in reader:
                    if None in source_row or any(value is None for value in source_row.values()):
                        raise _failed()
                    canonical_row = {
                        canonical_header(header): value for header, value in source_row.items()
                    }
                    batch.append(canonical_row)
                    output_batch.append({header: source_row[header] for header in selected_original})
                    if len(batch) == chunk_size:
                        _score_batch(batch, model, scores)
                        total += len(batch)
                        progress(total)
                        yield from output_batch
                        batch.clear()
                        output_batch.clear()
                if batch:
                    _score_batch(batch, model, scores)
                    total += len(batch)
                    progress(total)
                    yield from output_batch
        except ScoringError:
            raise
        except (OSError, csv.Error, TypeError, ValueError, UnicodeError):
            raise _failed() from None

    def score_values() -> Iterator[float]:
        while True:
            if not scores:
                return
            yield scores.popleft()

    try:
        # The two synchronized iterators retain at most one model batch.
        original_headers = _original_selected_headers(source, selected_headers)
        write_scored_csv(selected_rows(), result, selected_headers=original_headers, scores=score_values())
    except ScoringError:
        _remove_result(result)
        raise
    except Exception:
        _remove_result(result)
        raise _failed() from None
    return total


def _original_selected_headers(source: Path, selected_headers: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve user selections to the source spelling used in the export header."""
    try:
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            headers = next(reader)
        canonical_to_original = {canonical_header(header): header for header in headers}
        if len(canonical_to_original) != len(headers):
            raise _failed()
        resolved = tuple(canonical_to_original[canonical_header(header)] for header in selected_headers)
        if not resolved or len(set(canonical_header(header) for header in resolved)) != len(resolved):
            raise _failed()
        return resolved
    except ScoringError:
        raise
    except (KeyError, OSError, csv.Error, StopIteration, TypeError, ValueError, UnicodeError):
        raise _failed() from None


def _score_batch(batch: Sequence[Mapping[str, object]], model: ModelSpec, scores: deque[float]) -> None:
    try:
        required_rows = tuple(
            {column: row[column] for column in model.required_columns} for row in batch
        )
        produced = model.adapter.score_rows(required_rows)
    except Exception:
        raise _failed() from None
    scores.extend(_validated_scores(produced, len(batch)))


def _remove_result(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
