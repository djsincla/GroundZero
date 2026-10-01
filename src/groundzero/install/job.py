"""Unattended ESXi (re)install of one host, end to end.

Safety properties:
- The spec is derived from the running host (network, boot disk), so the reinstall keeps its identity.
- Refuses to start on a preflight FAIL or if foreign virtual media is mounted.
- The disk is only touched once the installer has booted from *our* ISO (proven by the media
  fetch log). If the host comes back on its old build without reading the ISO, the job stops.
- Media is always ejected and its URL revoked, even on failure.
- Every BMC write is recorded in the result.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import BmcAudit, Host, OsAccess
from groundzero.esxi.models import EsxiAbout, EsxiNetworkConfig, EsxiStorage
from groundzero.esxi.ops import EsxiOps
from groundzero.install.crypt import sha512_crypt
from groundzero.install.iso import build_install_iso, inspect_iso
from groundzero.install.kickstart import render_kickstart
from groundzero.install.spec import InstallSpec, ManagementNetwork
from groundzero.inventory.collect import collect_inventory
from groundzero.media.registry import MediaRegistry, media_url, source_address_towards
from groundzero.preflight.evaluate import CheckStatus, evaluate
from groundzero.redfish import actions
from groundzero.redfish.capabilities import VirtualMediaSlot, discover_capabilities
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import detect
from groundzero.redfish.oem import profile_for

logger = logging.getLogger(__name__)

# The installer pulls well over this from the ISO; a mount alone reads only a few hundred KB.
INSTALLER_BOOT_BYTES = 32 * 1024 * 1024


def installer_boot_threshold(iso_size: int) -> int:
    """Bytes the BMC must have read before we believe the installer (not a mount probe) is running."""
    return min(INSTALLER_BOOT_BYTES, iso_size // 2)


class InstallError(Exception):
    error_type = "install_failed"


class InstallRequest(BaseModel):
    iso_path: str = Field(description="Stock ESXi installer ISO on the GroundZero host")
    confirm: str = Field(description='Must be exactly "install <host name>"')
    ntp_servers: list[str] = Field(default_factory=lambda: ["pool.ntp.org"])
    wipe_install_disk_vmfs: bool = Field(default=False, description="Overwrite VMFS on the install disk")
    allow_legacy_cpu: bool | None = Field(default=None, description="Default: on if preflight flags the CPU")
    profile: str = "holodeck-9"
    variant: str | None = None
    timeout_minutes: int = Field(default=90, ge=10, le=240)


class InstallTimings(BaseModel):
    poll_seconds: float = 20.0
    action_timeout: float = 180.0
    installer_boot_minutes: float = 20.0


class ValidationCheck(BaseModel):
    name: str
    ok: bool
    expected: str
    observed: str


class InstallReport(BaseModel):
    host: str
    iso_version: str | None
    iso_build: str | None
    previous_build: str | None
    installed_build: str | None = None
    spec: dict[str, Any]
    media_url_host: str
    media_bytes_served: int = 0
    reset_type: str | None = None
    boot_method: str | None = None
    validation: list[ValidationCheck] = Field(default_factory=list)
    bmc_audit: BmcAudit | None = None
    durations_s: dict[str, float] = Field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return all(c.ok for c in self.validation)


def derive_spec(
    network: EsxiNetworkConfig, storage: EsxiStorage, req: InstallRequest, legacy_cpu: bool, password: str
) -> InstallSpec:
    mgmt = network.management
    if mgmt is None or not mgmt.ip or not mgmt.netmask or mgmt.dhcp:
        raise InstallError("Current management vmk has no static IPv4 configuration to preserve")
    if not network.hostname or not network.default_gateway or not network.dns_servers:
        raise InstallError("Current host is missing hostname, gateway or DNS; cannot derive install network")
    install_nic = network.install_nic()
    if install_nic is None:
        raise InstallError("Cannot determine the management uplink to install on")
    if storage.boot_disk is None:
        raise InstallError("Cannot determine the current boot disk (no OSDATA volume found)")
    return InstallSpec(
        install_disk=storage.boot_disk,
        preserve_vmfs=not req.wipe_install_disk_vmfs,
        allow_legacy_cpu=legacy_cpu,
        root_password_hash=sha512_crypt(password),
        network=ManagementNetwork(
            hostname=network.hostname,
            ip=mgmt.ip,
            netmask=mgmt.netmask,
            gateway=network.default_gateway,
            nameservers=network.dns_servers,
            vlan_id=network.management_vlan(),
            install_nic=install_nic,
            extra_uplinks=[n for n in network.management_uplinks() if n != install_nic],
        ),
        ntp_servers=req.ntp_servers,
    )


def validate_install(
    spec: InstallSpec,
    expected_build: str | None,
    about: EsxiAbout | None,
    network: EsxiNetworkConfig,
    storage: EsxiStorage,
    before: EsxiStorage,
) -> list[ValidationCheck]:
    net = spec.network
    mgmt = network.management
    expected_vmfs = before.vmfs_names
    if spec.preserve_vmfs is False:  # a wiped install disk loses its VMFS by design
        expected_vmfs = [
            d.name for d in before.datastores if d.type == "VMFS" and spec.install_disk not in d.disks
        ]
    missing = sorted(set(expected_vmfs) - set(storage.vmfs_names))
    uplinks = sorted([net.install_nic, *net.extra_uplinks])

    def check(name: str, ok: bool, expected: object, observed: object) -> ValidationCheck:
        return ValidationCheck(name=name, ok=ok, expected=str(expected), observed=str(observed))

    return [
        check(
            "esxi.build", bool(about and about.build == expected_build), expected_build, about and about.build
        ),
        check("mgmt.ip", bool(mgmt and mgmt.ip == net.ip), net.ip, mgmt and mgmt.ip),
        check("mgmt.vlan", network.management_vlan() == net.vlan_id, net.vlan_id, network.management_vlan()),
        check(
            "mgmt.uplinks",
            sorted(network.management_uplinks()) == uplinks,
            uplinks,
            network.management_uplinks(),
        ),
        check("hostname", network.hostname == net.hostname, net.hostname, network.hostname),
        check(
            "ntp", set(spec.ntp_servers) <= set(network.ntp_servers), spec.ntp_servers, network.ntp_servers
        ),
        check(
            "datastores", not missing, expected_vmfs, f"missing {missing}" if missing else storage.vmfs_names
        ),
    ]


class Installer:
    def __init__(
        self,
        *,
        host: Host,
        bmc_password: str,
        os_access: OsAccess,
        os_password: str,
        request: InstallRequest,
        client_factory: Callable[[Host, str], RedfishClient],
        esxi: EsxiOps,
        media: MediaRegistry,
        media_dir: Path,
        media_base_url: str | None,
        media_port: int,
        timings: InstallTimings,
    ) -> None:
        self.host = host
        self.bmc_password = bmc_password
        self.access = os_access
        self.os_password = os_password
        self.req = request
        self.client_factory = client_factory
        self.esxi = esxi
        self.media = media
        self.media_dir = media_dir
        self.media_base_url = media_base_url
        self.media_port = media_port
        self.t = timings
        self.last_report: InstallReport | None = None

    async def run(self, ctx: JobContext) -> dict[str, Any]:
        started = time.monotonic()
        marks: dict[str, float] = {}

        def mark(name: str) -> None:
            marks[name] = round(time.monotonic() - started, 1)

        ctx.progress(0.02, f"Reading current configuration of {self.access.address}")
        network = await self.esxi.read_network(self.access, self.os_password)
        before = await self.esxi.read_storage(self.access, self.os_password)
        previous = await self.esxi.probe(self.access.address)

        ctx.progress(0.05, "Running preflight against the BMC")
        async with self.client_factory(self.host, self.bmc_password) as client:
            _, inventory = await collect_inventory(client)
        preflight = evaluate(inventory, self.req.profile, self.req.variant)
        if preflight.overall is CheckStatus.FAIL:
            failed = [c.id for c in preflight.checks if c.status is CheckStatus.FAIL]
            raise InstallError(f"Preflight failed ({', '.join(failed)}); refusing to install")
        cpu = next((c for c in preflight.checks if c.id == "cpu.generation"), None)
        legacy_cpu = self.req.allow_legacy_cpu
        if legacy_cpu is None:
            legacy_cpu = cpu is not None and cpu.status is CheckStatus.WARN

        spec = derive_spec(network, before, self.req, legacy_cpu, self.os_password)
        stock = Path(self.req.iso_path)
        iso_info = inspect_iso(stock)
        ctx.progress(0.08, f"Building installer ISO (ESXi {iso_info.version} build {iso_info.build})")
        built = self.media_dir / f"{ctx.job.id}-{spec.network.hostname}.iso"
        await asyncio.to_thread(build_install_iso, stock, built, render_kickstart(spec), spec.kernel_options)
        mark("iso_built")

        base = self.media_base_url or f"https://{source_address_towards(self.host.bmc_address)}"
        if not self.media_base_url and self.media_port != 443:
            base += f":{self.media_port}"
        token = self.media.publish(built, timedelta(minutes=self.req.timeout_minutes + 30), built.name)
        url = media_url(base, token, built.name)
        report = InstallReport(
            host=self.host.name,
            iso_version=iso_info.version,
            iso_build=iso_info.build,
            previous_build=previous.build if previous else None,
            spec=spec.model_dump(exclude={"root_password_hash"}),
            media_url_host=base,
        )
        self.last_report = report

        slot: VirtualMediaSlot | None = None
        async with self.client_factory(self.host, self.bmc_password) as client:
            try:
                identity = await detect(client)
                system = await client.get_json(identity.system_path)
                manager = await client.get_json(identity.manager_path) if identity.manager_path else None
                caps = await discover_capabilities(client, system, manager)
                profile = profile_for(identity.vendor)

                ctx.progress(0.12, "Mounting installer ISO and setting one-time boot")
                slot, report.boot_method = await actions.boot_once_from_virtual_cd(
                    client, identity, caps, profile, url, action_timeout=self.t.action_timeout
                )
                ctx.progress(0.15, "Restarting the host into the installer")
                report.reset_type = await actions.restart(client, identity, caps)
                mark("reset")

                threshold = installer_boot_threshold(built.stat().st_size)
                await self._wait_for_installer(ctx, token, report.previous_build, threshold)
                mark("installer_booted")
                await self._wait_for_new_build(ctx, iso_info.build, started)
                mark("esxi_up")
            finally:
                stats = self.media.stats(token)
                report.media_bytes_served = stats.bytes_served if stats else 0
                if slot is not None:
                    try:
                        await actions.eject(client, slot)
                    except Exception:
                        logger.exception("Could not eject installer media from %s", slot.path)
                self.media.revoke(token)
                report.bmc_audit = BmcAudit(
                    requests=len(client.request_log),
                    non_get=[f"{r.method} {r.path}" for r in client.request_log if r.method != "GET"],
                )

        ctx.progress(0.9, "Validating the installed host")
        report.validation = await self._validate(spec, iso_info.build, before)
        report.installed_build = next((c.observed for c in report.validation if c.name == "esxi.build"), None)
        mark("validated")
        report.durations_s = marks
        built.unlink(missing_ok=True)
        if not report.valid:
            failed = [c.name for c in report.validation if not c.ok]
            raise InstallError(f"ESXi installed but validation failed: {', '.join(failed)}")
        return {"install": report.model_dump(mode="json")}

    async def _wait_for_installer(
        self, ctx: JobContext, token: str, previous_build: str | None, threshold: int
    ) -> None:
        """The disk is safe until this returns: proves the host booted the ISO, not its old disk.

        Fails (without having installed anything) if the host goes down and comes back on its
        previous build while the ISO was barely read, i.e. the one-time CD boot did not take.
        """
        deadline = time.monotonic() + self.t.installer_boot_minutes * 60
        seen_down = False
        while time.monotonic() < deadline:
            served = self._served(token)
            if served >= threshold:
                ctx.progress(0.3, f"Installer booted from the ISO ({served // 2**20} MiB read)")
                return
            about = await self.esxi.probe(self.access.address)
            if about is None:
                seen_down = True
            elif seen_down and about.build == previous_build and self._served(token) < threshold:
                raise InstallError(
                    "Host restarted into its existing ESXi instead of the installer "
                    "(one-time virtual CD boot did not take). Nothing was installed."
                )
            state = "down, booting" if about is None else f"answering as build {about.build}"
            ctx.progress(0.2, f"Waiting for the installer to load: host {state}, {served // 2**20} MiB read")
            await asyncio.sleep(self.t.poll_seconds)
        raise InstallError("Host did not boot the installer ISO in time. Nothing was installed.")

    def _served(self, token: str) -> int:
        stats = self.media.stats(token)
        return stats.bytes_served if stats else 0

    async def _wait_for_new_build(self, ctx: JobContext, build: str | None, started: float) -> None:
        deadline = started + self.req.timeout_minutes * 60
        while time.monotonic() < deadline:
            about = await self.esxi.probe(self.access.address)
            if about and about.build == build:
                ctx.progress(0.85, f"ESXi {about.version} build {about.build} is up")
                return
            ctx.progress(0.5, "Installing ESXi (waiting for the host to come back on the new build)")
            await asyncio.sleep(self.t.poll_seconds)
        raise InstallError(
            f"Host did not come back on build {build} within {self.req.timeout_minutes} minutes"
        )

    async def _validate(
        self, spec: InstallSpec, build: str | None, before: EsxiStorage
    ) -> list[ValidationCheck]:
        # Firstboot (extra uplinks, NTP) runs shortly after hostd starts; give it a few polls to settle.
        checks: list[ValidationCheck] = []
        for _ in range(10):
            about = await self.esxi.probe(self.access.address)
            network = await self.esxi.read_network(self.access, self.os_password)
            storage = await self.esxi.read_storage(self.access, self.os_password)
            checks = validate_install(spec, build, about, network, storage, before)
            if all(c.ok for c in checks):
                break
            await asyncio.sleep(self.t.poll_seconds)
        return checks
