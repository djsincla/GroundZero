"""FastAPI dependencies: bearer-token auth and access to the application services."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from groundzero.core.services import Services

_bearer = HTTPBearer(auto_error=False, description="API token (see `groundzero token show`)")


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected: str = request.app.state.api_token
    if credentials is None or not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=401, detail="Missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"}
        )


ServicesDep = Annotated[Services, Depends(get_services)]
