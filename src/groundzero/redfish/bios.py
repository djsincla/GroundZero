"""Change BIOS settings over Redfish: pending settings, applied by the BIOS on the next reset.

The settings Holodeck needs are processor virtualization (VT-x / AMD-V), the IOMMU (VT-d / AMD-Vi) and UEFI
boot mode. Each vendor names them differently (see the vendor profiles); on Dell, ProcVirtualization covers
both VT-x and VT-d. New values are written to the BIOS ``Settings`` object with an apply time of OnReset
(on iDRAC9 that creates the BIOS configuration job), the server is restarted once, and the change is only
reported as done once the current BIOS values read back as requested.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from groundzero.redfish import actions
from groundzero.redfish.actions import BmcActionError
from groundzero.redfish.capabilities import BmcCapabilities
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import BmcIdentity
from groundzero.redfish.errors import RedfishError
from groundzero.redfish.oem.base import VendorProfile, bios_flag

Setting = Literal["cpu_virtualization", "iommu", "boot_mode"]
SETTING_TITLES: dict[str, str] = {
    "cpu_virtualization": "Processor virtualization (VT-x / AMD-V)",
    "iommu": "IOMMU (VT-d / AMD-Vi)",
    "boot_mode": "UEFI boot mode",
}
_ENABLE = {"DISABLED": "ENABLED", "DISABLE": "ENABLE", "OFF": "ON", "FALSE": "TRUE", "NO": "YES"}


class BiosChange(BaseModel):
    setting: str = Field(description="cpu_virtualization, iommu or boot_mode")
    attribute: str = Field(description="The vendor's BIOS attribute, e.g. ProcVirtualization")
    before: str | bool | int | None
    after: str | bool | int


def _same_case(template: str, word: str) -> str:
    """'Enabled' for 'Disabled', 'ENABLED' for 'DISABLED': keep the BIOS's own spelling style."""
    if template.isupper():
        return word.upper()
    if template.islower():
        return word.lower()
    return word.capitalize()


def _target(setting: str, current: Any) -> Any:
    if setting == "boot_mode":
        return (
            None
            if isinstance(current, str) and "UEFI" in current.upper()
            else _same_case(str(current), "Uefi")
        )
    if isinstance(current, bool):
        return True
    word = _ENABLE.get(str(current).upper())
    return _same_case(str(current), word) if word else None


def plan_changes(
    attributes: dict[str, Any], profile: VendorProfile, wanted: list[str]
) -> tuple[list[BiosChange], list[str]]:
    """The attribute changes that make ``wanted`` true, and the settings this BIOS does not expose."""
    keys = {
        "cpu_virtualization": profile.cpu_virtualization_keys,
        "iommu": profile.iommu_keys,
        "boot_mode": profile.boot_mode_keys,
    }
    changes: list[BiosChange] = []
    unsupported: list[str] = []
    for setting in wanted:
        attribute = next((k for k in keys[setting] if k in attributes and attributes[k] is not None), None)
        if attribute is None:
            unsupported.append(setting)
            continue
        current = attributes[attribute]
        if setting != "boot_mode" and bios_flag({attribute: current}, (attribute,)) is True:
            continue  # already enabled
        target = _target(setting, current)
        if target is None:
            if setting != "boot_mode":
                unsupported.append(setting)  # a value we don't know how to flip
            continue
        if any(c.attribute == attribute for c in changes):
            continue  # one attribute covers two settings (Dell ProcVirtualization: VT-x and VT-d)
        changes.append(BiosChange(setting=setting, attribute=attribute, before=current, after=target))
    return changes, unsupported


def wanted_from_inventory(
    cpu_virtualization: bool | None, iommu: bool | None, boot_mode: str | None
) -> list[str]:
    """The settings the inventory shows as wrong (unknown ones are left alone)."""
    out = []
    if cpu_virtualization is False:
        out.append("cpu_virtualization")
    if iommu is False:
        out.append("iommu")
    if boot_mode and "UEFI" not in boot_mode.upper():
        out.append("boot_mode")
    return out


async def apply_changes(
    client: RedfishClient,
    identity: BmcIdentity,
    caps: BmcCapabilities,
    changes: list[BiosChange],
    *,
    apply_minutes: float,
    poll_seconds: float,
    log: Callable[[str], None] = lambda m: None,
) -> dict[str, Any]:
    """Write the pending settings, restart once, and wait until the BIOS reports the new values."""
    system = await client.get_json(identity.system_path)
    bios_path = (system.get("Bios") or {}).get("@odata.id") or f"{identity.system_path}/Bios"
    bios = await client.get_json(bios_path)
    settings = bios.get("@Redfish.Settings") or {}
    settings_path = (settings.get("SettingsObject") or {}).get("@odata.id") or f"{bios_path}/Settings"
    body: dict[str, Any] = {"Attributes": {c.attribute: c.after for c in changes}}
    if "OnReset" in (settings.get("SupportedApplyTimes") or []):
        body["@Redfish.SettingsApplyTime"] = {"ApplyTime": "OnReset"}
    log(f"Writing {', '.join(f'{c.attribute}={c.after}' for c in changes)} to {settings_path}")
    await client.patch(settings_path, body)
    reset = await actions.restart(client, identity, caps)
    log(f"Restarted the server ({reset}); the BIOS applies the settings during POST")
    deadline = asyncio.get_running_loop().time() + apply_minutes * 60
    wanted = {c.attribute: c.after for c in changes}
    seen: dict[str, Any] = {}
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            seen = (await client.get_json(bios_path)).get("Attributes") or {}
        except RedfishError:
            seen = {}  # the BMC can be busy while the host runs its BIOS job
        if seen and all(seen.get(k) == v for k, v in wanted.items()):
            return {k: seen.get(k) for k in wanted}
        if asyncio.get_running_loop().time() > deadline:
            now = ", ".join(f"{k}={seen.get(k, '?')}" for k in wanted)
            raise BmcActionError(
                f"The BIOS did not apply the change within {apply_minutes:.0f} minutes (now {now}). "
                "Check the BIOS configuration job on the BMC (on iDRAC: Maintenance → Job Queue)."
            )
        log("Waiting for the BIOS to apply the settings")
