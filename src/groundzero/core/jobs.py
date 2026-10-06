"""In-process asynchronous job runner.

Every long-running operation (inventory, preflight, and later OS install / Holodeck deploy) is a Job:
it is persisted, addressable by id, observable through per-job events, and cancellable.
Policy: at most one active job per host; at most ``max_concurrent`` jobs running overall.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from groundzero.core import diagnostics
from groundzero.core.models import Job, JobError, JobEvent, JobStatus, JobStep, JobStepStatus
from groundzero.core.store import Store, utcnow

logger = logging.getLogger(__name__)

_QUEUE_SIZE = 256


class HostBusyError(Exception):
    def __init__(self, host_id: str, job_id: str) -> None:
        super().__init__(f"Host {host_id} already has an active job ({job_id})")
        self.host_id = host_id
        self.job_id = job_id


class JobContext:
    """Handle given to a job function for reporting progress and named steps."""

    def __init__(self, runner: JobRunner, job: Job) -> None:
        self._runner = runner
        self.job = job

    def progress(self, fraction: float, message: str) -> None:
        self.job.progress = max(0.0, min(1.0, fraction))
        self.job.message = message
        diagnostics.record("progress", progress=round(self.job.progress, 3), message=message)
        self._runner._persist_and_publish(self.job)

    def plan(self, steps: list[tuple[str, str]]) -> None:
        """Declare the steps up front so they show as pending before they run."""
        for key, title in steps:
            self._step(key, title)
        self._runner._persist_and_publish(self.job)

    @asynccontextmanager
    async def step(self, key: str, title: str) -> AsyncIterator[JobStep]:
        """Run a block as a named step: running → succeeded/failed/cancelled, with timestamps."""
        step = self._step(key, title)
        step.status, step.started_at, step.finished_at = JobStepStatus.RUNNING, utcnow(), None
        self.job.message = title
        diagnostics.record("step", key=key, status="running", title=title)
        self._runner._persist_and_publish(self.job)
        try:
            yield step
        except asyncio.CancelledError:
            step.status = JobStepStatus.CANCELLED
            raise
        except Exception as exc:
            step.status = JobStepStatus.FAILED
            step.message = step.message or str(exc)
            raise
        else:
            step.status = JobStepStatus.SUCCEEDED
        finally:
            step.finished_at = utcnow()
            diagnostics.record("step", key=key, status=step.status.value, message=step.message)
            self._runner._persist_and_publish(self.job)

    def skip(self, key: str, title: str, reason: str) -> None:
        step = self._step(key, title)
        step.status, step.message = JobStepStatus.SKIPPED, reason
        diagnostics.record("step", key=key, status="skipped", message=reason)
        self._runner._persist_and_publish(self.job)

    def _step(self, key: str, title: str) -> JobStep:
        for step in self.job.steps:
            if step.key == key:
                return step
        step = JobStep(key=key, title=title)
        self.job.steps.append(step)
        return step


JobFunc = Callable[[JobContext], Awaitable[dict[str, Any]]]


class JobRunner:
    def __init__(self, store: Store, max_concurrent: int) -> None:
        self._store = store
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._active_by_host: dict[str, str] = {}
        self._subscribers: dict[str, set[asyncio.Queue[JobEvent]]] = {}

    def submit(self, *, task: str, host_id: str, params: dict[str, Any], func: JobFunc) -> Job:
        if active := self._active_by_host.get(host_id):
            raise HostBusyError(host_id, active)
        job = self._store.create_job(task=task, host_id=host_id, params=params)
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
        diag = diagnostics.Diagnostics(job.id)
        diagnostics.current.set(diag)  # this task's context: everything the job awaits records here
        diag.record("job", task=job.task, params=job.params)
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
            logger.exception("Job %s (%s) failed", job.id, job.task)
            job.status = JobStatus.FAILED
            job.error = JobError(type=getattr(exc, "error_type", type(exc).__name__), message=str(exc))
            job.message = "Failed"
            diag.record("error", type=job.error.type, message=str(exc), traceback=traceback.format_exc())
        finally:
            job.finished_at = utcnow()
            diag.record("job", status=job.status.value, message=job.message)
            try:
                self._store.save_diagnostics(job.id, diag.export())
            except Exception:
                logger.exception("Could not save diagnostics for job %s", job.id)
            self._persist_and_publish(job)
            self._active_by_host.pop(job.host_id, None)
            self._tasks.pop(job.id, None)

    def _persist_and_publish(self, job: Job) -> None:
        self._store.save_job(job)
        event = JobEvent(
            job_id=job.id,
            status=job.status,
            progress=job.progress,
            message=job.message,
            at=utcnow(),
            steps=[s.model_copy() for s in job.steps],
        )
        for queue in list(self._subscribers.get(job.id, ())):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
