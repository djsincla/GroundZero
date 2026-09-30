"""End-to-end user workflows through the real CLI and server processes (simulated R740xd)."""

from __future__ import annotations

import pytest

from .harness import GroundZero

pytestmark = pytest.mark.functional

BMC = "198.51.100.11"


def _add(gz: GroundZero) -> None:
    result = gz.cli("hosts", "add", "--bmc", BMC, "--name", "r740xd")
    assert result.code == 0, result.output
    assert "Added host r740xd" in result.output


def test_server_reports_simulated_mode(simulated_r740xd: GroundZero) -> None:
    with simulated_r740xd.api() as api:
        health = api.get("/healthz").json()
    assert health == {"status": "ok", "version": health["version"], "mode": "simulated"}


def test_register_then_preflight_holodeck(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _add(gz)

    result = gz.cli("preflight", "r740xd")
    assert result.code == 0, result.output  # WARN is not a failure
    out = result.output
    assert "r740xd vs holodeck-9 / VCF 9.0 (vSAN ESA), single site: WARN" in out
    assert "Skylake-SP" in out
    assert "12 passed, 1 warnings, 0 failed, 0 unknown" in out

    listing = gz.cli("hosts", "list").output
    assert "dell" in listing and "PowerEdge R740xd" in listing  # identity learned from the BMC


def test_preflight_exit_code_2_when_host_fails(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _add(gz)
    result = gz.cli("preflight", "r740xd", "--variant", "vcf-9.1-dual")  # needs 1.5 TB RAM
    assert result.code == 2, result.output
    assert ": FAIL" in result.output


def test_inventory_and_jobs_are_visible(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _add(gz)
    inventory = gz.cli("inventory", "r740xd")
    assert inventory.code == 0, inventory.output
    assert "Intel(R) Xeon(R) Platinum 8168" in inventory.output

    jobs = gz.cli("jobs", "list").output
    assert "inventory" in jobs and "succeeded" in jobs


def test_preflight_is_read_only_against_the_bmc(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _add(gz)
    with gz.api() as api:
        host_id = api.get("/api/v1/hosts").json()[0]["id"]
        job = api.post(f"/api/v1/hosts/{host_id}/preflight").json()
        gz.cli("jobs", "show", job["id"])  # exercise the CLI path too
        for _ in range(100):
            job = api.get(f"/api/v1/jobs/{job['id']}").json()
            if job["status"] == "succeeded":
                break
        audit = job["result"]["audit"]
    assert audit["requests"] > 40
    assert audit["non_get"] == [
        "POST /redfish/v1/SessionService/Sessions",
        "DELETE /redfish/v1/SessionService/Sessions/1",
    ]


def test_user_errors_are_clear(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _add(gz)

    dup = gz.cli("hosts", "add", "--bmc", BMC)
    assert dup.code == 1 and "Conflict" in dup.output

    unknown = gz.cli("preflight", "no-such-host")
    assert unknown.code == 1 and "no host matches 'no-such-host'" in unknown.output

    bad_variant = gz.cli("preflight", "r740xd", "--variant", "vcf-99")
    assert bad_variant.code == 1 and "Unknown variant 'vcf-99'" in bad_variant.output


def test_state_survives_restart(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    _add(gz)
    assert gz.cli("preflight", "r740xd").code == 0
    gz.stop()
    gz.start()

    assert "r740xd" in gz.cli("hosts", "list").output
    with gz.api() as api:
        host_id = api.get("/api/v1/hosts").json()[0]["id"]
        report = api.get(f"/api/v1/hosts/{host_id}/preflight")
    assert report.status_code == 200 and report.json()["overall"] == "warn"


def test_cli_reports_unreachable_server(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    gz.stop()
    result = gz.cli("hosts", "list")
    assert result.code == 1 and "cannot reach the GroundZero API" in result.output
