"""BMC write operations an unattended install needs: virtual media, one-time boot, power.

Vendor differences live in the VendorProfile (which CD slot, how to request a one-time CD boot);
this module sequences the calls and verifies each one took effect. None of these are retried
after a timeout (see RedfishClient), so a reset is never sent twice.
"""

from __future__ import annotations

import asyncio
import logging

from groundzero.redfish.capabilities import BmcCapabilities, VirtualMediaSlot
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import BmcIdentity
from groundzero.redfish.errors import RedfishError
from groundzero.redfish.oem import VendorProfile

logger = logging.getLogger(__name__)


class BmcActionError(Exception):
    error_type = "bmc_action_failed"


async def slot_state(client: RedfishClient, slot: VirtualMediaSlot) -> tuple[bool, str | None]:
    vm = await client.get_json(slot.path)
    return bool(vm.get("Inserted")), vm.get("Image") or None


async def eject(client: RedfishClient, slot: VirtualMediaSlot) -> None:
    inserted, _ = await slot_state(client, slot)
    if not inserted:
        return
    if not slot.eject_target:
        raise BmcActionError(f"{slot.path} has no EjectMedia action")
    await client.post(slot.eject_target, {})
    inserted, image = await slot_state(client, slot)
    if inserted:
        raise BmcActionError(f"{slot.path} still has {image} inserted after EjectMedia")


async def insert(client: RedfishClient, slot: VirtualMediaSlot, url: str) -> None:
    """Mount ``url`` read-only. Refuses to replace media someone else mounted."""
    inserted, image = await slot_state(client, slot)
    if inserted and image != url:
        raise BmcActionError(f"{slot.path} already has {image} inserted; eject it first")
    if not inserted:
        if not slot.insert_target:
            raise BmcActionError(f"{slot.path} has no InsertMedia action")
        await client.post(slot.insert_target, {"Image": url, "Inserted": True, "WriteProtected": True})
    inserted, image = await slot_state(client, slot)
    if not inserted or image != url:
        raise BmcActionError(
            f"InsertMedia did not take effect on {slot.path} (inserted={inserted}, image={image})"
        )


async def power_state(client: RedfishClient, identity: BmcIdentity) -> str:
    return str((await client.get_json(identity.system_path)).get("PowerState", "Unknown"))


async def restart(client: RedfishClient, identity: BmcIdentity, caps: BmcCapabilities) -> str:
    """Power on, or force a restart if already on. Returns the ResetType sent."""
    if not caps.reset.target:
        raise BmcActionError("BMC exposes no ComputerSystem.Reset action")
    state = await power_state(client, identity)
    reset_type = "On" if state.lower() == "off" else "ForceRestart"
    if caps.reset.allowed_types and reset_type not in caps.reset.allowed_types:
        reset_type = "PowerCycle" if "PowerCycle" in caps.reset.allowed_types else reset_type
    await client.post(caps.reset.target, {"ResetType": reset_type})
    return reset_type


async def boot_once_from_virtual_cd(
    client: RedfishClient, identity: BmcIdentity, caps: BmcCapabilities, profile: VendorProfile, url: str
) -> VirtualMediaSlot:
    """Mount ``url`` and arrange for the next boot (only) to use it. Returns the slot used."""
    slot = profile.choose_cd_slot(caps)
    if slot is None:
        raise BmcActionError("No virtual CD slot with InsertMedia on this BMC")
    await insert(client, slot, url)
    try:
        await profile.set_one_time_cd_boot(client, identity, slot)
    except (RedfishError, BmcActionError):
        await eject(client, slot)  # leave the BMC as we found it
        raise
    return slot


async def wait_for_power(
    client: RedfishClient, identity: BmcIdentity, wanted: str, timeout: float, poll: float = 5.0
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if (await power_state(client, identity)).lower() == wanted.lower():
            return
        await asyncio.sleep(poll)
    raise BmcActionError(f"Power state did not become {wanted} within {timeout:.0f}s")
