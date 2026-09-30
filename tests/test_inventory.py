from __future__ import annotations

from typing import Any

from conftest import make_client

from groundzero.inventory.collect import collect_inventory
from groundzero.redfish.detect import Vendor, detect, match_vendor


def test_match_vendor_order() -> None:
    assert match_vendor("Dell Inc.") is Vendor.DELL
    assert match_vendor("Hewlett Packard Enterprise") is Vendor.HPE
    assert match_vendor("Supermicro", "Intel(R) Xeon") is Vendor.SUPERMICRO
    assert match_vendor("Contoso") is Vendor.GENERIC


async def test_detect_dell(idrac9: dict[str, Any]) -> None:
    async with make_client(idrac9) as client:
        ident = await detect(client)
    assert ident.vendor is Vendor.DELL
    assert ident.model == "PowerEdge R740xd"
    assert ident.system_path.endswith("System.Embedded.1")


async def test_collect_inventory(idrac9: dict[str, Any]) -> None:
    progress: list[str] = []
    client = make_client(idrac9)
    async with client:
        _, inv = await collect_inventory(client, lambda _f, m: progress.append(m))

    assert inv.total_cores == 40 and inv.total_threads == 80
    assert inv.memory.total_gib == 384 and inv.memory.dimm_count == 12
    assert len(inv.drives) == 5
    assert [d.id for d in inv.drives if d.is_boot_device] == ["Disk.Direct.0-0:AHCI.Slot.6-1"]
    assert sum(d.is_flash for d in inv.drives if not d.is_boot_device) == 2
    assert [p.id for p in inv.network_ports if p.link_up] == ["NIC.Integrated.1-1-1"]
    assert inv.bios.cpu_virtualization is True and inv.bios.iommu is True
    assert inv.bios.boot_mode == "Uefi"
    assert inv.bmc.firmware_version == "7.00.00.171"
    assert inv.bmc.license and inv.bmc.license.tier == "enterprise"
    assert inv.capabilities.virtual_media[0].transfer_protocols == ["CIFS", "HTTP", "HTTPS", "NFS"]
    assert "Cd" in inv.capabilities.boot_override.allowed_targets
    assert progress[0] == "Detecting BMC"

    # Read-only guarantee: nothing but GETs besides session create/delete.
    writes = {(r.method, r.path) for r in client.request_log if r.method != "GET"}
    assert writes == {
        ("POST", "/redfish/v1/SessionService/Sessions"),
        ("DELETE", "/redfish/v1/SessionService/Sessions/1"),
    }


async def test_missing_optional_resources_do_not_fail(idrac9: dict[str, Any]) -> None:
    del idrac9["/redfish/v1/Systems/System.Embedded.1/Bios"]
    del idrac9["/redfish/v1/LicenseService/Licenses"]
    async with make_client(idrac9) as client:
        _, inv = await collect_inventory(client)
    assert inv.bios.cpu_virtualization is None
    assert inv.bmc.license is None
