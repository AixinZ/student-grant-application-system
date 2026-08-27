"""Bounded, privacy-safe validation and staging for uploaded CSV files."""

import csv
import io
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import BinaryIO, Iterable

from .errors import CsvValidationError
from .types import ParsedUpload

_COPY_CHUNK_SIZE = 1024 * 1024
_DIALECT_SAMPLE_BYTES = 64 * 1024
_DELIMITER_CANDIDATES = ",;\t|:^~"


def canonical_header(value: str) -> str:
    """Return the comparison form of a source header."""
    return value.strip().casefold()


def _invalid() -> CsvValidationError:
    # Deliberately avoid including values, rows, or paths in parser errors.
    return CsvValidationError("CSV validation failed")


def validate_selected_headers(headers: Iterable[str], selected: Iterable[str]) -> tuple[str, ...]:
    """Validate selected source headers and return their canonical forms."""
    available = {canonical_header(header) for header in headers}
    selected_canonical = tuple(canonical_header(header) for header in selected)
    if not selected_canonical or len(set(selected_canonical)) != len(selected_canonical):
        raise _invalid()
    if any(header not in available for header in selected_canonical):
        raise _invalid()
    return selected_canonical


def _copy_stream(stream: BinaryIO, destination: Path, max_bytes: int) -> int:
    if max_bytes < 0:
        raise _invalid()
    size = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = stream.read(_COPY_CHUNK_SIZE)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                size += len(chunk)
                if size > max_bytes:
                    raise _invalid()
                output.write(chunk)
    except CsvValidationError:
        raise
    except (OSError, TypeError, UnicodeError):
        raise _invalid()
    return size


def _validate_comma_dialect(path: Path) -> None:
    """Reject source data that uses a delimiter other than a comma."""
    try:
        with path.open("rb") as raw:
            sample = raw.read(_DIALECT_SAMPLE_BYTES).decode("utf-8-sig")
        dialect = csv.Sniffer().sniff(sample, delimiters=_DELIMITER_CANDIDATES)
        if dialect.delimiter != ",":
            raise _invalid()
    except CsvValidationError:
        raise
    except (csv.Error, OSError, UnicodeError):
        raise _invalid() from None


def parse_upload(
    stream: BinaryIO,
    destination_dir: Path,
    *,
    upload_id: str,
    max_bytes: int,
    min_rows: int,
    max_rows: int,
    ttl_seconds: int,
    now: float | None = None,
) -> ParsedUpload:
    """Copy and validate a CSV stream, returning its staged upload metadata."""
    temporary: Path | None = None
    try:
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds < 0:
            raise _invalid()
        destination_dir = Path(destination_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination_dir, prefix=".csv-upload-", delete=False
        ) as handle:
            temporary = Path(handle.name)
        size_bytes = _copy_stream(stream, temporary, max_bytes)
        _validate_comma_dialect(temporary)

        headers: tuple[str, ...] | None = None
        canonical_headers: tuple[str, ...] | None = None
        row_count = 0
        try:
            with temporary.open("rb") as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                try:
                    reader = csv.reader(text, delimiter=",", strict=True)
                    try:
                        first = next(reader)
                    except StopIteration:
                        raise _invalid()
                    headers = tuple(first)
                    canonical_headers = tuple(canonical_header(value) for value in headers)
                    if not headers or any(not value for value in canonical_headers):
                        raise _invalid()
                    if len(set(canonical_headers)) != len(canonical_headers):
                        raise _invalid()
                    if "score" in canonical_headers:
                        raise _invalid()
                    for row in reader:
                        if len(row) != len(headers):
                            raise _invalid()
                        row_count += 1
                        if row_count > max_rows:
                            raise _invalid()
                finally:
                    text.detach()
        except CsvValidationError:
            raise
        except (csv.Error, UnicodeError, OSError, ValueError):
            raise _invalid()

        if row_count < min_rows or row_count > max_rows:
            raise _invalid()
        staged = destination_dir / f"upload-{uuid.uuid4().hex}.csv"
        os.replace(temporary, staged)
        temporary = None
        timestamp = time.time() if now is None else now
        return ParsedUpload(
            upload_id=upload_id,
            path=staged,
            headers=headers,
            canonical_headers=canonical_headers,
            row_count=row_count,
            size_bytes=size_bytes,
            expires_at=timestamp + ttl_seconds,
        )
    except CsvValidationError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError, csv.Error):
        raise _invalid()
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
