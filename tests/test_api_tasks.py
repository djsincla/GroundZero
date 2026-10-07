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
    assert p["next"]["task"] == "os.custom"  # VCF 9 readiness is optional; no OS access yet
    assert _task(p, "vcf.readiness")["optional"] and _task(p, "vcf.readiness")["state"] == "ready"
    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/vcf.readiness", json={}).json()["id"])
    assert job["status"] == "succeeded" and job["result"]["vcf_readiness"]["cpu_override_required"] is False
    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assert p["next"]["task"] == "os.custom"  # no OS access yet

    api.put(f"/api/v1/hosts/{host}/os", json={"address": "192.0.2.101", "password": "esxi-pw"})
    assert (
        api.get(f"/api/v1/hosts/{host}/pipeline").json()["next"]["task"] == "host.assess"
    )  # reads the OS itself
    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/os.read", json={}).json()["id"])
    assert job["status"] == "succeeded", job
    assert [s["key"] for s in job["steps"]] == ["connect", "network", "storage"]

    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assert _task(p, "os.read")["state"] == "done"
    assert _task(p, "os.read")["output"]["summary"].startswith("VMware ESXi")
    assert _task(p, "host.assess")["state"] == "ready"
    assert p["next"]["task"] == "host.assess"


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


def test_assess_reads_the_os_and_plans_fixes(api: TestClient) -> None:
    host = _host(api)
    api.put(f"/api/v1/hosts/{host}/os", json={"address": "192.0.2.101", "password": "esxi-pw"})
    blocked = api.post(f"/api/v1/hosts/{host}/tasks/host.assess", json={})
    assert blocked.status_code == 409 and "Holodeck preflight" in blocked.json()["detail"]  # needs its input

    assert (
        _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/preflight", json={}).json()["id"])["status"]
        == "succeeded"
    )
    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/host.assess", json={}).json()["id"])
    assert job["status"] == "succeeded", job
    assert [s["key"] for s in job["steps"]] == ["connect", "network", "storage", "evaluate"]

    report = api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()
    assert report["variant"] == "vcf-9.0-esa-single"  # taken from the preflight output
    assert report["storage"] == {**report["storage"], "kind": "existing", "datastore": "localHolodeck"}
    assert {a["id"] for a in report["plan"]} >= {"set_mtu", "configure_ntp", "verify_jumbo"}
    assert not report["ready"]

    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assess = _task(p, "host.assess")
    assert assess["state"] == "done" and "to fix for VCF 9.0" in assess["output"]["summary"]
    assert _task(p, "os.read")["state"] == "done"  # the assessment's fresh OS read is reused


def _app(tmp_path: Path, idrac9: dict[str, Any], esxi: SimulatedEsxi) -> TestClient:
    settings = Settings(home=tmp_path / "home2", api_token=TOKEN, iso_repository=tmp_path / "isos")
    client = TestClient(create_app(settings, client_factory=lambda h, p: make_client(idrac9), esxi=esxi))
    client.headers["Authorization"] = f"Bearer {TOKEN}"
    return client


def _assessed(api: TestClient) -> str:
    host = _host(api)
    api.put(f"/api/v1/hosts/{host}/os", json={"address": "192.0.2.101", "password": "esxi-pw"})
    assert (
        _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/preflight", json={}).json()["id"])["status"]
        == "succeeded"
    )
    for task in ("vcf.readiness", "host.assess"):
        job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/{task}", json={}).json()["id"])
        assert job["status"] == "succeeded", job
    return host


