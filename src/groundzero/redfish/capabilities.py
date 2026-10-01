"""Discover what the BMC can *do* — the actions an unattended OS install depends on.

Read-only: this module inspects resource ``Actions`` and allowable values, it never invokes them.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from groundzero.redfish.client import RedfishClient
from groundzero.redfish.errors import RedfishError

logger = logging.getLogger(__name__)


class ResetCapability(BaseModel):
    target: str | None
    allowed_types: list[str] = Field(default_factory=list)


class BootOption(BaseModel):
    id: str
    name: str | None = None
    uefi_device_path: str | None = None

    @property
    def is_virtual_optical(self) -> bool:
        """BMC virtual media as UEFI sees it ("Virtual Optical Drive" on iDRAC, "Virtual CD/DVD" else)."""
        return bool(re.search(r"virtual\s*(optical|cd|dvd)", self.name or "", re.IGNORECASE))


class BootOverrideCapability(BaseModel):
    options: list[BootOption] = Field(
        default_factory=list, description="UEFI boot options from the last POST"
    )
    allowed_targets: list[str] = Field(default_factory=list)
    allowed_modes: list[str] = Field(default_factory=list)
    current_enabled: str | None = None
    current_target: str | None = None
    current_mode: str | None = None


class VirtualMediaSlot(BaseModel):
    path: str
    name: str | None = None
    media_types: list[str] = Field(default_factory=list)
    transfer_protocols: list[str] = Field(default_factory=list)
    inserted: bool | None = None
    image: str | None = None
    insert_target: str | None = None
    eject_target: str | None = None

    @property
    def is_cd(self) -> bool:
        return any(t.upper() in ("CD", "DVD") for t in self.media_types)


class BmcCapabilities(BaseModel):
    reset: ResetCapability
    boot_override: BootOverrideCapability
    virtual_media: list[VirtualMediaSlot] = Field(default_factory=list)


def _allowable(resource: dict[str, Any], key: str) -> list[str]:
    values = resource.get(f"{key}@Redfish.AllowableValues")
    return [str(v) for v in values] if isinstance(values, list) else []


def _action(resource: dict[str, Any], name: str) -> dict[str, Any]:
    actions = resource.get("Actions", {})
    for key, value in actions.items():
        if key.endswith(name) and isinstance(value, dict):
            return value
    return {}


async def _action_info_allowables(client: RedfishClient, action: dict[str, Any], param: str) -> list[str]:
    info_path = action.get("@Redfish.ActionInfo")
    if not info_path:
        return []
    try:
        info = await client.get_json(info_path)
    except RedfishError:
        return []
    for p in info.get("Parameters", []):
        if p.get("Name") == param and isinstance(p.get("AllowableValues"), list):
            return [str(v) for v in p["AllowableValues"]]
    return []


async def _reset(client: RedfishClient, system: dict[str, Any]) -> ResetCapability:
    action = _action(system, "ComputerSystem.Reset")
    allowed = _allowable(action, "ResetType") or await _action_info_allowables(client, action, "ResetType")
    return ResetCapability(target=action.get("target"), allowed_types=allowed)


async def _boot_options(client: RedfishClient, system: dict[str, Any]) -> list[BootOption]:
    link = system.get("Boot", {}).get("BootOptions", {}).get("@odata.id")
    if not link:
        return []
    try:
        members = await client.get_members(link)
    except RedfishError:
        return []
    return [
        BootOption(id=str(m.get("Id")), name=m.get("DisplayName"), uefi_device_path=m.get("UefiDevicePath"))
        for m in members
    ]


async def _boot_override(client: RedfishClient, system: dict[str, Any]) -> BootOverrideCapability:
    boot = system.get("Boot", {})
    return BootOverrideCapability(
        options=await _boot_options(client, system),
        allowed_targets=_allowable(boot, "BootSourceOverrideTarget"),
        allowed_modes=_allowable(boot, "BootSourceOverrideMode"),
        current_enabled=boot.get("BootSourceOverrideEnabled"),
        current_target=boot.get("BootSourceOverrideTarget"),
        current_mode=boot.get("BootSourceOverrideMode"),
    )


async def _virtual_media_slots(
    client: RedfishClient, resources: list[dict[str, Any]]
) -> list[VirtualMediaSlot]:
    """Collect slots from both Manager and System VirtualMedia (iDRAC moved them between firmware lines)."""
    slots: dict[str, VirtualMediaSlot] = {}
    for resource in resources:
        link = resource.get("VirtualMedia", {}).get("@odata.id")
        if not link:
            continue
        try:
            members = await client.get_members(link)
        except RedfishError as exc:
            logger.debug("VirtualMedia collection %s unavailable: %s", link, exc)
            continue
        for vm in members:
            insert = _action(vm, "VirtualMedia.InsertMedia")
            protocols = _allowable(insert, "TransferProtocolType") or await _action_info_allowables(
                client, insert, "TransferProtocolType"
            )
            if not protocols and vm.get("TransferProtocolType"):
                protocols = [str(vm["TransferProtocolType"])]
            path = str(vm.get("@odata.id", link))
            slots[path] = VirtualMediaSlot(
                path=path,
                name=vm.get("Name"),
                media_types=[str(t) for t in vm.get("MediaTypes", [])],
                transfer_protocols=protocols,
                inserted=vm.get("Inserted"),
                image=vm.get("Image") or None,
                insert_target=insert.get("target"),
                eject_target=_action(vm, "VirtualMedia.EjectMedia").get("target"),
            )
    return list(slots.values())


async def discover_capabilities(
    client: RedfishClient, system: dict[str, Any], manager: dict[str, Any] | None
) -> BmcCapabilities:
    resources = [r for r in (manager, system) if r]
    return BmcCapabilities(
        reset=await _reset(client, system),
        boot_override=await _boot_override(client, system),
        virtual_media=await _virtual_media_slots(client, resources),
    )
