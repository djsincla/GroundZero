"""Application services: the single entry point used by the API (and therefore by every client).

HTTP handlers stay thin; everything here is plain Python that can be tested without a server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from groundzero import __version__
from groundzero.core import diagnostics
from groundzero.core.config import Settings
from groundzero.core.credentials import CredentialCipher
from groundzero.core.jobs import JobContext, JobRunner
from groundzero.core.models import (
    BmcAudit,
    ConfigSet,
    ConfigSetWrite,
    Host,
    HostCreate,
    Job,
    JobKind,
    OsAccess,
    OsAccessSet,
)
from groundzero.core.store import Store, utcnow
from groundzero.core.tasks import (
    CATALOG,
    TASKS,
    Pipeline,
    TaskInfo,
    TaskRun,
    evaluate_pipeline,
    info,
)
from groundzero.core.tls import PinnedCertificate, check_pin, fetch_certificate, fingerprint, pinned_context
from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage
from groundzero.esxi.ops import EsxiOps, LiveEsxiOps, OsTarget
from groundzero.install.job import InstallConfig, Installer, InstallRequest, InstallTimings
from groundzero.install.kickstart import render_kickstart
from groundzero.inventory.collect import collect_inventory
from groundzero.inventory.models import HostInventory
from groundzero.isos import IsoImage, IsoRepository
from groundzero.media.registry import MediaRegistry
from groundzero.osconfig import PLUGINS, OsConfigError, plugin_for
from groundzero.osconfig.esxi import EsxiHostValues, EsxiPlugin, EsxiSettings
from groundzero.preflight.evaluate import PreflightReport, UnknownProfileError, evaluate, load_profile
from groundzero.readiness import ReadinessReport, assess
from groundzero.redfish.capture import load_recording
from groundzero.redfish.client import RedfishClient
from groundzero.simulator.bmc import SimulatedBmc
from groundzero.simulator.esxi import SimulatedEsxi

logger = logging.getLogger(__name__)

ClientFactory = Callable[[Host, str], RedfishClient]


class NotFoundError(LookupError):
    error_type = "not_found"


class ConflictError(ValueError):
    error_type = "conflict"


class ConfirmationError(ValueError):
    error_type = "confirmation_required"


class SettingsValidationError(ValueError):
    """Settings failed the OS family's schema; carries field-level errors for the UI."""

    error_type = "validation_error"

    def __init__(self, where: str, exc: ValidationError) -> None:
        self.errors: list[dict[str, object]] = [
            {"loc": [where, *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        super().__init__(
            f"Invalid {where}: "
            + "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        )


class OsFamily(BaseModel):
    family: str
    title: str
    install_supported: bool
    settings_schema: dict[str, Any]
    host_values_schema: dict[str, Any]
    secret_fields: list[str]


class InstallPreview(BaseModel):
    """What a deployment would do, without touching the BMC or the server."""

    iso: IsoImage | None
    config_set: str | None
    spec: dict[str, Any]
    kickstart: str  # root password hash masked
    notes: list[str]


ASSESS_STEPS = [
    ("connect", "Connect to the OS"),
    ("network", "Read network and NTP"),
    ("storage", "Read disks and datastores"),
    ("evaluate", "Evaluate Holodeck readiness"),
]


class Services:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        runner: JobRunner,
        cipher: CredentialCipher,
        *,
        client_factory: ClientFactory | None = None,
        esxi: EsxiOps | None = None,
        media: MediaRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.media = media or MediaRegistry()
        self.store = store
        self.runner = runner
        self._cipher = cipher
        # Simulation mode (demos, black-box tests): one stateful BMC + ESXi pair shared by all clients.
        self.sim_esxi = (
            SimulatedEsxi(
                settings.simulate_esxi_dir,
                unreachable_until_installed="os-unreachable" in settings.simulate_faults,
                faults=frozenset(settings.simulate_faults),
            )
            if settings.simulate_esxi_dir
            else None
        )
        self.sim_bmc = (
            SimulatedBmc(
                load_recording(settings.simulate_bmc_dir),
                esxi=self.sim_esxi,
                faults=frozenset(settings.simulate_faults),
            )
            if settings.simulate_bmc_dir
            else None
        )
        self._client_factory = client_factory or self._default_client
        settings.ensure_home()
        self.isos = IsoRepository(settings.iso_dir, settings.home / "iso-cache.json")
        self.esxi: EsxiOps = esxi or self.sim_esxi or LiveEsxiOps()

    # ── hosts ────────────────────────────────────────────────────────────
    def add_host(self, req: HostCreate) -> Host:
        if self.store.find_host_by_address(req.bmc_address):
            raise ConflictError(f"A host with BMC address {req.bmc_address} is already registered")
        return self.store.add_host(
            name=req.name or req.bmc_address,
            bmc_address=req.bmc_address,
            username=req.username,
            secret=self._cipher.encrypt(req.password.get_secret_value()),
            verify_tls=req.verify_tls,
        )

    def get_host(self, host_id: str) -> Host:
        host = self.store.get_host(host_id)
        if host is None:
            raise NotFoundError(f"Host {host_id} not found")
        return host

    def list_hosts(self) -> list[Host]:
        return self.store.list_hosts()

    def delete_host(self, host_id: str) -> None:
        self.get_host(host_id)
        if self.runner.active_job(host_id):
            raise ConflictError(f"Host {host_id} has an active job; cancel it first")
        self.store.delete_host(host_id)

    def latest_output(self, host_id: str, kind: str) -> dict[str, Any]:
        self.get_host(host_id)
        meta = self.store.latest_output(host_id=host_id, kind=kind)
        if meta is None:
            raise NotFoundError(f"No {kind} for host {host_id} yet")
        return meta.data

    def latest_result(self, host_id: str, kind: JobKind) -> dict[str, Any]:
        self.get_host(host_id)
        result = self.store.latest_result(host_id=host_id, kind=kind.value)
        if result is None:
            raise NotFoundError(f"No {kind.value} result for host {host_id} yet")
        return result

    # ── installed OS ─────────────────────────────────────────────────────
    def set_os_access(self, host_id: str, req: OsAccessSet) -> OsAccess:
        self.get_host(host_id)
        access = OsAccess(address=req.address, username=req.username, verify_tls=req.verify_tls)
        self.store.set_os_access(host_id, access, self._cipher.encrypt(req.password.get_secret_value()))
        return access

    def get_os_access(self, host_id: str) -> OsAccess:
        return self._os_access(host_id)[0]

    def start_os_network(self, host_id: str) -> Job:
        access, secret = self._os_access(host_id)
        password = self._cipher.decrypt(secret)

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan([("connect", "Connect to the OS"), ("network", "Read network and NTP"),
                      ("storage", "Read disks and datastores")])  # fmt: skip
            async with ctx.step("connect", "Connect to the OS"):
                target = await asyncio.to_thread(self.os_target, host_id, access)
            async with ctx.step("network", "Read network and NTP"):
                ctx.progress(0.3, f"Reading network configuration from {access.address}")
                config = await self.esxi.read_network(target, password)
            async with ctx.step("storage", "Read disks and datastores"):
                ctx.progress(0.7, f"Reading storage from {access.address}")
                storage = await self.esxi.read_storage(target, password)
            data = config.model_dump(mode="json")
            self.store.save_result(
                host_id=host_id, kind=JobKind.OS_NETWORK.value, job_id=ctx.job.id, data=data
            )
            self.store.save_result(
                host_id=host_id, kind="os_storage", job_id=ctx.job.id, data=storage.model_dump(mode="json")
            )
            return {"os_network": data, "os_storage": storage.model_dump(mode="json")}

        return self.runner.submit(kind=JobKind.OS_NETWORK, host_id=host_id, params={}, func=run)

    def start_install(self, host_id: str, req: InstallRequest) -> Job:
        """Reinstall ESXi on the host. Destructive: requires the exact confirmation phrase."""
        host = self.get_host(host_id)
        expected = f"install {host.name}"
        if req.confirm != expected:
            raise ConfirmationError(f'Confirmation must be exactly "{expected}"')
        req = req.model_copy(update={"iso_path": str(self._resolve_iso(req))})
        profile = load_profile(req.profile)  # bad profile/variant is a 4xx, not a failed job
        if req.variant is not None and req.variant not in profile.variants:
            raise UnknownProfileError(
                f"Unknown variant '{req.variant}'; choose from {sorted(profile.variants)}"
            )
        stored_access = self.store.get_os_access(host_id)
        access = stored_access[0] if stored_access else None
        os_password = self._cipher.decrypt(stored_access[1]) if stored_access else None
        config = self._install_config(host, req, os_password)
        if config is None and access is None:
            raise NotFoundError(
                f"No OS access configured for host {host_id}; set it, or install with a config set"
            )
        if config is not None:
            self.store.set_host_values(host.id, EsxiPlugin.family, config.values.model_dump(mode="json"))
        installer = Installer(
            host=host,
            bmc_password=self._cipher.decrypt(self._secret(host.id)),
            os_access=access,
            resolve_os=lambda a: self.os_target(host.id, a),
            repin_os=lambda a: self.os_target(host.id, a, repin=True),
            os_password=os_password,
            request=req,
            config=config,
            client_factory=self._client_factory,
            esxi=self.esxi,
            media=self.media,
            media_dir=self.settings.media_dir,
            media_base_url=self.settings.media_public_url,
            media_port=self.settings.media_port,
            timings=InstallTimings(
                poll_seconds=self.settings.install_poll_seconds,
                action_timeout=self.settings.redfish_action_timeout,
                media_settle_seconds=self.settings.media_settle_seconds,
                cleanup_watch_seconds=self.settings.media_cleanup_watch_seconds,
                media_attach_seconds=self.settings.media_attach_seconds,
                installer_boot_minutes=self.settings.installer_boot_minutes,
            ),
        )

        async def run(ctx: JobContext) -> dict[str, Any]:
            try:
                result = await installer.run(ctx)
                # A new OS: anything read from the previous one (network, readiness, prep) is now stale,
                # and it has a new SSH host key (the TLS certificate was re-pinned during the install).
                self.store.bump_os_epoch(host.id)
                self.store.delete_pin(host.id, "os-ssh")
                if installer.last_network is not None:
                    # Keep the host's "installed OS" view current without an extra read.
                    self.store.save_result(
                        host_id=host.id,
                        kind=JobKind.OS_NETWORK.value,
                        job_id=ctx.job.id,
                        data=installer.last_network.model_dump(mode="json"),
                    )
                if config is not None:  # the host now answers at the configured IP with the set's password
                    self.store.set_os_access(
                        host.id,
                        installer.new_access,
                        self._cipher.encrypt(config.root_password),
                    )
            finally:
                report = installer.last_report
                if report is not None:
                    self.store.save_result(
                        host_id=host.id,
                        kind=JobKind.INSTALL.value,
                        job_id=ctx.job.id,
                        data=report.model_dump(mode="json"),
                    )
            return result

        params = req.model_dump(exclude={"confirm", "host_values"})
        return self.runner.submit(kind=JobKind.INSTALL, host_id=host.id, params=params, func=run)

    def preview_install(self, host_id: str, req: InstallRequest) -> InstallPreview:
        """Build the spec and kickstart a deployment would use. No BMC or OS calls."""
        host = self.get_host(host_id)
        notes: list[str] = []
        iso = None
        if req.iso_id:
            resolved = self.isos.resolve(req.iso_id)
            if resolved is None:
                raise NotFoundError(
                    f"ISO {req.iso_id} is not in the repository; rescan or check {self.settings.iso_dir}"
                )
            iso = resolved[0]
        stored_access = self.store.get_os_access(host_id)
        os_password = self._cipher.decrypt(stored_access[1]) if stored_access else None
        config = self._install_config(host, req, os_password)
        if config is None:
            raise OsConfigError(
                "Preview needs a config set (without one, settings are captured at install time)"
            )
        current_disk = None
        if config.settings.install_disk.mode == "current-boot-disk":
            current_disk = "CURRENT-BOOT-DISK"  # placeholder: read from the running OS at install time
            notes.append(
                "The install disk is the current boot disk, read from the running OS at install time."
            )
        if config.settings.cpu_override == "auto":
            notes.append("The CPU override is decided by the preflight at install time (previewed as on).")
        spec = EsxiPlugin.build_spec(
            config.settings,
            config.values,
            root_password=config.root_password,
            legacy_cpu_detected=True,
            current_boot_disk=current_disk,
        )
        masked = render_kickstart(spec).replace(spec.root_password_hash, "$6$<hidden>")
        return InstallPreview(
            iso=iso,
            config_set=self._config_set_name(req.config_set_id),
            spec=spec.model_dump(mode="json", exclude={"root_password_hash"}),
            kickstart=masked,
            notes=notes,
        )

    # ── OS families, config sets, host values ───────────────────────────
    def list_os_families(self) -> list[OsFamily]:
        return [
            OsFamily(
                family=p.family,
                title=p.title,
                install_supported=p.install_supported,
                settings_schema=p.settings_model.model_json_schema(),
                host_values_schema=p.host_values_model.model_json_schema(),
                secret_fields=list(p.secret_fields),
            )
            for p in PLUGINS.values()
        ]

    def list_config_sets(self) -> list[ConfigSet]:
        return self.store.list_config_sets()

    def get_config_set(self, set_id: str) -> ConfigSet:
        found = self.store.get_config_set(set_id)
        if found is None:
            raise NotFoundError(f"Config set {set_id} not found")
        return found[0]

    def create_config_set(self, req: ConfigSetWrite, source: str = "manual") -> ConfigSet:
        settings = self._validated_settings(req.os_family, req.settings)
        if self.store.find_config_set_by_name(req.name):
            raise ConflictError(f"A config set named '{req.name}' already exists")
        values = self._secret_values(req)
        return self.store.add_config_set(
            name=req.name,
            os_family=req.os_family,
            settings=settings,
            secrets=self._seal_all(values) if values else None,
            secret_names=sorted(values),
            source=source,
        )

    def update_config_set(self, set_id: str, req: ConfigSetWrite) -> ConfigSet:
        current = self.get_config_set(set_id)
        if req.os_family != current.os_family:
            raise OsConfigError("The OS family of a config set cannot be changed; create a new one")
        other = self.store.find_config_set_by_name(req.name)
        if other is not None and other.id != set_id:
            raise ConflictError(f"A config set named '{req.name}' already exists")
        settings = self._validated_settings(req.os_family, req.settings)
        values = self._secret_values(req)
        if values:  # merge: secrets not sent are kept
            stored = self.store.get_config_set(set_id)
            merged = {**(self._unseal(stored[1]) if stored and stored[1] else {}), **values}
            sealed = self._seal_all(merged)
            self.store.update_config_set(
                set_id,
                name=req.name,
                settings=settings,
                secrets=sealed,
                secret_names=sorted(merged),
                keep_secrets=False,
            )
        else:
            self.store.update_config_set(
                set_id, name=req.name, settings=settings, secrets=None, keep_secrets=True
            )
        return self.get_config_set(set_id)

    def config_set_secrets(self, set_id: str) -> dict[str, str]:
        """Decrypted secrets of a config set (internal use only; never returned by the API)."""
        stored = self.store.get_config_set(set_id)
        if stored is None:
            raise NotFoundError(f"Config set {set_id} not found")
        return self._unseal(stored[1]) if stored[1] else {}

    def _secret_values(self, req: ConfigSetWrite) -> dict[str, str]:
        values = req.secret_values()
        allowed = set(plugin_for(req.os_family).secret_fields)
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise OsConfigError(
                f"Unknown secret(s) for {req.os_family}: {', '.join(unknown)}; allowed: {sorted(allowed)}"
            )
        return values

    def delete_config_set(self, set_id: str) -> None:
        if not self.store.delete_config_set(set_id):
            raise NotFoundError(f"Config set {set_id} not found")

    def get_host_values(self, host_id: str, family: str) -> dict[str, Any]:
        self.get_host(host_id)
        plugin_for(family)
        values = self.store.get_host_values(host_id, family)
        if values is None:
            raise NotFoundError(f"No {family} values stored for host {host_id}; capture or set them")
        return values

    def set_host_values(self, host_id: str, family: str, values: dict[str, Any]) -> dict[str, Any]:
        self.get_host(host_id)
        model = plugin_for(family).host_values_model
        data = self._validate(model, values, "host_values")
        self.store.set_host_values(host_id, family, data)
        return data

    def start_os_capture(self, host_id: str, name: str) -> Job:
        host = self.get_host(host_id)
        if self.store.find_config_set_by_name(name):
            raise ConflictError(f"A config set named '{name}' already exists")
        access, secret = self._os_access(host_id)
        password = self._cipher.decrypt(secret)

        async def run(ctx: JobContext) -> dict[str, Any]:
            async with ctx.step("read", "Read the running OS"):
                ctx.progress(0.2, f"Reading configuration from {access.address}")
                target = await asyncio.to_thread(self.os_target, host_id, access)
                network = await self.esxi.read_network(target, password)
                storage = await self.esxi.read_storage(target, password)
            captured = EsxiPlugin.capture(network, storage)
            ctx.progress(0.8, "Saving config set")
            config_set = self.create_config_set(
                ConfigSetWrite(
                    name=name,
                    os_family=EsxiPlugin.family,
                    settings=captured.settings,
                    root_password=password,
                ),
                source=f"captured from {host.name} ({access.address})",
            )
            self.store.set_host_values(host.id, EsxiPlugin.family, captured.host_values)
            return {"config_set_id": config_set.id, "host_values": captured.host_values}

        return self.runner.submit(kind=JobKind.OS_CAPTURE, host_id=host.id, params={"name": name}, func=run)

    # ── ISO repository ───────────────────────────────────────────────────
    def list_isos(self) -> list[IsoImage]:
        return self.isos.list()

    async def rescan_isos(self) -> list[IsoImage]:
        return await asyncio.to_thread(self.isos.scan)

    # ── tasks and the pipeline ──────────────────────────────────────────
    def list_tasks(self) -> list[TaskInfo]:
        return [info(t) for t in CATALOG]

    def pipeline(self, host_id: str) -> Pipeline:
        self.get_host(host_id)
        kinds = {t.produces for t in CATALOG if t.produces}
        return evaluate_pipeline(
            host_id=host_id,
            os_epoch=self.store.os_epoch(host_id),
            jobs=self.store.list_jobs(host_id=host_id, limit=500),
            outputs={k: self.store.latest_output(host_id=host_id, kind=k) for k in kinds},
            has_os_access=self.store.get_os_access(host_id) is not None,
        )

    def start_task(self, host_id: str, task_id: str, run: TaskRun) -> Job:
        """Start any catalog task, after checking its inputs exist and are current."""
        spec = TASKS.get(task_id)
        if spec is None:
            raise NotFoundError(f"Unknown task '{task_id}'; see GET /tasks")
        if not spec.available:
            raise ConflictError(f"“{spec.title}” is not available yet")
        state = next(t for s in self.pipeline(host_id).stages for t in s.tasks if t.id == task_id)
        if state.blocked_by:
            raise ConflictError(f"Can't run “{spec.title}” yet: " + "; ".join(state.blocked_by))
        p = run.params
        if task_id == "discover":
            return self.start_inventory(host_id)
        if task_id == "preflight":
            return self.start_preflight(host_id, p.get("profile", "holodeck-9"), p.get("variant"))
        if task_id in ("os.reimage", "os.custom"):
            req = InstallRequest.model_validate({**p, "confirm": run.confirm or ""})
            if task_id == "os.custom" and not req.config_set_id:
                raise OsConfigError(
                    "Deploy OS · custom ISO from a config set needs a config set (params.config_set_id)"
                )
            if task_id == "os.reimage" and req.config_set_id:
                raise OsConfigError(
                    "os.reimage builds the ISO from the current settings; use os.custom for a config set"
                )
            return self.start_install(host_id, req)
        if task_id == "os.read":
            return self.start_os_network(host_id)
        if task_id == "os.capture":
            return self.start_os_capture(host_id, str(p.get("name") or ""))
        if task_id == "host.assess":
            return self.start_assess(host_id, p.get("variant"))
        if task_id == "host.prep":
            checks = p.get("checks")
            return self.start_prep(host_id, list(checks) if checks is not None else None, run.confirm)
        if task_id == "net.verify_jumbo":
            return self.start_verify_jumbo(host_id)
        raise ConflictError(f"“{spec.title}” has no runner")  # pragma: no cover - catalog/dispatch mismatch

    def start_assess(self, host_id: str, variant: str | None = None) -> Job:
        """Read the installed OS live and assess it against Holodeck's needs (read-only)."""
        self.get_host(host_id)
        access, secret = self._os_access(host_id)
        password = self._cipher.decrypt(secret)
        stored = self.store.latest_output(host_id=host_id, kind=JobKind.PREFLIGHT.value)
        preflight = PreflightReport.model_validate(stored.data) if stored else None
        profile = load_profile(preflight.profile if preflight else "holodeck-9")
        variant = variant or (preflight.variant if preflight else profile.default_variant)
        if variant not in profile.variants:
            raise UnknownProfileError(f"Unknown variant '{variant}'; choose from {sorted(profile.variants)}")
        jumbo_meta = self.store.latest_output(host_id=host_id, kind="jumbo")
        epoch = self.store.os_epoch(host_id)
        jumbo = jumbo_meta.data if jumbo_meta and jumbo_meta.epoch >= epoch else None

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(ASSESS_STEPS)
            async with ctx.step("connect", "Connect to the OS"):
                target = await asyncio.to_thread(self.os_target, host_id, access)
            async with ctx.step("network", "Read network and NTP"):
                ctx.progress(0.3, f"Reading network configuration from {access.address}")
                network = await self.esxi.read_network(target, password)
            async with ctx.step("storage", "Read disks and datastores"):
                ctx.progress(0.6, f"Reading disks and datastores from {access.address}")
                storage = await self.esxi.read_storage(target, password)
            for kind, model in ((JobKind.OS_NETWORK.value, network), ("os_storage", storage)):
                self.store.save_result(
                    host_id=host_id, kind=kind, job_id=ctx.job.id, data=model.model_dump(mode="json")
                )
            async with ctx.step("evaluate", "Evaluate Holodeck readiness"):
                report = assess(profile=profile, variant=variant, network=network, storage=storage,
                                preflight=preflight, jumbo=jumbo)  # fmt: skip
                data = report.model_dump(mode="json")
                self.store.save_result(host_id=host_id, kind="readiness", job_id=ctx.job.id, data=data)
            return {"readiness": data}

        return self.runner.submit(kind=JobKind.ASSESS, host_id=host_id, params={"variant": variant}, func=run)

    def _readiness(self, host_id: str) -> ReadinessReport:
        meta = self.store.latest_output(host_id=host_id, kind="readiness")
        if meta is None:
            raise ConflictError("Assess Holodeck readiness first")
        return ReadinessReport.model_validate(meta.data)

    def _reassess(
        self, host_id: str, network: EsxiNetworkConfig, storage: EsxiStorage, job_id: str
    ) -> ReadinessReport:
        """Re-run the assessment with the variant the last one used (after prep or a jumbo test)."""
        previous = self._readiness(host_id)
        stored = self.store.latest_output(host_id=host_id, kind=JobKind.PREFLIGHT.value)
        preflight = PreflightReport.model_validate(stored.data) if stored else None
        jumbo_meta = self.store.latest_output(host_id=host_id, kind="jumbo")
        epoch = self.store.os_epoch(host_id)
        jumbo = jumbo_meta.data if jumbo_meta and jumbo_meta.epoch >= epoch else None
        report = assess(profile=load_profile(previous.profile), variant=previous.variant, network=network,
                        storage=storage, preflight=preflight, jumbo=jumbo)  # fmt: skip
        self.store.save_result(
            host_id=host_id, kind="readiness", job_id=job_id, data=report.model_dump(mode="json")
        )
        return report

    def start_prep(self, host_id: str, checks: list[str] | None, confirm: str | None) -> Job:
        """Apply planned readiness fixes (by check id; default: the recommended ones), then re-assess."""
        self.get_host(host_id)
        access, secret = self._os_access(host_id)
        password = self._cipher.decrypt(secret)
        report = self._readiness(host_id)
        plan = [a for a in report.plan if a.task == "host.prep"]
        by_check = {a.check: a for a in plan}
        if checks is None:
            selected = [a for a in plan if a.recommended]
        else:
            unknown = [c for c in checks if c not in by_check]
            if unknown:
                raise OsConfigError(
                    f"Not in the current plan: {', '.join(unknown)}. Assess again to refresh it."
                )
            selected = [by_check[c] for c in checks]
        if not selected:
            raise OsConfigError("Nothing selected to apply")
        for action in selected:
            if action.destructive and confirm != action.confirm_phrase:
                raise ConfirmationError(
                    f'“{action.title}” erases a disk: confirm with exactly "{action.confirm_phrase}"'
                )

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [(a.check, a.title) for a in selected] + [("reassess", "Read the host again and re-assess")]
            )
            target = await asyncio.to_thread(self.os_target, host_id, access)
            applied = []
            for i, action in enumerate(selected):
                async with ctx.step(action.check, action.title) as step:
                    ctx.progress(0.1 + 0.7 * i / len(selected), action.title)
                    record = await self.esxi.apply(target, password, action.id, action.params)
                    step.message = (
                        f"{record.before} → {record.after}" if record.changed else f"already {record.after}"
                    )
                    applied.append(record)
            async with ctx.step("reassess", "Read the host again and re-assess"):
                network = await self.esxi.read_network(target, password)
                storage = await self.esxi.read_storage(target, password)
                for kind, model in ((JobKind.OS_NETWORK.value, network), ("os_storage", storage)):
                    self.store.save_result(
                        host_id=host_id, kind=kind, job_id=ctx.job.id, data=model.model_dump(mode="json")
                    )
                after = self._reassess(host_id, network, storage, ctx.job.id)
            vswitch = after.target_vswitch
            trunk = next((pg.name for pg in network.portgroups if pg.is_trunk and pg.vswitch == vswitch
                          and pg.security.accepts_all), None)  # fmt: skip
            external = next((pg.name for pg in network.portgroups if pg.name == "Holodeck-External"), None)
            data = {
                "applied": [r.model_dump(mode="json") for r in applied],
                "vswitch": vswitch,
                "trunk_portgroup": trunk,
                "external_portgroup": external,
                "datastore": after.storage.datastore if after.storage.kind == "existing" else None,
                "ready": after.ready,
            }
            self.store.save_result(host_id=host_id, kind="host_prep", job_id=ctx.job.id, data=data)
            return {"host_prep": data, "readiness": after.model_dump(mode="json")}

        return self.runner.submit(kind=JobKind.HOST_PREP, host_id=host_id,
                                  params={"checks": [a.check for a in selected]}, func=run)  # fmt: skip

    def start_verify_jumbo(self, host_id: str) -> Job:
        """Loop test 9000-byte frames through the physical switch (temporary changes, always reverted)."""
        self.get_host(host_id)
        access, secret = self._os_access(host_id)
        password = self._cipher.decrypt(secret)
        self._readiness(host_id)
        pinned = self.store.get_pin(host_id, "os-ssh")

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan([("read", "Read the network"), ("loop", "Loop test through the switch"),
                      ("reassess", "Update the readiness report")])  # fmt: skip
            target = await asyncio.to_thread(self.os_target, host_id, access)
            async with ctx.step("read", "Read the network"):
                network = await self.esxi.read_network(target, password)
                vswitch = next(
                    (v for v in network.vswitches if v.name == self._readiness(host_id).target_vswitch), None
                )
                if vswitch is None or len(vswitch.uplinks) < 2:
                    raise OsConfigError("The jumbo-frame test needs a standard switch with two uplinks")
                # Management stays on the NIC whose MAC vmk0 uses; the other uplink is borrowed for the test.
                keep = network.install_nic()
                keep = keep if keep in vswitch.uplinks else vswitch.uplinks[0]
                borrow = next(u for u in vswitch.uplinks if u != keep)
                uplinks = (keep, borrow)
                vlan = network.management_vlan()
            async with ctx.step("loop", "Loop test through the switch") as step:
                result = await self.esxi.verify_jumbo(
                    target, password, vswitch=vswitch.name, uplinks=uplinks, vlan=vlan, mtu=9000,
                    pinned_ssh_key=pinned[1] if pinned else None, log=lambda m: ctx.progress(0.5, m),
                )  # fmt: skip
                if result.ssh_host_key and not pinned:
                    self.store.set_pin(host_id, "os-ssh", access.address, result.ssh_host_key)
                self.store.save_result(
                    host_id=host_id, kind="jumbo", job_id=ctx.job.id, data=result.model_dump(mode="json")
                )
                step.message = result.summary
            async with ctx.step("reassess", "Update the readiness report"):
                storage_meta = self.store.latest_output(host_id=host_id, kind="os_storage")
                if storage_meta is not None:
                    self._reassess(
                        host_id, network, EsxiStorage.model_validate(storage_meta.data), ctx.job.id
                    )
            if not result.restored:
                raise OsConfigError(f"The network configuration was not fully restored:\n{result.diff}")
            if not result.ok:
                raise OsConfigError(result.summary)
            return {"jumbo": result.model_dump(mode="json")}

        return self.runner.submit(kind=JobKind.VERIFY_JUMBO, host_id=host_id, params={}, func=run)

    def job_diagnostics(self, job_id: str) -> dict[str, Any]:
        """Everything needed to debug a job from a file: job, host, BMC identity and the redacted log."""
        job = self.get_job(job_id)
        host = self.store.get_host(job.host_id)
        recorded = self.store.get_diagnostics(job_id) or {"events": [], "dropped_events": 0}
        return {
            "groundzero": {"version": __version__, "mode": "simulated" if self.sim_bmc else "live"},
            "job": job.model_dump(mode="json"),
            "host": host.model_dump(mode="json", exclude={"username"}) if host else None,
            "bmc_identity": next((e for e in recorded["events"] if e.get("event") == "bmc_identity"), None),
            **recorded,
        }

    # ── jobs ─────────────────────────────────────────────────────────────
    def get_job(self, job_id: str) -> Job:
        job = self.store.get_job(job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    def list_jobs(self, host_id: str | None = None, limit: int = 50) -> list[Job]:
        return self.store.list_jobs(host_id=host_id, limit=limit)

    def cancel_job(self, job_id: str) -> Job:
        job = self.get_job(job_id)
        if job.status.is_terminal:
            raise ConflictError(f"Job {job_id} already finished ({job.status})")
        self.runner.cancel(job_id)
        return job

    def start_inventory(self, host_id: str) -> Job:
        host = self.get_host(host_id)

        async def run(ctx: JobContext) -> dict[str, Any]:
            async with ctx.step("collect", "Read hardware inventory from the BMC"):
                inventory, audit = await self._collect(host, ctx)
            return {"inventory": inventory.model_dump(mode="json"), "audit": audit.model_dump()}

        return self.runner.submit(kind=JobKind.INVENTORY, host_id=host.id, params={}, func=run)

    def start_preflight(self, host_id: str, profile: str, variant: str | None) -> Job:
        host = self.get_host(host_id)
        spec = load_profile(profile)  # validate before queuing so bad input is a 4xx, not a failed job
        variant = variant or spec.default_variant
        if variant not in spec.variants:
            raise UnknownProfileError(f"Unknown variant '{variant}'; choose from {sorted(spec.variants)}")
        evaluate_args = {"profile": profile, "variant": variant}

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [
                    ("collect", "Read hardware inventory from the BMC"),
                    ("evaluate", "Evaluate the requirements"),
                ]
            )
            async with ctx.step("collect", "Read hardware inventory from the BMC"):
                inventory, audit = await self._collect(host, ctx)
            async with ctx.step("evaluate", "Evaluate the requirements"):
                ctx.progress(0.97, "Evaluating preflight checks")
                report = evaluate(inventory, profile, variant)
            data = report.model_dump(mode="json")
            self.store.save_result(
                host_id=host.id, kind=JobKind.PREFLIGHT.value, job_id=ctx.job.id, data=data
            )
            return {"preflight": data, "audit": audit.model_dump()}

        return self.runner.submit(kind=JobKind.PREFLIGHT, host_id=host.id, params=evaluate_args, func=run)

    # ── internals ────────────────────────────────────────────────────────
    async def _collect(self, host: Host, ctx: JobContext) -> tuple[HostInventory, BmcAudit]:
        password = self._cipher.decrypt(self._secret(host.id))
        client = self._client_factory(host, password)
        async with client:
            identity, inventory = await collect_inventory(client, ctx.progress)
        diagnostics.record("bmc_identity", **identity.model_dump(mode="json"),
                           firmware=inventory.bmc.model_dump(mode="json"))  # fmt: skip
        audit = BmcAudit(
            requests=len(client.request_log),
            non_get=[f"{r.method} {r.path}" for r in client.request_log if r.method != "GET"],
        )
        if any("Sessions" not in call for call in audit.non_get):  # inventory must be read-only
            logger.error("Unexpected BMC writes during inventory of %s: %s", host.id, audit.non_get)
        self.store.update_host_identity(host.id, vendor=identity.vendor.value, model=identity.model)
        self.store.save_result(
            host_id=host.id,
            kind=JobKind.INVENTORY.value,
            job_id=ctx.job.id,
            data=inventory.model_dump(mode="json"),
        )
        return inventory, audit

    # ── certificate pinning ─────────────────────────────────────────────
    def pinned_pem(
        self, host_id: str, role: str, address: str, *, verify_tls: bool = False, repin: bool = False
    ) -> str | None:
        """The certificate to trust for this host/role: pinned on first use, checked on every use.

        Blocking (a TLS handshake); call via a thread from async code where practical.
        """
        if verify_tls:
            return None  # CA-validated instead
        stored = self.store.get_pin(host_id, role)
        if stored and stored[0] == address and not repin:
            check_pin(role, address, stored[1])  # clear error before any credential is sent
            return stored[1]
        pem = fetch_certificate(address)
        self.store.set_pin(host_id, role, address, pem)
        logger.info("Pinned %s certificate for host %s at %s: %s", role, host_id, address, fingerprint(pem))
        return pem

    def os_target(self, host_id: str, access: OsAccess, *, repin: bool = False) -> OsAccess:
        if not isinstance(self.esxi, LiveEsxiOps):
            return access  # simulated/injected ESXi: there is no real certificate to pin
        pem = self.pinned_pem(host_id, "os", access.address, verify_tls=access.verify_tls, repin=repin)
        return OsTarget(**access.model_dump(), pinned_pem=pem)

    def list_pins(self, host_id: str) -> list[PinnedCertificate]:
        self.get_host(host_id)
        return [
            PinnedCertificate(
                role=role,
                address=address,
                fingerprint=pem if role == "os-ssh" else fingerprint(pem),
                pinned_at=at,
            )
            for role, address, pem, at in self.store.list_pins(host_id)
        ]

    def retrust(self, host_id: str, role: str) -> PinnedCertificate:
        """Explicitly accept the certificate the server presents now (after a legitimate change)."""
        host = self.get_host(host_id)
        if role == "bmc":
            address = host.bmc_address
        elif role == "os":
            address = self._os_access(host_id)[0].address
        elif role == "os-ssh":  # an SSH key can only be seen by logging in: pinned again on next use
            address = self._os_access(host_id)[0].address
            self.store.delete_pin(host_id, role)
            return PinnedCertificate(role=role, address=address, fingerprint="(pinned again on next use)",
                                     pinned_at=utcnow())  # fmt: skip
        else:
            raise NotFoundError(f"Unknown certificate role '{role}' (bmc, os or os-ssh)")
        self.pinned_pem(host_id, role, address, repin=True)
        return next(p for p in self.list_pins(host_id) if p.role == role)

    def _resolve_iso(self, req: InstallRequest) -> Path:
        if req.iso_id:
            resolved = self.isos.resolve(req.iso_id)
            if resolved is None:
                raise NotFoundError(
                    f"ISO {req.iso_id} is not in the repository; rescan or check {self.settings.iso_dir}"
                )
            image, path = resolved
            if image.os_family != EsxiPlugin.family:
                raise OsConfigError(f"{image.filename} is not an ESXi installer ISO")
            return path
        if req.iso_path and Path(req.iso_path).is_file():
            return Path(req.iso_path)
        raise NotFoundError(f"ISO not found: {req.iso_path or req.iso_id}")

    def _install_config(
        self, host: Host, req: InstallRequest, os_password: str | None
    ) -> InstallConfig | None:
        if req.config_set_id is None:
            return None
        found = self.store.get_config_set(req.config_set_id)
        if found is None:
            raise NotFoundError(f"Config set {req.config_set_id} not found")
        config_set, sealed = found
        if config_set.os_family != EsxiPlugin.family:
            raise OsConfigError(f"Config set '{config_set.name}' is for {config_set.os_family}, not ESXi")
        raw_values = req.host_values or self.store.get_host_values(host.id, EsxiPlugin.family)
        if raw_values is None:
            raise OsConfigError(
                f"Per-server values (hostname, ip) are needed for {host.name}: pass host_values, "
                "set them for the host, or capture from its running OS"
            )
        values = EsxiHostValues.model_validate(self._validate(EsxiHostValues, raw_values, "host_values"))
        root_password = self._unseal(sealed).get("root_password") if sealed else None
        root_password = root_password or os_password
        if not root_password:
            raise OsConfigError(
                f"Config set '{config_set.name}' has no root password and the host has no OS access"
            )
        return InstallConfig(
            settings=EsxiSettings.model_validate(config_set.settings),
            values=values,
            root_password=root_password,
        )

    def _config_set_name(self, set_id: str | None) -> str | None:
        if set_id is None:
            return None
        found = self.store.get_config_set(set_id)
        return found[0].name if found else None

    def _validated_settings(self, family: str, settings: dict[str, Any]) -> dict[str, Any]:
        return self._validate(plugin_for(family).settings_model, settings, "settings")

    @staticmethod
    def _validate(model: type[BaseModel], data: dict[str, Any], where: str) -> dict[str, Any]:
        try:
            return model.model_validate(data).model_dump(mode="json")
        except ValidationError as exc:
            raise SettingsValidationError(where, exc) from exc

    def _seal(self, root_password: str) -> bytes:
        return self._seal_all({"root_password": root_password})

    def _seal_all(self, values: dict[str, str]) -> bytes:
        return self._cipher.encrypt(json.dumps(values))

    def _unseal(self, sealed: bytes) -> dict[str, str]:
        data: dict[str, str] = json.loads(self._cipher.decrypt(sealed))
        return data

    def _os_access(self, host_id: str) -> tuple[OsAccess, bytes]:
        self.get_host(host_id)
        stored = self.store.get_os_access(host_id)
        if stored is None:
            raise NotFoundError(f"No OS access configured for host {host_id}; PUT /hosts/{host_id}/os first")
        return stored

    def _secret(self, host_id: str) -> bytes:
        secret = self.store.get_host_secret(host_id)
        if secret is None:
            raise NotFoundError(f"Host {host_id} not found")
        return secret

    def _default_client(self, host: Host, password: str) -> RedfishClient:
        transport = self.sim_bmc.transport() if self.sim_bmc else None
        pem = (
            None
            if self.sim_bmc
            else self.pinned_pem(host.id, "bmc", host.bmc_address, verify_tls=host.verify_tls)
        )
        return RedfishClient(
            host.bmc_address,
            host.username,
            password,
            verify_tls=host.verify_tls,
            ssl_context=pinned_context(pem) if pem else None,
            timeout=self.settings.redfish_timeout,
            max_parallel=self.settings.redfish_max_parallel,
            transport=transport,
        )
