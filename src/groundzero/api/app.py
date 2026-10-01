"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from groundzero import __version__
from groundzero.api.deps import require_token
from groundzero.api.errors import install_error_handlers
from groundzero.api.routers import hosts, jobs, meta
from groundzero.core.config import Settings
from groundzero.core.credentials import CredentialCipher
from groundzero.core.jobs import JobRunner
from groundzero.core.services import ClientFactory, EsxiReader, Services
from groundzero.core.store import Store
from groundzero.media.registry import MediaRegistry

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    client_factory: ClientFactory | None = None,
    esxi_reader: EsxiReader | None = None,
    media: MediaRegistry | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_home()
        if settings.simulate_bmc_dir is not None:
            logger.warning(
                "SIMULATION MODE: BMCs are served from %s, not the network", settings.simulate_bmc_dir
            )
        store = Store(settings.db_path)
        store.mark_interrupted()
        runner = JobRunner(store, settings.max_concurrent_jobs)
        app.state.api_token = settings.resolve_api_token()
        app.state.services = Services(
            settings,
            store,
            runner,
            CredentialCipher(settings),
            client_factory=client_factory,
            esxi_reader=esxi_reader,
            media=media,
        )
        try:
            yield
        finally:
            await runner.shutdown()
            store.close()

    app = FastAPI(
        title="GroundZero API",
        version=__version__,
        summary="Bare metal → ESXi → VMware Holodeck, driven through one REST API.",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(meta.health_router)
    secured = [Depends(require_token)]
    for router in (meta.router, hosts.router, jobs.router):
        app.include_router(router, prefix=API_PREFIX, dependencies=secured)
    return app
