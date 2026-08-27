"""Single-worker execution for private CSV scoring jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from grant_app.diagnostics import log_exception_context

from .store import FileStore

_LOGGER = logging.getLogger(__name__)


class TaskExecutor:
    """Run scoring work serially and keep job failure details private."""

    def __init__(self, store: FileStore):
        self._store = store
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="csv-scoring")

    def submit(self, job_id: str, callable: Callable[[], object]) -> None:
        self._executor.submit(self._run, job_id, callable)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _run(self, job_id: str, work: Callable[[], object]) -> None:
        try:
            current = self._store.get_job(job_id)
            self._store.update_job(job_id, status="running", progress_rows=current.progress_rows)
            work()
            completed = self._store.get_job(job_id)
            self._store.update_job(
                job_id, status="completed", progress_rows=completed.progress_rows
            )
        except BaseException as error:
            log_exception_context(_LOGGER, "csv_scoring_task_failed", error)
            try:
                current = self._store.get_job(job_id)
                if current.status in ("queued", "running"):
                    self._store.update_job(
                        job_id,
                        status="failed",
                        progress_rows=current.progress_rows,
                        error_code="processing_failed",
                    )
            except BaseException as cleanup_error:
                log_exception_context(_LOGGER, "csv_scoring_task_cleanup_failed", cleanup_error)
