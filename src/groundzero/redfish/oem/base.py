"""Vendor profiles: the place for per-OEM knowledge (attribute names, OEM endpoints, quirks)."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from groundzero.redfish.capabilities import BmcCapabilities, VirtualMediaSlot
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import BmcIdentity, Vendor
from groundzero.redfish.errors import RedfishError

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

    def choose_cd_slot(self, caps: BmcCapabilities) -> VirtualMediaSlot | None:
        """Standard Redfish: prefer a System-scoped virtual CD, then a Manager-scoped one."""
        cds = [s for s in caps.virtual_media if s.is_cd and s.insert_target]
        cds.sort(key=lambda s: "/Systems/" not in s.path)
        return cds[0] if cds else None

    async def set_one_time_cd_boot(
        self, client: RedfishClient, identity: BmcIdentity, slot: VirtualMediaSlot
    ) -> None:
        """Standard Redfish one-time boot override to the (virtual) CD, UEFI mode."""
        boot = {
            "BootSourceOverrideTarget": "Cd",
            "BootSourceOverrideEnabled": "Once",
            "BootSourceOverrideMode": "UEFI",
        }
        await client.patch(identity.system_path, {"Boot": boot})
        current = (await client.get_json(identity.system_path)).get("Boot", {})
        if (current.get("BootSourceOverrideTarget"), current.get("BootSourceOverrideEnabled")) != (
            "Cd",
            "Once",
        ):
            raise RedfishError(f"Boot override did not take effect: {current}", path=identity.system_path)
