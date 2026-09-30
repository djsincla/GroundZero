"""FastAPI application factory."""

from __future__ import annotations

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
from groundzero.core.services import ClientFactory, Services
from groundzero.core.store import Store

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, client_factory: ClientFactory | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_home()
        store = Store(settings.db_path)
        store.mark_interrupted()
        runner = JobRunner(store, settings.max_concurrent_jobs)
        app.state.api_token = settings.resolve_api_token()
        app.state.services = Services(settings, store, runner, CredentialCipher(settings), client_factory)
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
