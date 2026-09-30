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


class MemoryInfo(BaseModel):
    total_gib: float
    dimm_count: int = 0


class Drive(BaseModel):
    id: str
    name: str | None = None
    model: str | None = None
    media_type: str | None = Field(default=None, description="SSD or HDD")
    protocol: str | None = Field(default=None, description="NVMe, SAS, SATA, ...")
    capacity_bytes: int = 0
    controller: str | None = None
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


class BiosSettings(BaseModel):
    boot_mode: str | None = None
    cpu_virtualization: bool | None = None
    iommu: bool | None = None
    attributes: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class BmcInfo(BaseModel):
    vendor: str
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
    capabilities: BmcCapabilities

    @property
    def total_cores(self) -> int:
        return sum(p.cores for p in self.processors)

    @property
    def total_threads(self) -> int:
        return sum(p.threads for p in self.processors)
