"""Detailed expectations against the real (sanitized) Dell R740xd capture."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_client

from groundzero.inventory.collect import collect_inventory
from groundzero.inventory.models import HostInventory
from groundzero.preflight.evaluate import CheckStatus, evaluate
from groundzero.redfish.capture import load_recording

CAPTURE = Path(__file__).parent / "fixtures" / "dell-r740xd"


@pytest.fixture
async def inventory() -> HostInventory:
    async with make_client(load_recording(CAPTURE)) as client:
        return (await collect_inventory(client))[1]


def test_hardware_facts(inventory: HostInventory) -> None:
    assert inventory.system.model == "PowerEdge R740xd"
    assert inventory.bmc.firmware_version == "7.00.00.182"  # not mistaken for an IP by the sanitizer
    assert (inventory.total_cores, inventory.total_threads) == (48, 96)
    assert inventory.memory.total_gib == 512
    boot = [d for d in inventory.drives if d.is_boot_device]
    assert len(boot) == 2 and all(d.controller == "BOSS-S1" for d in boot)
    assert sum(d.is_flash for d in inventory.drives if not d.is_boot_device) == 14
    assert sum(p.link_up for p in inventory.network_ports) == 4
    assert inventory.bmc.license is not None and inventory.bmc.license.tier == "enterprise"
    assert "FD0" not in inventory.bmc.license.name  # entitlement id is not surfaced


def test_virtual_media_on_both_manager_and_system_paths(inventory: HostInventory) -> None:
    cd_paths = {s.path for s in inventory.capabilities.virtual_media if s.is_cd}
    assert "/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD" in cd_paths
    assert "/redfish/v1/Systems/System.Embedded.1/VirtualMedia/1" in cd_paths


def test_holodeck_default_variant(inventory: HostInventory) -> None:
    report = evaluate(inventory, "holodeck-9")
    statuses = {c.id: c.status for c in report.checks}
    assert statuses.pop("cpu.generation") is CheckStatus.WARN  # Skylake-SP on ESXi 9
    assert set(statuses.values()) == {CheckStatus.PASS}
    assert report.overall is CheckStatus.WARN
