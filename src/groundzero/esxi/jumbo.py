"""Jumbo-frame loop test: 9000-byte frames out of one uplink and back in the other, through the switch.

The host's own MTU says nothing about the physical switch ports; this proves the whole path. Two test
vmkernel ports sit on *different* vSwitches (one per uplink) and different netstacks, so a ping between
them must leave the host on uplink A, cross the physical switch and come back on uplink B.

Temporary changes (made through the vSphere API, except the netstack/vmk/vmkping which need esxcli over
SSH) are always reverted: the vSwitch and port-group specs are captured before and written back after,
then compared. SSH is started only if it was off, and stopped again. The SSH host key is pinned like
the TLS certificate. Blocking: run in a worker thread.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

import paramiko

from groundzero.esxi.models import JumboProbe, JumboResult
from groundzero.esxi.reader import EsxiError

logger = logging.getLogger(__name__)

SCRATCH_VSWITCH = "gzMtuTest"
PG_A, PG_B = "gzMtuA", "gzMtuB"
VMK_A, VMK_B = "vmk10", "vmk11"
NETSTACK = "gzmtu"
IP_A, IP_B = "192.168.250.1", "192.168.250.2"


class SshHostKeyChangedError(EsxiError):
    error_type = "certificate_changed"


def key_fingerprint(key: paramiko.PKey) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


class _PinPolicy(paramiko.MissingHostKeyPolicy):
    """Trust on first use: accept and record the key, or require it to match the pinned fingerprint."""

    def __init__(self, pinned: str | None) -> None:
        self.pinned = pinned
        self.seen: str | None = None

    def missing_host_key(self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey) -> None:
        self.seen = key_fingerprint(key)
        if self.pinned and self.seen != self.pinned:
            raise SshHostKeyChangedError(
                f"The SSH host key of {hostname} is now {self.seen}, but {self.pinned} is pinned. "
                "No password was sent. If the host was reinstalled, re-trust it."
            )


class _Shell:
    def __init__(self, address: str, username: str, password: str, pinned: str | None) -> None:
        self.address, self.username, self.password = address, username, password
        self.policy = _PinPolicy(pinned)
        self.client: paramiko.SSHClient | None = None

    def connect(self) -> None:
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(self.policy)
        self.client.connect(
            self.address,
            username=self.username,
            password=self.password,
            timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )

    def run(self, cmd: str) -> tuple[int, str]:
        for attempt in range(3):
            try:
                if self.client is None:
                    self.connect()
                assert self.client is not None
                _, out, err = self.client.exec_command(cmd, timeout=60)
                code = out.channel.recv_exit_status()
                return code, (out.read() + err.read()).decode(errors="replace").strip()
            except (paramiko.SSHException, OSError, EOFError):
                if attempt == 2:
                    raise
                time.sleep(5)  # an uplink change can drop the session briefly
                self.client = None
        raise AssertionError("unreachable")

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


def _network_state(ns: Any, vswitch: str) -> str:
    """A comparable description of the switch and its port groups (what the test may touch)."""
    info = ns.networkInfo
    lines = []
    for vs in info.vswitch or []:
        if vs.name in (vswitch, SCRATCH_VSWITCH):
            order = (
                vs.spec.policy.nicTeaming.nicOrder if vs.spec.policy and vs.spec.policy.nicTeaming else None
            )
            lines.append(
                f"vswitch {vs.name} mtu={vs.mtu} uplinks={list(vs.spec.bridge.nicDevice or [])} "
                f"active={list(order.activeNic or []) if order else []} "
                f"standby={list(order.standbyNic or []) if order else []}"
            )
    for pg in info.portgroup or []:
        if pg.spec.vswitchName in (vswitch, SCRATCH_VSWITCH):
            team = pg.spec.policy.nicTeaming if pg.spec.policy else None
            order = team.nicOrder if team else None
            lines.append(
                f"portgroup {pg.spec.name} vlan={pg.spec.vlanId} "
                f"active={list(order.activeNic or []) if order else None} "
                f"standby={list(order.standbyNic or []) if order else None}"
            )
    lines += [f"vmk {v.device} pg={v.portgroup}" for v in info.vnic or []]
    return "\n".join(sorted(lines))


def verify_jumbo(
    host: Any,
    address: str,
    username: str,
    password: str,
    *,
    vswitch: str,
    uplinks: tuple[str, str],
    vlan: int,
    mtu: int = 9000,
    pinned_ssh_key: str | None = None,
    log: Callable[[str], None] = logger.info,
) -> JumboResult:
    import pyVmomi

    vim: Any = pyVmomi.vim  # untyped library
    a, b = uplinks
    ns = host.configManager.networkSystem
    svc = host.configManager.serviceSystem
    original = ns.networkInfo  # never mutated: every change below works on a fresh copy
    switch = next((v for v in original.vswitch or [] if v.name == vswitch), None)
    if switch is None:
        raise EsxiError(f"No standard switch named {vswitch}")
    if (switch.mtu or 1500) < mtu:
        raise EsxiError(f"{vswitch} MTU is {switch.mtu}; set it to {mtu} first (Prepare host)")
    if not {a, b} <= set(switch.spec.bridge.nicDevice or []):
        raise EsxiError(f"{vswitch} does not have both {a} and {b} as uplinks")
    before = _network_state(ns, vswitch)
    original_pgs = {p.spec.name: p.spec for p in original.portgroup or [] if p.spec.vswitchName == vswitch}
    ssh = next((s for s in svc.serviceInfo.service or [] if s.key == "TSM-SSH"), None)
    started_ssh = False
    shell = _Shell(address, username, password, pinned_ssh_key)
    probes: list[JumboProbe] = []

    def fresh_pg(name: str) -> Any:
        return next(p.spec for p in ns.networkInfo.portgroup if p.spec.name == name)

    try:
        if ssh is not None and not ssh.running:
            log("Starting SSH for the test (stopped again afterwards)")
            svc.StartService(id="TSM-SSH")
            started_ssh = True
        shell.connect()

        log(f"Pinning every port group on {vswitch} to {a} while {b} is borrowed")
        for name in original_pgs:
            spec = fresh_pg(name)
            spec.policy.nicTeaming = spec.policy.nicTeaming or vim.host.NetworkPolicy.NicTeamingPolicy()
            spec.policy.nicTeaming.nicOrder = vim.host.NetworkPolicy.NicOrderPolicy(
                activeNic=[a], standbyNic=[]
            )
            ns.UpdatePortGroup(pgName=name, portgrp=spec)
        log(f"Moving {b} from {vswitch} to a scratch switch {SCRATCH_VSWITCH} (MTU {mtu})")
        vs_spec = next(v.spec for v in ns.networkInfo.vswitch if v.name == vswitch)
        vs_spec.bridge.nicDevice = [n for n in vs_spec.bridge.nicDevice if n != b]
        if vs_spec.policy and vs_spec.policy.nicTeaming and vs_spec.policy.nicTeaming.nicOrder:
            order = vs_spec.policy.nicTeaming.nicOrder
            order.activeNic = [n for n in order.activeNic or [] if n != b]
            order.standbyNic = [n for n in order.standbyNic or [] if n != b]
        ns.UpdateVirtualSwitch(vswitchName=vswitch, spec=vs_spec)
        ns.AddVirtualSwitch(
            vswitchName=SCRATCH_VSWITCH,
            spec=vim.host.VirtualSwitch.Specification(
                numPorts=128, mtu=mtu, bridge=vim.host.VirtualSwitch.BondBridge(nicDevice=[b])
            ),
        )
        team_a = vim.host.NetworkPolicy(
            nicTeaming=vim.host.NetworkPolicy.NicTeamingPolicy(
                nicOrder=vim.host.NetworkPolicy.NicOrderPolicy(activeNic=[a])
            )
        )
        ns.AddPortGroup(
            portgrp=vim.host.PortGroup.Specification(
                name=PG_A, vlanId=vlan, vswitchName=vswitch, policy=team_a
            )
        )
        ns.AddPortGroup(
            portgrp=vim.host.PortGroup.Specification(
                name=PG_B, vlanId=vlan, vswitchName=SCRATCH_VSWITCH, policy=vim.host.NetworkPolicy()
            )
        )
        log(f"Adding test vmkernel ports {VMK_A} ({IP_A}) and {VMK_B} ({IP_B}, netstack {NETSTACK})")
        for cmd in (
            f"esxcli network ip netstack add -N {NETSTACK}",
            f"esxcli network ip interface add -i {VMK_A} -p {PG_A} -m {mtu}",
            f"esxcli network ip interface ipv4 set -i {VMK_A} -I {IP_A} -N 255.255.255.0 -t static",
            f"esxcli network ip interface add -i {VMK_B} -p {PG_B} -m {mtu} -N {NETSTACK}",
            f"esxcli network ip interface ipv4 set -i {VMK_B} -I {IP_B} -N 255.255.255.0 -t static",
        ):
            code, out = shell.run(cmd)
            if code != 0:
                raise EsxiError(f"{cmd} failed ({code}): {out[:300]}")
        time.sleep(5)  # let the uplinks settle

        payload = mtu - 28  # IP + ICMP headers
        # Unscored warm-up: the first frames after the test ports appear are lost to ARP and switch MAC
        # learning (seen live: 1 of 3 replies), which says nothing about the MTU.
        shell.run(f"vmkping -I {VMK_A} -c 3 {IP_B}")
        for label, cmd, expect in [
            ("1500-byte frames A→B", f"vmkping -I {VMK_A} -d -s 1472 -c 3 {IP_B}", True),
            (f"{mtu}-byte frames A→B", f"vmkping -I {VMK_A} -d -s {payload} -c 3 {IP_B}", True),
            (f"{mtu}-byte frames B→A", f"vmkping -S {NETSTACK} -I {VMK_B} -d -s {payload} -c 3 {IP_A}", True),
            (
                f"{mtu + 1}-byte frames are refused",
                f"vmkping -I {VMK_A} -d -s {payload + 1} -c 2 {IP_B}",
                False,
            ),
        ]:
            code, out = shell.run(cmd)
            if expect and code != 0:  # one retry for a transient loss; a real MTU problem fails both times
                time.sleep(2)
                code, out = shell.run(cmd)
            summary = next((ln.strip() for ln in out.splitlines() if "packets transmitted" in ln), out[-200:])
            probes.append(
                JumboProbe(
                    label=label,
                    command=cmd,
                    expect_success=expect,
                    exit_code=code,
                    passed=(code == 0) == expect,
                    output=summary,
                )
            )
            log(f"{label}: {'ok' if probes[-1].passed else 'FAILED'} ({summary})")
    finally:
        log("Restoring the network configuration")
        for cmd in (
            f"esxcli network ip interface remove -i {VMK_B}",
            f"esxcli network ip interface remove -i {VMK_A}",
            f"esxcli network ip netstack remove -N {NETSTACK}",
        ):
            try:
                shell.run(cmd)
            except Exception as exc:  # noqa: BLE001 - keep restoring; the comparison below reports leftovers
                log(f"  {cmd}: {exc}")
        undos: list[Callable[[], object]] = [
            lambda: ns.RemovePortGroup(pgName=PG_A),
            lambda: ns.RemovePortGroup(pgName=PG_B),
            lambda: ns.RemoveVirtualSwitch(vswitchName=SCRATCH_VSWITCH),
            lambda: ns.UpdateVirtualSwitch(vswitchName=vswitch, spec=switch.spec),
        ]
        for undo in undos:
            try:
                undo()
            except vim.fault.NotFound:
                pass
            except Exception as exc:  # noqa: BLE001
                log(f"  restore step failed: {exc}")
        for name, spec in original_pgs.items():
            try:
                ns.UpdatePortGroup(pgName=name, portgrp=spec)
            except Exception as exc:  # noqa: BLE001
                log(f"  restoring port group {name} failed: {exc}")
        shell.close()
        if started_ssh:
            svc.StopService(id="TSM-SSH")
    time.sleep(3)
    after = _network_state(ns, vswitch)
    restored = after == before
    diff = None
    if not restored:
        import difflib

        diff = "\n".join(
            difflib.unified_diff(before.splitlines(), after.splitlines(), "before", "after", lineterm="")
        )
    ok = bool(probes) and all(p.passed for p in probes) and restored
    jumbo = next((p for p in probes if p.label.startswith(f"{mtu}-byte frames A")), None)
    summary = (
        f"{mtu}-byte frames pass {a} ↔ {b} through the switch on VLAN {vlan}"
        if ok
        else "Configuration was not fully restored"
        if not restored
        else f"{mtu}-byte frames do not pass through the switch: check jumbo frames on the switch ports "
        f"for {a} and {b}"
        if jumbo and not jumbo.passed
        else "The loop test did not pass; see the probes"
    )
    return JumboResult(
        ok=ok,
        summary=summary,
        vswitch=vswitch,
        uplinks=[a, b],
        vlan=vlan,
        mtu=mtu,
        probes=probes,
        restored=restored,
        diff=diff,
        ssh_host_key=shell.policy.seen,
    )
