import threading
import time
from pathlib import Path

from grant_app.csv_scoring.store import FileStore
from grant_app.csv_scoring.tasks import TaskExecutor
from grant_app.csv_scoring.types import ParsedUpload


def parsed_upload(tmp_path: Path) -> ParsedUpload:
    source = tmp_path / "staged.csv"
    source.write_text("name,value\na,1\n", encoding="utf-8")
    return ParsedUpload(
        upload_id="upload_0123456789abcdef",
        path=source,
        headers=("name", "value"),
        canonical_headers=("name", "value"),
        row_count=1,
        size_bytes=15,
        expires_at=3_700.0,
    )


def make_job(tmp_path):
    store = FileStore(tmp_path / "store", ttl_seconds=3600)
    parsed = parsed_upload(tmp_path)
    store.save_upload(parsed)
    return store, store.create_job(parsed.upload_id, "iforest", ("name",), now=100.0)


def test_executor_marks_worker_exception_failed_and_removes_partial_result(tmp_path):
    store, job = make_job(tmp_path)
    store.result_path(job.job_id).write_text("partial", encoding="utf-8")
    executor = TaskExecutor(store)

    executor.submit(job.job_id, lambda: (_ for _ in ()).throw(RuntimeError("private source value")))
    executor.shutdown()

    failed = store.get_job(job.job_id)
    assert failed.status == "failed"
    assert failed.error_code == "processing_failed"
    assert not store.result_path(job.job_id).exists()


def test_executor_runs_only_one_job_at_a_time(tmp_path):
    store, first = make_job(tmp_path)
    second = store.create_job(first.upload_id, "iforest", ("name",), now=100.0)
    executor = TaskExecutor(store)
    started = []
    release_first = threading.Event()
    second_started = threading.Event()

    def first_work():
        started.append("first")
        release_first.wait(timeout=1)

    def second_work():
        started.append("second")
        second_started.set()

    executor.submit(first.job_id, first_work)
    executor.submit(second.job_id, second_work)
    time.sleep(0.05)
    assert started == ["first"]
    assert not second_started.is_set()
    release_first.set()
    executor.shutdown()
    assert started == ["first", "second"]
    assert store.get_job(first.job_id).status == "completed"
    assert store.get_job(second.job_id).status == "completed"
