"""Dell iDRAC (14G/15G/16G) specifics."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

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
    fields = ("LicenseDescription", "Description", "Name", "LicenseInfo", "EntitlementID")
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
