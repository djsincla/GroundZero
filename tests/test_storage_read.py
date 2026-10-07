"""Read storage: the R740xd's recorded layout, its boot volume, and the boot-volume install disk rule."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from groundzero.modules.storage import ReadStorage, boot_volume
from groundzero.osconfig import OsConfigError
from groundzero.osconfig.esxi import DiskRule, EsxiHostValues, EsxiPlugin, EsxiSettings
from groundzero.redfish.capture import load_recording, replay_transport
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.storage import StorageController, StorageLayout, StorageVolume, read_storage_layout

R740XD = Path(__file__).parent / "fixtures" / "dell-r740xd"


def _layout() -> StorageLayout:
    async def read() -> StorageLayout:
        client = RedfishClient(
            "198.51.100.11", "root", "x", transport=replay_transport(load_recording(R740XD))
        )
        async with client:
            return await read_storage_layout(client, "/redfish/v1/Systems/System.Embedded.1")

    return asyncio.run(read())


def test_the_boss_raid1_is_the_boot_volume() -> None:
    b = boot_volume(_layout())
    assert b is not None
    assert (b.controller_model, b.name, b.raid, b.capacity_gb, b.drives) == (
        "BOSS-S1",
        "boss",
        "RAID1",
        480.0,
        2,
    )
    assert b.install_match == "DELLBOSS"


def test_the_summary_names_the_boot_volume() -> None:
    layout = _layout()
    data = {**layout.model_dump(mode="json"), "boot_volume": boot_volume(layout).model_dump(mode="json")}  # type: ignore[union-attr]
    assert ReadStorage().summarize(data) == (
        "5 controllers · 1 RAID volume · 16 drives · boot: boss RAID1 480 GB on BOSS-S1"
    )


def test_a_volume_marked_boot_wins_over_a_boot_card() -> None:
    perc = StorageController(
        id="RAID.Slot.6-1",
        path="/p",
        model="PERC H730P Adapter",
        kind="raid",
        volumes=[
            StorageVolume(
                id="Disk.Virtual.1", path="/v1", name="os", raid="RAID1", capacity_gb=900, boot=True
            )
        ],
    )
    boss = StorageController(
        id="AHCI.Slot.1-1",
        path="/b",
        model="BOSS-S1",
        kind="boot",
        volumes=[StorageVolume(id="Disk.Virtual.0", path="/v0", name="boss", raid="RAID1", capacity_gb=480)],
    )
    b = boot_volume(StorageLayout(controllers=[boss, perc]))
    assert b is not None and b.name == "os" and b.install_match is None  # no installer match


def test_no_volumes_means_no_boot_volume() -> None:
    nvme = StorageController(
        id="PCIeExtender.Slot.3",
        path="/x",
        kind="passthrough",
        volumes=[StorageVolume(id="Disk.Bay.0", path="/d", raw=True, capacity_gb=1000)],
    )
    assert boot_volume(StorageLayout(controllers=[nvme])) is None


SETTINGS = EsxiSettings(
    netmask="255.255.255.0",
    gateway="192.0.2.1",
    nameservers=["192.0.2.53"],
    install_disk=DiskRule(mode="boot-volume"),
)
VALUES = EsxiHostValues(hostname="esxi1", ip="192.0.2.101")


def test_the_boot_volume_rule_installs_with_the_volumes_match() -> None:
    spec = EsxiPlugin.build_spec(
        SETTINGS,
        VALUES,
        root_password="pw",
        legacy_cpu_detected=False,
        current_boot_disk=None,
        boot_volume_match="DELLBOSS",
    )
    assert (spec.install_firstdisk, spec.install_disk) == ("DELLBOSS", None)


def test_the_boot_volume_rule_needs_read_storage() -> None:
    with pytest.raises(OsConfigError, match="run Read storage first"):
        EsxiPlugin.build_spec(
            SETTINGS, VALUES, root_password="pw", legacy_cpu_detected=False, current_boot_disk=None
        )
