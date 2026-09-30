"""/api/v1/jobs — status, cancellation and live events for long-running work."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from groundzero.api.deps import ServicesDep
from groundzero.core.models import Job, JobEvent
from groundzero.core.store import utcnow

router = APIRouter(prefix="/jobs", tags=["jobs"])

_KEEPALIVE_SECONDS = 15.0


@router.get("", response_model=list[Job])
def list_jobs(
    services: ServicesDep,
    host_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[Job]:
    return services.list_jobs(host_id=host_id, limit=limit)


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str, services: ServicesDep) -> Job:
    return services.get_job(job_id)


@router.post("/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED, response_model=Job)
def cancel_job(job_id: str, services: ServicesDep) -> Job:
    return services.cancel_job(job_id)


def _sse(event: JobEvent) -> str:
    return f"event: {event.status.value}\ndata: {event.model_dump_json()}\n\n"


@router.get(
    "/{job_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-sent JobEvent stream"}},
)
async def job_events(job_id: str, request: Request, services: ServicesDep) -> StreamingResponse:
    job = services.get_job(job_id)
    queue = services.runner.subscribe(job_id)

    async def stream() -> AsyncIterator[str]:
        try:
            current = services.get_job(job_id)
            yield _sse(
                JobEvent(
                    job_id=job.id,
                    status=current.status,
                    progress=current.progress,
                    message=current.message,
                    at=utcnow(),
                )
            )
            if current.status.is_terminal:
                return
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _sse(event)
                if event.status.is_terminal:
                    return
        finally:
            services.runner.unsubscribe(job_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