def test_prepare_then_verify_makes_the_host_ready(tmp_path: Path, idrac9: dict[str, Any]) -> None:
    esxi = SimulatedEsxi(ESXI1)
    with _app(tmp_path, idrac9, esxi) as api:
        host = _assessed(api)
        jumbo_early = api.post(f"/api/v1/hosts/{host}/tasks/net.verify_jumbo", json={})
        assert jumbo_early.status_code == 409 and "Prepare host" in jumbo_early.json()["detail"]

        bad = api.post(f"/api/v1/hosts/{host}/tasks/host.prep", json={"params": {"checks": ["nope"]}})
        assert bad.status_code == 422 and "Not in the current plan" in bad.json()["detail"]

        plan = api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()["plan"]
        checks = [
            a["check"] for a in plan if a["task"] == "host.prep"
        ]  # incl. the optional VLAN 100 external
        assert checks == ["ntp", "network.mtu", "network.external"]  # this esxi1 capture already has trunks
        job = _wait(
            api,
            api.post(f"/api/v1/hosts/{host}/tasks/host.prep", json={"params": {"checks": checks}}).json()[
                "id"
            ],
        )
        assert job["status"] == "succeeded", job
        assert [s["key"] for s in job["steps"]] == [*checks, "reassess"]
        assert all(s["status"] == "succeeded" for s in job["steps"])
        assert {c.action for c in esxi.changes} == {"configure_ntp", "set_mtu", "ensure_portgroup"}
        prep = job["result"]["host_prep"]
        assert (
            prep["trunk_portgroup"].startswith(("HoloDeck", "holo"))
            and prep["external_portgroup"] == "Holodeck-External"
        )
        assert prep["datastore"] == "localHolodeck" and prep["vswitch"] == "vSwitch0"

        report = api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()
        status = {c["id"]: c["status"] for c in report["checks"]}
        assert (
            status["network.mtu"]
            == status["network.trunk"]
            == status["ntp"]
            == status["network.external"]
            == "pass"
        )
        assert [a["id"] for a in report["plan"]] == ["verify_jumbo"]

        assert (
            api.post(f"/api/v1/hosts/{host}/tasks/host.prep", json={"params": {"checks": []}}).status_code
            == 422
        )

        job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/net.verify_jumbo", json={}).json()["id"])
        assert job["status"] == "succeeded", job
        assert (
            job["result"]["jumbo"]["uplinks"] == ["vmnic0", "vmnic1"]  # keep mgmt NIC, borrow vmnic1
            and job["result"]["jumbo"]["vlan"] == 100
        )
        report = api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()
        assert report["ready"] and report["plan"] == []
        pins = {c["role"]: c["fingerprint"] for c in api.get(f"/api/v1/hosts/{host}/certificates").json()}
        assert pins["os-ssh"] == "SHA256:simulated-host-key"

        p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
        assert _task(p, "host.prep")["state"] == "done" and _task(p, "net.verify_jumbo")["state"] == "done"
        assert p["next"]["task"] == "holodeck.router"  # the Holodeck stage is next


def test_formatting_a_disk_needs_its_typed_phrase(tmp_path: Path, idrac9: dict[str, Any]) -> None:
    esxi = SimulatedEsxi(ESXI1)
    big = next(d for d in esxi.storage.disks if "4TB" in (d.model or ""))  # free the 4 TB disk for the test
    esxi.storage.datastores = [d for d in esxi.storage.datastores if d.name != "localHolodeck"]
    big.datastores, big.partitions = [], 0
    with _app(tmp_path, idrac9, esxi) as api:
        host = _assessed(api)
        report = api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()
        action = next(a for a in report["plan"] if a["id"] == "create_datastore")
        assert action["destructive"] and action["params"]["disk"] == big.name
        body = {"params": {"checks": ["storage.datastore"]}, "confirm": "format it"}
        refused = api.post(f"/api/v1/hosts/{host}/tasks/host.prep", json=body)
        assert refused.status_code == 422 and action["confirm_phrase"] in refused.json()["detail"]
        assert esxi.changes == []

        body["confirm"] = action["confirm_phrase"]
        job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/host.prep", json=body).json()["id"])
        assert job["status"] == "succeeded", job
        report = api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()
        assert report["storage"]["kind"] == "existing" and report["storage"]["datastore"] == "holodeck"
        assert job["result"]["host_prep"]["datastore"] == "holodeck"


def test_a_switch_dropping_jumbo_frames_fails_the_check(tmp_path: Path, idrac9: dict[str, Any]) -> None:
    esxi = SimulatedEsxi(ESXI1, faults=frozenset({"jumbo-drops"}))
    with _app(tmp_path, idrac9, esxi) as api:
        host = _assessed(api)
        assert (
            _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/host.prep", json={}).json()["id"])["status"]
            == "succeeded"
        )
        job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/net.verify_jumbo", json={}).json()["id"])
        assert job["status"] == "failed" and "do not pass through the switch" in job["error"]["message"]
        loop = next(s for s in job["steps"] if s["key"] == "loop")
        assert loop["status"] == "succeeded"  # the test ran; it is the result that failed
        report = api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()
        jumbo_check = next(c for c in report["checks"] if c["id"] == "network.jumbo")
        assert jumbo_check["status"] == "fail" and not report["ready"]


