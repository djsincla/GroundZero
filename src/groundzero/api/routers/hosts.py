"""/api/v1/hosts — BMC targets and the jobs/results attached to them."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from groundzero.api.deps import ServicesDep
from groundzero.core.models import Host, HostCreate, Job, OsAccess, OsAccessSet
from groundzero.core.services import InstallPreview
from groundzero.core.tasks import Pipeline, TaskRun
from groundzero.core.tls import PinnedCertificate
from groundzero.install.job import InstallRequest

router = APIRouter(prefix="/hosts", tags=["hosts"])


def _accepted(response: Response, job: Job) -> Job:
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Host)
def create_host(body: HostCreate, services: ServicesDep, response: Response) -> Host:
    host = services.add_host(body)
    response.headers["Location"] = f"/api/v1/hosts/{host.id}"
    return host


@router.get("", response_model=list[Host])
def list_hosts(services: ServicesDep) -> list[Host]:
    return services.list_hosts()


@router.get("/{host_id}", response_model=Host)
def get_host(host_id: str, services: ServicesDep) -> Host:
    return services.get_host(host_id)


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_host(host_id: str, services: ServicesDep) -> None:
    services.delete_host(host_id)


@router.put("/{host_id}/os", response_model=OsAccess)
def set_os_access(host_id: str, body: OsAccessSet, services: ServicesDep) -> OsAccess:
    """Record how to reach the OS currently installed on the host (e.g. ESXi management IP)."""
    return services.set_os_access(host_id, body)


@router.get("/{host_id}/os", response_model=OsAccess)
def get_os_access(host_id: str, services: ServicesDep) -> OsAccess:
    return services.get_os_access(host_id)


@router.get("/{host_id}/host-values/{family}", response_model=dict[str, Any])
def get_host_values(host_id: str, family: str, services: ServicesDep) -> dict[str, Any]:
    return services.get_host_values(host_id, family)


@router.put("/{host_id}/host-values/{family}", response_model=dict[str, Any])
def set_host_values(host_id: str, family: str, body: dict[str, Any], services: ServicesDep) -> dict[str, Any]:
    """Per-server values (e.g. hostname, ip) validated against the OS family's schema."""
    return services.set_host_values(host_id, family, body)


@router.post("/{host_id}/install/preview", response_model=InstallPreview)
def preview_install(host_id: str, body: InstallRequest, services: ServicesDep) -> InstallPreview:
    """Show the spec and kickstart a deployment would use (password hidden). Touches nothing."""
    return services.preview_install(host_id, body)


@router.get("/{host_id}/certificates", response_model=list[PinnedCertificate])
def list_certificates(host_id: str, services: ServicesDep) -> list[PinnedCertificate]:
    """Pinned BMC/OS certificates (trust on first use). Credentials are only sent to these."""
    return services.list_pins(host_id)


@router.post("/{host_id}/certificates/{role}/trust", response_model=PinnedCertificate)
def trust_certificate(host_id: str, role: str, services: ServicesDep) -> PinnedCertificate:
    """Accept the certificate the BMC ("bmc") or installed OS ("os") presents now. Use only after a
    legitimate change (reinstall, renewed certificate): this replaces the pin."""
    return services.retrust(host_id, role)


@router.get("/{host_id}/pipeline", response_model=Pipeline)
def get_pipeline(host_id: str, services: ServicesDep) -> Pipeline:
    """Every task from bare metal to Holodeck for this host: its state (done, stale, ready, blocked,
    running, failed, planned), what blocks it, its last job and output, plus the recommended next step."""
    return services.pipeline(host_id)


@router.post("/{host_id}/tasks/{task_id}", status_code=status.HTTP_202_ACCEPTED, response_model=Job)
async def start_task(
    host_id: str, task_id: str, body: TaskRun, services: ServicesDep, response: Response
) -> Job:
    """Start a catalog task (GET /tasks). 409 if its inputs are missing or stale (the message says which
    task to run first). Destructive tasks need ``confirm``."""
    return _accepted(response, services.start_task(host_id, task_id, body))


class OutputSummary(BaseModel):
    kind: str
    job_id: str
    produced_at: datetime
    fresh: bool = Field(description="False when the OS was reinstalled after this output was produced")


@router.get("/{host_id}/outputs", response_model=list[OutputSummary])
def list_outputs(host_id: str, services: ServicesDep) -> list[OutputSummary]:
    """The latest output of each kind for this host: what later tasks will use as their inputs."""
    return [OutputSummary(**o) for o in services.list_outputs(host_id)]


@router.get("/{host_id}/outputs/{kind}", response_model=dict[str, Any])
def get_output(host_id: str, kind: str, services: ServicesDep) -> dict[str, Any]:
    """The latest output of one kind (e.g. inventory, preflight, os_network, install, readiness,
    vcf_readiness, host_prep, jumbo, holorouter). Each kind has a fixed shape; see GET /tasks."""
    return services.latest_output(host_id, kind)
