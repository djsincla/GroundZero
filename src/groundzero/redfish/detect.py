"""Identify the BMC vendor and locate the primary System / Manager / Chassis resources."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from groundzero.redfish.client import SERVICE_ROOT, RedfishClient
from groundzero.redfish.errors import RedfishError


class Vendor(StrEnum):
    DELL = "dell"
    HPE = "hpe"
    LENOVO = "lenovo"
    CISCO = "cisco"
    SUPERMICRO = "supermicro"
    INTEL = "intel"
    QUANTA = "quanta"
    GIGABYTE = "gigabyte"
    GENERIC = "generic"


# First match wins; order matters (e.g. "INTEL" appears in many non-Intel CPU strings, so it goes last).
_VENDOR_MARKERS: tuple[tuple[Vendor, tuple[str, ...]], ...] = (
    (Vendor.DELL, ("DELL",)),
    (Vendor.HPE, ("HPE", "HEWLETT")),
    (Vendor.LENOVO, ("LENOVO",)),
    (Vendor.CISCO, ("CISCO",)),
    (Vendor.SUPERMICRO, ("SUPERMICRO", "SUPER MICRO")),
    (Vendor.QUANTA, ("QUANTA", "QCT")),
    (Vendor.GIGABYTE, ("GIGABYTE", "GIGA-BYTE")),
    (Vendor.INTEL, ("INTEL",)),
)


class BmcIdentity(BaseModel):
    vendor: Vendor
    manufacturer: str
    model: str
    redfish_version: str | None
    system_path: str
    manager_path: str | None
    chassis_path: str | None


def match_vendor(*fields: str) -> Vendor:
    haystack = " ".join(fields).upper()
    for vendor, markers in _VENDOR_MARKERS:
        if any(marker in haystack for marker in markers):
            return vendor
    return Vendor.GENERIC


async def _first_member(client: RedfishClient, root: dict[str, Any], key: str) -> str | None:
    link = root.get(key, {}).get("@odata.id")
    if not link:
        return None
    try:
        members = (await client.get_json(link)).get("Members", [])
    except RedfishError:
        return None
    return str(members[0]["@odata.id"]) if members else None


async def detect(client: RedfishClient) -> BmcIdentity:
    root = await client.get_json(SERVICE_ROOT)
    system_path = await _first_member(client, root, "Systems")
    if system_path is None:
        raise RedfishError("BMC exposes no ComputerSystem resource", path=SERVICE_ROOT + "/Systems")
    system = await client.get_json(system_path)
    manufacturer = str(system.get("Manufacturer") or "")
    model = str(system.get("Model") or "")
    vendor = match_vendor(
        str(root.get("Vendor") or ""),
        manufacturer,
        " ".join(root.get("Oem", {}).keys()),
        str(root.get("Product") or ""),
    )
    return BmcIdentity(
        vendor=vendor,
        manufacturer=manufacturer,
        model=model,
        redfish_version=root.get("RedfishVersion"),
        system_path=system_path,
        manager_path=await _first_member(client, root, "Managers"),
        chassis_path=await _first_member(client, root, "Chassis"),
    )
