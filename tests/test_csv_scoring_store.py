import json
import os
from pathlib import Path

import pytest

from grant_app.csv_scoring.errors import JobNotFoundError, UploadNotFoundError
from grant_app.csv_scoring.store import FileStore
from grant_app.csv_scoring.types import ParsedUpload


def parsed_upload(tmp_path: Path, upload_id: str = "upload_0123456789abcdef") -> ParsedUpload:
    source = tmp_path / "staged.csv"
    source.write_text("name,value\na,1\n", encoding="utf-8")
    return ParsedUpload(
        upload_id=upload_id,
        path=source,
        headers=("name", "value"),
        canonical_headers=("name", "value"),
        row_count=1,
        size_bytes=15,
        expires_at=3_700.0,
    )


def test_save_upload_moves_source_and_persists_only_metadata(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path)

    store.save_upload(parsed)

    manifest = store.get_upload(parsed.upload_id)
    assert manifest.upload_id == parsed.upload_id
    assert manifest.headers == ("name", "value")
    assert manifest.row_count == 1
    assert not parsed.path.exists()
    serialized = (tmp_path / "store" / "uploads" / parsed.upload_id / "manifest.json").read_text()
    assert "a,1" not in serialized


def test_job_ids_are_random_and_manifests_are_immutable(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path)
    store.save_upload(parsed)

    first = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)
    second = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)

    assert first.job_id != second.job_id
    assert len(first.job_id) >= 24
    with pytest.raises((AttributeError, TypeError)):
        first.status = "completed"


def test_manifests_are_written_by_atomic_rename(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path)
    replacements = []
    original_replace = os.replace

    def recording_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr("grant_app.csv_scoring.store.os.replace", recording_replace)
    store.save_upload(parsed)

    assert any(source.name.startswith(".manifest-") and destination.name == "manifest.json"
               for source, destination in replacements)
    payload = json.loads((tmp_path / "store" / "uploads" / parsed.upload_id / "manifest.json").read_text())
    assert payload["upload_id"] == parsed.upload_id


def test_lookup_rejects_traversal_and_missing_manifests(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)

    with pytest.raises(UploadNotFoundError):
        store.get_upload("../secret")
    with pytest.raises(JobNotFoundError):
        store.get_job("missing_0123456789abcdef")
    with pytest.raises(JobNotFoundError):
        store.result_path("../../result")


def test_expired_upload_and_job_are_removed_without_sqlite(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=10)
    parsed = parsed_upload(tmp_path)
    store.save_upload(parsed)
    job = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)

    assert store.cleanup_expired(now=3_701.0) == 2
    assert not list((tmp_path / "store").rglob("*.sqlite"))
    with pytest.raises(UploadNotFoundError):
        store.get_upload(parsed.upload_id)
    with pytest.raises(JobNotFoundError):
        store.get_job(job.job_id)


def test_status_transitions_require_monotonic_progress_and_remove_failed_result(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path)
    store.save_upload(parsed)
    job = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)
    result = store.result_path(job.job_id)
    result.write_text("partial", encoding="utf-8")

    running = store.update_job(job.job_id, status="running", progress_rows=2)
    assert running.status == "running"
    assert running.progress_rows == 2
    with pytest.raises(ValueError):
        store.update_job(job.job_id, status="running", progress_rows=1)
    failed = store.update_job(job.job_id, status="failed", progress_rows=2, error_code="processing_failed")
    assert failed.error_code == "processing_failed"
    assert not result.exists()