def _fake_ova(isos: Path, name: str = "holorouter-9.1.1.0456.ova") -> None:
    """The Holorouter OVA with its real (trimmed) descriptor: the simulator rejects undeclared properties."""
    import tarfile

    isos.mkdir(parents=True, exist_ok=True)
    with tarfile.open(isos / name, "w") as tar:
        tar.add(
            Path(__file__).parent / "fixtures" / "ova" / "holorouter-9.1.1.ovf",
            arcname=name.replace(".ova", ".ovf"),
        )


def test_deploy_holorouter_after_prep(tmp_path: Path, idrac9: dict[str, Any]) -> None:
    esxi = SimulatedEsxi(ESXI1)
    _fake_ova(tmp_path / "isos")
    with _app(tmp_path, idrac9, esxi) as api:
        host = _assessed(api)
        image = next(i for i in api.post("/api/v1/images/rescan").json() if i["os_family"] == "holorouter")
        profile = {"name": "lab-router", "image_id": image["id"],
                   "values": {"mask": "24", "gateway": "192.0.2.1", "dns_server": "192.0.2.53"}}  # fmt: skip
        created = api.post("/api/v1/appliance-profiles", json=profile).json()

        def run(**params: Any) -> Any:
            return api.post(
                f"/api/v1/hosts/{host}/tasks/holodeck.router",
                json={"params": {"profile_id": created["id"], **params.pop("p", {})}, **params},
            )

        assert run().status_code == 409  # readiness/prep first (pipeline inputs)
        checks = [
            a["check"]
            for a in api.get(f"/api/v1/hosts/{host}/outputs/readiness").json()["plan"]
            if a["task"] == "host.prep"
        ]
        prep = api.post(f"/api/v1/hosts/{host}/tasks/host.prep", json={"params": {"checks": checks}}).json()
        assert _wait(api, prep["id"])["status"] == "succeeded"
        jumbo = api.post(f"/api/v1/hosts/{host}/tasks/net.verify_jumbo", json={}).json()
        assert _wait(api, jumbo["id"])["status"] == "succeeded"

        no_values = run()
        assert no_values.status_code == 422 and "Holodeck values" in no_values.json()["detail"]
        api.put(f"/api/v1/hosts/{host}/host-values/holodeck", json={"holorouter_ip": "192.0.2.150"})
        no_password = run()
        assert no_password.status_code == 422 and "no password" in no_password.json()["detail"]
        api.put(f"/api/v1/appliance-profiles/{created['id']}",
                json={**profile, "secrets": {"password": "Holo-pass1!"}})  # fmt: skip

        job = _wait(api, run().json()["id"])
        assert job["status"] == "succeeded", job
        assert [s["key"] for s in job["steps"]] == ["deploy", "ssh"]
        vm = esxi.vms["holo1-holorouter"]
        assert vm["datastore"] == "localHolodeck"
        assert vm["networks"] == {
            "VM Management Network": "Holodeck-External",
            "Trunk Portgroup for Site A": vm["networks"]["Trunk Portgroup for Site A"],
            "Trunk Portgroup for Site B": vm["networks"]["Trunk Portgroup for Site A"],
        }
        props = vm["properties"]  # as the guest reads them: qualified, every declared property present
        assert (props["network.ip"], props["network.mask"], props["network.gateway"]) == (
            "192.0.2.150", "24", "192.0.2.1")  # fmt: skip
        assert props["network.hostname"] == "holorouter"  # this host's value, from its Holodeck values
        assert props["extra.ssh_enabled"] == "True" and props["network.password"] == "Holo-pass1!"
        assert props["extra.webtop_enabled"] == "true"  # not in the profile: the OVA's default
        assert (
            "Holo-pass1!" not in json.dumps(job)
            and "Holo-pass1!" not in api.get(f"/api/v1/jobs/{job['id']}/diagnostics").text
        )

        p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
        router = _task(p, "holodeck.router")
        assert router["state"] == "done" and router["output"]["summary"].startswith(
            "holo1-holorouter at 192.0.2.150"
        )
        again = _wait(api, run().json()["id"])  # idempotent: the VM exists
        assert again["status"] == "succeeded" and again["steps"][0]["message"].endswith("left as is")

        # Changing a deployed Holorouter means a fresh VM (it applies settings on first boot only)
        unconfirmed = run(p={"replace": True, "values": {"network.gateway": "192.0.2.254"}})
        assert unconfirmed.status_code == 422 and "replace holo1-holorouter" in unconfirmed.json()["detail"]
        replaced = _wait(api, run(p={"replace": True, "values": {"network.gateway": "192.0.2.254"}},
                                  confirm="replace holo1-holorouter").json()["id"])  # fmt: skip
        assert replaced["status"] == "succeeded" and replaced["steps"][0]["message"].startswith("replaced")
        assert esxi.vms["holo1-holorouter"]["properties"]["network.gateway"] == "192.0.2.254"


