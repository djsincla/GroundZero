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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import BmcAudit, Host, OsAccess
from groundzero.core.store import utcnow
from groundzero.core.tls import CertificateChangedError
from groundzero.esxi.models import EsxiAbout, EsxiNetworkConfig, EsxiStorage
from groundzero.esxi.ops import EsxiOps
from groundzero.install.crypt import sha512_crypt
from groundzero.install.iso import build_install_iso, inspect_iso
from groundzero.install.kickstart import render_kickstart
from groundzero.install.spec import InstallSpec, ManagementNetwork
from groundzero.inventory.collect import collect_inventory
from groundzero.media.registry import MediaFetch, MediaRegistry, media_url, source_address_towards
from groundzero.osconfig.esxi import EsxiHostValues, EsxiPlugin, EsxiSettings
from groundzero.preflight.evaluate import CheckStatus, evaluate
from groundzero.redfish import actions
from groundzero.redfish.capabilities import VirtualMediaSlot, discover_capabilities
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.detect import detect
from groundzero.redfish.oem import profile_for

logger = logging.getLogger(__name__)

# The installer pulls well over this from the ISO; a mount alone reads only a few hundred KB.
INSTALLER_BOOT_BYTES = 32 * 1024 * 1024


INSTALL_STEPS = [
    ("snapshot", "Read the current OS"),
    ("bmc_check", "Check the BMC and hardware"),
    ("build", "Build the installer ISO"),
    ("mount", "Mount the ISO and set a one-time boot"),
    ("reset", "Restart into the installer"),
    ("boot", "Load the installer"),
    ("install", "Install ESXi"),
    ("validate", "Validate the installed host"),
]


def installer_boot_threshold(iso_size: int) -> int:
    """Bytes the BMC must have read before we believe the installer (not a mount probe) is running."""
    return min(INSTALLER_BOOT_BYTES, iso_size // 2)


class InstallError(Exception):
    error_type = "install_failed"


class InstallRequest(BaseModel):
    iso_id: str | None = Field(default=None, description="Stock ISO from the repository (GET /isos)")
    iso_path: str | None = Field(
        default=None, description="Alternative to iso_id: a path on the GroundZero host"
    )
    confirm: str = Field(description='Must be exactly "install <host name>"')
    config_set_id: str | None = Field(
        default=None,
        description="Config set to apply. Without one, settings are captured from the running OS "
        "(and ntp_servers / wipe_install_disk_vmfs / allow_legacy_cpu below apply).",
    )
    host_values: dict[str, Any] | None = Field(
        default=None, description="Per-server values (hostname, ip, ...); default: remembered for this host"
    )
    ntp_servers: list[str] = Field(default_factory=lambda: ["pool.ntp.org"])
    wipe_install_disk_vmfs: bool = Field(default=False, description="Overwrite VMFS on the install disk")
    allow_legacy_cpu: bool | None = Field(default=None, description="Default: on if preflight flags the CPU")
    profile: str = "holodeck-9"
    variant: str | None = None
    timeout_minutes: int = Field(default=90, ge=10, le=240)
    boot_method: Literal["auto", "cd", "uefi-target"] = Field(
        default="auto", description="How to request the one-time virtual CD boot (auto: vendor default)"
    )


class InstallTimings(BaseModel):
    poll_seconds: float = 20.0
    action_timeout: float = 180.0
    media_settle_seconds: float = 20.0
    cleanup_watch_seconds: float = 90.0
    media_attach_seconds: float = 600.0
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
    media_fetches: list[MediaFetch] = Field(
        default_factory=list, description="Every BMC request for the ISO (diagnoses boots that never read it)"
    )
    reset_at: datetime | None = None
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


def _on_install_disk(spec: InstallSpec, disks: list[str]) -> bool:
    if spec.install_disk:
        return spec.install_disk in disks
    tokens = [t.upper() for t in (spec.install_firstdisk or "").split(",") if t and t.lower() != "local"]
    return any(tok in disk.upper() for disk in disks for tok in tokens)


def validate_install(
    spec: InstallSpec,
    expected_build: str | None,
    about: EsxiAbout | None,
    network: EsxiNetworkConfig,
    storage: EsxiStorage,
    before: EsxiStorage | None,
) -> list[ValidationCheck]:
    net = spec.network
    mgmt = network.management
    expected_vmfs: list[str] = []
    if before is not None:
        expected_vmfs = before.vmfs_names
        if spec.preserve_vmfs is False:  # a wiped install disk loses its VMFS by design
            expected_vmfs = [
                d.name for d in before.datastores if d.type == "VMFS" and not _on_install_disk(spec, d.disks)
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
            "datastores",
            not missing,
            expected_vmfs
            if before is not None
            else "not checked: the OS was not readable before the install",
            f"missing {missing}" if missing else storage.vmfs_names,
        ),
    ]


