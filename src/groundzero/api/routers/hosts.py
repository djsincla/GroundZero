"""/api/v1/hosts — BMC targets and the jobs/results attached to them."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from groundzero.api.deps import ServicesDep
from groundzero.core.models import Host, HostCreate, Job, JobKind, OsAccess, OsAccessSet
from groundzero.esxi.models import EsxiNetworkConfig
from groundzero.inventory.models import HostInventory
from groundzero.preflight.evaluate import PreflightReport

router = APIRouter(prefix="/hosts", tags=["hosts"])


class PreflightRequest(BaseModel):
    profile: str = Field(default="holodeck-9", description="Requirements profile id (see GET /profiles)")
    variant: str | None = Field(
        default=None, description="Profile variant; defaults to the profile's default"
    )


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


@router.post("/{host_id}/inventory", status_code=status.HTTP_202_ACCEPTED, response_model=Job)
async def start_inventory(host_id: str, services: ServicesDep, response: Response) -> Job:
    return _accepted(response, services.start_inventory(host_id))


@router.get("/{host_id}/inventory", response_model=HostInventory)
def latest_inventory(host_id: str, services: ServicesDep) -> HostInventory:
    return HostInventory.model_validate(services.latest_result(host_id, JobKind.INVENTORY))


@router.post("/{host_id}/preflight", status_code=status.HTTP_202_ACCEPTED, response_model=Job)
async def start_preflight(
    host_id: str, services: ServicesDep, response: Response, body: PreflightRequest | None = None
) -> Job:
    body = body or PreflightRequest()
    return _accepted(response, services.start_preflight(host_id, body.profile, body.variant))


@router.get("/{host_id}/preflight", response_model=PreflightReport)
def latest_preflight(host_id: str, services: ServicesDep) -> PreflightReport:
    return PreflightReport.model_validate(services.latest_result(host_id, JobKind.PREFLIGHT))


@router.put("/{host_id}/os", response_model=OsAccess)
def set_os_access(host_id: str, body: OsAccessSet, services: ServicesDep) -> OsAccess:
    """Record how to reach the OS currently installed on the host (e.g. ESXi management IP)."""
    return services.set_os_access(host_id, body)


@router.get("/{host_id}/os", response_model=OsAccess)
def get_os_access(host_id: str, services: ServicesDep) -> OsAccess:
    return services.get_os_access(host_id)


@router.post("/{host_id}/os/network", status_code=status.HTTP_202_ACCEPTED, response_model=Job)
async def start_os_network(host_id: str, services: ServicesDep, response: Response) -> Job:
    """Read the installed hypervisor's network configuration (read-only)."""
    return _accepted(response, services.start_os_network(host_id))


@router.get("/{host_id}/os/network", response_model=EsxiNetworkConfig)
def latest_os_network(host_id: str, services: ServicesDep) -> EsxiNetworkConfig:
    return EsxiNetworkConfig.model_validate(services.latest_result(host_id, JobKind.OS_NETWORK))
