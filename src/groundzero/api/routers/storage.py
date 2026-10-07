"""/api/v1/storage-profiles: RAID volumes, controller mode, drive state and hot spares, as saved rules."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from groundzero.api.deps import ServicesDep
from groundzero.redfish.storage_config import StorageCapture, StoragePlan, StorageProfile, StorageProfileWrite

router = APIRouter(tags=["storage"])


@router.get("/storage-profiles", response_model=list[StorageProfile])
def list_storage_profiles(services: ServicesDep) -> list[StorageProfile]:
    return services.list_storage_profiles()


@router.post("/storage-profiles", status_code=status.HTTP_201_CREATED, response_model=StorageProfile)
def create_storage_profile(
    body: StorageProfileWrite, services: ServicesDep, response: Response
) -> StorageProfile:
    profile = services.save_storage_profile(body)
    response.headers["Location"] = f"/api/v1/storage-profiles/{profile.id}"
    return profile


@router.get("/storage-profiles/{profile_id}", response_model=StorageProfile)
def get_storage_profile(profile_id: str, services: ServicesDep) -> StorageProfile:
    return services.get_storage_profile(profile_id)


@router.put("/storage-profiles/{profile_id}", response_model=StorageProfile)
def update_storage_profile(
    profile_id: str, body: StorageProfileWrite, services: ServicesDep
) -> StorageProfile:
    return services.save_storage_profile(body, profile_id)


@router.delete("/storage-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_storage_profile(profile_id: str, services: ServicesDep) -> None:
    """Refused while a spec's Configure storage step uses it."""
    services.delete_storage_profile(profile_id)


@router.post(
    "/hosts/{host_id}/storage-profiles/capture",
    status_code=status.HTTP_201_CREATED,
    response_model=StorageProfile,
)
def capture_storage_profile(
    host_id: str, body: StorageCapture, services: ServicesDep, response: Response
) -> StorageProfile:
    """A profile describing the server's layout as Read storage last saw it (nothing is read or changed)."""
    profile = services.capture_storage_profile(host_id, body)
    response.headers["Location"] = f"/api/v1/storage-profiles/{profile.id}"
    return profile


@router.get("/hosts/{host_id}/storage-plan", response_model=StoragePlan)
def storage_plan(
    host_id: str, profile_id: str, services: ServicesDep, allow_boot_volume: bool = False
) -> StoragePlan:
    """What Configure storage would change with this profile: each change (and whether it loses data), and
    why it can't go ahead, if it can't. From the last Read storage; nothing is read or changed."""
    return services.storage_plan(host_id, profile_id, allow_boot_volume)
