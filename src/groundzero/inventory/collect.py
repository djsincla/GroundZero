"""Build a HostInventory from a live BMC. Read-only: GET requests only (plus session login/logout)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from groundzero.core.store import utcnow
from groundzero.inventory.models import (
    BiosSettings,
    BmcInfo,
    Drive,
    HostInventory,
    MemoryInfo,
    NetworkPort,
    Processor,
    SystemInfo,
)
from groundzero.redfish.capabilities import discover_capabilities
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import BmcIdentity, detect
from groundzero.redfish.errors import RedfishError
from groundzero.redfish.oem import VendorProfile, profile_for

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]
_BOOT_CONTROLLER_MARKERS = ("BOSS", "M.2", "SD MODULE", "IDSDM", "NS204")


def _link(resource: dict[str, Any], key: str) -> str | None:
    value = resource.get(key)
    return value.get("@odata.id") if isinstance(value, dict) else None


def _absent(resource: dict[str, Any]) -> bool:
    return str(resource.get("Status", {}).get("State", "")).lower() == "absent"


async def _optional_members(client: RedfishClient, path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    try:
        return await client.get_members(path)
    except RedfishError as exc:
        logger.info("Skipping %s: %s", path, exc)
        return []


async def _optional_json(client: RedfishClient, path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        return await client.get_json(path)
    except RedfishError as exc:
        logger.info("Skipping %s: %s", path, exc)
        return {}


def parse_processor(raw: dict[str, Any]) -> Processor:
    return Processor(
        socket=raw.get("Socket"),
        manufacturer=raw.get("Manufacturer"),
        model=str(raw.get("Model") or raw.get("Name") or "Unknown"),
        cores=int(raw.get("TotalCores") or 0),
        threads=int(raw.get("TotalThreads") or 0),
        max_speed_mhz=raw.get("MaxSpeedMHz"),
    )


def parse_drive(raw: dict[str, Any], controller: str | None) -> Drive:
    controller_upper = (controller or "").upper()
    return Drive(
        id=str(raw.get("Id") or raw.get("@odata.id")),
        name=raw.get("Name"),
        model=raw.get("Model"),
        media_type=raw.get("MediaType"),
        protocol=raw.get("Protocol"),
        capacity_bytes=int(raw.get("CapacityBytes") or 0),
        controller=controller,
        is_boot_device=any(m in controller_upper for m in _BOOT_CONTROLLER_MARKERS),
    )


def _controller_name(storage: dict[str, Any]) -> str | None:
    controllers = storage.get("StorageControllers") or []
    if controllers and isinstance(controllers[0], dict):
        name = controllers[0].get("Model") or controllers[0].get("Name")
        if name:
            return str(name)
    return storage.get("Name") or storage.get("Id")


async def _drives(client: RedfishClient, system: dict[str, Any]) -> list[Drive]:
    drives: list[Drive] = []
    for storage in await _optional_members(client, _link(system, "Storage")):
        controller = _controller_name(storage)
        links = [d["@odata.id"] for d in storage.get("Drives", []) if "@odata.id" in d]
        raws = await asyncio.gather(*(client.get_json(p) for p in links))
        drives.extend(parse_drive(raw, controller) for raw in raws if not _absent(raw))
    return drives


def parse_port(raw: dict[str, Any]) -> NetworkPort:
    return NetworkPort(
        id=str(raw.get("Id") or raw.get("@odata.id")),
        name=raw.get("Name"),
        mac_address=raw.get("MACAddress") or raw.get("PermanentMACAddress"),
        link_status=raw.get("LinkStatus"),
        speed_mbps=raw.get("SpeedMbps"),
    )


def parse_bios(raw: dict[str, Any], profile: VendorProfile, system: dict[str, Any]) -> BiosSettings:
    attributes = {
        k: v for k, v in raw.get("Attributes", {}).items() if isinstance(v, str | int | float | bool)
    }
    boot_mode = profile.boot_mode(attributes) or system.get("Boot", {}).get("BootSourceOverrideMode")
    return BiosSettings(
        boot_mode=boot_mode,
        cpu_virtualization=profile.cpu_virtualization(attributes),
        iommu=profile.iommu(attributes),
        attributes=attributes,
    )


async def collect_inventory(
    client: RedfishClient, progress: ProgressFn | None = None
) -> tuple[BmcIdentity, HostInventory]:
    def report(fraction: float, message: str) -> None:
        if progress:
            progress(fraction, message)

    report(0.05, "Detecting BMC")
    identity = await detect(client)
    profile = profile_for(identity.vendor)
    system = await client.get_json(identity.system_path)
    manager = await _optional_json(client, identity.manager_path) or None

    report(0.2, "Reading processors and memory")
    processors = [
        parse_processor(p)
        for p in await _optional_members(client, _link(system, "Processors"))
        if str(p.get("ProcessorType", "CPU")).upper() == "CPU" and not _absent(p)
    ]
    dimms = await _optional_json(client, _link(system, "Memory"))
    memory = MemoryInfo(
        total_gib=float(system.get("MemorySummary", {}).get("TotalSystemMemoryGiB") or 0),
        dimm_count=int(dimms.get("Members@odata.count") or len(dimms.get("Members", []))),
    )

    report(0.4, "Reading storage")
    drives = await _drives(client, system)

    report(0.6, "Reading network interfaces")
    ports = [parse_port(p) for p in await _optional_members(client, _link(system, "EthernetInterfaces"))]

    report(0.7, "Reading BIOS settings")
    bios_raw = await _optional_json(client, _link(system, "Bios"))
    bios = parse_bios(bios_raw, profile, system)

    # The BMC's own name (cluster mode builds server names from it)
    bmc_nics = await _optional_members(client, _link(manager or {}, "EthernetInterfaces")) if manager else []
    bmc_nic = next((n for n in bmc_nics if n.get("HostName")), {})

    report(0.85, "Reading BMC capabilities and license")
    capabilities = await discover_capabilities(client, system, manager)
    license_info = await profile.license(client, identity)

    inventory = HostInventory(
        collected_at=utcnow(),
        system=SystemInfo(
            manufacturer=identity.manufacturer,
            model=identity.model,
            serial_number=system.get("SerialNumber"),
            bios_version=system.get("BiosVersion"),
            power_state=system.get("PowerState"),
            health=system.get("Status", {}).get("HealthRollup") or system.get("Status", {}).get("Health"),
        ),
        processors=processors,
        memory=memory,
        drives=drives,
        network_ports=ports,
        bios=bios,
        bmc=BmcInfo(
            vendor=identity.vendor.value,
            hostname=bmc_nic.get("HostName") or None,
            fqdn=bmc_nic.get("FQDN") or None,
            firmware_version=(manager or {}).get("FirmwareVersion"),
            redfish_version=identity.redfish_version,
            license=license_info,
        ),
        capabilities=capabilities,
    )
    report(0.95, "Inventory collected")
    return identity, inventory
