"""/api/v1/bios-profiles and BIOS registries: saved BIOS settings, checked against what the BIOS accepts."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from groundzero.api.deps import ServicesDep
from groundzero.redfish.bios_profiles import (
    BiosCapture,
    BiosImport,
    BiosPlan,
    BiosProfile,
    BiosProfileWrite,
    RegistryInfo,
)

router = APIRouter(tags=["bios"])


class RegistrySummary(BaseModel):
    key: str
    model: str | None
    fetched_at: str


@router.get("/bios-profiles", response_model=list[BiosProfile])
def list_bios_profiles(services: ServicesDep) -> list[BiosProfile]:
    return services.list_bios_profiles()


@router.post("/bios-profiles", status_code=status.HTTP_201_CREATED, response_model=BiosProfile)
def create_bios_profile(body: BiosProfileWrite, services: ServicesDep, response: Response) -> BiosProfile:
    """Every value is checked against the registry: allowed values, bounds, read-only. No passwords."""
    profile = services.save_bios_profile(body)
    response.headers["Location"] = f"/api/v1/bios-profiles/{profile.id}"
    return profile


@router.post("/bios-profiles/import", status_code=status.HTTP_201_CREATED, response_model=BiosProfile)
def import_bios_profile(body: BiosImport, services: ServicesDep, response: Response) -> BiosProfile:
    """From a file: {attribute: value}, {"Attributes": {...}}, or a Dell Server Configuration Profile JSON.
    Settings the BIOS won't take (read-only, passwords) are left out."""
    profile = services.import_bios_profile(body)
    response.headers["Location"] = f"/api/v1/bios-profiles/{profile.id}"
    return profile


@router.get("/bios-profiles/{profile_id}", response_model=BiosProfile)
def get_bios_profile(profile_id: str, services: ServicesDep) -> BiosProfile:
    return services.get_bios_profile(profile_id)


@router.put("/bios-profiles/{profile_id}", response_model=BiosProfile)
def update_bios_profile(profile_id: str, body: BiosProfileWrite, services: ServicesDep) -> BiosProfile:
    return services.save_bios_profile(body, profile_id)


@router.delete("/bios-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bios_profile(profile_id: str, services: ServicesDep) -> None:
    """Refused while a spec's Configure BIOS step uses it."""
    services.delete_bios_profile(profile_id)


@router.post(
    "/hosts/{host_id}/bios-profiles/capture", status_code=status.HTTP_201_CREATED, response_model=BiosProfile
)
async def capture_bios_profile(
    host_id: str, body: BiosCapture, services: ServicesDep, response: Response
) -> BiosProfile:
    """A profile from the server's current BIOS settings (its latest inventory). Reads the registry from the
    BMC if it isn't cached yet (read-only)."""
    profile = await services.capture_bios_profile(host_id, body)
    response.headers["Location"] = f"/api/v1/bios-profiles/{profile.id}"
    return profile


@router.get("/hosts/{host_id}/bios-plan", response_model=BiosPlan)
def bios_plan(host_id: str, services: ServicesDep, profile_id: str | None = None) -> BiosPlan:
    """What Configure BIOS would write now, with or without a profile (from the inventory; no BMC calls)."""
    return services.bios_plan(host_id, profile_id)


@router.get("/hosts/{host_id}/bios-registry", response_model=RegistryInfo)
async def host_bios_registry(host_id: str, services: ServicesDep, refresh: bool = False) -> RegistryInfo:
    """The settable BIOS attributes of this server, in setup order. Cached per model and BIOS version;
    read from the BMC (read-only) the first time or with ``refresh``."""
    return await services.bios_registry_for_host(host_id, refresh=refresh)


@router.get("/bios-registries", response_model=list[RegistrySummary])
def list_bios_registries(services: ServicesDep) -> list[RegistrySummary]:
    return [
        RegistrySummary(key=k, model=m, fetched_at=f) for k, m, f in services.store.list_bios_registries()
    ]


@router.get("/bios-registries/{key:path}", response_model=RegistryInfo)
def get_bios_registry(key: str, services: ServicesDep) -> RegistryInfo:
    return services.bios_registry(key)
