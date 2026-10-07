"""Specs and runs through the API (in-process, replayed BMC): the jobs picked for a server, run as one."""

from __future__ import annotations

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


def _host(api: TestClient, name: str = "esxi1") -> str:
    body = {"bmc_address": f"{name}.test", "name": name, "username": "root", "password": "calvin"}
    return str(api.post("/api/v1/hosts", json=body).json()["id"])


def _spec(api: TestClient, name: str, *tasks: str, **params: dict[str, Any]) -> dict[str, Any]:
    steps = [{"task": t, "params": params.get(t.replace(".", "_"), {})} for t in tasks]
    response = api.post("/api/v1/specs", json={"name": name, "steps": steps})
    assert response.status_code == 201, response.text
    return dict(response.json())


def _wait_run(api: TestClient, run_id: str) -> dict[str, Any]:
    for _ in range(400):
        run = api.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] != "running":
            return dict(run)
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def _task(pipeline: dict[str, Any], task_id: str) -> dict[str, Any]:
    return next(t for s in pipeline["stages"] for t in s["tasks"] if t["id"] == task_id)


def test_a_spec_is_checked_and_kept_in_pipeline_order(api: TestClient) -> None:
    bad = api.post(
        "/api/v1/specs",
        json={
            "name": "bad",
            "steps": [
                {"task": "nope"},
                {"task": "preflight", "params": {"variant": 12}},
                {"task": "preflight"},
                {"task": "appliance.deploy", "params": {"image_id": "missing.ova", "secrets": {"pw": "x"}}},
                {"task": "holodeck.deploy"},
            ],
        },
    )
    assert bad.status_code == 422
    found = {(tuple(e["loc"]), e["type"]) for e in bad.json()["errors"]}
    assert (("steps", 0, "task"), "unknown") in found
    assert (("steps", 1, "params", "variant"), "string_type") in found
    assert (("steps", 2, "task"), "duplicate") in found
    assert (("steps", 3, "params", "secrets"), "secret") in found
    assert (("steps", 3, "params", "image_id"), "not_found") in found
    assert (("steps", 4, "task"), "unavailable") in found

    spec = _spec(api, "Readiness", "vcf.readiness", "preflight", "discover")
    assert [s["task"] for s in spec["steps"]] == ["discover", "preflight", "vcf.readiness"]
    clash = api.post("/api/v1/specs", json={"name": "Readiness", "steps": [{"task": "discover"}]})
    assert clash.status_code == 409


def test_the_pipeline_follows_the_hosts_spec(api: TestClient) -> None:
    host = _host(api)
    plain = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assert plain["spec"] is None and _task(plain, "discover")["in_spec"] is None

    spec = _spec(api, "Readiness", "preflight", "vcf.readiness", preflight={"variant": "vcf-9.0-esa-single"})
    assigned = api.put(f"/api/v1/hosts/{host}/spec", json={"spec_id": spec["id"]}).json()
    assert assigned["source"] == "host" and assigned["spec"]["name"] == "Readiness"
    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assert p["spec"] == {
        "id": spec["id"],
        "name": "Readiness",
        "source": "host",
        "tasks": ["preflight", "vcf.readiness"],
    }
    assert _task(p, "preflight")["in_spec"] is True and _task(p, "discover")["in_spec"] is False
    assert _task(p, "preflight")["spec_params"] == {"variant": "vcf-9.0-esa-single"}
    assert p["next"]["task"] == "preflight" and "Readiness" in p["next"]["reason"]


def test_a_run_skips_what_is_done_and_needs_its_phrase(api: TestClient) -> None:
    host = _host(api)
    spec = _spec(api, "Readiness", "preflight", "vcf.readiness")
    api.put(f"/api/v1/hosts/{host}/spec", json={"spec_id": spec["id"]})

    preview = api.get(f"/api/v1/hosts/{host}/runs/preview").json()
    assert preview["phrase"] == "run Readiness on esxi1" and preview["destructive"] == []
    actions = {s["task"]: (s["action"], s["reason"]) for s in preview["steps"]}
    assert actions["preflight"] == ("run", None)
    assert actions["vcf.readiness"] == ("run", "After the steps before it")  # preflight makes the inventory

    refused = api.post(f"/api/v1/hosts/{host}/runs", json={"confirm": "yes"})
    assert refused.status_code == 422 and "run Readiness on esxi1" in refused.text
    started = api.post(f"/api/v1/hosts/{host}/runs", json={"confirm": "run Readiness on esxi1"})
    assert started.status_code == 202 and started.headers["Location"].startswith("/api/v1/runs/")
    run = _wait_run(api, started.json()["id"])
    assert run["status"] == "succeeded", run
    assert [(s["task"], s["status"]) for s in run["steps"]] == [
        ("preflight", "succeeded"),
        ("vcf.readiness", "succeeded"),
    ]
    assert all(s["job_id"] for s in run["steps"])
    assert api.get(f"/api/v1/hosts/{host}/pipeline").json()["next"]["title"] == "Done"

    again = _wait_run(
        api, api.post(f"/api/v1/hosts/{host}/runs", json={"confirm": "run Readiness on esxi1"}).json()["id"]
    )
    assert again["status"] == "succeeded"
    assert [s["status"] for s in again["steps"]] == ["skipped", "skipped"]
    assert again["steps"][0]["reason"].startswith("Done already: ")
    assert [r["id"] for r in api.get(f"/api/v1/hosts/{host}/runs").json()] == [again["id"], run["id"]]