class InstallConfig(BaseModel):
    """A resolved config set for one server: shared settings + per-server values + root password."""

    settings: EsxiSettings
    values: EsxiHostValues
    root_password: str


class Installer:
    def __init__(
        self,
        *,
        host: Host,
        bmc_password: str,
        os_access: OsAccess | None,
        os_password: str | None,
        resolve_os: Callable[[OsAccess], OsAccess] | None = None,
        repin_os: Callable[[OsAccess], OsAccess] | None = None,
        request: InstallRequest,
        config: InstallConfig | None = None,
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
        self._resolve_os = resolve_os or (lambda a: a)
        self._repin_os = repin_os or (lambda a: a)
        self.req = request
        self.config = config
        # The *new* OS is reached at the configured IP with the configured root password.
        if config is not None:
            self.new_access = OsAccess(address=config.values.ip, username="root", verify_tls=False)
            self.new_password = config.root_password
        else:
            assert os_access is not None and os_password is not None
            self.new_access, self.new_password = os_access, os_password
        self.client_factory = client_factory
        self.esxi = esxi
        self.media = media
        self.media_dir = media_dir
        self.media_base_url = media_base_url
        self.media_port = media_port
        self.t = timings
        self.last_report: InstallReport | None = None
        self.last_network: EsxiNetworkConfig | None = None  # the new OS as read during validation

    async def run(self, ctx: JobContext) -> dict[str, Any]:
        try:
            return await self._run(ctx)
        finally:
            # Built ISOs are ~700 MB each; never leave one behind, whatever happened.
            for leftover in self.media_dir.glob(f"{ctx.job.id}-*.iso*"):
                leftover.unlink(missing_ok=True)

    async def _run(self, ctx: JobContext) -> dict[str, Any]:
        started = time.monotonic()
        marks: dict[str, float] = {}

        def mark(name: str) -> None:
            marks[name] = round(time.monotonic() - started, 1)

        ctx.plan(INSTALL_STEPS)
        if self.access is None or self.os_password is None:
            ctx.skip("snapshot", "Read the current OS", "No OS access: installing from the config set only")
            network, before, previous = None, None, None
        else:
            async with ctx.step("snapshot", "Read the current OS"):
                network, before, previous = await self._snapshot(ctx)

        async with ctx.step("bmc_check", "Check the BMC and hardware"):
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

        if self.config is not None:
            spec = EsxiPlugin.build_spec(
                self.config.settings,
                self.config.values,
                root_password=self.config.root_password,
                legacy_cpu_detected=legacy_cpu,
                current_boot_disk=before.boot_disk if before else None,
            )
        else:
            if network is None or before is None or self.os_password is None:
                raise InstallError(
                    "Without a config set, the running OS must be reachable to capture its settings"
                )
            spec = derive_spec(network, before, self.req, legacy_cpu, self.os_password)
        if not self.req.iso_path:
            raise InstallError("No installer ISO resolved for this install")
        stock = Path(self.req.iso_path)
        async with ctx.step("build", "Build the installer ISO"):
            iso_info = inspect_iso(stock)
            ctx.progress(0.08, f"Building installer ISO (ESXi {iso_info.version} build {iso_info.build})")
            built = self.media_dir / f"{ctx.job.id}-{spec.network.hostname}.iso"
            await asyncio.to_thread(
                build_install_iso, stock, built, render_kickstart(spec), spec.kernel_options
            )
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

                async with ctx.step("mount", "Mount the ISO and set a one-time boot"):
                    ctx.progress(
                        0.12, "Mounting installer ISO, waiting for it to attach, setting one-time boot"
                    )
                    slot, report.boot_method = await actions.boot_once_from_virtual_cd(
                        client,
                        identity,
                        caps,
                        profile,
                        url,
                        action_timeout=self.t.action_timeout,
                        boot_method=self.req.boot_method,
                        settle_seconds=self.t.media_settle_seconds,
                        cleanup_watch_seconds=self.t.cleanup_watch_seconds,
                        attach_timeout=self.t.media_attach_seconds,
                    )
                async with ctx.step("reset", "Restart into the installer"):
                    ctx.progress(0.15, "Restarting the host into the installer")
                    report.reset_type = await actions.restart(client, identity, caps)
                    report.reset_at = utcnow()
                mark("reset")

                async with ctx.step("boot", "Load the installer"):
                    threshold = installer_boot_threshold(built.stat().st_size)
                    await self._wait_for_installer(ctx, token, report.previous_build, threshold)
                mark("installer_booted")
                async with ctx.step("install", "Install ESXi"):
                    await self._wait_for_new_build(ctx, iso_info.build, started, report.previous_build)
                    # A reinstall generates a new host certificate: trust it now that the new build answers.
                    self.new_access = await asyncio.to_thread(self._repin_os, self.new_access)
                mark("esxi_up")
            finally:
                stats = self.media.stats(token)
                report.media_bytes_served = stats.bytes_served if stats else 0
                report.media_fetches = self.media.fetches(token)[:2000]
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

        async with ctx.step("validate", "Validate the installed host"):
            ctx.progress(0.9, "Validating the installed host")
            report.validation = await self._validate(spec, iso_info.build, before)
            report.installed_build = next(
                (c.observed for c in report.validation if c.name == "esxi.build"), None
            )
            mark("validated")
            report.durations_s = marks
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
            about = await self.esxi.probe(self.new_access.address)
            if about is None:
                seen_down = True
            elif seen_down and about.build == previous_build and self._served(token) < threshold:
                raise InstallError(
                    "Host restarted into its existing ESXi instead of the installer "
                    "(one-time virtual CD boot did not take). Nothing was installed."
                )
            state = "down, booting" if about is None else f"answering as build {about.build}"
            requests = len(self.media.fetches(token))
            ctx.progress(
                0.2,
                f"Waiting for the installer to load: host {state}, {requests} ISO requests, "
                f"{served // 2**20} MiB read",
            )
            await asyncio.sleep(self.t.poll_seconds)
        raise InstallError("Host did not boot the installer ISO in time. Nothing was installed.")

    def _served(self, token: str) -> int:
        stats = self.media.stats(token)
        return stats.bytes_served if stats else 0

    async def _wait_for_new_build(
        self, ctx: JobContext, build: str | None, started: float, previous_build: str | None
    ) -> None:
        deadline = started + self.req.timeout_minutes * 60
        while time.monotonic() < deadline:
            about = await self.esxi.probe(self.new_access.address)
            if about and about.build == build:
                ctx.progress(0.85, f"ESXi {about.version} build {about.build} is up")
                return
            if about and previous_build and about.build == previous_build:
                # The installer ran but rebooted without installing (live run 8: kickstart parse error).
                raise InstallError(
                    f"The installer exited without installing: the host is back on its previous build "
                    f"{previous_build}. Check the server console for the installer's error message."
                )
            ctx.progress(0.5, "Installing ESXi (waiting for the host to come back on the new build)")
            await asyncio.sleep(self.t.poll_seconds)
        raise InstallError(
            f"Host did not come back on build {build} within {self.req.timeout_minutes} minutes"
        )

    async def _snapshot(
        self, ctx: JobContext
    ) -> tuple[EsxiNetworkConfig | None, EsxiStorage | None, EsxiAbout | None]:
        """Read the running OS. Optional with a config set: the install works without it."""
        if self.access is None or self.os_password is None:
            return None, None, None
        ctx.progress(0.02, f"Reading current configuration of {self.access.address}")
        try:
            target = await asyncio.to_thread(self._resolve_os, self.access)  # pinned certificate
            network = await self.esxi.read_network(target, self.os_password)
            before = await self.esxi.read_storage(target, self.os_password)
            previous = await self.esxi.probe(self.access.address)
        except CertificateChangedError:
            raise  # never proceed past a changed certificate, config set or not
        except Exception as exc:
            if self.config is None:
                raise
            logger.warning("Running OS not readable (%s); continuing from the config set", exc)
            return None, None, None
        return network, before, previous

    async def _validate(
        self, spec: InstallSpec, build: str | None, before: EsxiStorage | None
    ) -> list[ValidationCheck]:
        # Firstboot (extra uplinks, NTP) runs shortly after hostd starts; give it a few polls to settle.
        checks: list[ValidationCheck] = []
        for _ in range(10):
            about = await self.esxi.probe(self.new_access.address)
            network = await self.esxi.read_network(self.new_access, self.new_password)
            storage = await self.esxi.read_storage(self.new_access, self.new_password)
            self.last_network = network
            checks = validate_install(spec, build, about, network, storage, before)
            if all(c.ok for c in checks):
                break
            await asyncio.sleep(self.t.poll_seconds)
        return checks
