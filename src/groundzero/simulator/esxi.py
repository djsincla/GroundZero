"""A simulated ESXi host for demo/simulation mode and black-box functional tests.

Starts from recorded captures (network, storage, version). When the simulated BMC "boots the
installer", the host goes down and comes back with whatever the installer ISO's KS.CFG says:
the build from .DISCINFO and the management network from the kickstart. A wrong kickstart
therefore shows up as a failed post-install validation, not a silent pass.
"""

from __future__ import annotations

import asyncio
import io
import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pycdlib

from groundzero.core.models import OsAccess
from groundzero.esxi import ovf
from groundzero.esxi.models import (
    ChangeRecord,
    Datastore,
    EsxiAbout,
    EsxiNetworkConfig,
    EsxiStorage,
    JumboProbe,
    JumboResult,
    PortGroup,
    SecurityPolicy,
    VmkInterface,
)
from groundzero.esxi.ovf import OvaDeployResult
from groundzero.esxi.reader import EsxiError


def _read_iso_file(iso_bytes: bytes, path: str) -> str:
    iso = pycdlib.PyCdlib()
    iso.open_fp(io.BytesIO(iso_bytes))
    try:
        buf = io.BytesIO()
        iso.get_file_from_iso_fp(buf, iso_path=path)
        return buf.getvalue().decode()
    finally:
        iso.close()


def _options(line: str) -> dict[str, str]:
    opts: dict[str, str] = {}
    for token in shlex.split(line)[1:]:
        key, _, value = token.removeprefix("--").partition("=")
        opts[key] = value
    return opts


