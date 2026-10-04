"""Read a server's storage layout over Redfish: controllers, drives, volumes, spares (read-only).

Standard Redfish first (Storage, StorageControllers, Volumes, Drives), Dell OEM where the standard has
no answer (controller mode, a drive's RAID state, the RAID service's actions). Vendors differ: anything
not reported stays None rather than guessed, and the diagnostics bundle keeps every raw response.

NVMe drives behind a PCIe extender show up as one "RawDevice" volume each: that is pass-through, not
RAID, so such volumes are marked ``raw`` and never treated as something to configure.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from groundzero.redfish.client import RedfishClient
from groundzero.redfish.errors import RedfishError

ControllerKind = Literal["raid", "boot", "passthrough", "software", "other"]


class StorageDrive(BaseModel):
    id: str
    path: str
    name: str | None = None
    model: str | None = None
    media: str | None = Field(default=None, description="SSD or HDD")
    protocol: str | None = Field(default=None, description="SATA, SAS, NVMe, PCIe")
    capacity_gb: float = 0
    state: str | None = Field(
        default=None, description="Dell RaidStatus: Online, Ready, NonRAID, ... (None: unknown)"
    )
    hotspare: str | None = Field(default=None, description="None, Global or Dedicated")
    volumes: list[str] = Field(default_factory=list, description="Volume ids this drive belongs to")
    health: str | None = None


class StorageVolume(BaseModel):
    id: str
    path: str
    name: str | None = None
    raid: str | None = Field(default=None, description="RAID0, RAID1, RAID5, ... (None for raw devices)")
    volume_type: str | None = None
    capacity_gb: float = 0
    drives: list[str] = Field(default_factory=list)
    raw: bool = Field(default=False, description="Pass-through device (e.g. NVMe), not a RAID volume")
    boot: bool | None = Field(default=None, description="The controller's boot volume (None: not reported)")


class StorageController(BaseModel):
    id: str
    path: str
    name: str | None = None
    model: str | None = None
    kind: ControllerKind
    mode: str | None = Field(
        default=None, description="RAID, HBA, EnhancedHBA, NotSupported (Dell); None: unknown"
    )
    mode_settable: bool = Field(
        default=False, description="Mode can be changed over Redfish on this firmware"
    )
    supported_raid: list[str] = Field(default_factory=list)
    volume_apply_times: list[str] = Field(default_factory=list, description="Immediate and/or OnReset")
    drives: list[StorageDrive] = Field(default_factory=list)
    volumes: list[StorageVolume] = Field(default_factory=list)

    @property
    def raid_volumes(self) -> list[StorageVolume]:
        return [v for v in self.volumes if not v.raw]


class StorageLayout(BaseModel):
    controllers: list[StorageController] = Field(default_factory=list)
    raid_service_actions: list[str] = Field(
        default_factory=list, description="Dell DellRaidService actions available"
    )

    def controller(self, controller_id: str) -> StorageController | None:
        return next((c for c in self.controllers if c.id == controller_id), None)


def _kind(model: str, supported_raid: list[str], drives: list[StorageDrive]) -> ControllerKind:
    text = model.upper()
    if "BOSS" in text or "M.2" in text:
        return "boot"
    if "PERC S" in text or "SOFTWARE" in text:  # host-based RAID (e.g. PERC S140)
        return "software"
    if not supported_raid and (
        "EXTENDER" in text or "NVME" in text or all(d.protocol in ("NVMe", "PCIe") for d in drives)
    ):
        return "passthrough"
    return "raid" if supported_raid else "other"


async def _members(client: RedfishClient, path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        return await client.get_members(path)
    except RedfishError:
        return []


def _drive(raw: dict[str, Any]) -> StorageDrive:
    dell = raw.get("Oem", {}).get("Dell", {}).get("DellPhysicalDisk", {}) or {}
    return StorageDrive(
        id=raw.get("Id", raw["@odata.id"].rsplit("/", 1)[-1]),
        path=raw["@odata.id"],
        name=raw.get("Name"),
        model=(raw.get("Model") or "").strip() or None,
        media=raw.get("MediaType"),
        protocol=raw.get("Protocol"),
        capacity_gb=round((raw.get("CapacityBytes") or 0) / 1e9, 1),
        state=dell.get("RaidStatus"),
        hotspare=raw.get("HotspareType") if raw.get("HotspareType") not in (None, "None") else None,
        health=(raw.get("Status") or {}).get("Health"),
    )


def _volume(raw: dict[str, Any]) -> StorageVolume:
    dell = raw.get("Oem", {}).get("Dell", {})
    dell_vd = dell.get("DellVolume") or dell.get("DellVirtualDisk") or {}
    boot = dell_vd.get("BootVolumeSource") or dell_vd.get("BootVolume")
    volume_type = raw.get("VolumeType")
    return StorageVolume(
        id=raw.get("Id", raw["@odata.id"].rsplit("/", 1)[-1]),
        path=raw["@odata.id"],
        name=raw.get("Name"),
        raid=raw.get("RAIDType"),
        volume_type=volume_type,
        capacity_gb=round((raw.get("CapacityBytes") or 0) / 1e9, 1),
        drives=[
            d["@odata.id"].rsplit("/", 1)[-1]
            for d in raw.get("Links", {}).get("Drives", [])
            if "@odata.id" in d
        ],
        raw=volume_type == "RawDevice"
        or (raw.get("RAIDType") is None and volume_type in (None, "RawDevice")),
        boot=None if boot is None else str(boot).lower() in ("true", "yes", "primary"),
    )


async def read_storage_layout(client: RedfishClient, system_path: str, *, dell: bool = True) -> StorageLayout:
    system = await client.get_json(system_path)
    storage_path = (system.get("Storage") or {}).get("@odata.id")
    controllers: list[StorageController] = []
    for storage in await _members(client, storage_path):
        sc = (storage.get("StorageControllers") or [{}])[0]
        model = sc.get("Model") or sc.get("Name") or storage.get("Name") or storage.get("Id", "")
        supported = [str(r) for r in sc.get("SupportedRAIDTypes") or []]
        drives = [
            _drive(d) for d in await _gather(client, [x["@odata.id"] for x in storage.get("Drives", [])])
        ]
        volumes_path = (storage.get("Volumes") or {}).get("@odata.id")
        apply_times: list[str] = []
        volumes: list[StorageVolume] = []
        if volumes_path:
            try:
                collection = await client.get_json(volumes_path)
                apply_times = list(
                    (collection.get("@Redfish.OperationApplyTimeSupport") or {}).get("SupportedValues", [])
                )
                volumes = [
                    _volume(v)
                    for v in await _gather(client, [m["@odata.id"] for m in collection.get("Members", [])])
                ]
            except RedfishError:
                pass
        for volume in volumes:
            for drive in drives:
                if drive.id in volume.drives:
                    drive.volumes.append(volume.id)
        dell_ctrl = storage.get("Oem", {}).get("Dell", {}).get("DellController", {}) or {}
        mode = dell_ctrl.get("CurrentControllerMode")
        controllers.append(
            StorageController(
                id=storage.get("Id", ""),
                path=storage["@odata.id"],
                name=storage.get("Name"),
                model=model,
                kind=_kind(model, supported, drives),
                mode=mode,
                mode_settable="@Redfish.Settings" in storage and mode not in (None, "NotSupported"),
                supported_raid=supported,
                volume_apply_times=apply_times,
                drives=drives,
                volumes=volumes,
            )
        )
    actions: list[str] = []
    if dell:
        try:
            service = await client.get_json(f"{system_path}/Oem/Dell/DellRaidService")
            actions = sorted({a.lstrip("#").rsplit(".", 1)[-1] for a in service.get("Actions", {})})
        except RedfishError:
            actions = []
    return StorageLayout(controllers=controllers, raid_service_actions=actions)


async def _gather(client: RedfishClient, paths: list[str]) -> list[dict[str, Any]]:
    import asyncio

    results = await asyncio.gather(*(client.get_json(p) for p in paths), return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]
