"""Vendor profiles: the place for per-OEM knowledge (attribute names, OEM endpoints, quirks)."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import BmcIdentity, Vendor

_TRUTHY = frozenset({"ENABLED", "ENABLE", "ON", "TRUE", "YES", "AUTO"})
_FALSY = frozenset({"DISABLED", "DISABLE", "OFF", "FALSE", "NO"})


class LicenseInfo(BaseModel):
    name: str
    tier: str  # e.g. "enterprise", "datacenter", "express", "basic", "unknown"
    supports_virtual_media: bool | None


def bios_flag(attributes: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    """Return the first recognisable on/off value among ``keys``, or None if none is present."""
    for key in keys:
        if key not in attributes:
            continue
        value = attributes[key]
        if isinstance(value, bool):
            return value
        text = str(value).strip().upper()
        if text in _TRUTHY:
            return True
        if text in _FALSY:
            return False
    return None


class VendorProfile:
    vendor: ClassVar[Vendor] = Vendor.GENERIC
    # BIOS attribute names seen across OEMs (collected from the legacy per-vendor baselines).
    cpu_virtualization_keys: ClassVar[tuple[str, ...]] = (
        "ProcVirtualization",
        "IntelVirtualizationTechnology",
        "Processors_IntelVirtualizationTechnology",
        "IntelVT",
        "SvmMode",
        "AmdVirtualization",
    )
    iommu_keys: ClassVar[tuple[str, ...]] = (
        "VtdSupport",
        "IntelVTD",
        "IntelVtd",
        "IntelVTForDirectedIO",
        "IntelVTforDirectedIOVTd",
        "Processors_IntelVTforDirectedIOVTd",
        "IntelProcVtd",
        "ProcAmdIoVt",
        "Iommu",
    )
    boot_mode_keys: ClassVar[tuple[str, ...]] = ("BootMode", "BootModeSelect", "BootModeOptimized")

    def cpu_virtualization(self, attributes: dict[str, Any]) -> bool | None:
        return bios_flag(attributes, self.cpu_virtualization_keys)

    def iommu(self, attributes: dict[str, Any]) -> bool | None:
        return bios_flag(attributes, self.iommu_keys)

    def boot_mode(self, attributes: dict[str, Any]) -> str | None:
        for key in self.boot_mode_keys:
            if attributes.get(key):
                return str(attributes[key])
        return None

    async def license(self, client: RedfishClient, identity: BmcIdentity) -> LicenseInfo | None:
        """BMC license tier, if the vendor gates features (like virtual media) behind one."""
        return None
