"""Private, expiring filesystem storage for CSV scoring uploads and jobs."""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .errors import CsvValidationError, JobNotFoundError, UploadNotFoundError
from .types import ParsedUpload

JobStatus = Literal["queued", "running", "completed", "failed"]
_STATUSES = frozenset(("queued", "running", "completed", "failed"))
_IDENTIFIER_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


@dataclass(frozen=True, slots=True)
class UploadManifest:
    """Metadata for one private uploaded source file."""

    upload_id: str
    headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]
    row_count: int
    size_bytes: int
    expires_at: float
    source_path: Path


@dataclass(frozen=True, slots=True)
class JobManifest:
    """Metadata and lifecycle state for one scoring request."""

    job_id: str
    upload_id: str
    model_id: str
    selected_headers: tuple[str, ...]
    status: JobStatus
    progress_rows: int
    error_code: str | None
    expires_at: float


class FileStore:
    """Keep temporary uploads, results, and metadata outside application databases."""

    def __init__(self, root: Path, ttl_seconds: int):
        self.root = Path(root).resolve()
        self.ttl_seconds = ttl_seconds
        self._uploads = self.root / "uploads"
        self._jobs = self.root / "jobs"
        self._upload_id_key_path = self.root / ".upload-id-key"
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.root.chmod(0o700)
            self._uploads.mkdir(mode=0o700, exist_ok=True)
            self._jobs.mkdir(mode=0o700, exist_ok=True)
            self._upload_id_key = self._load_upload_id_key()
        except OSError as error:
            raise CsvValidationError("Temporary storage unavailable") from error

    def save_upload(self, parsed: ParsedUpload) -> None:
        """Move a validated staged CSV into its private upload directory."""
        upload_id = self._upload_id(parsed.upload_id)
        directory = self._uploads / upload_id
        source = directory / "source.csv"
        owns_directory = False
        try:
            directory.mkdir(mode=0o700)
            owns_directory = True
            os.replace(parsed.path, source)
            self._write_manifest(
                directory / "manifest.json",
                {
                    "upload_id": upload_id,
                    "headers": list(parsed.headers),
                    "canonical_headers": list(parsed.canonical_headers),
                    "row_count": parsed.row_count,
                    "size_bytes": parsed.size_bytes,
                    "expires_at": parsed.expires_at,
                },
            )
        except (OSError, TypeError, ValueError) as error:
            if owns_directory:
                self._remove_directory(directory)
            raise CsvValidationError("Temporary storage unavailable") from error

    def new_upload_id(self) -> str:
        """Issue an authenticated, random identifier for a staged upload."""
        nonce = secrets.token_hex(16)
        signature = hmac.new(self._upload_id_key, nonce.encode("ascii"), hashlib.sha256).hexdigest()
        return f"u{nonce}{signature}"

    def get_upload(self, upload_id: str) -> UploadManifest:
        directory = self._upload_directory(upload_id)
        payload = self._read_manifest(directory / "manifest.json", UploadNotFoundError)
        try:
            if payload["upload_id"] != upload_id:
                raise ValueError
            return UploadManifest(
                upload_id=payload["upload_id"],
                headers=tuple(payload["headers"]),
                canonical_headers=tuple(payload["canonical_headers"]),
                row_count=int(payload["row_count"]),
                size_bytes=int(payload["size_bytes"]),
                expires_at=float(payload["expires_at"]),
                source_path=directory / "source.csv",
            )
        except (KeyError, TypeError, ValueError) as error:
            raise UploadNotFoundError("Upload not found") from error

    def create_job(
        self, upload_id: str, model_id: str, selected_headers: tuple[str, ...], now: float
    ) -> JobManifest:
        self.get_upload(upload_id)
        job_id = self._new_identifier()
        directory = self._jobs / job_id
        manifest = JobManifest(
            job_id=job_id,
            upload_id=upload_id,
            model_id=model_id,
            selected_headers=tuple(selected_headers),
            status="queued",
            progress_rows=0,
            error_code=None,
            expires_at=now + self.ttl_seconds,
        )
        try:
            directory.mkdir(mode=0o700)
            self._write_manifest(directory / "manifest.json", self._job_payload(manifest))
        except (OSError, TypeError, ValueError) as error:
            self._remove_directory(directory)
            raise JobNotFoundError("Job not found") from error
        return manifest

    def get_job(self, job_id: str) -> JobManifest:
        directory = self._job_directory(job_id)
        payload = self._read_manifest(directory / "manifest.json", JobNotFoundError)
        try:
            status = payload["status"]
            if payload["job_id"] != job_id or status not in _STATUSES:
                raise ValueError
            return JobManifest(
                job_id=payload["job_id"],
                upload_id=payload["upload_id"],
                model_id=payload["model_id"],
                selected_headers=tuple(payload["selected_headers"]),
                status=status,
                progress_rows=int(payload["progress_rows"]),
                error_code=payload.get("error_code"),
                expires_at=float(payload["expires_at"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise JobNotFoundError("Job not found") from error

    def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus,
        progress_rows: int,
        error_code: str | None = None,
    ) -> JobManifest:
        current = self.get_job(job_id)
        if status not in _STATUSES or not isinstance(progress_rows, int) or progress_rows < current.progress_rows:
            raise ValueError("Invalid job update")
        if not self._transition_allowed(current.status, status):
            raise ValueError("Invalid job transition")
        if error_code not in (None, "processing_failed"):
            raise ValueError("Invalid job update")
        updated = JobManifest(
            job_id=current.job_id,
            upload_id=current.upload_id,
            model_id=current.model_id,
            selected_headers=current.selected_headers,
            status=status,
            progress_rows=progress_rows,
            error_code=error_code if status == "failed" else None,
            expires_at=current.expires_at,
        )
        if status == "failed":
            self.result_path(job_id).unlink(missing_ok=True)
        self._write_manifest(self._job_directory(job_id) / "manifest.json", self._job_payload(updated))
        return updated

    def result_path(self, job_id: str) -> Path:
        return self._job_directory(job_id) / "result.csv"

    def cleanup_expired(self, now: float) -> int:
        """Remove every expired upload or job directory and return its count."""
        removed = 0
        for base, missing_error in ((self._uploads, UploadNotFoundError), (self._jobs, JobNotFoundError)):
            try:
                directories = tuple(path for path in base.iterdir() if path.is_dir())
            except OSError:
                continue
            for directory in directories:
                try:
                    payload = self._read_manifest(directory / "manifest.json", missing_error)
                    expires_at = float(payload["expires_at"])
                except (KeyError, TypeError, ValueError, UploadNotFoundError, JobNotFoundError):
                    continue
                if expires_at <= now:
                    self._remove_directory(directory)
                    removed += 1
        return removed

    def _upload_id(self, upload_id: str) -> str:
        if not self._valid_upload_identifier(upload_id):
            raise CsvValidationError("CSV validation failed")
        return upload_id

    def _upload_directory(self, upload_id: str) -> Path:
        if not self._valid_upload_identifier(upload_id):
            raise UploadNotFoundError("Upload not found")
        return self._safe_child(self._uploads, upload_id, UploadNotFoundError)

    def _job_directory(self, job_id: str) -> Path:
        if not self._valid_identifier(job_id):
            raise JobNotFoundError("Job not found")
        return self._safe_child(self._jobs, job_id, JobNotFoundError)

    @staticmethod
    def _valid_identifier(identifier: str) -> bool:
        return isinstance(identifier, str) and 16 <= len(identifier) <= 128 and all(
            character in _IDENTIFIER_ALPHABET for character in identifier
        )

    def _valid_upload_identifier(self, identifier: str) -> bool:
        if not isinstance(identifier, str) or len(identifier) != 97 or not identifier.startswith("u"):
            return False
        nonce = identifier[1:33]
        signature = identifier[33:]
        if any(character not in "0123456789abcdef" for character in nonce + signature):
            return False
        expected = hmac.new(
            self._upload_id_key, nonce.encode("ascii"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def _load_upload_id_key(self) -> bytes:
        try:
            return self._upload_id_key_path.read_bytes()
        except FileNotFoundError:
            key = secrets.token_bytes(32)
            descriptor = os.open(self._upload_id_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                self._upload_id_key_path.unlink(missing_ok=True)
                raise
            return key

    @staticmethod
    def _safe_child(base: Path, identifier: str, error_type):
        child = (base / identifier).resolve()
        try:
            child.relative_to(base.resolve())
        except ValueError as error:
            raise error_type("Not found") from error
        return child

    @staticmethod
    def _new_identifier() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def _transition_allowed(current: JobStatus, proposed: JobStatus) -> bool:
        return (current, proposed) in {
            ("queued", "running"),
            ("queued", "failed"),
            ("running", "running"),
            ("running", "completed"),
            ("running", "failed"),
            ("failed", "failed"),
        }

    @staticmethod
    def _job_payload(manifest: JobManifest) -> dict[str, object]:
        return {
            "job_id": manifest.job_id,
            "upload_id": manifest.upload_id,
            "model_id": manifest.model_id,
            "selected_headers": list(manifest.selected_headers),
            "status": manifest.status,
            "progress_rows": manifest.progress_rows,
            "error_code": manifest.error_code,
            "expires_at": manifest.expires_at,
        }

    @staticmethod
    def _write_manifest(path: Path, payload: dict[str, object]) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=".manifest-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_manifest(path: Path, error_type):
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            raise error_type("Not found") from error

    @staticmethod
    def _remove_directory(directory: Path) -> None:
        try:
            shutil.rmtree(directory)
        except OSError:
            pass
