"""Unattended ESXi reinstall through the real CLI/server against the simulated iDRAC + ESXi.

The simulated iDRAC downloads the ISO from GroundZero's real HTTPS media server, and the simulated
ESXi comes back configured from the KS.CFG inside that ISO, so these tests check the generated
kickstart and ISO as well as the orchestration.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from .harness import GroundZero

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isofactory import make_stock_iso

pytestmark = pytest.mark.functional

LAB_VMFS = ["boss", "esx1ds", "esx2ds", "esx3ds", "esxi4ds", "esxi5ds", "localHolodeck", "localVM"]


def _prepare(gz: GroundZero) -> Path:
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("os", "set", "esxi1", "--address", "192.0.2.101").code == 0
    return make_stock_iso(gz.home / "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso")


def _report(gz: GroundZero) -> dict:
    with gz.api() as api:
        host_id = api.get("/api/v1/hosts").json()[0]["id"]
        return dict(api.get(f"/api/v1/hosts/{host_id}/install").json())


def test_install_reinstalls_and_validates(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    iso = _prepare(gz)
    result = gz.cli(
        "install",
        "esxi1",
        "--iso",
        str(iso),
        "--confirm",
        "install esxi1",
        "--timeout-minutes",
        "240",
        timeout=180,
    )
    assert result.code == 0, result.output
    assert "ESXi 9.1.1 build 25714478 on esxi1 (was 24957456)" in result.output

    report = _report(gz)
    checks = {c["name"]: c for c in report["validation"]}
    assert all(c["ok"] for c in checks.values()), checks
    assert checks["mgmt.vlan"]["observed"] == "100"
    assert checks["mgmt.uplinks"]["observed"] == "['vmnic0', 'vmnic1']"
    assert checks["ntp"]["observed"] == "['pool.ntp.org']"
    assert checks["datastores"]["observed"] == str(LAB_VMFS)  # --preservevmfs kept 'boss'

    spec = report["spec"]
    assert spec["preserve_vmfs"] is True and spec["allow_legacy_cpu"] is True  # Skylake-SP → override
    assert spec["install_disk"].startswith("t10.ATA_____DELLBOSS_VD")
    assert spec["network"]["install_nic"] == "vmnic0" and spec["network"]["extra_uplinks"] == ["vmnic1"]
    assert "root_password_hash" not in spec

    writes = [w.split("/redfish/v1/")[-1] for w in report["bmc_audit"]["non_get"]]
    assert "Systems/System.Embedded.1/VirtualMedia/1/Actions/VirtualMedia.InsertMedia" in writes  # RFS slot
    assert "Systems/System.Embedded.1" in writes  # standard Boot PATCH
    assert "Managers/iDRAC.Embedded.1/Attributes" not in writes  # VCD-DVD does not boot RFS media (live)
    assert report["boot_method"] == "Cd"  # Dell default, learned from live runs 2 and 3
    assert "Systems/System.Embedded.1/Actions/ComputerSystem.Reset" in writes
    assert writes[-1].endswith("VirtualMedia.EjectMedia")  # media ejected last
    assert report["reset_type"] == "ForceRestart"
    assert report["media_bytes_served"] > 0
    fetches = report["media_fetches"]
    assert fetches and {f["method"] for f in fetches} >= {"HEAD", "GET"}
    assert all(f["client"].count(":") == 1 for f in fetches)  # ip:port recorded
    with gz.api() as api:
        assert api.get("/api/v1/jobs").json()[0]["params"]["timeout_minutes"] == 240
    assert any(f["at"] > report["reset_at"] for f in fetches)  # the "installer" read the ISO after the reset
    assert not list((gz.home / "media").glob("*.iso"))  # built ISO cleaned up
    with gz.api() as api:  # regression (user report): the host's OS view must reflect the new build
        host_id = api.get("/api/v1/hosts").json()[0]["id"]
        os_now = api.get(f"/api/v1/hosts/{host_id}/os/network").json()
    assert os_now["build"] == "25714478" and os_now["product"] == "VMware ESXi 9.1.1"


def test_install_requires_exact_confirmation(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    iso = _prepare(gz)
    result = gz.cli("install", "esxi1", "--iso", str(iso), "--confirm", "install esxi2")
    assert result.code == 1 and 'Confirmation must be exactly "install esxi1"' in result.output
    assert "No install" not in result.output
    assert "install" not in gz.cli("jobs", "list").output


def test_install_refuses_on_preflight_fail_without_touching_the_bmc(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    iso = _prepare(gz)
    with gz.api() as api:
        host_id = api.get("/api/v1/hosts").json()[0]["id"]
        body = {
            "iso_path": str(iso),
            "confirm": "install esxi1",
            "variant": "vcf-9.1-dual",
        }  # needs 1.5 TB RAM
        job = api.post(f"/api/v1/hosts/{host_id}/install", json=body).json()
        for _ in range(200):
            job = api.get(f"/api/v1/jobs/{job['id']}").json()
            if job["status"] not in ("queued", "running"):
                break
        assert job["status"] == "failed"
        assert "Preflight failed" in job["error"]["message"] and "memory.total" in job["error"]["message"]
        assert api.get(f"/api/v1/hosts/{host_id}/install").status_code == 404  # never got to the BMC
    assert not list((gz.home / "media").glob("*.iso"))


def test_failed_one_time_boot_stops_safely(simulated_r740xd_ignoring_boot_once: GroundZero) -> None:
    gz = simulated_r740xd_ignoring_boot_once
    iso = _prepare(gz)
    result = gz.cli("install", "esxi1", "--iso", str(iso), "--confirm", "install esxi1", timeout=180)
    assert result.code == 1
    assert "instead of the installer" in result.output and "Nothing was installed" in result.output
    report = _report(gz)
    assert report["installed_build"] is None and report["validation"] == []
    assert report["bmc_audit"]["non_get"][-1].endswith("VirtualMedia.EjectMedia")  # media still ejected
    assert not list((gz.home / "media").glob("*.iso*"))  # built ISO removed even on failure


def test_slow_insert_media_is_verified_not_retried(simulated_r740xd_slow_insert: GroundZero) -> None:
    """Regression (live R740xd): InsertMedia answered after the client timeout but had mounted."""
    gz = simulated_r740xd_slow_insert
    iso = _prepare(gz)
    result = gz.cli("install", "esxi1", "--iso", str(iso), "--confirm", "install esxi1", timeout=180)
    assert result.code == 0, result.output
    report = _report(gz)
    inserts = [w for w in report["bmc_audit"]["non_get"] if w.endswith("VirtualMedia.InsertMedia")]
    assert len(inserts) == 1  # verified by reading the slot back, never re-sent
    assert all(c["ok"] for c in report["validation"])


def test_boot_method_can_be_chosen_per_install(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    iso = _prepare(gz)
    with gz.api() as api:
        host_id = api.get("/api/v1/hosts").json()[0]["id"]
        body = {"iso_path": str(iso), "confirm": "install esxi1", "boot_method": "uefi-target"}
        job = api.post(f"/api/v1/hosts/{host_id}/install", json=body).json()
        for _ in range(600):
            job = api.get(f"/api/v1/jobs/{job['id']}").json()
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        assert job["status"] == "succeeded", job
        report = api.get(f"/api/v1/hosts/{host_id}/install").json()
    assert report["boot_method"].startswith("UefiTarget PciRoot(0x0)/Pci(0x14,0x0)/USB(0xD,0x0)")


def test_media_that_attaches_after_a_failed_mount_is_ejected(
    simulated_r740xd_late_attach: GroundZero,
) -> None:
    """Regression (live run 5): RAC0720 returned, the image attached a minute later and was left mounted."""
    gz = simulated_r740xd_late_attach
    iso = _prepare(gz)
    result = gz.cli("install", "esxi1", "--iso", str(iso), "--confirm", "install esxi1", timeout=180)
    assert result.code == 1 and "Unable to locate the ISO" in result.output
    writes = _report(gz)["bmc_audit"]["non_get"]
    assert writes[-1].endswith("VirtualMedia.EjectMedia")  # the late attach was found and ejected
    assert not any(w.endswith("ComputerSystem.Reset") for w in writes)  # never reset after a failed mount
    assert not list((gz.home / "media").glob("*.iso*"))  # built ISO removed even on failure


def test_installer_that_exits_without_installing_fails_fast(
    simulated_r740xd_kickstart_error: GroundZero,
) -> None:
    """Regression (live run 8): kickstart parse error, installer rebooted, the job waited for its timeout."""
    gz = simulated_r740xd_kickstart_error
    iso = _prepare(gz)
    result = gz.cli("install", "esxi1", "--iso", str(iso), "--confirm", "install esxi1", timeout=180)
    assert result.code == 1
    assert "installer exited without installing" in result.output and "24957456" in result.output
    report = _report(gz)
    assert report["media_bytes_served"] > 0  # it did boot the installer
    assert report["bmc_audit"]["non_get"][-1].endswith("VirtualMedia.EjectMedia")
    assert not list((gz.home / "media").glob("*.iso*"))
