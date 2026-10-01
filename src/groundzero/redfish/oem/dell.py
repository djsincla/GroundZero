"""Dell iDRAC (14G/15G/16G) specifics."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from groundzero.redfish.capabilities import BmcCapabilities, VirtualMediaSlot
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import BmcIdentity, Vendor
from groundzero.redfish.errors import RedfishError
from groundzero.redfish.oem.base import LicenseInfo, VendorProfile

logger = logging.getLogger(__name__)

# Standard LicenseService (newer iDRAC9 firmware) first, then the Dell OEM collection.
_LICENSE_COLLECTIONS = (
    "/redfish/v1/LicenseService/Licenses",
    "/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLicenses",
)
# Remote virtual media needs iDRAC Enterprise or better.
_TIERS = (
    ("datacenter", True),
    ("enterprise", True),
    ("secured enterprise", True),
    ("express", False),
    ("basic", False),
)


def classify_license(text: str) -> LicenseInfo | None:
    lowered = text.lower()
    for tier, virtual_media in _TIERS:
        if tier in lowered:
            return LicenseInfo(name=text.strip(), tier=tier, supports_virtual_media=virtual_media)
    return None


def _license_text(entry: dict[str, Any]) -> str:
    # Descriptive fields only: Name/Id carry the license entitlement id on iDRAC9.
    fields = ("LicenseDescription", "Description")
    parts: list[str] = []
    for field in fields:
        value = entry.get(field)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts)


class DellProfile(VendorProfile):
    vendor: ClassVar[Vendor] = Vendor.DELL
    # On Dell, "ProcVirtualization" enables both VT-x and VT-d (DMAR table); there is no separate VT-d knob.
    cpu_virtualization_keys: ClassVar[tuple[str, ...]] = ("ProcVirtualization",)
    iommu_keys: ClassVar[tuple[str, ...]] = ("ProcVirtualization",)

    def choose_cd_slot(self, caps: BmcCapabilities) -> VirtualMediaSlot | None:
        """Dell: classic iDRAC virtual CD (Managers/.../VirtualMedia/CD) + FirstBootDevice=VCD-DVD.

        The System-scoped slots on newer firmware are Remote File Share (RFS) devices.
        """
        for slot in caps.virtual_media:
            if slot.path.endswith("/VirtualMedia/CD") and slot.insert_target:
                return slot
        return super().choose_cd_slot(caps)

    async def set_one_time_cd_boot(
        self, client: RedfishClient, identity: BmcIdentity, slot: VirtualMediaSlot
    ) -> None:
        if not slot.path.endswith("/VirtualMedia/CD") or not identity.manager_path:
            await super().set_one_time_cd_boot(client, identity, slot)
            return
        attrs_path = identity.manager_path + "/Attributes"
        wanted = {"ServerBoot.1.BootOnce": "Enabled", "ServerBoot.1.FirstBootDevice": "VCD-DVD"}
        await client.patch(attrs_path, {"Attributes": wanted})
        current = (await client.get_json(attrs_path)).get("Attributes", {})
        if any(current.get(k) != v for k, v in wanted.items()):
            got = {k: current.get(k) for k in wanted}
            raise RedfishError(f"iDRAC one-time boot attributes did not apply: {got}", path=attrs_path)

    async def license(self, client: RedfishClient, identity: BmcIdentity) -> LicenseInfo | None:
        best: LicenseInfo | None = None
        for collection in _LICENSE_COLLECTIONS:
            try:
                entries = await client.get_members(collection)
            except RedfishError as exc:
                logger.debug("License collection %s unavailable: %s", collection, exc)
                continue
            for entry in entries:
                info = classify_license(_license_text(entry))
                if info and (
                    best is None or (info.supports_virtual_media and not best.supports_virtual_media)
                ):
                    best = info
            if best:
                return best
        return best