def test_pipeline_shows_what_each_task_uses_and_feeds(api: TestClient) -> None:
    """Outputs of one step are the inputs of the next: the pipeline names both directions."""
    host = _host(api)
    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    assess = _task(p, "host.assess")
    inputs = {i["kind"]: i for i in assess["inputs"]}
    assert inputs["preflight"] == {**inputs["preflight"], "required": True, "status": "missing",
                                   "from_task": "preflight", "from_title": "Holodeck preflight"}  # fmt: skip
    assert inputs["os_access"]["status"] == "missing" and inputs["jumbo"]["required"] is False
    assert {(f["task"], f["kind"]) for f in _task(p, "preflight")["feeds"]} >= {
        ("host.assess", "preflight"), ("vcf.readiness", "inventory")}  # fmt: skip

    _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/preflight", json={}).json()["id"])
    p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
    ref = next(i for i in _task(p, "host.assess")["inputs"] if i["kind"] == "preflight")
    assert ref["status"] == "ok" and ref["produced_at"]
    kinds = {o["kind"] for o in api.get(f"/api/v1/hosts/{host}/outputs").json()}
    assert kinds == {"preflight", "inventory"}  # preflight also saved the inventory
    assert api.get(f"/api/v1/hosts/{host}/outputs/inventory").json()["system"]["model"] == "PowerEdge R740xd"
    assert api.get(f"/api/v1/hosts/{host}/outputs/nope").status_code == 404


def test_deploy_any_appliance_from_a_profile(tmp_path: Path, idrac9: dict[str, Any]) -> None:
    import tarfile

    esxi = SimulatedEsxi(ESXI1)
    repo = tmp_path / "isos"
    repo.mkdir(parents=True, exist_ok=True)
    name = "VCF-SDDC-Manager-Appliance-9.1.1.0.25713928.ova"
    with tarfile.open(repo / name, "w") as tar:
        tar.add(
            Path(__file__).parent / "fixtures" / "ova" / "sddc-manager-9.1.1.ovf", arcname=name[:-4] + ".ovf"
        )
    with _app(tmp_path, idrac9, esxi) as api:
        host = _host(api)
        api.put(f"/api/v1/hosts/{host}/os", json={"address": "192.0.2.101", "password": "esxi-pw"})
        image = next(i for i in api.post("/api/v1/images/rescan").json() if i["kind"] == "ova")
        profile = api.post("/api/v1/appliance-profiles", json={
            "name": "lab-sddc", "image_id": image["id"],
            "values": {"vami.hostname": "sddc-manager", "ip0": "192.0.2.20", "netmask0": "255.255.255.0"},
            "secrets": {"ROOT_PASSWORD": "Example-pass-15chars"},
        }).json()  # fmt: skip

        def deploy(confirm: str | None = None, **params: Any) -> Any:
            body = {
                "params": {
                    "image_id": image["id"],
                    "profile_id": profile["id"],
                    "vm_name": "sddc-manager",
                    "datastore": "localHolodeck",
                    **params,
                }
            }
            return api.post(f"/api/v1/hosts/{host}/tasks/appliance.deploy", json={**body, "confirm": confirm})

        unmapped = deploy(values={"bogus": "1"})
        assert unmapped.status_code == 422
        assert {tuple(e["loc"]) for e in unmapped.json()["errors"]} == {
            ("values", "bogus"),
            ("networks", "Network 1"),
        }
        assert api.get("/api/v1/jobs").json() == []  # nothing queued

        job = _wait(api, deploy(networks={"Network 1": "VM Network"}).json()["id"])
        assert job["status"] == "succeeded", job
        assert "Example-pass-15chars" not in json.dumps(job)  # passwords never land on the job
        vm = esxi.vms["sddc-manager"]
        assert (
            vm["properties"]["vami.ip0.SDDC-Manager"] == "192.0.2.20"
        )  # instance-qualified, as the guest reads it
        assert vm["properties"]["ROOT_PASSWORD"] == "Example-pass-15chars"
        assert vm["properties"]["vami.ip_address_version.SDDC-Manager"] == "IPv4"  # the OVA's default
        out = api.get(f"/api/v1/hosts/{host}/outputs/appliance:sddc-manager").json()
        assert (out["product"], out["ip"], out["datastore"]) == (
            "VMware VCF SDDC Manager Appliance",
            "192.0.2.20",
            "localHolodeck",
        )
        assert "appliance:sddc-manager" in {
            o["kind"] for o in api.get(f"/api/v1/hosts/{host}/outputs").json()
        }

        again = deploy(networks={"Network 1": "VM Network"}, replace=True)
        assert again.status_code == 422 and 'exactly "replace sddc-manager"' in again.json()["detail"]
        replaced = _wait(
            api,
            deploy("replace sddc-manager", networks={"Network 1": "VM Network"}, replace=True).json()["id"],
        )
        assert replaced["status"] == "succeeded" and replaced["result"]["appliance"]["replaced"] is True


