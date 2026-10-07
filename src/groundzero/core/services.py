"""Application services: the single entry point used by the API (and therefore by every client).

HTTP handlers stay thin; everything here is plain Python that can be tested without a server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    OsAccess,
    OsAccessSet,
)
from groundzero.core.store import Store, utcnow
from groundzero.core.tasks import Pipeline, TaskInfo, TaskRun, catalog, evaluate_pipeline, info
from groundzero.core.tls import PinnedCertificate, check_pin, fetch_certificate, fingerprint, pinned_context
from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage
from groundzero.esxi.ops import EsxiOps, LiveEsxiOps, OsTarget
from groundzero.install.job import InstallRequest
from groundzero.install.kickstart import render_kickstart
from groundzero.inventory.collect import collect_inventory as read_inventory
from groundzero.inventory.models import HostInventory
from groundzero.isos import Image, IsoRepository
from groundzero.media.registry import MediaRegistry
from groundzero.modules import REGISTRY
from groundzero.modules.base import Inputs
from groundzero.modules.os import install_config
from groundzero.modules.outputs import OUTPUTS
from groundzero.modules.prep import current_jumbo
from groundzero.osconfig import PLUGINS, OsConfigError, plugin_for
from groundzero.osconfig.esxi import EsxiPlugin
from groundzero.ova.descriptor import OvfDescriptor, descriptor_schema, read_ova_descriptor
from groundzero.ova.profiles import ApplianceProfile, ApplianceProfileWrite, check_values
from groundzero.preflight.evaluate import PreflightReport, load_profile
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

    def __init__(self, where: str, exc: ValidationError | list[dict[str, object]]) -> None:
        """From a Pydantic error, or from field errors whose ``loc`` already starts with ``where``."""
        if isinstance(exc, ValidationError):
            self.errors: list[dict[str, object]] = [
                {"loc": [where, *e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()
            ]
        else:
            self.errors = exc
        super().__init__(
            f"Invalid {where}: "
            + "; ".join(
                f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}"  # type: ignore[index]
                for e in self.errors
            )
        )


class OsFamily(BaseModel):
    family: str
    title: str
    install_supported: bool
    settings_schema: dict[str, Any]
    host_values_schema: dict[str, Any]
    secret_fields: list[str]


class ImageDescriptor(BaseModel):
    image: Image
    descriptor: OvfDescriptor
    schema_: dict[str, Any] = Field(alias="schema", description="JSON Schema of the user-configurable inputs")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class InstallPreview(BaseModel):
    """What a deployment would do, without touching the BMC or the server."""

    iso: Image | None
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

    # ── installed OS ─────────────────────────────────────────────────────
    def set_os_access(self, host_id: str, req: OsAccessSet) -> OsAccess:
        self.get_host(host_id)
        access = OsAccess(address=req.address, username=req.username, verify_tls=req.verify_tls)
        self.store.set_os_access(host_id, access, self._cipher.encrypt(req.password.get_secret_value()))
        return access

    def get_os_access(self, host_id: str) -> OsAccess:
        return self._os_access(host_id)[0]

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
        config = install_config(self, host, req, os_password)
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

    # ── appliance profiles (saved values for an OVA) ─────────────────────
    def list_appliance_profiles(self) -> list[ApplianceProfile]:
        return self.store.list_appliance_profiles()

    def get_appliance_profile(self, profile_id: str) -> ApplianceProfile:
        found = self.store.get_appliance_profile(profile_id)
        if found is None:
            raise NotFoundError(f"Appliance profile {profile_id} not found")
        return found[0]

    def appliance_profile_secrets(self, profile_id: str) -> dict[str, str]:
        """Decrypted passwords of a profile (internal use only; never returned by the API)."""
        found = self.store.get_appliance_profile(profile_id)
        if found is None:
            raise NotFoundError(f"Appliance profile {profile_id} not found")
        return self._unseal(found[1]) if found[1] else {}

    def save_appliance_profile(
        self, req: ApplianceProfileWrite, *, profile_id: str | None = None, source: str = "manual"
    ) -> ApplianceProfile:
        """Create (no id) or replace a profile, checked against the descriptor of ``req.image_id``."""
        current = self.get_appliance_profile(profile_id) if profile_id else None
        other = self.store.find_appliance_profile_by_name(req.name)
        if other is not None and other.id != profile_id:
            raise ConflictError(f"An appliance profile named '{req.name}' already exists")
        resolved = self.isos.resolve(req.image_id)
        if resolved is None or resolved[0].kind != "ova":
            raise NotFoundError(f"OVA {req.image_id} is not in the image repository")
        desc = read_ova_descriptor(resolved[1])
        product = desc.product or resolved[0].filename
        if current is not None and current.product != product:
            raise OsConfigError(f"This profile is for {current.product}; {resolved[0].filename} is {product}")
        values, secrets, errors = check_values(desc, req.values, req.secret_values(), req.networks)
        if errors:
            raise SettingsValidationError("profile", errors)
        sealed: bytes | None = None
        names: list[str] | None = None
        if secrets or current is None:  # merge: passwords not sent are kept
            merged = {**(self.appliance_profile_secrets(current.id) if current else {}), **secrets}
            sealed = self._seal_all(merged) if merged else None
            names = sorted(merged)
        return self.store.save_appliance_profile(
            profile_id=profile_id,
            name=req.name,
            product=product,
            image_id=req.image_id,
            values=values,
            networks=req.networks,
            source=current.source if current else source,
            secrets=sealed,
            secret_names=names,
        )

    def delete_appliance_profile(self, profile_id: str) -> None:
        if not self.store.delete_appliance_profile(profile_id):
            raise NotFoundError(f"Appliance profile {profile_id} not found")

    # ── ISO repository ───────────────────────────────────────────────────
    def list_images(self) -> list[Image]:
        return self.isos.list()

    async def rescan_images(self) -> list[Image]:
        return await asyncio.to_thread(self.isos.scan)

    async def image_descriptor(self, image_id: str) -> ImageDescriptor:
        """What an OVA is and the inputs it takes, with a JSON Schema for the form."""
        resolved = self.isos.resolve(image_id)
        if resolved is None:
            raise NotFoundError(
                f"Image {image_id} is not in the repository; rescan or check {self.settings.iso_dir}"
            )
        image, path = resolved
        if image.kind != "ova":
            raise ConflictError(f"{image.filename} is not an OVA")
        desc = await asyncio.to_thread(read_ova_descriptor, path)
        return ImageDescriptor(image=image, descriptor=desc, schema_=descriptor_schema(desc))

    # ── tasks and the pipeline ──────────────────────────────────────────
    def list_tasks(self) -> list[TaskInfo]:
        return [info(m.spec(), m.params_schema()) for m in REGISTRY.values()]

    def list_outputs(self, host_id: str) -> list[dict[str, Any]]:
        """The latest output of each kind this host has, newest first."""
        self.get_host(host_id)
        epoch = self.store.os_epoch(host_id)
        found = []
        for kind in sorted({t.produces for t in catalog() if t.produces} | set(OUTPUTS)):
            meta = self.store.latest_output(host_id=host_id, kind=kind)
            if meta is not None:
                found.append(
                    {
                        "kind": kind,
                        "job_id": meta.job_id,
                        "produced_at": meta.created_at,
                        "fresh": meta.epoch >= epoch,
                    }
                )
        return sorted(found, key=lambda o: o["produced_at"], reverse=True)

    def pipeline(self, host_id: str) -> Pipeline:
        self.get_host(host_id)
        kinds = {t.produces for t in catalog() if t.produces}
        return evaluate_pipeline(
            host_id=host_id,
            os_epoch=self.store.os_epoch(host_id),
            jobs=self.store.list_jobs(host_id=host_id, limit=500),
            outputs={k: self.store.latest_output(host_id=host_id, kind=k) for k in kinds},
            has_os_access=self.store.get_os_access(host_id) is not None,
        )

    def start_task(self, host_id: str, task_id: str, run: TaskRun) -> Job:
        """Start any catalog task: its inputs must exist and be current, its parameters valid."""
        module = REGISTRY.get(task_id)
        if module is None:
            raise NotFoundError(f"Unknown task '{task_id}'; see GET /tasks")
        if not module.available:
            raise ConflictError(f"“{module.title}” is not available yet")
        host = self.get_host(host_id)
        state = next(t for s in self.pipeline(host_id).stages for t in s.tasks if t.id == task_id)
        if state.blocked_by:
            raise ConflictError(f"Can't run “{module.title}” yet: " + "; ".join(state.blocked_by))
        params = module.Params.model_validate(self._validate(module.Params, run.params, "params"))
        prepared = module.prepare(self, host, params, Inputs(self.store, host_id), run.confirm)
        return self.runner.submit(task=module.id, host_id=host_id, params=prepared.params, func=prepared.run)

    # ── shared plumbing for modules (the Deps protocol in groundzero.modules.base) ──
    def save_output(self, host_id: str, kind: str, job_id: str, output: BaseModel | dict[str, Any]) -> None:
        """Store a module's output, checked against the output registry so the next module can read it."""
        data = output.model_dump(mode="json") if isinstance(output, BaseModel) else output
        model = OUTPUTS.get(kind)
        if model is not None:
            model.model_validate(data)  # an output that doesn't match its type is a bug, not bad input
        self.store.save_result(host_id=host_id, kind=kind, job_id=job_id, data=data)

    def reassess(
        self, host_id: str, network: EsxiNetworkConfig, storage: EsxiStorage, job_id: str
    ) -> ReadinessReport:
        """Re-run the assessment with the variant the last one used (after prep or a jumbo test)."""
        inputs = Inputs(self.store, host_id)
        previous = inputs.require("readiness", ReadinessReport, "Assess Holodeck readiness first")
        preflight = inputs.get("preflight", PreflightReport)
        jumbo = current_jumbo(inputs)
        report = assess(
            profile=load_profile(previous.profile),
            variant=previous.variant,
            network=network,
            storage=storage,
            preflight=preflight,
            jumbo=jumbo,
        )
        self.save_output(host_id, "readiness", job_id, report)
        return report

    def client_factory(self, host: Host, password: str) -> RedfishClient:
        return self._client_factory(host, password)

    def bmc_password(self, host_id: str) -> str:
        return self._cipher.decrypt(self._secret(host_id))

    def os_access(self, host_id: str) -> tuple[OsAccess, str]:
        """How to reach the installed OS, with its password; NotFound until OS access is set."""
        access, secret = self._os_access(host_id)
        return access, self._cipher.decrypt(secret)

    def stored_os_access(self, host_id: str) -> tuple[OsAccess, str] | None:
        stored = self.store.get_os_access(host_id)
        return (stored[0], self._cipher.decrypt(stored[1])) if stored else None

    def save_os_access(self, host_id: str, access: OsAccess, password: str) -> None:
        self.store.set_os_access(host_id, access, self._cipher.encrypt(password))

    def validate_values(self, model: type[BaseModel], data: dict[str, Any], where: str) -> dict[str, Any]:
        return self._validate(model, data, where)

    async def wait_for_port(self, address: str, port: int, *, minutes: float, ctx: JobContext) -> None:
        if not isinstance(self.esxi, LiveEsxiOps):
            return  # simulated appliances have no real network presence
        deadline = asyncio.get_running_loop().time() + minutes * 60
        while True:
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), timeout=5)
                writer.close()
                return
            except (OSError, TimeoutError):
                if asyncio.get_running_loop().time() > deadline:
                    raise OsConfigError(
                        f"{address}:{port} did not answer within {minutes:.0f} minutes"
                    ) from None
                ctx.progress(0.95, f"Waiting for {address}:{port}")
                await asyncio.sleep(10)

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

    # ── internals ────────────────────────────────────────────────────────
    async def collect_inventory(self, host: Host, ctx: JobContext) -> tuple[HostInventory, dict[str, Any]]:
        """Read the BMC's inventory (read-only), save it as the host's inventory output, audit the calls."""
        password = self._cipher.decrypt(self._secret(host.id))
        client = self._client_factory(host, password)
        async with client:
            identity, inventory = await read_inventory(client, ctx.progress)
        diagnostics.record(
            "bmc_identity", **identity.model_dump(mode="json"), firmware=inventory.bmc.model_dump(mode="json")
        )
        audit = BmcAudit(
            requests=len(client.request_log),
            non_get=[f"{r.method} {r.path}" for r in client.request_log if r.method != "GET"],
        )
        if any("Sessions" not in call for call in audit.non_get):  # inventory must be read-only
            logger.error("Unexpected BMC writes during inventory of %s: %s", host.id, audit.non_get)
        self.store.update_host_identity(host.id, vendor=identity.vendor.value, model=identity.model)
        self.save_output(host.id, "inventory", ctx.job.id, inventory)
        return inventory, audit.model_dump()

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
            return PinnedCertificate(
                role=role, address=address, fingerprint="(pinned again on next use)", pinned_at=utcnow()
            )
        else:
            raise NotFoundError(f"Unknown certificate role '{role}' (bmc, os or os-ssh)")
        self.pinned_pem(host_id, role, address, repin=True)
        return next(p for p in self.list_pins(host_id) if p.role == role)

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
