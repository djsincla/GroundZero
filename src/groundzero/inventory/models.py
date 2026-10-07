"""Typed hardware inventory. Pure data: no verdicts, no presentation."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from groundzero.redfish.capabilities import BmcCapabilities
from groundzero.redfish.oem import LicenseInfo


class SystemInfo(BaseModel):
    manufacturer: str
    model: str
    serial_number: str | None = None
    service_tag: str | None = Field(default=None, description="Dell service tag (the system SKU)")
    asset_tag: str | None = None
    bios_version: str | None = None
    power_state: str | None = None
    health: str | None = None


class Processor(BaseModel):
    socket: str | None = None
    manufacturer: str | None = None
    model: str
    cores: int = 0
    threads: int = 0
    max_speed_mhz: int | None = None


class MemoryModule(BaseModel):
    id: str
    slot: str | None = None
    capacity_mib: int = 0
    type: str | None = Field(default=None, description="e.g. DDR4")
    speed_mhz: int | None = None
    manufacturer: str | None = None
    part_number: str | None = None
    health: str | None = None


class MemoryInfo(BaseModel):
    total_gib: float
    dimm_count: int = 0
    modules: list[MemoryModule] = Field(default_factory=list)


class Drive(BaseModel):
    id: str
    name: str | None = None
    model: str | None = None
    media_type: str | None = Field(default=None, description="SSD or HDD")
    protocol: str | None = Field(default=None, description="NVMe, SAS, SATA, ...")
    capacity_bytes: int = 0
    controller: str | None = None
    firmware_version: str | None = Field(default=None, description="The drive's firmware revision")
    is_boot_device: bool = Field(default=False, description="Dedicated boot device such as a Dell BOSS card")

    @property
    def is_flash(self) -> bool:
        return (self.media_type or "").upper() == "SSD" or (self.protocol or "").upper() == "NVME"


class NetworkPort(BaseModel):
    id: str
    name: str | None = None
    mac_address: str | None = None
    link_status: str | None = None
    speed_mbps: int | None = None

    @property
    def link_up(self) -> bool:
        return (self.link_status or "").lower() in ("linkup", "up")


class FirmwareItem(BaseModel):
    id: str
    name: str
    version: str | None = None
    updateable: bool | None = None
    health: str | None = None


class NetworkAdapter(BaseModel):
    id: str
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    part_number: str | None = None
    firmware_version: str | None = None
    ports: int = 0
    health: str | None = None


class PcieDevice(BaseModel):
    id: str
    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    device_class: str | None = Field(
        default=None, description="e.g. MassStorageController, NetworkController"
    )
    firmware_version: str | None = None
    slot: str | None = None
    health: str | None = None


class PowerSupply(BaseModel):
    name: str
    model: str | None = None
    manufacturer: str | None = None
    capacity_watts: float | None = None
    firmware_version: str | None = None
    health: str | None = None


class BiosSettings(BaseModel):
    boot_mode: str | None = None
    cpu_virtualization: bool | None = None
    iommu: bool | None = None
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    registry_id: str | None = Field(default=None, description="The attribute registry the BIOS names")


class BmcInfo(BaseModel):
    vendor: str
    hostname: str | None = Field(default=None, description="The BMC's own DNS name, e.g. idrac-esx01")
    fqdn: str | None = None
    firmware_version: str | None = None
    redfish_version: str | None = None
    license: LicenseInfo | None = None


class HostInventory(BaseModel):
    collected_at: datetime
    system: SystemInfo
    processors: list[Processor]
    memory: MemoryInfo
    drives: list[Drive]
    network_ports: list[NetworkPort]
    bios: BiosSettings
    bmc: BmcInfo
    firmware: list[FirmwareItem] = Field(
        default_factory=list, description="Every installed firmware the BMC lists"
    )
    network_adapters: list[NetworkAdapter] = Field(default_factory=list)
    pcie_devices: list[PcieDevice] = Field(default_factory=list)
    power_supplies: list[PowerSupply] = Field(default_factory=list)
    capabilities: BmcCapabilities

    @property
    def total_cores(self) -> int:
        return sum(p.cores for p in self.processors)

    @property
    def total_threads(self) -> int:
        return sum(p.threads for p in self.processors)
