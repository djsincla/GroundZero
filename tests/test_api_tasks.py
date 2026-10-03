"""API: task catalog, per-host pipeline, generic task start and job diagnostics."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import make_client
from fastapi.testclient import TestClient

from groundzero.api.app import create_app
from groundzero.core.config import Settings
from groundzero.core.models import Host
from groundzero.redfish.client import RedfishClient
from groundzero.simulator.esxi import SimulatedEsxi

ESXI1 = Path(__file__).parent / "fixtures" / "esxi1"
TOKEN = "test-token"


@pytest.fixture
def api(tmp_path: Path, idrac9: dict[str, Any]) -> Iterator[TestClient]:
    settings = Settings(home=tmp_path / "home", api_token=TOKEN, iso_repository=tmp_path / "isos")

    def factory(host: Host, password: str) -> RedfishClient:
        return make_client(idrac9)

    with TestClient(create_app(settings, client_factory=factory, esxi=SimulatedEsxi(ESXI1))) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield client


def _host(api: TestClient) -> str:
    host = api.post(
        "/api/v1/hosts", json={"bmc_address": "bmc.test", "username": "root", "password": "calvin"}
    )
    return str(host.json()["id"])


def _wait(api: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(200):
        job = api.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return dict(job)
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _task(pipeline: dict[str, Any], task_id: str) -> dict[str, Any]:
    return next(t for s in pipeline["stages"] for t in s["tasks"] if t["id"] == task_id)


def test_catalog_lists_tasks_in_pipeline_order(api: TestClient) -> None:
    tasks = api.get("/api/v1/tasks").json()
    ids = [t["id"] for t in tasks]
    assert (
        ids.index("preflight")
        < ids.index("os.read")
        < ids.index("host.assess")
        < ids.index("holodeck.deploy")
    )
    custom = next(t for t in tasks if t["id"] == "os.custom")
    assert custom["destructive"] and custom["produces"] == "install"
    assert next(t for t in tasks if t["id"] == "os.read")["requires"] == ["os_access"]


def test_pipeline_walks_from_preflight_to_reading_the_os(api: TestClient) -> None:
    host = _host(api)
    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assert p["next"]["task"] == "preflight"

    blocked = api.post(f"/api/v1/hosts/{host}/tasks/os.read", json={})
    assert blocked.status_code == 409 and "Set OS access" in blocked.json()["detail"]

    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/preflight", json={}).json()["id"])
    assert job["status"] == "succeeded" and job["task"] == "preflight"
    assert [s["key"] for s in job["steps"]] == ["collect", "evaluate"]
    assert all(s["status"] == "succeeded" for s in job["steps"])

    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assert _task(p, "preflight")["state"] == "done"
    assert _task(p, "discover")["state"] == "done"  # preflight also produced the inventory
    assert p["next"]["task"] == "os.custom"  # no OS access yet

    api.put(f"/api/v1/hosts/{host}/os", json={"address": "192.0.2.101", "password": "esxi-pw"})
    assert api.get(f"/api/v1/hosts/{host}/pipeline").json()["next"]["task"] == "os.read"
    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/os.read", json={}).json()["id"])
    assert job["status"] == "succeeded", job
    assert [s["key"] for s in job["steps"]] == ["connect", "network", "storage"]

    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assert _task(p, "os.read")["state"] == "done"
    assert _task(p, "os.read")["output"]["summary"].startswith("VMware ESXi")
    assert _task(p, "host.assess")["state"] == "planned"


def test_unknown_and_unavailable_tasks(api: TestClient) -> None:
    host = _host(api)
    assert api.post(f"/api/v1/hosts/{host}/tasks/nope", json={}).status_code == 404
    planned = api.post(f"/api/v1/hosts/{host}/tasks/holodeck.deploy", json={})
    assert planned.status_code == 409 and "not available yet" in planned.json()["detail"]
    custom = api.post(f"/api/v1/hosts/{host}/tasks/os.custom", json={"confirm": "install bmc.test"})
    assert custom.status_code == 422 and "config set" in custom.json()["detail"]


def test_job_diagnostics_bundle_has_the_bmc_exchanges_and_no_secrets(api: TestClient) -> None:
    host = _host(api)
    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/discover", json={}).json()["id"])
    bundle = api.get(f"/api/v1/jobs/{job['id']}/diagnostics").json()
    assert bundle["job"]["id"] == job["id"] and bundle["groundzero"]["version"]
    assert bundle["bmc_identity"]["vendor"] == "dell"
    redfish = [e for e in bundle["events"] if e["event"] == "redfish"]
    assert len(redfish) > 10 and all("status" in e or "error" in e for e in redfish)
    assert "calvin" not in json.dumps(bundle)
    assert api.get("/api/v1/jobs/nope/diagnostics").status_code == 404
