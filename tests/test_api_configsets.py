"""API: OS families, config sets, per-server values, capture, ISO repository, deploy preview."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import make_client
from fastapi.testclient import TestClient
from isofactory import make_stock_iso

from groundzero.api.app import create_app
from groundzero.core.config import Settings
from groundzero.core.models import Host
from groundzero.redfish.client import RedfishClient
from groundzero.simulator.esxi import SimulatedEsxi

ESXI1 = Path(__file__).parent / "fixtures" / "esxi1"
TOKEN = "test-token"
SECRET = "S3cret-root!"

LAB = {
    "netmask": "255.255.255.0",
    "gateway": "192.0.2.1",
    "nameservers": ["8.8.8.8"],
    "vlan_id": 100,
    "install_nic": "vmnic0",
    "extra_uplinks": ["vmnic1"],
    "ntp_servers": ["pool.ntp.org"],
    "install_disk": {"mode": "first-match", "value": "DELLBOSS"},
}


@pytest.fixture
def api(tmp_path: Path, idrac9: dict[str, Any]) -> Iterator[TestClient]:
    isos = tmp_path / "isos"
    make_stock_iso(isos / "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso")
    (isos / "notes.iso").write_bytes(b"not an installer")
    settings = Settings(home=tmp_path / "home", api_token=TOKEN, iso_repository=isos)

    def factory(host: Host, password: str) -> RedfishClient:
        return make_client(idrac9)

    with TestClient(create_app(settings, client_factory=factory, esxi=SimulatedEsxi(ESXI1))) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield client


def _host(api: TestClient, with_os: bool = True) -> str:
    host = api.post(
        "/api/v1/hosts",
        json={"bmc_address": "bmc.test", "username": "root", "password": "calvin", "name": "esxi1"},
    ).json()
    if with_os:
        assert (
            api.put(
                f"/api/v1/hosts/{host['id']}/os", json={"address": "192.0.2.101", "password": "esxi-pw"}
            ).status_code
            == 200
        )
    return str(host["id"])


def _wait(api: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(200):
        job = api.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return dict(job)
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_os_families_expose_schemas(api: TestClient) -> None:
    families = api.get("/api/v1/os-families").json()
    esxi = next(f for f in families if f["family"] == "esxi")
    assert esxi["install_supported"] is True and esxi["secret_fields"] == ["root_password"]
    assert {"netmask", "vlan_id", "install_disk", "cpu_override"} <= set(
        esxi["settings_schema"]["properties"]
    )
    assert set(esxi["host_values_schema"]["required"]) == {"hostname", "ip"}


def test_config_set_crud_never_returns_the_password(api: TestClient) -> None:
    body = {"name": "lab-esxi", "os_family": "esxi", "settings": LAB, "root_password": SECRET}
    created = api.post("/api/v1/config-sets", json=body)
    assert created.status_code == 201, created.text
    cs = created.json()
    assert cs["has_root_password"] is True and cs["source"] == "manual"
    assert cs["settings"]["cpu_override"] == "auto"  # defaults filled in

    assert api.post("/api/v1/config-sets", json=body).status_code == 409  # duplicate name

    # Updating without a password keeps the stored one
    upd = api.put(
        f"/api/v1/config-sets/{cs['id']}",
        json={**body, "root_password": None, "settings": {**LAB, "vlan_id": 200}},
    )
    assert (
        upd.status_code == 200
        and upd.json()["settings"]["vlan_id"] == 200
        and upd.json()["has_root_password"]
    )

    for resp in (api.get("/api/v1/config-sets"), api.get(f"/api/v1/config-sets/{cs['id']}"), upd):
        assert SECRET not in resp.text and '"root_password":' not in resp.text  # names only, never values
    assert cs["secrets_set"] == ["root_password"]

    assert api.delete(f"/api/v1/config-sets/{cs['id']}").status_code == 204
    assert api.get(f"/api/v1/config-sets/{cs['id']}").status_code == 404


def test_settings_are_validated_with_field_locations(api: TestClient) -> None:
    bad = {**LAB, "gateway": "nope", "install_disk": {"mode": "exact"}}
    resp = api.post("/api/v1/config-sets", json={"name": "bad", "os_family": "esxi", "settings": bad})
    assert resp.status_code == 422
    locs = {tuple(e["loc"]) for e in resp.json()["errors"]}
    assert ("settings", "gateway") in locs and ("settings", "install_disk") in locs
    unknown = api.post("/api/v1/config-sets", json={"name": "w", "os_family": "windows", "settings": {}})
    assert unknown.status_code == 422 and "Unknown OS family" in unknown.json()["detail"]


def test_capture_creates_a_set_and_per_server_values(api: TestClient) -> None:
    host_id = _host(api)
    capture = {"params": {"name": "from-esxi1"}}
    job = _wait(api, api.post(f"/api/v1/hosts/{host_id}/tasks/os.capture", json=capture).json()["id"])
    assert job["status"] == "succeeded", job
    cs = api.get(f"/api/v1/config-sets/{job['result']['config_set_id']}").json()
    assert cs["source"].startswith("captured from esxi1") and cs["has_root_password"]
    assert cs["settings"]["vlan_id"] == 100 and cs["settings"]["extra_uplinks"] == ["vmnic1"]
    values = api.get(f"/api/v1/hosts/{host_id}/host-values/esxi").json()
    assert values["hostname"] == "esxi1"
    assert api.post(f"/api/v1/hosts/{host_id}/tasks/os.capture", json=capture).status_code == 409


def test_host_values_are_validated(api: TestClient) -> None:
    host_id = _host(api, with_os=False)
    assert api.get(f"/api/v1/hosts/{host_id}/host-values/esxi").status_code == 404
    bad = api.put(f"/api/v1/hosts/{host_id}/host-values/esxi", json={"hostname": "esxi1", "ip": "999.1.1.1"})
    assert bad.status_code == 422
    ok = api.put(f"/api/v1/hosts/{host_id}/host-values/esxi", json={"hostname": "esxi9", "ip": "192.0.2.109"})
    assert ok.status_code == 200 and ok.json()["install_nic"] is None


def test_iso_repository_lists_detected_isos(api: TestClient) -> None:
    isos = api.post("/api/v1/images/rescan").json()
    by_name = {i["filename"]: i for i in isos}
    esxi = by_name["VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso"]
    assert (esxi["os_family"], esxi["version"], esxi["build"]) == ("esxi", "9.1.1", "25714478")
    assert len(esxi["sha256"]) == 64 and esxi["id"] == esxi["sha256"][:12]
    assert by_name["notes.iso"]["os_family"] is None
    assert api.get("/api/v1/images").json() == isos


def test_preview_shows_the_kickstart_without_secrets(api: TestClient) -> None:
    host_id = _host(api, with_os=False)
    iso = next(i for i in api.post("/api/v1/images/rescan").json() if i["os_family"] == "esxi")
    cs = api.post(
        "/api/v1/config-sets",
        json={"name": "lab", "os_family": "esxi", "settings": LAB, "root_password": SECRET},
    ).json()
    body = {
        "confirm": "-",
        "iso_id": iso["id"],
        "config_set_id": cs["id"],
        "host_values": {"hostname": "esxi7", "ip": "192.0.2.107"},
    }
    resp = api.post(f"/api/v1/hosts/{host_id}/install/preview", json=body)
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    ks = preview["kickstart"]
    assert "install --firstdisk=DELLBOSS --preservevmfs" in ks
    assert "--ip=192.0.2.107" in ks and "--hostname=esxi7" in ks and "--vlanid=100" in ks
    assert "$6$<hidden>" in ks and SECRET not in resp.text and "root_password_hash" not in preview["spec"]
    assert preview["config_set"] == "lab" and preview["iso"]["build"] == "25714478"


def test_install_with_a_set_needs_per_server_values(api: TestClient) -> None:
    host_id = _host(api, with_os=False)
    iso = next(i for i in api.post("/api/v1/images/rescan").json() if i["os_family"] == "esxi")
    cs = api.post(
        "/api/v1/config-sets",
        json={"name": "lab", "os_family": "esxi", "settings": LAB, "root_password": SECRET},
    ).json()
    resp = api.post(
        f"/api/v1/hosts/{host_id}/tasks/os.custom",
        json={"params": {"iso_id": iso["id"], "config_set_id": cs["id"]}, "confirm": "install esxi1"},
    )
    assert resp.status_code == 422 and "Per-server values" in resp.json()["detail"]
    assert api.get("/api/v1/jobs").json() == []  # rejected before queuing


def test_certificate_routes(api: TestClient) -> None:
    host_id = _host(api, with_os=False)
    assert api.get(f"/api/v1/hosts/{host_id}/certificates").json() == []
    resp = api.post(f"/api/v1/hosts/{host_id}/certificates/printer/trust")
    assert resp.status_code == 404 and "bmc, os or os-ssh" in resp.json()["detail"]


def test_isos_are_listed_after_a_restart_without_a_rescan(api: TestClient) -> None:
    """Regression: the image list (formerly GET /isos) was empty after every restart until a Rescan."""
    names = [i["filename"] for i in api.get("/api/v1/images").json()]
    assert "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso" in names


HOLODECK = {"holorouter_gateway": "192.0.2.1", "holorouter_dns": "8.8.8.8"}


def test_holodeck_settings_are_a_config_set_family_with_named_secrets(api: TestClient) -> None:
    fam = next(f for f in api.get("/api/v1/os-families").json() if f["family"] == "holodeck")
    assert fam["install_supported"] is False
    assert fam["secret_fields"] == ["holorouter_password", "download_token", "offline_depot_password"]
    assert {"version", "depot_type", "holorouter_gateway"} <= set(fam["settings_schema"]["properties"])
    assert set(fam["host_values_schema"]["required"]) == {"holorouter_ip"}

    body = {"name": "lab-holodeck", "os_family": "holodeck", "settings": HOLODECK,
            "secrets": {"holorouter_password": "Holo-pass1!", "download_token": "tok-123456"}}  # fmt: skip
    created = api.post("/api/v1/config-sets", json=body)
    assert created.status_code == 201, created.text
    cs = created.json()
    assert cs["secrets_set"] == ["download_token", "holorouter_password"]
    assert cs["settings"]["version"] == "9.1.1.0" and cs["settings"]["management_only"] is True

    # Updating one secret keeps the others; values never come back
    upd = api.put(f"/api/v1/config-sets/{cs['id']}",
                  json={**body, "secrets": {"offline_depot_password": "depot-pw"}})  # fmt: skip
    assert upd.json()["secrets_set"] == ["download_token", "holorouter_password", "offline_depot_password"]
    for resp in (created, upd, api.get(f"/api/v1/config-sets/{cs['id']}"), api.get("/api/v1/config-sets")):
        assert (
            "Holo-pass1!" not in resp.text and "tok-123456" not in resp.text and "depot-pw" not in resp.text
        )

    wrong = api.post(
        "/api/v1/config-sets", json={**body, "name": "x", "secrets": {"root_password": "nope1234"}}
    )
    assert wrong.status_code == 422 and "Unknown secret" in wrong.json()["detail"]
    bad = api.post(
        "/api/v1/config-sets", json={**body, "name": "y", "settings": {**HOLODECK, "cidr": "10.1.0.0/24"}}
    )
    assert bad.status_code == 422 and ("settings", "cidr") in {tuple(e["loc"]) for e in bad.json()["errors"]}


def test_holodeck_host_values(api: TestClient) -> None:
    host_id = _host(api, with_os=False)
    ok = api.put(f"/api/v1/hosts/{host_id}/host-values/holodeck", json={"holorouter_ip": "192.0.2.150"})
    expected = {"instance_id": "holo1", "holorouter_ip": "192.0.2.150", "holorouter_hostname": "holorouter"}
    assert ok.status_code == 200 and ok.json() == expected
    bad_values = {"holorouter_ip": "192.0.2.150", "instance_id": "Bad ID!"}
    bad = api.put(f"/api/v1/hosts/{host_id}/host-values/holodeck", json=bad_values)
    assert bad.status_code == 422


def test_ovas_are_recognised_in_the_image_repository(tmp_path: Path, api: TestClient) -> None:
    import tarfile

    isos = Path(api.app.state.services.settings.iso_dir)  # type: ignore[attr-defined]
    for name, product, extra in [
        ("holorouter-9.1.1.0456.ova", "HoloRouter", ""),
        ("VCF-SDDC-Manager-Appliance-9.1.1.0.25713928.ova", "VMware VCF SDDC Manager Appliance",
         "<Version>9.1.1.0</Version><FullVersion>9.1.1.0_Build_25713928</FullVersion>"),
    ]:  # fmt: skip
        ovf = tmp_path / name.replace(".ova", ".ovf")
        ovf.write_text(
            f"<Envelope><ProductSection><Product>{product}</Product>{extra}</ProductSection></Envelope>"
        )
        with tarfile.open(isos / name, "w") as tar:
            tar.add(ovf, arcname=ovf.name)
    by_name = {i["filename"]: i for i in api.post("/api/v1/images/rescan").json()}
    router = by_name["holorouter-9.1.1.0456.ova"]
    assert (router["kind"], router["os_family"], router["version"], router["build"]) == (
        "ova",
        "holorouter",
        "9.1.1",
        "0456",
    )
    installer = by_name["VCF-SDDC-Manager-Appliance-9.1.1.0.25713928.ova"]
    assert (installer["os_family"], installer["version"], installer["build"]) == (
        "vcf-installer",
        "9.1.1.0",
        "25713928",
    )


def test_an_ovas_inputs_are_read_from_its_descriptor(tmp_path: Path, api: TestClient) -> None:
    """Any OVA: its properties become a form (JSON Schema) keyed as the guest reads them."""
    import tarfile

    repo = Path(api.app.state.services.settings.iso_dir)  # type: ignore[attr-defined]
    fixture = Path(__file__).parent / "fixtures" / "ova" / "sddc-manager-9.1.1.ovf"
    with tarfile.open(repo / "VCF-SDDC-Manager-Appliance-9.1.1.0.25713928.ova", "w") as tar:
        tar.add(fixture, arcname="VCF-SDDC-Manager-Appliance-9.1.1.0.25713928.ovf")
    image = next(i for i in api.post("/api/v1/images/rescan").json() if i["kind"] == "ova")
    info = api.get(f"/api/v1/images/{image['id']}/descriptor").json()
    d, schema = info["descriptor"], info["schema"]
    assert (d["product"], d["cpus"], d["memory_mb"], [n["name"] for n in d["networks"]]) == (
        "VMware VCF SDDC Manager Appliance", 4, 16384, ["Network 1"])  # fmt: skip
    props = schema["properties"]
    assert props["ROOT_PASSWORD"]["format"] == "password" and props["ROOT_PASSWORD"]["minLength"] == 15
    assert props["vami.ip_address_version.SDDC-Manager"]["enum"] == ["IPv4", "IPv4 and IPv6"]
    assert props["vami.ip0.SDDC-Manager"]["x-group"] == "Networking Configuration"
    assert "VCF_PASSWORD" not in props  # not user-configurable: sent with its default, never asked for
    assert "ROOT_PASSWORD" in schema["x-secret-fields"]
    iso = next(i for i in api.get("/api/v1/images").json() if i["kind"] == "iso")
    assert api.get(f"/api/v1/images/{iso['id']}/descriptor").status_code == 409
    assert api.get("/api/v1/images/nope/descriptor").status_code == 404


def _ova_from_fixture(api: TestClient, fixture: str, filename: str) -> dict[str, Any]:
    import tarfile

    repo = Path(api.app.state.services.settings.iso_dir)  # type: ignore[attr-defined]
    with tarfile.open(repo / filename, "w") as tar:
        tar.add(
            Path(__file__).parent / "fixtures" / "ova" / fixture, arcname=filename.replace(".ova", ".ovf")
        )
    return next(i for i in api.post("/api/v1/images/rescan").json() if i["filename"] == filename)


def test_appliance_profiles_are_checked_against_the_ova(api: TestClient) -> None:
    router = _ova_from_fixture(api, "holorouter-9.1.1.ovf", "holorouter-9.1.1.0456.ova")
    sddc = _ova_from_fixture(api, "sddc-manager-9.1.1.ovf", "VCF-SDDC-Manager-Appliance-9.1.1.0.25713928.ova")
    body = {
        "name": "lab-router",
        "image_id": router["id"],
        "values": {
            "ip": "192.0.2.150",
            "network.mask": "24",
            "ssh_enabled": "true",
            "hostname": "holorouter",
        },
        "secrets": {"password": "Example-pass1!"},
        "networks": {
            "VM Management Network": "Holodeck-External",
            "Trunk Portgroup for Site A": "Holodeck-Trunk",
        },
    }
    created = api.post("/api/v1/appliance-profiles", json=body)
    assert created.status_code == 201, created.text
    p = created.json()
    assert p["product"] == "HoloRouter" and p["secrets_set"] == ["network.password"]
    assert p["values"] == {"network.ip": "192.0.2.150", "network.mask": "24", "extra.ssh_enabled": True,
                           "network.hostname": "holorouter"}  # fmt: skip
    assert "Example-pass1!" not in json.dumps(api.get(f"/api/v1/appliance-profiles/{p['id']}").json())

    # Passwords not sent on update are kept; values are replaced
    update = {**body, "secrets": None, "values": {"ip": "192.0.2.151"}}
    updated = api.put(f"/api/v1/appliance-profiles/{p['id']}", json=update).json()
    assert updated["secrets_set"] == ["network.password"] and updated["values"] == {
        "network.ip": "192.0.2.151"
    }
    services = api.app.state.services  # type: ignore[attr-defined]
    assert services.appliance_profile_secrets(p["id"]) == {"network.password": "Example-pass1!"}

    bad = api.post("/api/v1/appliance-profiles", json={
        "name": "bad", "image_id": sddc["id"],
        "values": {"bogus": "1", "ROOT_PASSWORD": "in-the-clear",
                   "vami.ip_address_version.SDDC-Manager": "IPv5"},
        "secrets": {"ROOT_PASSWORD": "short"},
        "networks": {"Nope": "VM Network"},
    })  # fmt: skip
    assert bad.status_code == 422
    problems = {tuple(e["loc"]): e["type"] for e in bad.json()["errors"]}
    assert problems == {
        ("values", "bogus"): "unknown_property",
        ("values", "ROOT_PASSWORD"): "secret",  # a password must never be sent as a plain value
        ("values", "vami.ip_address_version.SDDC-Manager"): "enum",
        ("secrets", "ROOT_PASSWORD"): "too_short",  # MinLen(15) from the descriptor
        ("networks", "Nope"): "network",
    }
    other_product = api.put(
        f"/api/v1/appliance-profiles/{p['id']}", json={**body, "image_id": sddc["id"], "values": {}}
    )
    assert other_product.status_code == 422 and "HoloRouter" in other_product.json()["detail"]
    assert api.post("/api/v1/appliance-profiles", json=body).status_code == 409  # duplicate name
    assert api.delete(f"/api/v1/appliance-profiles/{p['id']}").status_code == 204
    assert api.get(f"/api/v1/appliance-profiles/{p['id']}").status_code == 404
