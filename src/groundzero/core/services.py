"""Application services: the single entry point used by the API (and therefore by every client).

HTTP handlers stay thin; everything here is plain Python that can be tested without a server.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from groundzero.core.config import Settings
from groundzero.core.credentials import CredentialCipher
from groundzero.core.jobs import JobContext, JobRunner
from groundzero.core.models import BmcAudit, Host, HostCreate, Job, JobKind, OsAccess, OsAccessSet
from groundzero.core.store import Store
from groundzero.esxi.models import EsxiNetworkConfig
from groundzero.esxi.reader import read_network
from groundzero.inventory.collect import collect_inventory
from groundzero.inventory.models import HostInventory
from groundzero.media.registry import MediaRegistry
from groundzero.preflight.evaluate import UnknownProfileError, evaluate, load_profile
from groundzero.redfish.capture import load_recording, replay_transport
from groundzero.redfish.client import RedfishClient

logger = logging.getLogger(__name__)

ClientFactory = Callable[[Host, str], RedfishClient]
EsxiReader = Callable[[OsAccess, str], Awaitable[EsxiNetworkConfig]]


class NotFoundError(LookupError):
    error_type = "not_found"


class ConflictError(ValueError):
    error_type = "conflict"


class Services:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        runner: JobRunner,
        cipher: CredentialCipher,
        *,
        client_factory: ClientFactory | None = None,
        esxi_reader: EsxiReader | None = None,
        media: MediaRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.media = media or MediaRegistry()
        self.store = store
        self.runner = runner
        self._cipher = cipher
        self._client_factory = client_factory or self._default_client
        self._esxi_reader = esxi_reader or self._default_esxi_reader

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
            config = await self._esxi_reader(access, password)
            data = config.model_dump(mode="json")
            self.store.save_result(
                host_id=host_id, kind=JobKind.OS_NETWORK.value, job_id=ctx.job.id, data=data
            )
            return {"os_network": data}

        return self.runner.submit(kind=JobKind.OS_NETWORK, host_id=host_id, params={}, func=run)

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

    async def _default_esxi_reader(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
        if self.settings.simulate_esxi_file is not None:
            recorded = EsxiNetworkConfig.model_validate_json(self.settings.simulate_esxi_file.read_text())
            return recorded.model_copy(update={"address": access.address})
        return await read_network(access.address, access.username, password, verify_tls=access.verify_tls)

    def _default_client(self, host: Host, password: str) -> RedfishClient:
        transport = None
        if self.settings.simulate_bmc_dir is not None:
            transport = replay_transport(load_recording(self.settings.simulate_bmc_dir))
        return RedfishClient(
            host.bmc_address,
            host.username,
            password,
            verify_tls=host.verify_tls,
            timeout=self.settings.redfish_timeout,
            max_parallel=self.settings.redfish_max_parallel,
            transport=transport,
        )
