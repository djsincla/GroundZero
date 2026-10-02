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
from groundzero.redfish.errors import RedfishTransportError
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


async def insert(
    client: RedfishClient,
    slot: VirtualMediaSlot,
    url: str,
    *,
    action_timeout: float = 180.0,
    settle_timeout: float = 120.0,
    poll: float = 5.0,
) -> None:
    """Mount ``url`` read-only. Refuses to replace media someone else mounted.

    InsertMedia is never retried. If the call times out (seen live: iDRAC answered after >30 s while
    the mount went through), the slot is polled until our image shows up or ``settle_timeout`` ends.
    """
    inserted, image = await slot_state(client, slot)
    if inserted and image != url:
        raise BmcActionError(f"{slot.path} already has {image} inserted; eject it first")
    if not inserted:
        if not slot.insert_target:
            raise BmcActionError(f"{slot.path} has no InsertMedia action")
        body = {"Image": url, "Inserted": True, "WriteProtected": True}
        try:
            await client.post(slot.insert_target, body, timeout=action_timeout)
        except RedfishTransportError:
            logger.warning("InsertMedia on %s timed out; checking whether it took effect", slot.path)
            if not await _wait_for_image(client, slot, url, settle_timeout, poll):
                raise
    inserted, image = await slot_state(client, slot)
    if not inserted or image != url:
        raise BmcActionError(
            f"InsertMedia did not take effect on {slot.path} (inserted={inserted}, image={image})"
        )


async def _wait_for_image(
    client: RedfishClient, slot: VirtualMediaSlot, url: str, timeout: float, poll: float
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        inserted, image = await slot_state(client, slot)
        if inserted and image == url:
            return True
        await asyncio.sleep(poll)
    return False


async def eject_if_ours(client: RedfishClient, slot: VirtualMediaSlot, url: str) -> None:
    """Best-effort cleanup that never ejects media someone else mounted."""
    try:
        inserted, image = await slot_state(client, slot)
        if inserted and image == url:
            await eject(client, slot)
    except Exception:
        logger.exception("Could not clean up media on %s", slot.path)


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
    client: RedfishClient,
    identity: BmcIdentity,
    caps: BmcCapabilities,
    profile: VendorProfile,
    url: str,
    *,
    action_timeout: float = 180.0,
    boot_method: str = "auto",
    settle_seconds: float = 0.0,
) -> tuple[VirtualMediaSlot, str]:
    """Mount ``url`` and arrange for the next boot (only) to use it. Returns (slot, boot method)."""
    slot = profile.choose_cd_slot(caps)
    if slot is None:
        raise BmcActionError("No virtual CD slot with InsertMedia on this BMC")
    try:
        await insert(client, slot, url, action_timeout=action_timeout)
        if settle_seconds:  # let the virtual USB optical device attach before POST enumerates USB
            await asyncio.sleep(settle_seconds)
        method = await profile.set_one_time_cd_boot(client, identity, caps, boot_method)
        logger.info("One-time boot to virtual CD via %s", method)
    except BaseException:
        await eject_if_ours(client, slot, url)  # leave the BMC as we found it, even if the mount half-worked
        raise
    return slot, method


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
