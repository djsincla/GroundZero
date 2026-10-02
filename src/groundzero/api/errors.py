"""One error envelope for the whole API: RFC 9457 problem details (application/problem+json)."""

from __future__ import annotations

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from groundzero.core.jobs import HostBusyError
from groundzero.core.services import ConfirmationError, ConflictError, NotFoundError, SettingsValidationError
from groundzero.osconfig import OsConfigError
from groundzero.preflight.evaluate import UnknownProfileError

PROBLEM_JSON = "application/problem+json"


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    errors: list[dict[str, object]] | None = None


def problem_response(
    request: Request,
    status: int,
    code: str,
    detail: str | None,
    *,
    errors: list[dict[str, object]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = Problem(
        type=f"urn:groundzero:problem:{code}",
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=request.url.path,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


_DOMAIN_ERRORS: tuple[tuple[type[Exception], int, str], ...] = (
    (NotFoundError, 404, "not_found"),
    (ConflictError, 409, "conflict"),
    (HostBusyError, 409, "host_busy"),
    (UnknownProfileError, 422, "unknown_profile"),
    (ConfirmationError, 422, "confirmation_required"),
    (OsConfigError, 422, "os_config_invalid"),
)


def install_error_handlers(app: FastAPI) -> None:
    for exc_type, status, code in _DOMAIN_ERRORS:

        def handler(request: Request, exc: Exception, _s: int = status, _c: str = code) -> JSONResponse:
            return problem_response(request, _s, _c, str(exc))

        app.add_exception_handler(exc_type, handler)

    def http_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, HTTPException)
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        return problem_response(
            request,
            exc.status_code,
            code,
            str(exc.detail),
            headers=dict(exc.headers) if exc.headers else None,
        )

    def validation_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return problem_response(request, 422, "validation_error", "Request validation failed", errors=errors)

    def settings_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, SettingsValidationError)
        return problem_response(request, 422, "validation_error", str(exc), errors=exc.errors)

    app.add_exception_handler(SettingsValidationError, settings_handler)
    app.add_exception_handler(HTTPException, http_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
