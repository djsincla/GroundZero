"""/api/v1/specs and runs: the jobs you pick for a server or a cluster, and running them as one."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from groundzero.api.deps import ServicesDep
from groundzero.specs import (
    ClusterRunPreview,
    EffectiveSpec,
    Run,
    RunPreview,
    RunStart,
    Spec,
    SpecAssignment,
    SpecWrite,
)

router = APIRouter()


# ── specs ────────────────────────────────────────────────────────────────
@router.get("/specs", response_model=list[Spec], tags=["specs"])
def list_specs(services: ServicesDep) -> list[Spec]:
    return services.list_specs()


@router.post("/specs", status_code=status.HTTP_201_CREATED, response_model=Spec, tags=["specs"])
def create_spec(body: SpecWrite, services: ServicesDep, response: Response) -> Spec:
    """Every step is checked: the task exists, its parameters are valid, and what they refer to (images,
    config sets, profiles) exists. Steps are kept in pipeline order. Secrets are refused."""
    spec = services.save_spec(body)
    response.headers["Location"] = f"/api/v1/specs/{spec.id}"
    return spec


@router.get("/specs/{spec_id}", response_model=Spec, tags=["specs"])
def get_spec(spec_id: str, services: ServicesDep) -> Spec:
    return services.get_spec(spec_id)


@router.put("/specs/{spec_id}", response_model=Spec, tags=["specs"])
def update_spec(spec_id: str, body: SpecWrite, services: ServicesDep) -> Spec:
    return services.save_spec(body, spec_id)


@router.delete("/specs/{spec_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["specs"])
def delete_spec(spec_id: str, services: ServicesDep) -> None:
    """Servers that had it as their own spec fall back to their cluster's. Refused while a cluster uses it."""
    services.delete_spec(spec_id)


@router.get("/hosts/{host_id}/spec", response_model=EffectiveSpec | None, tags=["specs"])
def get_host_spec(host_id: str, services: ServicesDep) -> EffectiveSpec | None:
    """The spec this server runs: its own, else its cluster's, else null."""
    services.get_host(host_id)
    return services.effective_spec(host_id)


@router.put("/hosts/{host_id}/spec", response_model=EffectiveSpec | None, tags=["specs"])
def set_host_spec(host_id: str, body: SpecAssignment, services: ServicesDep) -> EffectiveSpec | None:
    """Give the server its own spec (it overrides its cluster's), or null to use its cluster's."""
    return services.set_host_spec(host_id, body.spec_id)


# ── runs ─────────────────────────────────────────────────────────────────
@router.get("/hosts/{host_id}/runs/preview", response_model=RunPreview, tags=["runs"])
def preview_run(host_id: str, services: ServicesDep) -> RunPreview:
    """What running this server's spec would do now: each step runs, is skipped (done or not needed), or
    is blocked; the destructive steps; and the phrase that starts it."""
    return services.runs.preview(host_id)


@router.post("/hosts/{host_id}/runs", status_code=status.HTTP_202_ACCEPTED, response_model=Run, tags=["runs"])
async def start_run(host_id: str, body: RunStart, services: ServicesDep, response: Response) -> Run:
    """Run the server's spec: steps start one after another and the run stops at the first failure.
    ``confirm`` approves every step, destructive ones included."""
    run = services.runs.start(host_id, body.confirm)
    response.headers["Location"] = f"/api/v1/runs/{run.id}"
    return run


@router.get("/hosts/{host_id}/runs", response_model=list[Run], tags=["runs"])
def list_host_runs(host_id: str, services: ServicesDep, limit: int = 20) -> list[Run]:
    services.get_host(host_id)
    return services.store.list_runs(host_id=host_id, limit=limit)


@router.get("/clusters/{cluster_id}/runs/preview", response_model=ClusterRunPreview, tags=["runs"])
def preview_cluster_run(cluster_id: str, services: ServicesDep) -> ClusterRunPreview:
    return services.runs.cluster_preview(cluster_id)


@router.post(
    "/clusters/{cluster_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=list[Run],
    tags=["runs"],
)
async def start_cluster_run(cluster_id: str, body: RunStart, services: ServicesDep) -> list[Run]:
    """Run every member's spec at once (a member's own spec, else the cluster's). A member that fails
    doesn't stop the others."""
    return services.runs.start_cluster(cluster_id, body.confirm)


@router.get("/runs/{run_id}", response_model=Run, tags=["runs"])
def get_run(run_id: str, services: ServicesDep) -> Run:
    return services.runs.get(run_id)


@router.post("/runs/{run_id}/cancel", response_model=Run, tags=["runs"])
async def cancel_run(run_id: str, services: ServicesDep) -> Run:
    """Stop the run: its current job is cancelled and no later step starts."""
    return services.runs.cancel(run_id)
