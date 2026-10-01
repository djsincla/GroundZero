from __future__ import annotations

import httpx
import pytest

from groundzero.redfish.client import RedfishClient
from groundzero.redfish.errors import (
    RedfishAuthError,
    RedfishError,
    RedfishNotFoundError,
    RedfishTransportError,
)


def _client(handler: httpx.MockTransport) -> RedfishClient:
    return RedfishClient("bmc.test", "root", "calvin", transport=handler, retry_backoff=0)


async def test_session_login_uses_token_and_logs_out() -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.headers.get("X-Auth-Token")))
        if req.method == "POST":
            return httpx.Response(
                201, headers={"X-Auth-Token": "tok", "Location": "/redfish/v1/SessionService/Sessions/9"}
            )
        if req.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"ok": True})

    async with _client(httpx.MockTransport(handler)) as client:
        assert (await client.get_json("/redfish/v1/Systems")) == {"ok": True}

    assert seen == [
        ("POST", "/redfish/v1/SessionService/Sessions", None),
        ("GET", "/redfish/v1/Systems", "tok"),
        ("DELETE", "/redfish/v1/SessionService/Sessions/9", "tok"),
    ]


async def test_bad_credentials_raise_auth_error() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(401))
    with pytest.raises(RedfishAuthError):
        async with _client(transport):
            pass


async def test_falls_back_to_basic_auth_when_sessions_unsupported() -> None:
    auth_headers: list[str | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(405)
        auth_headers.append(req.headers.get("Authorization"))
        return httpx.Response(200, json={})

    async with _client(httpx.MockTransport(handler)) as client:
        await client.get("/redfish/v1/Chassis")
    assert all(h and h.startswith("Basic ") for h in auth_headers)


@pytest.mark.parametrize(
    "busy",
    [
        httpx.Response(503),
        httpx.Response(400, json={"error": {"@Message.ExtendedInfo": [{"MessageId": "IDRAC.2.8.SYS518"}]}}),
    ],
)
async def test_retries_transient_busy_responses(busy: httpx.Response) -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        calls["n"] += 1
        return busy if calls["n"] == 1 else httpx.Response(200, json={"v": 1})

    async with _client(httpx.MockTransport(handler)) as client:
        assert (await client.get_json("/redfish/v1")) == {"v": 1}
    assert calls["n"] == 2


async def test_not_found_is_typed_and_carries_message() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        return httpx.Response(404, json={"error": {"message": "nope"}})

    async with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(RedfishNotFoundError, match="nope"):
            await client.get("/redfish/v1/Nope")


async def test_refuses_links_to_other_hosts() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, headers={"X-Auth-Token": "t", "Location": "https://evil.test/redfish/v1/x"}
        )

    async with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(RedfishError, match="another host"):
            await client.get("https://evil.test/redfish/v1/Systems")
        assert client._session_uri is None  # foreign Location header ignored, token never sent there


async def test_actions_are_not_replayed_after_a_timeout() -> None:
    """Regression (live iDRAC): a timed-out InsertMedia was re-sent and collided with itself."""
    posts = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/Sessions"):
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        if req.method == "POST":
            posts["n"] += 1
            raise httpx.ReadTimeout("BMC still working", request=req)
        return httpx.Response(200, json={})

    async with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(RedfishTransportError):
            await client.post("/redfish/v1/Systems/1/Actions/ComputerSystem.Reset", {"ResetType": "On"})
    assert posts["n"] == 1


async def test_reads_are_retried_after_a_timeout() -> None:
    gets = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        gets["n"] += 1
        if gets["n"] == 1:
            raise httpx.ConnectTimeout("blip", request=req)
        return httpx.Response(200, json={"ok": 1})

    async with _client(httpx.MockTransport(handler)) as client:
        assert await client.get_json("/redfish/v1") == {"ok": 1}
    assert gets["n"] == 2


async def test_timeout_error_message_is_never_empty() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path.endswith("/Sessions"):
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        raise httpx.ReadTimeout("", request=req)

    async with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(RedfishTransportError, match="failed: ReadTimeout"):
            await client.post("/redfish/v1/x/Actions/VirtualMedia.InsertMedia", {}, timeout=1)
