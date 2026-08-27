"""Atomic, privacy-safe CSV result export."""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from .calibration import format_score
from .errors import ScoringError


def _failed() -> ScoringError:
    return ScoringError("CSV scoring failed")


def write_scored_csv(
    rows: Iterable[Mapping[str, object]],
    output_path: Path,
    *,
    selected_headers: tuple[str, ...],
    scores: Iterable[float],
) -> None:
    """Atomically write selected source fields and their normalized scores."""
    temporary: Path | None = None
    try:
        output = Path(output_path)
        if not selected_headers:
            raise _failed()
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", dir=output.parent,
            prefix=".result-", suffix=".csv", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.writer(handle)
            writer.writerow([*selected_headers, "SCORE"])
            row_iterator = iter(rows)
            score_iterator = iter(scores)
            sentinel = object()
            while True:
                row = next(row_iterator, sentinel)
                score = next(score_iterator, sentinel)
                if row is sentinel and score is sentinel:
                    break
                if row is sentinel or score is sentinel:
                    raise _failed()
                try:
                    rendered_score = format_score(score)
                    writer.writerow([row[header] for header in selected_headers] + [rendered_score])
                except (KeyError, TypeError, ValueError, OverflowError):
                    raise _failed() from None
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        temporary = None
    except ScoringError:
        raise
    except Exception:
        raise _failed() from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
