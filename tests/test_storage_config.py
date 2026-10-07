"""Configure storage: capture rules from the R740xd's layout, and plan changes against it (pure logic)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from groundzero.redfish.capture import load_recording, replay_transport
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.storage import StorageDrive, StorageLayout, read_storage_layout
from groundzero.redfish.storage_config import (
    ControllerRule,
    DriveMatch,
    StorageProfileWrite,
    VolumeRule,
    capture_profile,
    plan_storage,
)
from groundzero.simulator.bmc import SimulatedBmc

R740XD = Path(__file__).parent / "fixtures" / "dell-r740xd"
BOSS_VOLUME = "Disk.Virtual.0:AHCI.Slot.1-1"


def _layout(*faults: str) -> StorageLayout:
    async def read() -> StorageLayout:
        transport = (
            SimulatedBmc(load_recording(R740XD), faults=frozenset(faults)).transport()
            if faults
            else (replay_transport(load_recording(R740XD)))
        )
        async with RedfishClient("198.51.100.11", "root", "x", transport=transport) as client:
            return await read_storage_layout(client, "/redfish/v1/Systems/System.Embedded.1")

    return asyncio.run(read())


def _profile(*rules: ControllerRule) -> StorageProfileWrite:
    return StorageProfileWrite(name="p", controllers=list(rules))


def test_capture_describes_the_boss_boot_volume() -> None:
    rules = capture_profile(_layout(), BOSS_VOLUME)
    assert len(rules) == 1  # the PERCs are empty and their mode can't be set; NVMe is pass-through
    boss = rules[0]
    assert (boss.kind, boss.model, boss.hot_spares) == ("boot", "BOSS-S1", 0)
    assert boss.volumes == [
        VolumeRule(
            name="boss", raid="RAID1", drives=DriveMatch(count=2, media="SSD", protocol="SATA"), boot=True
        )
    ]


def test_a_captured_profile_matches_its_own_server() -> None:
    layout = _layout()
    plan = plan_storage(layout, _profile(*capture_profile(layout, BOSS_VOLUME)), protected=BOSS_VOLUME)
    assert plan.actions == [] and plan.problems == [] and plan.boot_volume == BOSS_VOLUME


def test_the_boot_volume_is_never_deleted_unless_allowed() -> None:
    layout = _layout()
    wipe = _profile(ControllerRule(kind="boot", volumes=[], remove_other_volumes=True))
    refused = plan_storage(layout, wipe, protected=BOSS_VOLUME)
    assert refused.actions == [] and "the boot volume the OS runs from" in refused.problems[0]
    allowed = plan_storage(layout, wipe, protected=BOSS_VOLUME, allow_boot_volume=True)
    assert [(a.kind, a.volume_id, a.destroys_data) for a in allowed.actions] == [
        ("delete_volume", BOSS_VOLUME, True)
    ]


def test_a_new_raid5_with_a_spare_on_the_perc() -> None:
    layout = _layout("perc-drives")
    rule = ControllerRule(
        kind="raid",
        model="H730P",
        volumes=[
            VolumeRule(name="data", raid="RAID5", drives=DriveMatch(count=3, media="SSD", protocol="SAS"))
        ],
        hot_spares=1,
    )
    plan = plan_storage(layout, _profile(rule), protected=BOSS_VOLUME)
    assert plan.problems == []
    assert [a.kind for a in plan.actions] == ["create_volume", "assign_spare"]
    create = plan.actions[0]
    assert len(create.drives) == 3 and "about 1920 GB" in create.title and not create.destroys_data
    assert plan.actions[1].drives[0] not in create.drives


def test_problems_are_named_not_guessed() -> None:
    layout = _layout("perc-drives")
    too_many = ControllerRule(
        kind="raid",
        volumes=[VolumeRule(name="big", raid="RAID6", drives=DriveMatch(count=6, protocol="SAS"))],
    )
    hba = ControllerRule(kind="raid", mode="HBA", volumes=[VolumeRule(name="x", raid="RAID1")])
    nothing = ControllerRule(kind="software", model="PERC S999")
    plan = plan_storage(layout, _profile(too_many, hba, nothing), protected=BOSS_VOLUME)
    assert any("not enough free drives for big" in p for p in plan.problems)
    assert any("can't hold RAID volumes in HBA mode" in p for p in plan.problems)
    assert "No software controller (PERC S999) on this server" in plan.problems


def test_rules_are_checked_when_written() -> None:
    with pytest.raises(ValidationError, match="RAID5 needs at least 3 drives"):
        VolumeRule(name="v", raid="RAID5", drives=DriveMatch(count=2))
    with pytest.raises(ValidationError, match="Only one boot volume"):
        _profile(
            ControllerRule(kind="boot", volumes=[VolumeRule(name="a", raid="RAID1", boot=True)]),
            ControllerRule(kind="raid", volumes=[VolumeRule(name="b", raid="RAID1", boot=True)]),
        )


def test_drive_matching_uses_media_protocol_and_size() -> None:
    ssd = StorageDrive(id="d", path="/d", media="SSD", protocol="SAS", capacity_gb=960)
    assert DriveMatch(media="SSD", protocol="SAS", min_gb=900).fits(ssd)
    assert not DriveMatch(media="HDD").fits(ssd) and not DriveMatch(min_gb=1000).fits(ssd)
    assert DriveMatch(protocol="SAS", count=3).words() == "3 SAS drives"
