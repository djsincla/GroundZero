"""Black-box: cluster mode through the real server (simulated R740xd whose iDRAC is named idrac-esx01)."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from .conftest import _simulated
from .harness import GroundZero

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isofactory import make_stock_iso

pytestmark = pytest.mark.functional

LAB = {"netmask": "255.255.255.0", "gateway": "192.0.2.1", "nameservers": ["192.0.2.53"], "vlan_id": 100,
       "install_nic": "vmnic0", "extra_uplinks": ["vmnic1"], "ntp_servers": ["pool.ntp.org"],
       "install_disk": {"mode": "first-match", "value": "DELLBOSS"}, "root_password": None}  # fmt: skip


def _server(tmp_path: Path, dns: dict[str, str]) -> GroundZero:
    gz = _simulated(
        tmp_path, GROUNDZERO_SIMULATE_BMC_HOSTNAME="idrac-esx01", GROUNDZERO_SIMULATE_DNS=json.dumps(dns)
    )
    make_stock_iso(gz.home / "isos" / "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso")
    gz.start()
    return gz


@pytest.fixture
def dns_ready(tmp_path: Path) -> Iterator[GroundZero]:
    gz = _server(tmp_path, {"esx01.lab.example": "192.0.2.101"})
    yield gz
    gz.stop()


@pytest.fixture
def dns_wrong(tmp_path: Path) -> Iterator[GroundZero]:
    gz = _server(tmp_path, {"esx01.lab.example": "192.0.2.150"})  # someone else's address
    yield gz
    gz.stop()


def _setup(gz: GroundZero, require_dns: bool) -> tuple[Any, str, str, str]:
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "rack1-u10").code == 0
    api = gz.api()
    host = api.get("/api/v1/hosts").json()[0]["id"]
    cs = api.post("/api/v1/config-sets", json={"name": "lab", "os_family": "esxi", "settings": LAB,
                                               "root_password": "Example-root1!"}).json()  # fmt: skip
    cluster = api.post("/api/v1/clusters", json={
        "name": "lab-a", "config_set_id": cs["id"], "ip_first": "192.0.2.101", "ip_last": "192.0.2.103",
        "dns_domain": "lab.example", "strip_prefix": "idrac-", "require_dns": require_dns,
    }).json()  # fmt: skip
    return api, host, cs["id"], cluster["id"]


def _install(api: Any, host: str, cs: str, iso: str) -> Any:
    body = {"params": {"iso_id": iso, "config_set_id": cs}, "confirm": "install rack1-u10"}
    return api.post(f"/api/v1/hosts/{host}/tasks/os.custom", json=body)


def _wait(api: Any, job_id: str) -> dict[str, Any]:
    for _ in range(300):
        job = api.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return dict(job)
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_a_member_is_named_after_its_bmc_and_given_the_next_address(dns_ready: GroundZero) -> None:
    api, host, cs, cluster = _setup(dns_ready, require_dns=True)
    member = api.post(f"/api/v1/clusters/{cluster}/members", json={"host_id": host})
    assert member.status_code == 201, member.text
    m = member.json()
    assert (m["bmc_hostname"], m["hostname"], m["ip"]) == ("idrac-esx01", "esx01", "192.0.2.101")
    values = api.get(f"/api/v1/hosts/{host}/host-values/esxi").json()
    assert (values["hostname"], values["ip"]) == ("esx01", "192.0.2.101")  # what the install will use
    again = api.post(f"/api/v1/clusters/{cluster}/members", json={"host_id": host})
    assert again.status_code == 409 and "already in cluster lab-a" in again.json()["detail"]

    iso = next(i for i in api.post("/api/v1/images/rescan").json() if i["kind"] == "iso")["id"]
    refused = _install(api, host, cs, iso)  # the cluster requires DNS: nothing has been checked yet
    assert refused.status_code == 409 and "Verify DNS" in refused.json()["detail"]

    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/dns.verify", json={}).json()["id"])
    assert job["status"] == "succeeded", job
    dns = api.get(f"/api/v1/hosts/{host}/outputs/dns").json()
    assert (dns["fqdn"], dns["servers"], dns["ok"]) == ("esx01.lab.example", ["192.0.2.53"], True)

    started = _install(api, host, cs, iso)
    assert started.status_code == 202, started.text
    api.post(f"/api/v1/jobs/{started.json()['id']}/cancel")


def test_wrong_records_are_named_and_block_the_install(dns_wrong: GroundZero) -> None:
    api, host, cs, cluster = _setup(dns_wrong, require_dns=True)
    api.post(f"/api/v1/clusters/{cluster}/members", json={"host_id": host})
    job = _wait(api, api.post(f"/api/v1/hosts/{host}/tasks/dns.verify", json={}).json()["id"])
    assert job["status"] == "failed"
    assert "esx01.lab.example resolves to 192.0.2.150, not 192.0.2.101" in job["error"]["message"]
    assert "192.0.2.101 has no PTR record" in job["error"]["message"]
    iso = next(i for i in api.post("/api/v1/images/rescan").json() if i["kind"] == "iso")["id"]
    refused = _install(api, host, cs, iso)
    assert refused.status_code == 409 and "DNS is not ready for esx01.lab.example" in refused.json()["detail"]
    override = {"iso_id": iso, "config_set_id": cs, "skip_dns_check": True}
    skipped = api.post(
        f"/api/v1/hosts/{host}/tasks/os.custom", json={"params": override, "confirm": "install rack1-u10"}
    )
    assert skipped.status_code == 202  # the explicit override
    api.post(f"/api/v1/jobs/{skipped.json()['id']}/cancel")


def test_the_dns_check_is_an_option(dns_wrong: GroundZero) -> None:
    """A cluster that does not ask for it installs without a DNS check, even with bad records."""
    api, host, cs, cluster = _setup(dns_wrong, require_dns=False)
    api.post(f"/api/v1/clusters/{cluster}/members", json={"host_id": host})
    iso = next(i for i in api.post("/api/v1/images/rescan").json() if i["kind"] == "iso")["id"]
    started = _install(api, host, cs, iso)
    assert started.status_code == 202, started.text
    api.post(f"/api/v1/jobs/{started.json()['id']}/cancel")
