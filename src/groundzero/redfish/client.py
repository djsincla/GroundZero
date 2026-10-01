"""Async Redfish client.

Design rules (lessons from the legacy collector):
- every call returns a typed response or raises a typed ``RedfishError``; nothing returns ``None`` on failure
- supports all verbs (GET/POST/PATCH/DELETE) so later milestones can drive VirtualMedia, boot and reset
- session auth with fallback to legacy ``/redfish/v1/Sessions`` and finally Basic auth
- the session token is only ever sent to the BMC host itself (Location headers pointing elsewhere are ignored)
- every request is recorded in ``request_log`` so callers can prove what was (not) changed on the BMC
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from groundzero.redfish.errors import (
    RedfishAuthError,
    RedfishError,
    RedfishNotFoundError,
    RedfishServerError,
    RedfishTransportError,
    RedfishUnsupportedError,
)

logger = logging.getLogger(__name__)

SERVICE_ROOT = "/redfish/v1"
_SESSION_PATHS = ("/redfish/v1/SessionService/Sessions", "/redfish/v1/Sessions")
# Transient "busy" conditions reported with non-503 statuses by some BMCs.
_BUSY_MESSAGE_MARKERS = ("SYS518", "ResourceNotReady", "ServiceTemporarilyUnavailable")
_RETRY_STATUSES = frozenset({429, 503})
# Safe to resend after a lost response. Busy/503 replies are retried for every verb: the BMC
# explicitly did not act on the request.
_IDEMPOTENT = frozenset({"GET", "HEAD", "DELETE"})


@dataclass(frozen=True)
class RedfishResponse:
    status: int
    headers: httpx.Headers
    body: dict[str, Any] | None

    def json(self) -> dict[str, Any]:
        return self.body or {}


@dataclass(frozen=True)
class RequestRecord:
    method: str
    path: str
    status: int | None


ResponseHook = Callable[[str, dict[str, Any]], None]


class RedfishClient:
    def __init__(
        self,
        bmc_address: str,
        username: str,
        password: str,
        *,
        verify_tls: bool = False,
        timeout: float = 30.0,
        max_parallel: int = 4,
        retries: int = 3,
        retry_backoff: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
        on_response: ResponseHook | None = None,
    ) -> None:
        self.base_url = bmc_address if "://" in bmc_address else f"https://{bmc_address}"
        self._host = urlsplit(self.base_url).netloc.lower()
        self._username = username
        self._password = password
        self._retries = max(1, retries)
        self._backoff = retry_backoff
        self._parallel = asyncio.Semaphore(max_parallel)
        self._on_response = on_response
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            verify=verify_tls,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json", "OData-Version": "4.0"},
        )
        self._token: str | None = None
        self._session_uri: str | None = None
        self._basic_auth = False
        self.request_log: list[RequestRecord] = []

    # ── lifecycle ────────────────────────────────────────────────────────
    async def __aenter__(self) -> Self:
        await self.login()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def login(self) -> None:
        """Create a Redfish session, falling back to Basic auth when sessions are unavailable."""
        credentials = {"UserName": self._username, "Password": self._password}
        for path in _SESSION_PATHS:
            resp = await self._send("POST", path, json=credentials, authenticate=False)
            if resp.status in (401, 403):
                raise RedfishAuthError("BMC rejected the credentials", status=resp.status, path=path)
            if resp.status in (404, 405):
                continue
            token = resp.headers.get("X-Auth-Token")
            if resp.status in (200, 201) and token:
                self._token = token
                self._session_uri = self._same_host_path(resp.headers.get("Location"))
                return
            break
        logger.info("Redfish sessions unavailable on %s; using Basic auth", self._host)
        self._basic_auth = True
        await self.get(SERVICE_ROOT + "/Systems")  # validates the credentials

    async def close(self) -> None:
        try:
            if self._token and self._session_uri:
                await self._send("DELETE", self._session_uri, authenticate=True)
        except RedfishError as exc:
            logger.warning("Failed to delete Redfish session on %s: %s", self._host, exc)
        finally:
            self._token = None
            await self._http.aclose()

    # ── verbs ────────────────────────────────────────────────────────────
    async def get(self, path: str) -> RedfishResponse:
        resp = await self.request("GET", path)
        if self._on_response is not None and resp.body is not None:
            self._on_response(self.normalize_path(path), resp.body)
        return resp

    async def get_json(self, path: str) -> dict[str, Any]:
        return (await self.get(path)).json()

    async def get_members(self, collection_path: str) -> list[dict[str, Any]]:
        collection = await self.get_json(collection_path)
        paths = [m["@odata.id"] for m in collection.get("Members", []) if "@odata.id" in m]
        return list(await asyncio.gather(*(self.get_json(p) for p in paths)))

    async def post(self, path: str, body: dict[str, Any], *, timeout: float | None = None) -> RedfishResponse:
        """``timeout`` overrides the client default; BMC actions (e.g. InsertMedia) can take minutes."""
        return await self.request("POST", path, json=body, timeout=timeout)

    async def patch(self, path: str, body: dict[str, Any], *, etag: str | None = None) -> RedfishResponse:
        headers = {"If-Match": etag} if etag else None
        return await self.request("PATCH", path, json=body, headers=headers)

    async def delete(self, path: str) -> RedfishResponse:
        return await self.request("DELETE", path)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> RedfishResponse:
        path = self.normalize_path(path)
        relogged = False
        for attempt in range(1, self._retries + 1):
            try:
                async with self._parallel:
                    resp = await self._send(method, path, json=json, headers=headers, timeout=timeout)
            except RedfishTransportError:
                # A timed-out action may still be executing on the BMC (seen live: iDRAC InsertMedia).
                # Replaying it could double a Reset or collide with itself, so only idempotent verbs retry.
                if attempt == self._retries or method not in _IDEMPOTENT:
                    raise
                await self._sleep(attempt)
                continue
            if resp.status == 401 and self._token and not relogged:
                relogged = True  # session expired: log in again once
                self._token = None
                await self.login()
                continue
            if attempt < self._retries and _is_transient(resp):
                await self._sleep(attempt)
                continue
            _raise_for_status(resp, path)
            return resp
        raise RedfishServerError("Exhausted retries", path=path)  # pragma: no cover - loop always returns

    # ── helpers ──────────────────────────────────────────────────────────
    def normalize_path(self, path: str) -> str:
        """Accept a Redfish path or same-host absolute URL; refuse anything pointing elsewhere."""
        if "://" in path:
            parts = urlsplit(path)
            if parts.netloc.lower() != self._host:
                raise RedfishError(f"Refusing to follow link to another host: {parts.netloc}", path=path)
            path = parts.path + (f"?{parts.query}" if parts.query else "")
        if not path.startswith("/redfish/"):
            raise RedfishError(f"Not a Redfish path: {path}", path=path)
        return path

    def _same_host_path(self, location: str | None) -> str | None:
        if not location:
            return None
        try:
            return self.normalize_path(location)
        except RedfishError:
            logger.warning("Ignoring session Location outside %s: %s", self._host, location)
            return None

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticate: bool = True,
        timeout: float | None = None,
    ) -> RedfishResponse:
        req_headers = dict(headers or {})
        auth: httpx.BasicAuth | None = None
        if authenticate:
            if self._token:
                req_headers["X-Auth-Token"] = self._token
            elif self._basic_auth:
                auth = httpx.BasicAuth(self._username, self._password)
        try:
            extra: dict[str, Any] = {"timeout": timeout} if timeout is not None else {}
            raw = await self._http.request(method, path, json=json, headers=req_headers, auth=auth, **extra)
        except httpx.HTTPError as exc:
            self.request_log.append(RequestRecord(method, path, None))
            detail = str(exc) or type(exc).__name__  # e.g. ReadTimeout carries no message
            raise RedfishTransportError(f"{method} {path} failed: {detail}", path=path) from exc
        self.request_log.append(RequestRecord(method, path, raw.status_code))
        return RedfishResponse(status=raw.status_code, headers=raw.headers, body=_parse_body(raw))

    async def _sleep(self, attempt: int) -> None:
        if self._backoff > 0:
            await asyncio.sleep(self._backoff * attempt)


def _parse_body(raw: httpx.Response) -> dict[str, Any] | None:
    if not raw.content:
        return None
    try:
        data = raw.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else {"value": data}


def _message_ids(body: dict[str, Any] | None) -> tuple[str, ...]:
    if not body:
        return ()
    error = body.get("error", {})
    infos = error.get("@Message.ExtendedInfo", []) if isinstance(error, dict) else []
    ids = [str(i.get("MessageId", "")) for i in infos if isinstance(i, dict)]
    if isinstance(error, dict) and error.get("code"):
        ids.append(str(error["code"]))
    return tuple(i for i in ids if i)


def _error_message(body: dict[str, Any] | None, fallback: str) -> str:
    if body and isinstance(body.get("error"), dict):
        err = body["error"]
        infos = err.get("@Message.ExtendedInfo") or []
        if infos and isinstance(infos[0], dict) and infos[0].get("Message"):
            return str(infos[0]["Message"])
        if err.get("message"):
            return str(err["message"])
    return fallback


def _is_transient(resp: RedfishResponse) -> bool:
    if resp.status in _RETRY_STATUSES:
        return True
    if resp.status >= 400:
        ids = " ".join(_message_ids(resp.body))
        return any(marker in ids for marker in _BUSY_MESSAGE_MARKERS)
    return False


def _raise_for_status(resp: RedfishResponse, path: str) -> None:
    if resp.status < 400:
        return
    ids = _message_ids(resp.body)
    msg = _error_message(resp.body, f"HTTP {resp.status} for {path}")
    kwargs: dict[str, Any] = {"status": resp.status, "path": path, "message_ids": ids}
    if resp.status in (401, 403):
        raise RedfishAuthError(msg, **kwargs)
    if resp.status == 404:
        raise RedfishNotFoundError(msg, **kwargs)
    if resp.status in (405, 501):
        raise RedfishUnsupportedError(msg, **kwargs)
    if resp.status >= 500:
        raise RedfishServerError(msg, **kwargs)
    raise RedfishError(msg, **kwargs)
