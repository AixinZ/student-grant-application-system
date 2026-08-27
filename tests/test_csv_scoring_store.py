import json
import logging
import os
from pathlib import Path

import pytest

from grant_app.csv_scoring.errors import CsvValidationError, JobNotFoundError, UploadNotFoundError
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
    parsed = parsed_upload(tmp_path, store.new_upload_id())

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
    parsed = parsed_upload(tmp_path, store.new_upload_id())
    store.save_upload(parsed)

    first = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)
    second = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)

    assert first.job_id != second.job_id
    assert len(first.job_id) >= 24
    with pytest.raises((AttributeError, TypeError)):
        first.status = "completed"


def test_manifests_are_written_by_atomic_rename(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path, store.new_upload_id())
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
    parsed = parsed_upload(tmp_path, store.new_upload_id())
    store.save_upload(parsed)
    job = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)

    assert store.cleanup_expired(now=3_701.0) == 2
    assert not list((tmp_path / "store").rglob("*.sqlite"))
    with pytest.raises(UploadNotFoundError):
        store.get_upload(parsed.upload_id)
    with pytest.raises(JobNotFoundError):
        store.get_job(job.job_id)


def test_cleanup_removes_stale_staging_and_unreadable_manifest_directories(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=10)
    stale_staging = store.root / ".csv-upload-interrupted"
    stale_staging.write_text("partial", encoding="utf-8")
    stale_upload = store.root / "uploads" / "interrupted_upload"
    stale_upload.mkdir()
    stale_job = store.root / "jobs" / "interrupted_job"
    stale_job.mkdir()
    (stale_job / "manifest.json").write_text("not json", encoding="utf-8")
    active_staging = store.root / "upload-active.csv"
    active_staging.write_text("still writing", encoding="utf-8")
    active_upload = store.root / "uploads" / "active_upload"
    active_upload.mkdir()
    for path in (stale_staging, stale_upload, stale_job):
        os.utime(path, (89.0, 89.0))
    os.utime(active_upload, (99.0, 99.0))

    assert store.cleanup_expired(now=100.0) == 3
    assert not stale_staging.exists()
    assert not stale_upload.exists()
    assert not stale_job.exists()
    assert active_staging.exists()
    assert active_upload.exists()


def test_cleanup_reports_failed_orphan_deletion_without_logging_its_path(tmp_path, monkeypatch, caplog):
    store = FileStore(tmp_path / "store", ttl_seconds=10)
    stale_upload = store.root / "uploads" / "interrupted_upload"
    stale_upload.mkdir()
    os.utime(stale_upload, (89.0, 89.0))

    def fail_rmtree(path):
        raise OSError("private path must not be logged")

    monkeypatch.setattr("grant_app.csv_scoring.store.shutil.rmtree", fail_rmtree)
    caplog.set_level(logging.ERROR, logger="grant_app.csv_scoring.store")

    assert store.cleanup_expired(now=100.0) == 0
    assert stale_upload.exists()
    assert "csv_scoring_orphan_cleanup_failed" in caplog.text
    assert str(stale_upload) not in caplog.text


def test_status_transitions_require_monotonic_progress_and_remove_failed_result(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path, store.new_upload_id())
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


def test_save_upload_rejects_predictable_identifier(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)

    with pytest.raises(CsvValidationError):
        store.save_upload(parsed_upload(tmp_path, "a" * 32))


def test_duplicate_upload_save_preserves_existing_upload(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    upload_id = store.new_upload_id()
    first = parsed_upload(tmp_path, upload_id)
    store.save_upload(first)
    first_source = store.get_upload(upload_id).source_path.read_bytes()
    second_source = tmp_path / "second.csv"
    second_source.write_text("name,value\nb,2\n", encoding="utf-8")
    second = ParsedUpload(
        upload_id=upload_id, path=second_source, headers=("name", "value"),
        canonical_headers=("name", "value"), row_count=1, size_bytes=15, expires_at=3_700.0,
    )

    with pytest.raises(CsvValidationError):
        store.save_upload(second)

    assert store.get_upload(upload_id).source_path.read_bytes() == first_source
    assert second_source.exists()


def test_failed_result_is_deleted_before_failed_manifest_is_persisted(tmp_path, monkeypatch):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path, store.new_upload_id())
    store.save_upload(parsed)
    job = store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)
    store.update_job(job.job_id, status="running", progress_rows=0)
    result = store.result_path(job.job_id)
    result.write_text("partial", encoding="utf-8")
    original_unlink = Path.unlink

    def assert_running_then_unlink(path, *args, **kwargs):
        if path == result:
            assert store.get_job(job.job_id).status == "running"
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", assert_running_then_unlink)
    store.update_job(job.job_id, status="failed", progress_rows=0, error_code="processing_failed")

    assert store.get_job(job.job_id).status == "failed"
    assert not result.exists()
