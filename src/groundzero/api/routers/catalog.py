"""OS families, config sets and the image repository (ISOs and OVAs)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from groundzero.api.deps import ServicesDep
from groundzero.core.models import ConfigSet, ConfigSetWrite
from groundzero.core.services import ImageDescriptor, OsFamily
from groundzero.isos import Image

router = APIRouter(tags=["catalog"])


@router.get("/os-families", response_model=list[OsFamily])
def list_os_families(services: ServicesDep) -> list[OsFamily]:
    """OS families with the JSON schemas the UI renders config-set and per-server forms from."""
    return services.list_os_families()


@router.get("/config-sets", response_model=list[ConfigSet])
def list_config_sets(services: ServicesDep) -> list[ConfigSet]:
    return services.list_config_sets()


@router.post("/config-sets", status_code=status.HTTP_201_CREATED, response_model=ConfigSet)
def create_config_set(body: ConfigSetWrite, services: ServicesDep, response: Response) -> ConfigSet:
    config_set = services.create_config_set(body)
    response.headers["Location"] = f"/api/v1/config-sets/{config_set.id}"
    return config_set


@router.get("/config-sets/{set_id}", response_model=ConfigSet)
def get_config_set(set_id: str, services: ServicesDep) -> ConfigSet:
    return services.get_config_set(set_id)


@router.put("/config-sets/{set_id}", response_model=ConfigSet)
def update_config_set(set_id: str, body: ConfigSetWrite, services: ServicesDep) -> ConfigSet:
    """Replace a config set. Omit root_password to keep the stored one."""
    return services.update_config_set(set_id, body)


@router.delete("/config-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config_set(set_id: str, services: ServicesDep) -> None:
    services.delete_config_set(set_id)


@router.get("/images", response_model=list[Image])
def list_images(services: ServicesDep) -> list[Image]:
    """Stock installer ISOs and appliance OVAs found in the repository folder (you add/remove files there)."""
    return services.list_images()


@router.post("/images/rescan", response_model=list[Image])
async def rescan_images(services: ServicesDep) -> list[Image]:
    return await services.rescan_images()


@router.get("/images/{image_id}/descriptor", response_model=ImageDescriptor)
async def image_descriptor(image_id: str, services: ServicesDep) -> ImageDescriptor:
    """An OVA's descriptor: product, networks, size, and every input (OVF property) it takes, plus a
    JSON Schema of the inputs a person sets."""
    return await services.image_descriptor(image_id)
