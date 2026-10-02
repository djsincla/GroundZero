"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

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


# Swagger's info block shows only the title (no spec link or tagline). Inside the web UI (?embed=1) the title
# and Authorize blocks go too and the UI's session token is reused (same origin and tab: same sessionStorage).
_DOCS_EMBED = """
<style>.swagger-ui .info .link, .swagger-ui .info .description { display: none; }</style>
<script>
  if (new URLSearchParams(location.search).has("embed")) {
    const style = document.createElement("style");
    style.textContent = "body{margin:0}.swagger-ui .information-container,.swagger-ui .scheme-container"
      + "{display:none}.swagger-ui .wrapper{padding:0 16px}";
    document.head.append(style);
    const token = sessionStorage.getItem("gz-token");
    const authorize = () => {
      if (typeof ui !== "undefined" && token) ui.preauthorizeApiKey("HTTPBearer", token);
    };
    window.addEventListener("load", () => setTimeout(authorize, 0));
  }
</script>
"""


class _UiFiles(StaticFiles):
    """UI modules are revalidated on each load (cheap via ETag): an upgrade never mixes old and new."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


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
        docs_url=None,  # served below, so the UI can embed it without Swagger's own header
    )
    install_error_handlers(app)
    # Web UI: static files, a pure client of the API below (served without auth; data calls need the token).
    web = resources.files("groundzero") / "web"
    app.mount("/ui", _UiFiles(directory=str(web)), name="ui")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(web / "index.html"), headers={"Cache-Control": "no-store"})

    @app.get("/docs", include_in_schema=False)
    def docs() -> HTMLResponse:
        page = get_swagger_ui_html(openapi_url=app.openapi_url or "/openapi.json", title="GroundZero API")
        html = bytes(page.body).decode().replace("</body>", _DOCS_EMBED + "</body>")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.include_router(meta.health_router)
    secured = [Depends(require_token)]
    for router in (meta.router, hosts.router, jobs.router, catalog.router):
        app.include_router(router, prefix=API_PREFIX, dependencies=secured)
    return app
