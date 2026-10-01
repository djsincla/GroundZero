"""Lab diagnostic: jumbo-frame (MTU 9000) loop test vmnic0 <-> vmnic1 through the upstream switch.

Frames must cross the physical switch: the two test vmkernel ports sit on different vSwitches and
different netstacks. Every change is temporary and reverted in `finally`, then the config is diffed
against a snapshot.

Run after a fresh install (an expired ESXi evaluation rejects API/SSH changes with RestrictedVersion):
    GROUNDZERO_ESXI_HOST=192.0.2.101 uv run python tools/esxi_mtu_loop_test.py
To be folded into GroundZero's post-install validation job (M2).
"""

from __future__ import annotations

import os
import ssl
import sys
import time

import paramiko
from pydantic_settings import BaseSettings, SettingsConfigDict
from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

HOST = os.environ.get("GROUNDZERO_ESXI_HOST", "192.0.2.101")
VLAN = 100
A_IP, B_IP = "192.168.250.1", "192.168.250.2"


class E(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GROUNDZERO_ESXI_", env_file=".env", extra="ignore")
    username: str = "root"
    password: str


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


e = E()
si = SmartConnect(host=HOST, user=e.username, pwd=e.password, sslContext=ssl._create_unverified_context())
content = si.RetrieveContent()
view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
host = view.view[0]
view.Destroy()
svc = host.configManager.serviceSystem
ssh_before = next(s for s in svc.serviceInfo.service if s.key == "TSM-SSH")
log(f"SSH before: running={ssh_before.running} policy={ssh_before.policy}")


class Shell:
    def __init__(self) -> None:
        self.c: paramiko.SSHClient | None = None

    def connect(self) -> None:
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.c.connect(
            HOST, username=e.username, password=e.password, timeout=15, allow_agent=False, look_for_keys=False
        )

    def run(self, cmd: str, check: bool = True) -> tuple[int, str]:
        for attempt in range(3):
            try:
                assert self.c is not None
                _, out, err = self.c.exec_command(cmd, timeout=60)
                code = out.channel.recv_exit_status()
                text = (out.read() + err.read()).decode().strip()
                if check and code != 0:
                    raise RuntimeError(f"{cmd!r} -> {code}: {text}")
                return code, text
            except (paramiko.SSHException, OSError, EOFError):
                if attempt == 2:
                    raise
                log("  ssh session dropped (uplink reset?) - reconnecting")
                time.sleep(5)
                self.connect()
        raise AssertionError


def snapshot(sh: Shell) -> str:
    parts = [sh.run("esxcli network vswitch standard list")[1]]
    for pg in sh.run("esxcli network vswitch standard portgroup list")[1].splitlines()[2:]:
        name = pg.split("  ")[0].strip()
        parts.append(
            f"## {name}\n"
            + sh.run(f"esxcli network vswitch standard portgroup policy failover get -p '{name}'")[1]
        )
    parts.append(sh.run("esxcli network ip interface list")[1])
    parts.append(sh.run("esxcli network ip netstack list")[1])
    return "\n".join(parts)


ok = True
sh = Shell()
try:
    if not ssh_before.running:
        log("Enabling SSH temporarily")
        svc.StartService(id="TSM-SSH")
    sh.connect()
    before = snapshot(sh)
    log("Snapshot taken")

    steps = [
        (
            "Management Network: active vmnic0 only (temporarily)",
            "esxcli network vswitch standard portgroup policy failover set -p 'Management Network' -a vmnic0",
        ),
        (
            "Move vmnic1 off vSwitch0 (mgmt stays on vmnic0)",
            "esxcli network vswitch standard uplink remove -u vmnic1 -v vSwitch0",
        ),
        (
            "Create scratch vSwitch gzMtuTest (MTU 9000) with vmnic1",
            "esxcli network vswitch standard add -v gzMtuTest && esxcli network vswitch standard set -v gzMtuTest -m 9000 "
            "&& esxcli network vswitch standard uplink add -u vmnic1 -v gzMtuTest",
        ),
        (
            "Raise vSwitch0 MTU to 9000 (uplink may reset briefly)",
            "esxcli network vswitch standard set -v vSwitch0 -m 9000",
        ),
        (
            "Port group gzMtuA (VLAN 100, vmnic0 only) on vSwitch0",
            f"esxcli network vswitch standard portgroup add -p gzMtuA -v vSwitch0 && "
            f"esxcli network vswitch standard portgroup set -p gzMtuA -v {VLAN} && "
            f"esxcli network vswitch standard portgroup policy failover set -p gzMtuA -a vmnic0",
        ),
        (
            "Port group gzMtuB (VLAN 100) on gzMtuTest",
            f"esxcli network vswitch standard portgroup add -p gzMtuB -v gzMtuTest && "
            f"esxcli network vswitch standard portgroup set -p gzMtuB -v {VLAN}",
        ),
        ("Scratch netstack gzmtu", "esxcli network ip netstack add -N gzmtu"),
        (
            f"vmk10 {A_IP} MTU 9000 on gzMtuA (default netstack)",
            f"esxcli network ip interface add -i vmk10 -p gzMtuA -m 9000 && "
            f"esxcli network ip interface ipv4 set -i vmk10 -I {A_IP} -N 255.255.255.0 -t static",
        ),
        (
            f"vmk11 {B_IP} MTU 9000 on gzMtuB (netstack gzmtu)",
            f"esxcli network ip interface add -i vmk11 -p gzMtuB -m 9000 -N gzmtu && "
            f"esxcli network ip interface ipv4 set -i vmk11 -I {B_IP} -N 255.255.255.0 -t static",
        ),
    ]
    for title, cmd in steps:
        log(title)
        sh.run(cmd)
    time.sleep(5)

    log("Uplink link state:")
    print(sh.run("esxcli network nic list | egrep 'Name|vmnic0|vmnic1'")[1])
    results = {}
    for label, cmd in [
        ("A->B 1500 (1472 payload, DF)", f"vmkping -I vmk10 -d -s 1472 -c 3 {B_IP}"),
        ("A->B 9000 (8972 payload, DF)", f"vmkping -I vmk10 -d -s 8972 -c 3 {B_IP}"),
        ("B->A 9000 (8972 payload, DF)", f"vmkping -S gzmtu -I vmk11 -d -s 8972 -c 3 {A_IP}"),
        ("A->B 9001 frame must fail (8973, DF)", f"vmkping -I vmk10 -d -s 8973 -c 2 {B_IP}"),
    ]:
        code, out = sh.run(cmd, check=False)
        summary = next((ln.strip() for ln in out.splitlines() if "packets transmitted" in ln), out[-200:])
        results[label] = (code, summary)
        log(f"{label}: exit={code}  {summary}")
finally:
    log("Reverting")
    revert = [
        "esxcli network ip interface remove -i vmk11",
        "esxcli network ip interface remove -i vmk10",
        "esxcli network ip netstack remove -N gzmtu",
        "esxcli network vswitch standard portgroup remove -p gzMtuB -v gzMtuTest",
        "esxcli network vswitch standard portgroup remove -p gzMtuA -v vSwitch0",
        "esxcli network vswitch standard uplink remove -u vmnic1 -v gzMtuTest",
        "esxcli network vswitch standard remove -v gzMtuTest",
        "esxcli network vswitch standard uplink add -u vmnic1 -v vSwitch0",
        "esxcli network vswitch standard policy failover set -v vSwitch0 -a vmnic0 -s vmnic1",
        "esxcli network vswitch standard portgroup policy failover set -p 'Management Network' -a vmnic0,vmnic1",
        "esxcli network vswitch standard set -v vSwitch0 -m 1500",
    ]
    try:
        if sh.c is None:
            sh.connect()
        for cmd in revert:
            code, out = sh.run(cmd, check=False)
            if code != 0:
                log(f"  revert step returned {code}: {cmd} :: {out[:160]}")
        time.sleep(5)
        after = snapshot(sh)
        if after == before:
            log("Network config identical to snapshot")
        else:
            ok = False
            log("WARNING: config differs from snapshot:")
            import difflib

            print(
                "\n".join(
                    difflib.unified_diff(
                        before.splitlines(), after.splitlines(), "before", "after", lineterm=""
                    )
                )
            )
    finally:
        if not ssh_before.running:
            log("Disabling SSH again")
            svc.StopService(id="TSM-SSH")
        Disconnect(si)
sys.exit(0 if ok else 1)