def test_the_simulated_host_rejects_properties_the_ova_does_not_declare(tmp_path: Path) -> None:
    """Like a real appliance: an undeclared key would be ignored by the guest, so it is an error."""
    import asyncio
    import tarfile

    from groundzero.core.models import OsAccess
    from groundzero.esxi.reader import EsxiError

    ova = tmp_path / "holorouter.ova"
    with tarfile.open(ova, "w") as tar:
        tar.add(Path(__file__).parent / "fixtures" / "ova" / "holorouter-9.1.1.ovf", arcname="holorouter.ovf")
    esxi = SimulatedEsxi(ESXI1)
    with pytest.raises(EsxiError, match="declares no property bogus"):
        asyncio.run(
            esxi.deploy_ova(
                OsAccess(address="192.0.2.101", username="root", verify_tls=False),
                "pw",
                ova,
                vm_name="x",
                datastore="localHolodeck",
                networks={},
                properties={"bogus": "1"},
                progress=lambda f, m: None,
            )
        )


def test_capture_a_profile_from_a_deployed_appliance(tmp_path: Path, idrac9: dict[str, Any]) -> None:
    """Read an existing deployment to make the next one easy: the OVA is matched by the VM's settings."""
    esxi = SimulatedEsxi(ESXI1)
    _fake_ova(tmp_path / "isos")
    with _app(tmp_path, idrac9, esxi) as api:
        host = _host(api)
        api.put(f"/api/v1/hosts/{host}/os", json={"address": "192.0.2.101", "password": "esxi-pw"})
        image = next(i for i in api.post("/api/v1/images/rescan").json() if i["kind"] == "ova")
        params = {"image_id": image["id"], "vm_name": "router-a", "datastore": "localHolodeck",
                  "values": {"ip": "192.0.2.150", "gateway": "192.0.2.1", "webtop_enabled": False},
                  "secrets": {"password": "Holo-pass1!"},
                  "networks": dict.fromkeys(("VM Management Network", "Trunk Portgroup for Site A",
                                             "Trunk Portgroup for Site B"), "VM Network")}  # fmt: skip
        deployed = api.post(f"/api/v1/hosts/{host}/tasks/appliance.deploy", json={"params": params}).json()
        assert _wait(api, deployed["id"])["status"] == "succeeded"

        capture = {"params": {"vm_name": "router-a", "name": "from-router-a"}}
        job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/appliance.capture", json=capture).json()["id"])
        assert job["status"] == "succeeded", job
        assert job["result"]["passwords_not_copied"] == ["network.password"]
        profile = api.get(f"/api/v1/appliance-profiles/{job['result']['profile_id']}").json()
        assert profile["product"] == "HoloRouter" and profile["image_id"] == image["id"]
        assert profile["source"].startswith("captured from router-a")
        assert (
            profile["values"]["network.ip"] == "192.0.2.150"
            and profile["values"]["extra.webtop_enabled"] is False
        )
        assert profile["secrets_set"] == []  # passwords are never copied out of a VM
        assert profile["networks"]["VM Management Network"] == "VM Network"
        assert "Holo-pass1!" not in json.dumps(job)

        again = api.post(f"/api/v1/hosts/{host}/tasks/appliance.capture", json=capture)
        assert again.status_code == 409  # the name is taken
        missing = {"params": {"vm_name": "nope", "name": "x"}}
        job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/appliance.capture", json=missing).json()["id"])
        assert job["status"] == "failed" and "No VM named nope" in job["error"]["message"]


