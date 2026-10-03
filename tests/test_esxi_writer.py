"""Host-prep writes against fake vSphere objects: idempotency, exact calls, and refusing unsafe formats."""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

import pytest
from pyVmomi import vim

from groundzero.esxi import writer
from groundzero.esxi.reader import EsxiError


class FakeNetworkSystem:
    def __init__(self, vswitches: list[Any], portgroups: list[Any]) -> None:
        self.networkInfo = NS(vswitch=vswitches, portgroup=portgroups)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def UpdateVirtualSwitch(self, **kw: Any) -> None:
        self.calls.append(("UpdateVirtualSwitch", kw))

    def AddPortGroup(self, **kw: Any) -> None:
        self.calls.append(("AddPortGroup", kw))

    def UpdatePortGroup(self, **kw: Any) -> None:
        self.calls.append(("UpdatePortGroup", kw))


def _host(**managers: Any) -> Any:
    return NS(configManager=NS(**managers), config=NS(dateTimeInfo=None), datastore=[])


def _vswitch(mtu: int) -> Any:
    return NS(name="vSwitch0", mtu=mtu, spec=vim.host.VirtualSwitch.Specification(numPorts=128, mtu=mtu))


def _portgroup(name: str, vlan: int, promiscuous: bool | None = None) -> Any:
    sec = vim.host.NetworkPolicy.SecurityPolicy(
        allowPromiscuous=promiscuous, macChanges=promiscuous, forgedTransmits=promiscuous
    )
    spec = vim.host.PortGroup.Specification(
        name=name, vlanId=vlan, vswitchName="vSwitch0", policy=vim.host.NetworkPolicy(security=sec)
    )
    return NS(spec=spec)


ACCEPT = {"allow_promiscuous": True, "mac_changes": True, "forged_transmits": True}


def test_mtu_is_changed_once() -> None:
    ns = FakeNetworkSystem([_vswitch(1500)], [])
    record = writer.set_vswitch_mtu(_host(networkSystem=ns), "vSwitch0", 9000)
    assert record.changed and record.before == "MTU 1500" and record.after == "MTU 9000"
    assert ns.calls[0][0] == "UpdateVirtualSwitch" and ns.calls[0][1]["spec"].mtu == 9000

    ns = FakeNetworkSystem([_vswitch(9000)], [])
    assert not writer.set_vswitch_mtu(_host(networkSystem=ns), "vSwitch0", 9000).changed
    assert ns.calls == []
    with pytest.raises(EsxiError, match="No standard switch"):
        writer.set_vswitch_mtu(_host(networkSystem=ns), "vSwitch9", 9000)


def test_trunk_port_group_is_created_with_accept_security() -> None:
    ns = FakeNetworkSystem([_vswitch(9000)], [])
    record = writer.ensure_portgroup(_host(networkSystem=ns), "Holodeck-Trunk", "vSwitch0", 4095, ACCEPT)
    assert record.changed and record.before == "absent"
    spec = ns.calls[0][1]["portgrp"]
    assert ns.calls[0][0] == "AddPortGroup" and spec.vlanId == 4095
    assert (
        spec.policy.security.allowPromiscuous,
        spec.policy.security.macChanges,
        spec.policy.security.forgedTransmits,
    ) == (True, True, True)


def test_existing_port_group_is_fixed_or_left_alone() -> None:
    ns = FakeNetworkSystem([_vswitch(9000)], [_portgroup("Holodeck-Trunk", 4095, promiscuous=False)])
    record = writer.ensure_portgroup(_host(networkSystem=ns), "Holodeck-Trunk", "vSwitch0", 4095, ACCEPT)
    assert record.changed and "Reject" in record.before and ns.calls[0][0] == "UpdatePortGroup"

    ns = FakeNetworkSystem([_vswitch(9000)], [_portgroup("Holodeck-Trunk", 4095, promiscuous=True)])
    assert not writer.ensure_portgroup(
        _host(networkSystem=ns), "Holodeck-Trunk", "vSwitch0", 4095, ACCEPT
    ).changed
    assert ns.calls == []


def test_ntp_policy_only_fix_does_not_restart_the_service() -> None:
    calls: list[str] = []
    svc = NS(
        serviceInfo=NS(service=[NS(key="ntpd", running=True, policy="off")]),
        UpdateServicePolicy=lambda **kw: calls.append(f"policy:{kw['policy']}"),
        StartService=lambda **kw: calls.append("start"),
        RestartService=lambda **kw: calls.append("restart"),
    )
    host = _host(
        serviceSystem=svc, dateTimeSystem=NS(UpdateDateTimeConfig=lambda **kw: calls.append("servers"))
    )
    host.config = NS(dateTimeInfo=NS(ntpConfig=NS(server=["pool.ntp.org"])))
    record = writer.configure_ntp(host, ["pool.ntp.org"], "on")
    assert record.changed and calls == ["policy:on"]


def _storage_host(available: list[Any], partitions: int) -> tuple[Any, list[Any]]:
    created: list[Any] = []
    option = NS(spec=NS(vmfs=NS(volumeName=None)))
    ds_sys = NS(
        QueryAvailableDisksForVmfs=lambda: available,
        QueryVmfsDatastoreCreateOptions=lambda devicePath: [option],
        CreateVmfsDatastore=lambda spec: created.append(spec),
    )
    storage = NS(RetrieveDiskPartitionInfo=lambda devicePath: [NS(spec=NS(partition=[1] * partitions))])
    return _host(datastoreSystem=ds_sys, storageSystem=storage), created


def test_formatting_only_happens_on_a_disk_that_is_still_unused() -> None:
    disk = NS(canonicalName="t10.NVMe_X", devicePath="/vmfs/devices/disks/t10.NVMe_X")
    host, created = _storage_host([disk], partitions=0)
    record = writer.create_vmfs_datastore(host, "t10.NVMe_X", "holodeck")
    assert record.changed and created[0].vmfs.volumeName == "holodeck"

    host, created = _storage_host([], partitions=0)  # someone used the disk since the assessment
    with pytest.raises(EsxiError, match="no longer available"):
        writer.create_vmfs_datastore(host, "t10.NVMe_X", "holodeck")
    host, created = _storage_host([disk], partitions=2)
    with pytest.raises(EsxiError, match="now has 2 partitions"):
        writer.create_vmfs_datastore(host, "t10.NVMe_X", "holodeck")
    assert created == []
