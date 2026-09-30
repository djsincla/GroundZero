"""Vendor profile registry."""

from __future__ import annotations

from groundzero.redfish.detect import Vendor
from groundzero.redfish.oem.base import LicenseInfo, VendorProfile
from groundzero.redfish.oem.dell import DellProfile

_PROFILES: dict[Vendor, type[VendorProfile]] = {
    Vendor.DELL: DellProfile,
}


def profile_for(vendor: Vendor) -> VendorProfile:
    """Vendor-specific profile, falling back to the generic DMTF behaviour."""
    return _PROFILES.get(vendor, VendorProfile)()


__all__ = ["LicenseInfo", "VendorProfile", "profile_for"]
