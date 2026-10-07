"""Service metadata: health and the task catalog."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from groundzero import __version__
from groundzero.api.deps import ServicesDep
from groundzero.core.tasks import TaskInfo

health_router = APIRouter(tags=["meta"])
router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: str
    version: str
    mode: Literal["live", "simulated"]


@health_router.get("/healthz", response_model=Health)
def healthz(request: Request) -> Health:
    simulated = request.app.state.services.settings.simulate_bmc_dir is not None
    return Health(status="ok", version=__version__, mode="simulated" if simulated else "live")


@router.get("/tasks", response_model=list[TaskInfo])
def list_tasks(services: ServicesDep) -> list[TaskInfo]:
    """The task catalog: what each task needs (``requires``) and makes (``produces``), in pipeline order."""
    return services.list_tasks()


@router.get("/output-kinds", response_model=dict[str, dict[str, Any]])
def output_kinds(services: ServicesDep) -> dict[str, dict[str, Any]]:
    """Every output kind a task can produce (and you can set by hand): its title and JSON Schema."""
    return services.output_kinds()
