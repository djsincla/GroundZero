"""Config sets end to end through the real CLI/server: capture → install with the set, and installs
that do not need the old OS at all (simulated R740xd + ESXi)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from .harness import GroundZero

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isofactory import make_stock_iso

pytestmark = pytest.mark.functional


def _iso(gz: GroundZero) -> str:
    repo = gz.home / "isos"
    make_stock_iso(repo / "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso")
    return "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso"


def test_capture_then_install_with_the_captured_set(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("os", "set", "esxi1", "--address", "192.0.2.101").code == 0
    captured = gz.cli("config", "capture", "esxi1", "--name", "lab-esxi")
    assert captured.code == 0, captured.output
    listing = gz.cli("config", "list").output
    assert "lab-esxi" in listing and "captured from esxi1" in listing and "set" in listing

    iso = _iso(gz)
    isos = gz.cli("isos", "list")
    assert isos.code == 0 and "25714478" in isos.output and "esxi" in isos.output

    result = gz.cli(
        "install", "esxi1", "--iso", iso, "--config", "lab-esxi", "--confirm", "install esxi1", timeout=180
    )
    assert result.code == 0, result.output
    assert "ESXi 9.1.1 build 25714478 on esxi1" in result.output


def test_install_from_a_set_when_the_old_os_is_unreachable(
    simulated_r740xd_os_unreachable: GroundZero,
) -> None:
    gz = simulated_r740xd_os_unreachable
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    with gz.api() as api:
        host_id = api.get("/api/v1/hosts").json()[0]["id"]
        settings = {
            "netmask": "255.255.255.0",
            "gateway": "192.0.2.1",
            "nameservers": ["8.8.8.8"],
            "vlan_id": 100,
            "extra_uplinks": ["vmnic1"],
            "install_disk": {"mode": "first-match", "value": "DELLBOSS"},
        }
        cs = api.post(
            "/api/v1/config-sets",
            json={
                "name": "boss-any",
                "os_family": "esxi",
                "settings": settings,
                "root_password": "simulated",
            },
        )
        assert cs.status_code == 201, cs.text
        values = {"hostname": "esxi1", "ip": "192.0.2.101"}
        assert api.put(f"/api/v1/hosts/{host_id}/host-values/esxi", json=values).status_code == 200

    iso = _iso(gz)
    result = gz.cli(
        "install", "esxi1", "--iso", iso, "--config", "boss-any", "--confirm", "install esxi1", timeout=180
    )
    assert result.code == 0, result.output
    with gz.api() as api:
        report = api.get(f"/api/v1/hosts/{host_id}/outputs/install").json()
        os_access = api.get(f"/api/v1/hosts/{host_id}/os").json()
    assert report["spec"]["install_firstdisk"] == "DELLBOSS" and report["previous_build"] is None
    datastores = next(c for c in report["validation"] if c["name"] == "datastores")
    assert datastores["ok"] and "not checked" in datastores["expected"]
    assert os_access == {
        "address": "192.0.2.101",
        "username": "root",
        "verify_tls": False,
    }  # set after install


def test_install_without_set_or_os_access_is_refused(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    iso = _iso(gz)
    result = gz.cli("install", "esxi1", "--iso", iso, "--confirm", "install esxi1")
    assert result.code == 1 and "Set OS access, or deploy an OS" in result.output