def test_adopt_a_hand_deployed_holorouter_and_correct_its_record(
    tmp_path: Path, idrac9: dict[str, Any]
) -> None:
    """A VM deployed outside GroundZero feeds the later Holodeck steps once it is adopted."""
    esxi = SimulatedEsxi(ESXI1)
    _fake_ova(tmp_path / "isos")
    with _app(tmp_path, idrac9, esxi) as api:
        host = _host(api)
        api.put(f"/api/v1/hosts/{host}/os", json={"address": "192.0.2.101", "password": "esxi-pw"})
        image = next(i for i in api.post("/api/v1/images/rescan").json() if i["kind"] == "ova")
        nets = dict.fromkeys(
            ("VM Management Network", "Trunk Portgroup for Site A", "Trunk Portgroup for Site B"),
            "VM Network",
        )
        by_hand = {
            "image_id": image["id"],
            "vm_name": "my-router",
            "datastore": "localHolodeck",
            "networks": nets,
            "values": {"ip": "192.0.2.150", "hostname": "router"},
            "secrets": {"password": "Holo-pass1!"},
        }
        assert (
            _wait(
                api,
                api.post(f"/api/v1/hosts/{host}/tasks/appliance.deploy", json={"params": by_hand}).json()[
                    "id"
                ],
            )["status"]
            == "succeeded"
        )
        assert "my-router" in {v["name"] for v in api.get(f"/api/v1/hosts/{host}/vms").json()}

        adopt = {
            "params": {"vm_name": "my-router", "role": "holorouter", "profile_name": "my-router-profile"}
        }
        job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/appliance.adopt", json=adopt).json()["id"])
        assert job["status"] == "succeeded", job
        assert [s["key"] for s in job["steps"]] == ["read", "ssh", "record"]
        assert (
            job["result"]["holorouter"]["ip"] == "192.0.2.150"
            and job["result"]["holorouter"]["hostname"] == "router"
        )
        profile = api.get(f"/api/v1/appliance-profiles/{job['result']['profile_id']}").json()
        assert profile["product"] == "HoloRouter" and profile["values"]["network.ip"] == "192.0.2.150"

        p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
        router = _task(p, "holodeck.router")
        assert router["state"] == "done" and router["output"]["source"] == "adopted"
        stage = next(i for i in _task(p, "holodeck.stage")["inputs"] if i["kind"] == "holorouter")
        assert stage["status"] == "ok"  # the next Holodeck step sees it like a GroundZero deployment

        # Correct the record by hand: checked against the output's model, marked manual
        fixed = {**job["result"]["holorouter"], "ip": "192.0.2.151"}
        assert api.put(f"/api/v1/hosts/{host}/outputs/holorouter", json=fixed).status_code == 200
        assert api.get(f"/api/v1/hosts/{host}/outputs/holorouter").json()["ip"] == "192.0.2.151"
        p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
        assert _task(p, "holodeck.router")["output"]["source"] == "manual"
        bad = api.put(f"/api/v1/hosts/{host}/outputs/holorouter", json={"ip": "192.0.2.151"})
        assert bad.status_code == 422 and ("output", "vm_name") in {
            tuple(e["loc"]) for e in bad.json()["errors"]
        }
        assert api.put(f"/api/v1/hosts/{host}/outputs/nope", json={}).status_code == 404
        kinds = api.get("/api/v1/output-kinds").json()
        assert (
            kinds["holorouter"]["title"] == "Holorouter"
            and "vm_name" in kinds["holorouter"]["schema"]["properties"]
        )
