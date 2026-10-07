"""Configure storage: RAID volumes, controller mode, drive state and hot spares, from a saved profile.

A storage profile is a set of rules, not drive ids, so one profile fits every server of a kind: "on the
boot card, one RAID1 of two SSDs, the boot volume"; "on the RAID controller, RAID mode, one RAID5 of every
SAS SSD, one global hot spare". It is captured from a server's layout (Read storage) or written by hand.

``plan_storage`` compares a profile with a server's current layout and lists what would change, in the
order it's applied: volumes deleted (data lost), controller modes, drives converted, volumes created, hot
spares assigned. It never touches the boot volume (where the OS lives) unless that's explicitly allowed.
``apply_plan`` writes the changes over Redfish (standard Volumes where they exist, Dell's RAID service for
drive conversions and spares), restarts the server once if any change waits for a reset, and reads the
layout back until the profile is met.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from groundzero.redfish import actions
from groundzero.redfish.actions import BmcActionError
from groundzero.redfish.capabilities import BmcCapabilities
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import BmcIdentity
from groundzero.redfish.errors import RedfishError
from groundzero.redfish.storage import (
    ControllerKind,
    StorageController,
    StorageDrive,
    StorageLayout,
    StorageVolume,
    read_storage_layout,
)

RaidLevel = Literal["RAID0", "RAID1", "RAID5", "RAID6", "RAID10", "RAID50", "RAID60"]
RAID_MIN_DRIVES = {"RAID0": 1, "RAID1": 2, "RAID5": 3, "RAID6": 4, "RAID10": 4, "RAID50": 6, "RAID60": 8}
_MEDIA = {"SSD": ("SSD", "SolidStateDrive"), "HDD": ("HDD", "HardDiskDrive")}
_PROTOCOL = {"SATA": "SATA", "SAS": "SAS", "NVME": "NVMe"}


# ── profiles ─────────────────────────────────────────────────────────────
class DriveMatch(BaseModel):
    count: int | None = Field(
        default=None, ge=1, description="How many drives; empty: every matching free drive"
    )
    media: Literal["SSD", "HDD"] | None = None
    protocol: Literal["SATA", "SAS", "NVMe"] | None = None
    min_gb: float | None = Field(default=None, ge=0, title="Smallest drive (GB)")

    def fits(self, drive: StorageDrive) -> bool:
        if self.media and (drive.media or "") not in _MEDIA[self.media]:
            return False
        if self.protocol and (drive.protocol or "").upper() != self.protocol.upper():
            return False
        return not (self.min_gb and drive.capacity_gb < self.min_gb)

    def words(self) -> str:
        kind = " ".join(x for x in (self.protocol, self.media, "drives") if x)
        size = f" of at least {self.min_gb:g} GB" if self.min_gb else ""
        return f"{self.count} {kind}{size}" if self.count else f"every free {kind}{size}"


class VolumeRule(BaseModel):
    name: str = Field(min_length=1, max_length=15, pattern=r"^[A-Za-z0-9_-]+$")
    raid: RaidLevel
    drives: DriveMatch = Field(default_factory=DriveMatch)
    boot: bool = Field(default=False, description="The volume the OS installs to")

    @model_validator(mode="after")
    def _enough(self) -> VolumeRule:
        if self.drives.count is not None and self.drives.count < RAID_MIN_DRIVES[self.raid]:
            raise ValueError(f"{self.raid} needs at least {RAID_MIN_DRIVES[self.raid]} drives")
        if self.raid in ("RAID1",) and self.drives.count not in (None, 2):
            raise ValueError("RAID1 is exactly 2 drives")
        if self.raid in ("RAID10",) and self.drives.count is not None and self.drives.count % 2:
            raise ValueError("RAID10 needs an even number of drives")
        return self


class ControllerRule(BaseModel):
    kind: ControllerKind = Field(description="boot (BOSS, M.2), raid (PERC), passthrough, software")
    model: str | None = Field(default=None, description="Only controllers whose model contains this")
    mode: Literal["RAID", "HBA", "EnhancedHBA"] | None = Field(default=None, description="Empty: leave as is")
    volumes: list[VolumeRule] = Field(default_factory=list)
    remove_other_volumes: bool = Field(
        default=False,
        description="Delete volumes on this controller that no rule describes (their data is lost)",
    )
    unused_drives: Literal["leave", "non-raid", "raid"] = Field(
        default="leave", description="What to do with drives no volume or spare uses"
    )
    hot_spares: int = Field(default=0, ge=0, description="Global hot spares on this controller")

    def matches(self, controller: StorageController) -> bool:
        if controller.kind != self.kind:
            return False
        return not self.model or self.model.lower() in (controller.model or controller.name or "").lower()

    def words(self) -> str:
        return f"{self.kind} controller" + (f" ({self.model})" if self.model else "")


class StorageProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    controllers: list[ControllerRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_boot(self) -> StorageProfileWrite:
        boots = [v.name for c in self.controllers for v in c.volumes if v.boot]
        if len(boots) > 1:
            raise ValueError(f"Only one boot volume: {', '.join(boots)} are all marked boot")
        return self


class StorageProfile(StorageProfileWrite):
    id: str
    source: str = "manual"
    created_at: datetime
    updated_at: datetime


class StorageCapture(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""


def capture_profile(layout: StorageLayout, boot_volume_id: str | None) -> list[ControllerRule]:
    """Rules that describe this layout: each controller with volumes, spares or a set mode."""
    rules = []
    for c in layout.controllers:
        volumes = c.raid_volumes
        spares = [d for d in c.drives if d.hotspare]
        if c.kind == "passthrough" or not (volumes or spares or c.mode_settable):
            continue
        drives = {d.id: d for d in c.drives}
        rules.append(
            ControllerRule(
                kind=c.kind,
                model=c.model,
                mode=c.mode if c.mode_settable and c.mode in ("RAID", "HBA", "EnhancedHBA") else None,
                volumes=[
                    _volume_rule(v, drives, v.id == boot_volume_id)
                    for v in volumes
                    if v.raid in RAID_MIN_DRIVES
                ],
                hot_spares=len(spares),
            )
        )
    return rules


def _volume_rule(volume: StorageVolume, drives: dict[str, StorageDrive], boot: bool) -> VolumeRule:
    members = [drives[d] for d in volume.drives if d in drives]
    media = {("SSD" if (d.media or "") in _MEDIA["SSD"] else "HDD") for d in members if d.media}
    protocols = {_PROTOCOL.get((d.protocol or "").upper()) for d in members} - {None}
    name = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in (volume.name or volume.id))[:15]
    return VolumeRule(
        name=name or "volume",
        raid=volume.raid,
        drives=DriveMatch(
            count=len(volume.drives),
            media=media.pop() if len(media) == 1 else None,
            protocol=protocols.pop() if len(protocols) == 1 else None,
        ),
        boot=boot,
    )


# ── planning ─────────────────────────────────────────────────────────────
ActionKind = Literal[
    "delete_volume", "set_mode", "convert_to_raid", "convert_to_nonraid", "create_volume", "assign_spare"
]
_ORDER = {
    "delete_volume": 0,
    "set_mode": 1,
    "convert_to_raid": 2,
    "convert_to_nonraid": 2,
    "create_volume": 3,
    "assign_spare": 4,
}


class StorageAction(BaseModel):
    kind: ActionKind
    controller_id: str
    controller: str = Field(description="The controller's model, for people")
    title: str = Field(description="What happens, in words")
    volume_id: str | None = None
    name: str | None = None
    raid: str | None = None
    mode: str | None = None
    drives: list[str] = Field(default_factory=list, description="Drive ids involved")
    destroys_data: bool = False


class StoragePlan(BaseModel):
    actions: list[StorageAction] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list, description="Why the profile can't be met as it stands")
    boot_volume: str | None = Field(
        default=None, description="The volume the profile marks as boot, once met"
    )

    @property
    def destroys(self) -> list[str]:
        return [a.title for a in self.actions if a.destroys_data]


def plan_storage(
    layout: StorageLayout,
    profile: StorageProfileWrite,
    *,
    protected: str | None,
    allow_boot_volume: bool = False,
) -> StoragePlan:
    """What applying ``profile`` to ``layout`` would change. ``protected``: the boot volume's id (where the
    OS lives); a plan that would delete it, or convert its drives, is refused unless allowed."""
    plan = StoragePlan()
    for rule in profile.controllers:
        matched = [c for c in layout.controllers if rule.matches(c)]
        if not matched:
            plan.problems.append(f"No {rule.words()} on this server")
        for controller in matched:
            _plan_controller(plan, controller, rule, protected, allow_boot_volume)
    plan.actions.sort(key=lambda a: _ORDER[a.kind])
    return plan


def _plan_controller(
    plan: StoragePlan, c: StorageController, rule: ControllerRule, protected: str | None, allow_boot: bool
) -> None:
    label = c.model or c.name or c.id
    act = plan.actions.append

    def problem(text: str) -> None:
        plan.problems.append(f"{label}: {text}")

    existing = list(c.raid_volumes)
    drives = {d.id: d for d in c.drives}
    kept: list[StorageVolume] = []
    to_create: list[VolumeRule] = []
    for want in rule.volumes:
        found = next((v for v in existing if v not in kept and _satisfies(v, want, drives)), None)
        if found is not None:
            kept.append(found)
            if want.boot:
                plan.boot_volume = found.id
        else:
            to_create.append(want)
    leftovers = [v for v in existing if v not in kept]
    deleted: list[StorageVolume] = []
    if rule.remove_other_volumes:
        for v in leftovers:
            if v.id == protected and not allow_boot:
                problem(
                    f"would delete {v.name or v.id}, the boot volume the OS runs from (allow it to go ahead)"
                )
                continue
            deleted.append(v)
            act(
                StorageAction(
                    kind="delete_volume",
                    controller_id=c.id,
                    controller=label,
                    volume_id=v.id,
                    name=v.name,
                    raid=v.raid,
                    drives=v.drives,
                    destroys_data=True,
                    title=f"Delete {v.name or v.id} ({v.raid}, {v.capacity_gb:g} GB) on {label}: "
                    "its data is lost",
                )
            )
    remaining = [v for v in existing if v not in deleted]

    if rule.mode and c.mode != rule.mode:
        if not c.mode_settable:
            problem(f"is in {c.mode or 'an unknown'} mode and its mode can't be changed over Redfish")
        elif rule.mode != "RAID" and remaining:
            problem(f"can't change to {rule.mode} while it holds volumes (tick remove other volumes)")
        else:
            act(
                StorageAction(
                    kind="set_mode",
                    controller_id=c.id,
                    controller=label,
                    mode=rule.mode,
                    title=f"Set {label} to {rule.mode} mode",
                )
            )
    final_mode = rule.mode or c.mode
    if to_create and final_mode in ("HBA",):
        problem(f"can't hold RAID volumes in {final_mode} mode")
        to_create = []

    used = {d for v in remaining for d in v.drives}
    free = [d for d in c.drives if d.id not in used and not d.hotspare and (d.health or "OK") != "Critical"]
    for want in to_create:
        if c.supported_raid and want.raid not in c.supported_raid:
            problem(f"doesn't support {want.raid}")
            continue
        fitting = sorted((d for d in free if want.drives.fits(d)), key=lambda d: (d.capacity_gb, d.id))
        need = want.drives.count or len(fitting)
        if need < RAID_MIN_DRIVES[want.raid] or len(fitting) < need:
            problem(
                f"not enough free drives for {want.name} ({want.raid} of {want.drives.words()}): "
                f"{len(fitting)} available"
            )
            continue
        chosen = fitting[:need]
        free = [d for d in free if d not in chosen]
        nonraid = [d for d in chosen if d.state == "NonRAID"]
        if nonraid:
            act(
                StorageAction(
                    kind="convert_to_raid",
                    controller_id=c.id,
                    controller=label,
                    drives=[d.id for d in nonraid],
                    destroys_data=True,
                    title=f"Make {len(nonraid)} non-RAID drive(s) on {label} RAID-capable: "
                    "anything on them is lost",
                )
            )
        size = _volume_size(want.raid, [d.capacity_gb for d in chosen])
        act(
            StorageAction(
                kind="create_volume",
                controller_id=c.id,
                controller=label,
                name=want.name,
                raid=want.raid,
                drives=[d.id for d in chosen],
                title=f"Create {want.name}: {want.raid} of {len(chosen)} drives "
                f"(about {size:g} GB) on {label}" + (" (the boot volume)" if want.boot else ""),
            )
        )
        if want.boot:
            plan.boot_volume = f"new:{want.name}"

    spares = [d for d in c.drives if d.hotspare]
    if rule.hot_spares > len(spares):
        need = rule.hot_spares - len(spares)
        candidates = sorted(free, key=lambda d: (-d.capacity_gb, d.id))[:need]
        if len(candidates) < need:
            problem(f"not enough free drives for {rule.hot_spares} hot spare(s)")
        for d in candidates:
            act(
                StorageAction(
                    kind="assign_spare",
                    controller_id=c.id,
                    controller=label,
                    drives=[d.id],
                    title=f"Make {d.id.split(':')[0]} a global hot spare on {label}",
                )
            )
        free = [d for d in free if d not in candidates]

    if rule.unused_drives == "non-raid":
        ready = [d for d in free if d.state == "Ready"]
        if ready:
            act(
                StorageAction(
                    kind="convert_to_nonraid",
                    controller_id=c.id,
                    controller=label,
                    drives=[d.id for d in ready],
                    title=f"Pass {len(ready)} unused drive(s) on {label} straight through (non-RAID)",
                )
            )
    elif rule.unused_drives == "raid":
        nonraid = [d for d in free if d.state == "NonRAID"]
        if nonraid:
            act(
                StorageAction(
                    kind="convert_to_raid",
                    controller_id=c.id,
                    controller=label,
                    drives=[d.id for d in nonraid],
                    destroys_data=True,
                    title=f"Make {len(nonraid)} unused non-RAID drive(s) on {label} RAID-capable: "
                    "anything on them is lost",
                )
            )


def _satisfies(volume: StorageVolume, want: VolumeRule, drives: dict[str, StorageDrive]) -> bool:
    if volume.raid != want.raid:
        return False
    if want.drives.count is not None and len(volume.drives) != want.drives.count:
        return False
    members = [drives[d] for d in volume.drives if d in drives]
    return all(want.drives.fits(d) for d in members)


def _volume_size(raid: str, sizes: list[float]) -> float:
    if not sizes:
        return 0
    smallest, n = min(sizes), len(sizes)
    usable = {
        "RAID0": n,
        "RAID1": 1,
        "RAID5": n - 1,
        "RAID6": n - 2,
        "RAID10": n / 2,
        "RAID50": n - 2,
        "RAID60": n - 4,
    }
    return round(smallest * usable.get(raid, 1))


# ── applying ─────────────────────────────────────────────────────────────
async def apply_plan(
    client: RedfishClient,
    identity: BmcIdentity,
    caps: BmcCapabilities,
    layout: StorageLayout,
    plan: StoragePlan,
    *,
    done: Callable[[StorageLayout], bool],
    apply_minutes: float,
    poll_seconds: float,
    log: Callable[[str], None] = lambda m: None,
) -> StorageLayout:
    """Send every change, restart once if any waits for a reset, and read the layout until ``done``."""
    by_id = {c.id: c for c in layout.controllers}
    raid_service = f"{identity.system_path}/Oem/Dell/DellRaidService/Actions/DellRaidService"
    on_reset = False
    for action in plan.actions:
        c = by_id[action.controller_id]
        log(action.title)
        try:
            if action.kind == "delete_volume":
                volume = next(v for v in c.volumes if v.id == action.volume_id)
                await client.delete(volume.path)
                on_reset = on_reset or "Immediate" not in c.volume_apply_times
            elif action.kind == "set_mode":
                body: dict[str, Any] = {
                    "Oem": {"Dell": {"DellStorageController": {"ControllerMode": action.mode}}},
                    "@Redfish.SettingsApplyTime": {"ApplyTime": "OnReset"},
                }
                await client.patch(f"{c.path}/Settings", body)
                on_reset = True
            elif action.kind in ("convert_to_raid", "convert_to_nonraid"):
                verb = "ConvertToRAID" if action.kind == "convert_to_raid" else "ConvertToNonRAID"
                await client.post(f"{raid_service}.{verb}", {"PDArray": action.drives})
                on_reset = True
            elif action.kind == "create_volume":
                drive_paths = [d.path for d in c.drives if d.id in action.drives]
                body = {
                    "RAIDType": action.raid,
                    "Name": action.name,
                    "Links": {"Drives": [{"@odata.id": p} for p in drive_paths]},
                }
                if "OnReset" in c.volume_apply_times:
                    body["@Redfish.OperationApplyTime"] = "OnReset"
                    on_reset = True
                await client.post(f"{c.path}/Volumes", body)
            elif action.kind == "assign_spare":
                await client.post(
                    f"{raid_service}.AssignSpare", {"TargetFQDD": action.drives[0], "VirtualDiskArray": []}
                )
                on_reset = True
        except RedfishError as exc:
            raise BmcActionError(f"{action.title}: the BMC refused it ({exc})") from exc
    if on_reset:
        reset = await actions.restart(client, identity, caps)
        log(f"Restarted the server ({reset}); the controller applies the changes during POST")
    deadline = asyncio.get_running_loop().time() + apply_minutes * 60
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            now = await read_storage_layout(
                client, identity.system_path, dell=identity.vendor.value == "dell"
            )
        except RedfishError:
            now = None  # the BMC can be busy while the server runs its configuration jobs
        if now is not None and done(now):
            return now
        if asyncio.get_running_loop().time() > deadline:
            raise BmcActionError(
                f"The storage changes weren't all in place after {apply_minutes:.0f} minutes. Check the "
                "configuration jobs on the BMC (on iDRAC: Maintenance → Job Queue)."
            )
        log("Waiting for the controller to apply the changes")
