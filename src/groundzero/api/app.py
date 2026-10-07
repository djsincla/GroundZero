"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from groundzero import __version__
from groundzero.api.deps import require_token
from groundzero.api.errors import install_error_handlers
from groundzero.api.routers import catalog, clusters, hosts, jobs, meta, specs
from groundzero.core.config import Settings
from groundzero.core.credentials import CredentialCipher
from groundzero.core.jobs import JobRunner
from groundzero.core.services import ClientFactory, Services
from groundzero.core.store import Store
from groundzero.esxi.ops import EsxiOps
from groundzero.media.registry import MediaRegistry

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


# The API explorer (Swagger UI). Every operation opens ready to run, so the first button is "Execute".
# It signs in with the web UI's session token (same origin and tab: same sessionStorage) once the spec has
# loaded; before that, Swagger silently drops the credentials. Inside the UI (?embed=1) Swagger's own title
# and Authorize blocks are hidden; opened standalone, Authorize stays available for pasting a token.
_DOCS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GroundZero API</title>
<link rel="icon" href="/ui/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>
  body { margin: 0; }
  .swagger-ui .info .link, .swagger-ui .info .description { display: none; }
  .embed .swagger-ui .information-container, .embed .swagger-ui .scheme-container { display: none; }
  .embed .swagger-ui .wrapper { padding: 0 16px; }
  .swagger-ui .try-out { display: none; }  /* always in "try it out" mode: Execute is the action */
</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
  const embedded = new URLSearchParams(location.search).has("embed");
  if (embedded) document.body.classList.add("embed");
  let token = null;
  try { token = sessionStorage.getItem("gz-token"); } catch (e) { /* storage blocked */ }
  window.ui = SwaggerUIBundle({
    url: "__OPENAPI_URL__",
    dom_id: "#swagger-ui",
    layout: "BaseLayout",
    deepLinking: true,
    tryItOutEnabled: true,
    persistAuthorization: !embedded,
    presets: [SwaggerUIBundle.presets.apis],
    onComplete: () => { if (token) window.ui.preauthorizeApiKey("HTTPBearer", token); },
  });
</script>
</body>
</html>
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
        store.interrupt_runs()
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
            await app.state.services.runs.shutdown()
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
        html = _DOCS_HTML.replace("__OPENAPI_URL__", app.openapi_url or "/openapi.json")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.include_router(meta.health_router)
    secured = [Depends(require_token)]
    for router in (meta.router, hosts.router, jobs.router, catalog.router, clusters.router, specs.router):
        app.include_router(router, prefix=API_PREFIX, dependencies=secured)
    return app
