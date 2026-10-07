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
    FirmwareItem,
    HostInventory,
    MemoryInfo,
    MemoryModule,
    NetworkAdapter,
    NetworkPort,
    PcieDevice,
    PowerSupply,
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
        firmware_version=raw.get("Revision"),
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
        registry_id=raw.get("AttributeRegistry"),
    )


def _health(raw: dict[str, Any]) -> str | None:
    status = raw.get("Status") or {}
    return status.get("HealthRollup") or status.get("Health")


def parse_dimm(raw: dict[str, Any]) -> MemoryModule:
    return MemoryModule(
        id=raw.get("Id", raw.get("@odata.id", "").rsplit("/", 1)[-1]),
        slot=raw.get("DeviceLocator") or (raw.get("MemoryLocation") or {}).get("Slot"),
        capacity_mib=int(raw.get("CapacityMiB") or 0),
        type=raw.get("MemoryDeviceType"),
        speed_mhz=raw.get("OperatingSpeedMhz"),
        manufacturer=(raw.get("Manufacturer") or "").strip() or None,
        part_number=(raw.get("PartNumber") or "").strip() or None,
        health=_health(raw),
    )


def parse_adapter(raw: dict[str, Any]) -> NetworkAdapter:
    controller = (raw.get("Controllers") or [{}])[0]
    ports = (controller.get("ControllerCapabilities") or {}).get("NetworkPortCount")
    if ports is None:
        links = controller.get("Links") or {}
        ports = len(links.get("Ports") or links.get("NetworkPorts") or [])
    return NetworkAdapter(
        id=raw.get("Id", ""),
        name=raw.get("Model") or raw.get("Name"),
        manufacturer=raw.get("Manufacturer"),
        model=raw.get("Model"),
        part_number=raw.get("PartNumber") or None,
        firmware_version=controller.get("FirmwarePackageVersion") or None,
        ports=int(ports or 0),
        health=_health(raw),
    )


_PCIE_CLASSES = (
    (
        "storage",
        ("RAID", "SATA", "SAS", "NVME", "SSD", "BOSS", "PERC", "HBA", "STORAGE", "FIBRE", "EXPRESS FLASH"),
    ),
    ("network", ("ETHERNET", "NETWORK", "NIC", "CONNECTX", "QLOGIC", "MELLANOX")),
    ("accelerator", ("GPU", "NVIDIA", "TESLA", "ACCELERATOR", "FPGA")),
    ("display", ("GRAPHICS", "VGA", "MATROX")),
)


def pcie_class(name: str) -> str:
    """storage, network, accelerator, display or chipset, from the device's name (Dell reports no class)."""
    upper = name.upper()
    return next((kind for kind, words in _PCIE_CLASSES if any(w in upper for w in words)), "chipset")


def parse_pcie(raw: dict[str, Any]) -> PcieDevice:
    slot = ((raw.get("Slot") or {}).get("Location") or {}).get("PartLocation") or {}
    return PcieDevice(
        id=raw.get("Id", ""),
        name=raw.get("Name"),
        manufacturer=raw.get("Manufacturer"),
        model=raw.get("Model") or raw.get("Name"),
        device_class=pcie_class(raw.get("Name") or raw.get("Model") or ""),
        firmware_version=raw.get("FirmwareVersion") or None,
        slot=slot.get("ServiceLabel") or None,
        health=_health(raw),
    )


def parse_psu(raw: dict[str, Any]) -> PowerSupply:
    return PowerSupply(
        name=raw.get("Name") or raw.get("MemberId") or "Power supply",
        model=raw.get("Model"),
        manufacturer=raw.get("Manufacturer"),
        capacity_watts=raw.get("PowerCapacityWatts"),
        firmware_version=raw.get("FirmwareVersion") or None,
        health=_health(raw),
    )


async def _firmware(client: RedfishClient) -> list[FirmwareItem]:
    """Every firmware the BMC lists as installed (Dell also lists previous and available versions)."""
    service = await _optional_json(client, "/redfish/v1/UpdateService")
    items = await _optional_members(client, _link(service, "FirmwareInventory"))
    installed = [i for i in items if str(i.get("Id", "")).startswith("Installed")]
    return [
        FirmwareItem(
            id=i.get("Id", ""),
            name=i.get("Name") or i.get("Id", ""),
            version=i.get("Version"),
            updateable=i.get("Updateable"),
            health=_health(i),
        )
        for i in (installed or items)
    ]


async def _pcie_devices(
    client: RedfishClient, system: dict[str, Any], chassis: dict[str, Any]
) -> list[dict[str, Any]]:
    """PCIe devices: a list of links on the system (older schema) or a collection on the chassis."""
    listed = system.get("PCIeDevices")
    if isinstance(listed, list) and listed:
        paths = [d["@odata.id"] for d in listed if "@odata.id" in d]
        results = await asyncio.gather(*(client.get_json(p) for p in paths), return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]
    return await _optional_members(client, _link(chassis, "PCIeDevices") or _link(system, "PCIeDevices"))


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
    modules = [
        parse_dimm(m) for m in await _optional_members(client, _link(system, "Memory")) if not _absent(m)
    ]
    memory = MemoryInfo(
        total_gib=float(system.get("MemorySummary", {}).get("TotalSystemMemoryGiB") or 0),
        dimm_count=int(dimms.get("Members@odata.count") or len(dimms.get("Members", []))),
        modules=modules,
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

    report(0.78, "Reading firmware, adapters, PCIe devices and power supplies")
    chassis = await _optional_json(client, identity.chassis_path)
    firmware = await _firmware(client)
    adapters = [parse_adapter(a) for a in await _optional_members(client, _link(chassis, "NetworkAdapters"))]
    pcie = [parse_pcie(d) for d in await _pcie_devices(client, system, chassis) if not _absent(d)]
    power = await _optional_json(client, _link(chassis, "Power"))
    supplies = [parse_psu(p) for p in power.get("PowerSupplies") or [] if not _absent(p)]

    report(0.85, "Reading BMC capabilities and license")
    capabilities = await discover_capabilities(client, system, manager)
    license_info = await profile.license(client, identity)

    inventory = HostInventory(
        collected_at=utcnow(),
        system=SystemInfo(
            manufacturer=identity.manufacturer,
            model=identity.model,
            serial_number=system.get("SerialNumber"),
            service_tag=system.get("SKU") or None,
            asset_tag=system.get("AssetTag") or None,
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
        firmware=firmware,
        network_adapters=adapters,
        pcie_devices=pcie,
        power_supplies=supplies,
    )
    report(0.95, "Inventory collected")
    return identity, inventory
