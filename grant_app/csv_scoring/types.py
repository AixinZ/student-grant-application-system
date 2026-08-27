"""Value objects used by the CSV scoring upload boundary."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ParsedUpload:
    upload_id: str
    path: Path
    headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]
    row_count: int
    size_bytes: int
    expires_at: float

