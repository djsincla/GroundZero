"""In-process asynchronous job runner.

Every long-running operation (inventory, preflight, and later OS install / Holodeck deploy) is a Job:
it is persisted, addressable by id, observable through per-job events, and cancellable.
Policy: at most one active job per host; at most ``max_concurrent`` jobs running overall.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from groundzero.core.models import Job, JobError, JobEvent, JobKind, JobStatus
from groundzero.core.store import Store, utcnow

logger = logging.getLogger(__name__)

_QUEUE_SIZE = 256


class HostBusyError(Exception):
    def __init__(self, host_id: str, job_id: str) -> None:
        super().__init__(f"Host {host_id} already has an active job ({job_id})")
        self.host_id = host_id
        self.job_id = job_id


class JobContext:
    """Handle given to a job function for reporting progress."""

    def __init__(self, runner: JobRunner, job: Job) -> None:
        self._runner = runner
        self.job = job

    def progress(self, fraction: float, message: str) -> None:
        self.job.progress = max(0.0, min(1.0, fraction))
        self.job.message = message
        self._runner._persist_and_publish(self.job)


JobFunc = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobRunner:
    def __init__(self, store: Store, max_concurrent: int) -> None:
        self._store = store
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active_by_host: dict[str, str] = {}
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = {}

    def submit(self, *, kind: JobKind, host_id: str, params: dict[str, Any], func: JobFunc) -> Job:
        if active := self._active_by_host.get(host_id):
            raise HostBusyError(host_id, active)
        job = self._store.create_job(kind=kind, host_id=host_id, params=params)
        self._active_by_host[host_id] = job.id
        self._tasks[job.id] = asyncio.create_task(self._run(job, func), name=f"job-{job.id}")
        return job

    def active_job(self, host_id: str) -> str | None:
        return self._active_by_host.get(host_id)

    def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def subscribe(self, job_id: str) -> asyncio.Queue[JobEvent]:
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers.setdefault(job_id, set()).add(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue[JobEvent]) -> None:
        subs = self._subscribers.get(job_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(job_id, None)

    async def wait(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.shield(task)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job: Job, func: JobFunc) -> None:
        try:
            async with self._sem:
                job.status = JobStatus.RUNNING
                job.started_at = utcnow()
                self._persist_and_publish(job)
                job.result = await func(JobContext(self, job))
                job.status = JobStatus.SUCCEEDED
                job.progress = 1.0
                job.message = "Completed"
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.message = "Cancelled"
        except Exception as exc:
            logger.exception("Job %s (%s) failed", job.id, job.kind)
            job.status = JobStatus.FAILED
            job.error = JobError(type=getattr(exc, "error_type", type(exc).__name__), message=str(exc))
            job.message = "Failed"
        finally:
            job.finished_at = utcnow()
            self._persist_and_publish(job)
            self._active_by_host.pop(job.host_id, None)
            self._tasks.pop(job.id, None)

    def _persist_and_publish(self, job: Job) -> None:
        self._store.save_job(job)
        event = JobEvent(
            job_id=job.id, status=job.status, progress=job.progress, message=job.message, at=utcnow()
        )
        for queue in list(self._subscribers.get(job.id, ())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
