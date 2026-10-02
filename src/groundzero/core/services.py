"""Application services: the single entry point used by the API (and therefore by every client).

HTTP handlers stay thin; everything here is plain Python that can be tested without a server.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

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
from groundzero.core.store import Store
from groundzero.esxi.ops import EsxiOps, LiveEsxiOps
from groundzero.install.job import InstallConfig, Installer, InstallRequest, InstallTimings
from groundzero.install.kickstart import render_kickstart
from groundzero.inventory.collect import collect_inventory
from groundzero.inventory.models import HostInventory
from groundzero.isos import IsoImage, IsoRepository
from groundzero.media.registry import MediaRegistry
from groundzero.osconfig import PLUGINS, OsConfigError, plugin_for
from groundzero.osconfig.esxi import EsxiHostValues, EsxiPlugin, EsxiSettings
from groundzero.preflight.evaluate import UnknownProfileError, evaluate, load_profile
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
            ctx.progress(0.1, f"Reading network configuration from {access.address}")
            config = await self.esxi.read_network(access, password)
            data = config.model_dump(mode="json")
            self.store.save_result(
                host_id=host_id, kind=JobKind.OS_NETWORK.value, job_id=ctx.job.id, data=data
            )
            return {"os_network": data}

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
        return self.store.add_config_set(
            name=req.name,
            os_family=req.os_family,
            settings=settings,
            secrets=self._seal(req.root_password.get_secret_value()) if req.root_password else None,
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
        self.store.update_config_set(
            set_id,
            name=req.name,
            settings=settings,
            secrets=self._seal(req.root_password.get_secret_value()) if req.root_password else None,
            keep_secrets=req.root_password is None,
        )
        return self.get_config_set(set_id)

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
            ctx.progress(0.2, f"Reading configuration from {access.address}")
            network = await self.esxi.read_network(access, password)
            storage = await self.esxi.read_storage(access, password)
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
        import asyncio

        return await asyncio.to_thread(self.isos.scan)

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
            inventory, audit = await self._collect(host, ctx)
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
        return self._cipher.encrypt(json.dumps({"root_password": root_password}))

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
        return RedfishClient(
            host.bmc_address,
            host.username,
            password,
            verify_tls=host.verify_tls,
            timeout=self.settings.redfish_timeout,
            max_parallel=self.settings.redfish_max_parallel,
            transport=transport,
        )
