"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from groundzero import __version__
from groundzero.api.deps import require_token
from groundzero.api.errors import install_error_handlers
from groundzero.api.routers import catalog, hosts, jobs, meta
from groundzero.core.config import Settings
from groundzero.core.credentials import CredentialCipher
from groundzero.core.jobs import JobRunner
from groundzero.core.services import ClientFactory, Services
from groundzero.core.store import Store
from groundzero.esxi.ops import EsxiOps
from groundzero.media.registry import MediaRegistry

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    client_factory: ClientFactory | None = None,
    esxi: EsxiOps | None = None,
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
            esxi=esxi,
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
    # Web UI: static files, a pure client of the API below (served without auth; data calls need the token).
    web = resources.files("groundzero") / "web"
    app.mount("/ui", StaticFiles(directory=str(web)), name="ui")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(web / "index.html"), headers={"Cache-Control": "no-store"})

    app.include_router(meta.health_router)
    secured = [Depends(require_token)]
    for router in (meta.router, hosts.router, jobs.router, catalog.router):
        app.include_router(router, prefix=API_PREFIX, dependencies=secured)
    return app