def test_a_step_that_cant_start_stops_the_run(api: TestClient) -> None:
    host = _host(api)
    spec = _spec(api, "Read the OS", "preflight", "os.read", "host.assess")
    api.put(f"/api/v1/hosts/{host}/spec", json={"spec_id": spec["id"]})
    preview = api.get(f"/api/v1/hosts/{host}/runs/preview").json()
    blocked = next(s for s in preview["steps"] if s["task"] == "os.read")
    assert blocked["action"] == "blocked" and "OS access" in blocked["reason"]

    run = _wait_run(
        api, api.post(f"/api/v1/hosts/{host}/runs", json={"confirm": "run Read the OS on esxi1"}).json()["id"]
    )
    assert run["status"] == "failed" and "Read installed OS can't start" in run["error"]
    assert [s["status"] for s in run["steps"]] == ["succeeded", "failed", "cancelled"]


def test_a_cluster_spec_reaches_its_members_and_a_host_spec_overrides_it(api: TestClient) -> None:
    a, b = _host(api, "esx01"), _host(api, "esx02")
    cs = api.post(
        "/api/v1/config-sets",
        json={
            "name": "lab",
            "os_family": "esxi",
            "root_password": "pw-pw-pw",
            "settings": {"netmask": "255.255.255.0", "gateway": "192.0.2.1", "nameservers": ["192.0.2.53"]},
        },
    ).json()
    readiness = _spec(api, "Readiness", "preflight")
    discover = _spec(api, "Discover only", "discover")
    cluster = api.post(
        "/api/v1/clusters",
        json={
            "name": "lab",
            "config_set_id": cs["id"],
            "ip_first": "192.0.2.101",
            "ip_last": "192.0.2.110",
            "dns_domain": "lab.example",
            "spec_id": readiness["id"],
        },
    ).json()
    for h in (a, b):
        assert api.post(f"/api/v1/clusters/{cluster['id']}/members", json={"host_id": h}).status_code == 201
    api.put(f"/api/v1/hosts/{b}/spec", json={"spec_id": discover["id"]})

    assert api.get(f"/api/v1/hosts/{a}/spec").json()["source"] == "cluster"
    assert api.get(f"/api/v1/hosts/{b}/spec").json()["spec"]["name"] == "Discover only"
    preview = api.get(f"/api/v1/clusters/{cluster['id']}/runs/preview").json()
    assert preview["phrase"] == "run cluster lab"
    assert {p["host_name"]: p["spec_name"] for p in preview["hosts"]} == {
        "esx01": "Readiness",
        "esx02": "Discover only",
    }

    assert api.post(f"/api/v1/clusters/{cluster['id']}/runs", json={"confirm": "go"}).status_code == 422
    runs = api.post(f"/api/v1/clusters/{cluster['id']}/runs", json={"confirm": "run cluster lab"})
    assert runs.status_code == 202 and len(runs.json()) == 2
    done = [_wait_run(api, r["id"]) for r in runs.json()]
    assert {(r["host_name"], r["status"], r["cluster_id"]) for r in done} == {
        ("esx01", "succeeded", cluster["id"]),
        ("esx02", "succeeded", cluster["id"]),
    }

    in_use = api.delete(f"/api/v1/specs/{readiness['id']}")
    assert in_use.status_code == 409 and "cluster lab" in in_use.text
    assert api.delete(f"/api/v1/specs/{discover['id']}").status_code == 204
    assert api.get(f"/api/v1/hosts/{b}/spec").json()["source"] == "cluster"  # back to the cluster's
