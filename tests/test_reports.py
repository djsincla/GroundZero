"""Reports: the cluster comparison and the CSV rows (pure logic, on the R740xd's recorded inventory)."""

from __future__ import annotations

import asyncio
import csv
import io
from pathlib import Path

from groundzero.core.reports import Configuration, HostReport, compare, host_rows, to_csv
from groundzero.inventory.collect import collect_inventory, pcie_class
from groundzero.inventory.models import HostInventory
from groundzero.redfish.capture import load_recording, replay_transport
from groundzero.redfish.client import RedfishClient

R740XD = Path(__file__).parent / "fixtures" / "dell-r740xd"


def _inventory() -> HostInventory:
    async def read() -> HostInventory:
        async with RedfishClient(
            "198.51.100.11", "root", "x", transport=replay_transport(load_recording(R740XD))
        ) as c:
            return (await collect_inventory(c))[1]

    return asyncio.run(read())


def _report(name: str, inventory: HostInventory | None) -> HostReport:
    return HostReport(
        generated_at="2026-10-07T00:00:00Z",
        host_id=name,
        name=name,
        bmc_address="198.51.100.11",
        model="dell PowerEdge R740xd",
        inventory=inventory,
        configuration=Configuration(),
    )  # type: ignore[arg-type]


def test_the_full_inventory_is_read() -> None:
    inv = _inventory()
    assert len(inv.firmware) == 33 and inv.system.bios_version == "2.24.0"
    assert any(f.name == "Integrated Dell Remote Access Controller" for f in inv.firmware)
    assert len(inv.memory.modules) == 8 and inv.memory.modules[0].type == "DDR4"
    assert [(a.model, a.ports) for a in inv.network_adapters] == [("BRCM 10G/GbE 2+2P 57800-t rNDC", 4)]
    assert [(p.capacity_watts, p.firmware_version) for p in inv.power_supplies] == [(2000.0, "00.11.1A")] * 2
    kinds = {d.device_class for d in inv.pcie_devices}
    assert {"storage", "network", "display", "chipset"} <= kinds
    assert all(d.firmware_version for d in inv.drives if d.protocol == "PCIe")


def test_pcie_devices_are_classed_by_name() -> None:
    assert pcie_class("PERC H730P Adapter") == "storage"
    assert pcie_class("BCM57800 1-Gigabit Ethernet") == "network"
    assert pcie_class("NVIDIA A2") == "accelerator"
    assert pcie_class("C621 Series Chipset LPC/eSPI Controller") == "chipset"


def test_a_cluster_flags_what_differs() -> None:
    inv = _inventory()
    older = inv.model_copy(deep=True)
    older.system.bios_version = "2.19.1"
    older.firmware = [
        f.model_copy(update={"version": "6.10.30.00"}) if f.name.startswith("Integrated Dell") else f
        for f in older.firmware
    ]
    rows = {
        c.item: c for c in compare([_report("esx01", inv), _report("esx02", older), _report("esx03", None)])
    }
    assert rows["BIOS"].differs and rows["BIOS"].values == {
        "esx01": "2.24.0",
        "esx02": "2.19.1",
        "esx03": None,
    }
    assert rows["Firmware: Integrated Dell Remote Access Controller"].values["esx02"] == "6.10.30.00"
    assert rows["Hardware"].values == {"esx01": None, "esx02": None, "esx03": "not read"}
    assert not compare([_report("esx01", inv), _report("esx02", inv)])[
        0
    ].differs  # identical: nothing flagged


def test_the_csv_has_a_row_per_component() -> None:
    rows = list(csv.DictReader(io.StringIO(to_csv(host_rows(_report("esx01", _inventory()))))))
    sections = {r["section"] for r in rows}
    assert {
        "server",
        "processor",
        "memory",
        "drive",
        "network adapter",
        "power supply",
        "firmware",
    } <= sections
    assert {"section": "firmware", "component": "BIOS", "version": "2.24.0"}.items() <= next(
        r for r in rows if r["section"] == "firmware" and r["component"] == "BIOS"
    ).items()
