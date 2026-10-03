"""Jumbo-frame loop test against a fake host whose network really changes: it must restore everything."""

from __future__ import annotations

import copy
from types import SimpleNamespace as NS
from typing import Any

import paramiko
import pytest
from pyVmomi import vim

from groundzero.esxi import jumbo


def _team(active: list[str], standby: list[str] | None = None) -> Any:
    return vim.host.NetworkPolicy.NicTeamingPolicy(
        nicOrder=vim.host.NetworkPolicy.NicOrderPolicy(activeNic=active, standbyNic=standby or [])
    )


class FakeNetwork:
    """networkInfo returns a fresh copy each time, like the real property; methods change the state."""

    def __init__(self) -> None:
        vs0 = NS(
            name="vSwitch0",
            mtu=9000,
            spec=vim.host.VirtualSwitch.Specification(
                numPorts=128,
                mtu=9000,
                bridge=vim.host.VirtualSwitch.BondBridge(nicDevice=["vmnic0", "vmnic1"]),
                policy=vim.host.NetworkPolicy(nicTeaming=_team(["vmnic0", "vmnic1"])),
            ),
        )
        pgs = [
            NS(
                spec=vim.host.PortGroup.Specification(
                    name=n, vlanId=v, vswitchName="vSwitch0", policy=vim.host.NetworkPolicy()
                )
            )
            for n, v in (("Management Network", 100), ("Holodeck-Trunk", 4095))
        ]
        self.state = {
            "vswitch": [vs0],
            "portgroup": pgs,
            "vnic": [NS(device="vmk0", portgroup="Management Network")],
        }

    @property
    def networkInfo(self) -> Any:
        return NS(**copy.deepcopy(self.state))

    def UpdatePortGroup(self, pgName: str, portgrp: Any) -> None:
        self.state["portgroup"] = [p for p in self.state["portgroup"] if p.spec.name != pgName] + [
            NS(spec=copy.deepcopy(portgrp))
        ]

    def AddPortGroup(self, portgrp: Any) -> None:
        self.state["portgroup"].append(NS(spec=copy.deepcopy(portgrp)))

    def RemovePortGroup(self, pgName: str) -> None:
        self.state["portgroup"] = [p for p in self.state["portgroup"] if p.spec.name != pgName]

    def UpdateVirtualSwitch(self, vswitchName: str, spec: Any) -> None:
        vs = next(v for v in self.state["vswitch"] if v.name == vswitchName)
        vs.spec, vs.mtu = copy.deepcopy(spec), spec.mtu

    def AddVirtualSwitch(self, vswitchName: str, spec: Any) -> None:
        self.state["vswitch"].append(NS(name=vswitchName, mtu=spec.mtu, spec=copy.deepcopy(spec)))

    def RemoveVirtualSwitch(self, vswitchName: str) -> None:
        self.state["vswitch"] = [v for v in self.state["vswitch"] if v.name != vswitchName]


class FakeShell:
    def __init__(self, *args: Any, drops: bool = False, learning: int = 2) -> None:
        self.policy = NS(seen="SHA256:fake")
        self.commands: list[str] = []
        self.drops = drops
        self.learning = learning  # the first pings are lost to ARP/MAC learning, as seen live

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def run(self, cmd: str) -> tuple[int, str]:
        self.commands.append(cmd)
        if cmd.startswith("vmkping"):
            if self.learning:
                self.learning -= 1
                return 1, "3 packets transmitted, 1 packets received, 66.6667% packet loss"
            size = int(cmd.split(" -s ")[1].split()[0]) if " -s " in cmd else 56
            ok = size <= 8972 and not (self.drops and size > 1472)
            return (0 if ok else 1), f"3 packets transmitted, {3 if ok else 0} packets received"
        return 0, ""


def _host(net: FakeNetwork, ssh_running: bool = False) -> tuple[Any, list[str]]:
    calls: list[str] = []
    svc = NS(
        serviceInfo=NS(service=[NS(key="TSM-SSH", running=ssh_running)]),
        StartService=lambda id: calls.append(f"start {id}"),
        StopService=lambda id: calls.append(f"stop {id}"),
    )
    return NS(configManager=NS(networkSystem=net, serviceSystem=svc)), calls


@pytest.mark.parametrize("drops", [False, True])
def test_loop_test_restores_the_network_exactly(monkeypatch: pytest.MonkeyPatch, drops: bool) -> None:
    net = FakeNetwork()
    before = jumbo._network_state(net, "vSwitch0")
    shells: list[FakeShell] = []
    monkeypatch.setattr(jumbo, "_Shell", lambda *a: shells.append(FakeShell(drops=drops)) or shells[-1])
    monkeypatch.setattr(jumbo.time, "sleep", lambda s: None)
    host, svc_calls = _host(net)

    result = jumbo.verify_jumbo(
        host,
        "10.0.0.1",
        "root",
        "pw",
        vswitch="vSwitch0",
        uplinks=("vmnic0", "vmnic1"),
        vlan=100,
        log=lambda m: None,
    )
    assert result.restored and jumbo._network_state(net, "vSwitch0") == before
    assert svc_calls == ["start TSM-SSH", "stop TSM-SSH"]  # SSH was off: on for the test only
    assert result.ok is not drops and result.ssh_host_key == "SHA256:fake"
    if drops:
        assert "do not pass through the switch" in result.summary
    else:
        assert [p.passed for p in result.probes] == [True, True, True, True]  # incl. 9001 refused
    cmds = shells[0].commands
    assert "esxcli network ip netstack remove -N gzmtu" in cmds and cmds[-1].startswith("esxcli network ip")


def test_mtu_must_be_set_before_the_test(monkeypatch: pytest.MonkeyPatch) -> None:
    net = FakeNetwork()
    net.state["vswitch"][0].mtu = 1500
    host, _ = _host(net)
    with pytest.raises(jumbo.EsxiError, match="set it to 9000 first"):
        jumbo.verify_jumbo(
            host, "h", "root", "pw", vswitch="vSwitch0", uplinks=("vmnic0", "vmnic1"), vlan=100
        )


def test_ssh_host_key_is_pinned() -> None:
    key = paramiko.RSAKey.generate(1024)
    policy = jumbo._PinPolicy(pinned=None)
    policy.missing_host_key(paramiko.SSHClient(), "h", key)  # first use: accepted and recorded
    assert policy.seen == jumbo.key_fingerprint(key)
    with pytest.raises(jumbo.SshHostKeyChangedError, match="No password was sent"):
        jumbo._PinPolicy(pinned="SHA256:something-else").missing_host_key(paramiko.SSHClient(), "h", key)
