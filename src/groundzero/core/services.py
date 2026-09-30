"""Application services: the single entry point used by the API (and therefore by every client).

HTTP handlers stay thin; everything here is plain Python that can be tested without a server.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from groundzero.core.config import Settings
from groundzero.core.credentials import CredentialCipher
from groundzero.core.jobs import JobContext, JobRunner
from groundzero.core.models import Host, HostCreate, Job, JobKind
from groundzero.core.store import Store
from groundzero.inventory.collect import collect_inventory
from groundzero.inventory.models import HostInventory
from groundzero.preflight.evaluate import UnknownProfileError, evaluate, load_profile
from groundzero.redfish.client import RedfishClient

logger = logging.getLogger(__name__)

ClientFactory = Callable[[Host, str], RedfishClient]


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
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.runner = runner
        self._cipher = cipher
        self._client_factory = client_factory or self._default_client

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
            inventory = await self._collect(host, ctx)
            return {"inventory": inventory.model_dump(mode="json")}

        return self.runner.submit(kind=JobKind.INVENTORY, host_id=host.id, params={}, func=run)

    def start_preflight(self, host_id: str, profile: str, variant: str | None) -> Job:
        host = self.get_host(host_id)
        spec = load_profile(profile)  # validate before queuing so bad input is a 4xx, not a failed job
        variant = variant or spec.default_variant
        if variant not in spec.variants:
            raise UnknownProfileError(f"Unknown variant '{variant}'; choose from {sorted(spec.variants)}")
        evaluate_args = {"profile": profile, "variant": variant}

        async def run(ctx: JobContext) -> dict[str, Any]:
            inventory = await self._collect(host, ctx)
            ctx.progress(0.97, "Evaluating preflight checks")
            report = evaluate(inventory, profile, variant)
            data = report.model_dump(mode="json")
            self.store.save_result(
                host_id=host.id, kind=JobKind.PREFLIGHT.value, job_id=ctx.job.id, data=data
            )
            return {"preflight": data}

        return self.runner.submit(kind=JobKind.PREFLIGHT, host_id=host.id, params=evaluate_args, func=run)

    # ── internals ────────────────────────────────────────────────────────
    async def _collect(self, host: Host, ctx: JobContext) -> HostInventory:
        password = self._cipher.decrypt(self._secret(host.id))
        async with self._client_factory(host, password) as client:
            identity, inventory = await collect_inventory(client, ctx.progress)
            writes = [r for r in client.request_log if r.method != "GET" and "Sessions" not in r.path]
            if writes:  # M1 is strictly read-only; make any violation loud
                logger.error("Unexpected non-GET requests during inventory: %s", writes)
        self.store.update_host_identity(host.id, vendor=identity.vendor.value, model=identity.model)
        self.store.save_result(
            host_id=host.id,
            kind=JobKind.INVENTORY.value,
            job_id=ctx.job.id,
            data=inventory.model_dump(mode="json"),
        )
        return inventory

    def _secret(self, host_id: str) -> bytes:
        secret = self.store.get_host_secret(host_id)
        if secret is None:
            raise NotFoundError(f"Host {host_id} not found")
        return secret

    def _default_client(self, host: Host, password: str) -> RedfishClient:
        return RedfishClient(
            host.bmc_address,
            host.username,
            password,
            verify_tls=host.verify_tls,
            timeout=self.settings.redfish_timeout,
            max_parallel=self.settings.redfish_max_parallel,
        )
