from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import make_client
from fastapi.testclient import TestClient

from groundzero.api.app import create_app
from groundzero.core.config import Settings
from groundzero.core.models import Host, OsAccess
from groundzero.esxi.models import EsxiNetworkConfig
from groundzero.redfish.client import RedfishClient
from groundzero.simulator.esxi import SimulatedEsxi

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi.json"
ESXI1 = Path(__file__).parent / "fixtures" / "esxi1"
TOKEN = "test-token"


@pytest.fixture
def api(tmp_path: Path, idrac9: dict[str, Any]) -> Iterator[TestClient]:
    settings = Settings(home=tmp_path, api_token=TOKEN)

    def factory(host: Host, password: str) -> RedfishClient:
        assert password == "calvin"
        return make_client(idrac9)

    class Esxi(SimulatedEsxi):
        async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
            assert password == "esxi-secret"
            return await super().read_network(access, password)

    with TestClient(create_app(settings, client_factory=factory, esxi=Esxi(ESXI1))) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield client


def _add_host(api: TestClient) -> dict[str, Any]:
    resp = api.post(
        "/api/v1/hosts", json={"bmc_address": "bmc.test", "username": "root", "password": "calvin"}
    )
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


def _wait(api: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = api.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return dict(job)
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_healthz_is_public(api: TestClient) -> None:
    del api.headers["Authorization"]
    assert api.get("/healthz").json()["status"] == "ok"


def test_auth_required_with_problem_json(api: TestClient) -> None:
    del api.headers["Authorization"]
    resp = api.get("/api/v1/hosts")
    assert resp.status_code == 401
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["www-authenticate"] == "Bearer"
    assert resp.json()["type"] == "urn:groundzero:problem:unauthorized"


def test_host_crud_never_returns_password(api: TestClient) -> None:
    host = _add_host(api)
    assert "password" not in host and "secret" not in host
    assert api.get("/api/v1/hosts").json()[0]["id"] == host["id"]
    dup = api.post("/api/v1/hosts", json={"bmc_address": "bmc.test", "username": "x", "password": "y"})
    assert dup.status_code == 409
    assert api.delete(f"/api/v1/hosts/{host['id']}").status_code == 204
    assert api.get(f"/api/v1/hosts/{host['id']}").status_code == 404


def test_validation_errors_are_problems(api: TestClient) -> None:
    resp = api.post("/api/v1/hosts", json={"username": "root"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["type"] == "urn:groundzero:problem:validation_error"
    assert {tuple(e["loc"]) for e in body["errors"]} >= {("body", "bmc_address"), ("body", "password")}


def test_preflight_job_end_to_end(api: TestClient) -> None:
    host = _add_host(api)
    resp = api.post(f"/api/v1/hosts/{host['id']}/preflight", json={"profile": "holodeck-9"})
    assert resp.status_code == 202
    assert resp.headers["location"] == f"/api/v1/jobs/{resp.json()['id']}"

    job = _wait(api, resp.json()["id"])
    assert job["status"] == "succeeded", job
    assert job["result"]["preflight"]["overall"] == "pass"

    report = api.get(f"/api/v1/hosts/{host['id']}/preflight").json()
    assert report["variant"] == "vcf-9.0-esa-single"
    inventory = api.get(f"/api/v1/hosts/{host['id']}/inventory").json()
    assert inventory["system"]["model"] == "PowerEdge R740xd"
    refreshed = api.get(f"/api/v1/hosts/{host['id']}").json()
    assert (refreshed["vendor"], refreshed["model"]) == ("dell", "PowerEdge R740xd")


def test_bad_profile_and_variant_rejected_before_queueing(api: TestClient) -> None:
    host = _add_host(api)
    bad = api.post(f"/api/v1/hosts/{host['id']}/preflight", json={"profile": "nope"})
    assert bad.status_code == 422
    bad_variant = api.post(f"/api/v1/hosts/{host['id']}/preflight", json={"variant": "nope"})
    assert bad_variant.status_code == 422
    assert api.get("/api/v1/jobs").json() == []


def test_results_404_before_first_run(api: TestClient) -> None:
    host = _add_host(api)
    resp = api.get(f"/api/v1/hosts/{host['id']}/preflight")
    assert resp.status_code == 404
    assert resp.json()["type"] == "urn:groundzero:problem:not_found"


def test_job_events_stream_ends_with_terminal_event(api: TestClient) -> None:
    host = _add_host(api)
    job = api.post(f"/api/v1/hosts/{host['id']}/inventory").json()
    _wait(api, job["id"])
    with api.stream("GET", f"/api/v1/jobs/{job['id']}/events") as resp:
        body = "".join(resp.iter_text())
    assert "event: succeeded" in body


def test_profiles_listed(api: TestClient) -> None:
    profiles = api.get("/api/v1/profiles").json()
    assert profiles[0]["id"] == "holodeck-9"
    assert any(v["id"] == "vcf-9.1-single" for v in profiles[0]["variants"])


def test_openapi_snapshot(api: TestClient) -> None:
    """Contract guard: API changes must be deliberate (UPDATE_SNAPSHOTS=1 pytest to accept)."""
    spec = api.get("/openapi.json").json()
    if os.environ.get("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    assert spec == json.loads(SNAPSHOT.read_text())


def test_os_network_read_flow(api: TestClient) -> None:
    host = _add_host(api)
    missing = api.post(f"/api/v1/hosts/{host['id']}/os/network")
    assert missing.status_code == 404 and "PUT /hosts" in missing.json()["detail"]

    put = api.put(
        f"/api/v1/hosts/{host['id']}/os", json={"address": "192.0.2.101", "password": "esxi-secret"}
    )
    assert put.status_code == 200 and "password" not in put.json()
    assert put.json() == {"address": "192.0.2.101", "username": "root", "verify_tls": False}

    job = _wait(api, api.post(f"/api/v1/hosts/{host['id']}/os/network").json()["id"])
    assert job["status"] == "succeeded", job
    cfg = api.get(f"/api/v1/hosts/{host['id']}/os/network").json()
    assert cfg["address"] == "192.0.2.101"
    mgmt = next(p for p in cfg["portgroups"] if p["name"] == "Management Network")
    assert (mgmt["vlan_id"], mgmt["active_uplinks"]) == (100, ["vmnic0", "vmnic1"])