class SimulatedEsxi:
    def __init__(
        self,
        capture_dir: Path,
        *,
        boot_delay: float = 0.5,
        unreachable_until_installed: bool = False,
        faults: frozenset[str] = frozenset(),
    ) -> None:
        """``unreachable_until_installed``: the host answers nothing until the simulated installer has run."""
        self.unreachable = unreachable_until_installed
        self.faults = faults  # ntp-fails, datastore-create-fails, jumbo-drops
        self.changes: list[ChangeRecord] = []
        self.vms: dict[str, dict[str, Any]] = {}  # deployed appliances (e.g. the Holorouter)
        self.network = EsxiNetworkConfig.model_validate_json((capture_dir / "network.json").read_text())
        self.storage = EsxiStorage.model_validate_json((capture_dir / "storage.json").read_text())
        self.about: EsxiAbout | None = EsxiAbout.model_validate_json((capture_dir / "about.json").read_text())
        self.boot_delay = boot_delay
        self.installs = 0
        self._previous: EsxiAbout | None = self.about

    # ── EsxiOps ──────────────────────────────────────────────────────────
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
        self._reachable(access.address)
        return self.network.model_copy(update={"address": access.address})

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage:
        self._reachable(access.address)
        return self.storage.model_copy(deep=True)

    async def probe(self, address: str) -> EsxiAbout | None:
        return None if self.unreachable else self.about

    async def apply(
        self, access: OsAccess, password: str, action: str, params: dict[str, Any]
    ) -> ChangeRecord:
        """Host-prep actions against the simulated host's state (same idempotency as the real writer)."""
        self._reachable(access.address)
        net = self.network
        if action == "set_mtu":
            vs = next((v for v in net.vswitches if v.name == params["vswitch"]), None)
            if vs is None:
                raise EsxiError(f"No standard switch named {params['vswitch']}")
            before = f"MTU {vs.mtu}"
            record = ChangeRecord(
                action=action,
                target=vs.name,
                changed=vs.mtu != params["mtu"],
                before=before,
                after=f"MTU {params['mtu']}",
            )
            vs.mtu = int(params["mtu"])
        elif action == "ensure_portgroup":
            keys = ("allow_promiscuous", "mac_changes", "forged_transmits")
            existing = next((p for p in net.portgroups if p.name == params["name"]), None)
            security = (
                SecurityPolicy(**{k: params[k] for k in keys if k in params})
                if any(k in params for k in keys)
                else SecurityPolicy()
            )
            wanted = PortGroup(
                name=params["name"], vlan_id=int(params["vlan"]), vswitch=params["vswitch"], security=security
            )
            same = (
                existing is not None
                and existing.vlan_id == wanted.vlan_id
                and (not any(k in params for k in keys) or existing.security == security)
            )
            record = ChangeRecord(
                action=action,
                target=f"{wanted.name} on {wanted.vswitch}",
                changed=not same,
                before="absent" if existing is None else f"VLAN {existing.vlan_id}",
                after=f"VLAN {wanted.vlan_id}",
            )
            if not same:
                net.portgroups = [p for p in net.portgroups if p.name != wanted.name] + [wanted]
                for vs in net.vswitches:
                    if vs.name == wanted.vswitch and wanted.name not in vs.portgroups:
                        vs.portgroups.append(wanted.name)
        elif action == "configure_ntp":
            if "ntp-fails" in self.faults:
                raise EsxiError("Simulated fault: ntpd failed to start")
            servers = ",".join(net.ntp_servers) or "none"
            before = f"servers={servers} running={net.ntp_running} policy={net.ntp_policy}"
            changed = (net.ntp_servers, net.ntp_running, net.ntp_policy) != (
                params["servers"],
                True,
                params["policy"],
            )
            net.ntp_servers, net.ntp_running, net.ntp_policy = list(params["servers"]), True, params["policy"]
            record = ChangeRecord(
                action=action,
                target="ntpd",
                changed=changed,
                before=before,
                after=f"servers={','.join(net.ntp_servers)} running=True policy={net.ntp_policy}",
            )
        elif action == "create_datastore":
            if "datastore-create-fails" in self.faults:
                raise EsxiError("Simulated fault: CreateVmfsDatastore failed")
            disk = next((d for d in self.storage.disks if d.name == params["disk"]), None)
            if disk is None or not disk.unused:
                raise EsxiError(
                    f"Disk {params['disk']} is no longer available for a new datastore; assess again"
                )
            self.storage.datastores.append(
                Datastore(
                    name=params["name"],
                    type="VMFS",
                    capacity_gb=disk.capacity_gb,
                    free_gb=round(disk.capacity_gb * 0.99, 1),
                    ssd=disk.ssd,
                    local=True,
                    disks=[disk.name],
                )
            )
            disk.datastores, disk.partitions = [params["name"]], 1
            record = ChangeRecord(
                action=action,
                target=params["name"],
                changed=True,
                before=f"{disk.name}: unused",
                after=f"VMFS datastore {params['name']} on {disk.name}",
            )
        else:
            raise EsxiError(f"Unknown host-prep action {action}")
        self.changes.append(record)
        return record

    async def verify_jumbo(
        self,
        access: OsAccess,
        password: str,
        *,
        vswitch: str,
        uplinks: tuple[str, str],
        vlan: int,
        mtu: int,
        pinned_ssh_key: str | None,
        log: Callable[[str], None],
    ) -> JumboResult:
        self._reachable(access.address)
        vs = next((v for v in self.network.vswitches if v.name == vswitch), None)
        if vs is None or (vs.mtu or 1500) < mtu:
            raise EsxiError(f"{vswitch} MTU is {vs.mtu if vs else '?'}; set it to {mtu} first (Prepare host)")
        drops = "jumbo-drops" in self.faults
        log(f"Simulated loop test {uplinks[0]} ↔ {uplinks[1]} on VLAN {vlan}")
        probes = [
            JumboProbe(
                label="1500-byte frames A→B",
                command="vmkping -s 1472",
                expect_success=True,
                exit_code=0,
                passed=True,
                output="3 packets transmitted, 3 packets received",
            ),
            JumboProbe(
                label=f"{mtu}-byte frames A→B",
                command=f"vmkping -s {mtu - 28}",
                expect_success=True,
                exit_code=1 if drops else 0,
                passed=not drops,
                output="3 packets transmitted, 0 packets received"
                if drops
                else "3 packets transmitted, 3 packets received",
            ),
        ]
        ok = all(p.passed for p in probes)
        summary = (
            f"{mtu}-byte frames pass {uplinks[0]} ↔ {uplinks[1]} through the switch on VLAN {vlan}"
            if ok
            else f"{mtu}-byte frames do not pass through the switch: check jumbo frames on the switch ports"
        )
        return JumboResult(
            ok=ok,
            summary=summary,
            vswitch=vswitch,
            uplinks=list(uplinks),
            vlan=vlan,
            mtu=mtu,
            probes=probes,
            restored=True,
            ssh_host_key="SHA256:simulated-host-key",
        )

    async def deploy_ova(
        self,
        access: OsAccess,
        password: str,
        ova: Path,
        *,
        vm_name: str,
        datastore: str,
        networks: dict[str, str],
        properties: dict[str, str],
        progress: Callable[[float, str], None],
        replace: bool = False,
    ) -> OvaDeployResult:
        self._reachable(access.address)
        # Like the real host: the OVA's descriptor decides which properties exist (undeclared keys fail)
        properties = ovf.qualify_properties(ovf.read_descriptor(ova)[0], properties)
        replaced = False
        if vm_name in self.vms:
            if not replace:
                return OvaDeployResult(
                    vm_name=vm_name,
                    created=False,
                    powered_on=True,
                    message=f"{vm_name} already exists; left as is",
                )
            del self.vms[vm_name]
            replaced = True
        if not any(d.name == datastore for d in self.storage.datastores):
            raise EsxiError(f"Datastore {datastore} not found on the host")
        missing = sorted(
            pg for pg in networks.values() if pg not in {p.name for p in self.network.portgroups}
        )
        if missing:
            raise EsxiError(f"Port group(s) not found on the host: {', '.join(missing)}")
        size = ova.stat().st_size
        progress(0.5, f"Uploading {size / 1e9:.2f} GB (simulated)")
        self.vms[vm_name] = {
            "ova": ova.name,
            "datastore": datastore,
            "networks": networks,
            "properties": properties,
        }
        return OvaDeployResult(
            vm_name=vm_name, created=True, powered_on=True, uploaded_bytes=size, replaced=replaced
        )

    def _reachable(self, address: str) -> None:
        if self.unreachable or self.about is None:
            raise EsxiError(f"Cannot connect to ESXi at {address}: simulated host is not answering")

    # ── driven by the simulated BMC ──────────────────────────────────────
    def power_off(self) -> None:
        if self.about is not None:
            self._previous = self.about
        self.about = None

    async def boot_existing(self, previous: EsxiAbout) -> None:
        await asyncio.sleep(self.boot_delay)
        self.about = previous

    async def reject_kickstart(self) -> None:
        """The installer hit a kickstart error and rebooted: the host returns on its previous build."""
        await asyncio.sleep(self.boot_delay)
        self.about = self._previous

    async def run_installer(self, iso_bytes: bytes) -> None:
        """Apply the kickstart on the ISO the way the real installer would, then come up."""
        ks = _read_iso_file(iso_bytes, "/KS.CFG;1")
        discinfo = _read_iso_file(iso_bytes, "/.DISCINFO;1")
        m = re.search(r"Version:\s*(\d+\.\d+\.\d+)-\d+\.(\d+)", discinfo)
        version, build = (m.group(1), m.group(2)) if m else ("0.0.0", "0")
        await asyncio.sleep(self.boot_delay)

        lines = ks.splitlines()
        install = _options(next(ln for ln in lines if ln.startswith("install ")))
        net = _options(next(ln for ln in lines if ln.startswith("network ")))
        firstboot = ks.split("%firstboot", 1)[1] if "%firstboot" in ks else ""
        extra = re.findall(r"uplink add -u (vmnic\d+) -v vSwitch0", firstboot)
        ntp = re.findall(r"--server=(\S+)", firstboot)

        portgroups = [
            p.model_copy(
                update={"vlan_id": int(net.get("vlanid", 0)), "active_uplinks": [net["device"], *extra]}
            )
            for p in self.network.portgroups
            if p.name == "Management Network"
        ]
        old_mgmt = self.network.management
        self.network = self.network.model_copy(
            update={
                "product": f"VMware ESXi {version}",
                "version": version,
                "build": build,
                "hostname": net["hostname"],
                "default_gateway": net["gateway"],
                "dns_servers": net["nameserver"].split(","),
                "ntp_servers": ntp,
                "ntp_running": bool(
                    ntp
                ),  # firstboot starts ntpd but leaves its startup policy off (seen live)
                "ntp_policy": "off" if ntp else None,
                "portgroups": portgroups,  # a fresh install has only the management network
                "vmkernel": [
                    VmkInterface(
                        device="vmk0",
                        portgroup="Management Network",
                        ip=net["ip"],
                        netmask=net["netmask"],
                        mac=old_mgmt.mac if old_mgmt else None,
                        mtu=1500,
                        services=["management"],
                    )
                ],
            }
        )
        if "overwritevmfs" in install and "disk" in install:
            disk = install["disk"]
            self.storage = self.storage.model_copy(
                update={
                    "datastores": [
                        d for d in self.storage.datastores if disk not in d.disks or d.type != "VMFS"
                    ]
                }
            )
        self.about = EsxiAbout(product=f"VMware ESXi {version}", version=version, build=build)
        self.installs += 1
        self.unreachable = False
