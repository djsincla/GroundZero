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
from pathlib import Path

import pycdlib

from groundzero.core.models import OsAccess
from groundzero.esxi.models import EsxiAbout, EsxiNetworkConfig, EsxiStorage, VmkInterface


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
    def __init__(self, capture_dir: Path, *, boot_delay: float = 0.5) -> None:
        self.network = EsxiNetworkConfig.model_validate_json((capture_dir / "network.json").read_text())
        self.storage = EsxiStorage.model_validate_json((capture_dir / "storage.json").read_text())
        self.about: EsxiAbout | None = EsxiAbout.model_validate_json((capture_dir / "about.json").read_text())
        self.boot_delay = boot_delay
        self.installs = 0

    # ── EsxiOps ──────────────────────────────────────────────────────────
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
        return self.network.model_copy(update={"address": access.address})

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage:
        return self.storage.model_copy(deep=True)

    async def probe(self, address: str) -> EsxiAbout | None:
        return self.about

    # ── driven by the simulated BMC ──────────────────────────────────────
    def power_off(self) -> None:
        self.about = None

    async def boot_existing(self, previous: EsxiAbout) -> None:
        await asyncio.sleep(self.boot_delay)
        self.about = previous

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
                "hostname": net["hostname"],
                "default_gateway": net["gateway"],
                "dns_servers": net["nameserver"].split(","),
                "ntp_servers": ntp,
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
        if "overwritevmfs" in install:
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
