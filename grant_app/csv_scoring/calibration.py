"""Fixed training-time score calibration."""

import math


def normalize_score(raw_score: float, *, low: float, high: float, reverse: bool = False) -> float:
    """Map a finite raw model score onto the inclusive risk range ``0..1``."""
    try:
        raw = float(raw_score)
        lower = float(low)
        upper = float(high)
    except (TypeError, ValueError):
        raise ValueError("Invalid calibration values") from None
    if not all(math.isfinite(value) for value in (raw, lower, upper)) or lower >= upper:
        raise ValueError("Invalid calibration values")
    normalized = min(1.0, max(0.0, (raw - lower) / (upper - lower)))
    return 1.0 - normalized if reverse else normalized


def format_score(score: float) -> str:
    """Render normalized scores consistently for CSV output."""
    value = float(score)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("Invalid normalized score")
    return f"{value:.6f}"
