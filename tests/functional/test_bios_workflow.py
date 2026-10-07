"""Black-box: Configure BIOS through the real server and CLI, against a simulated R740xd."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from .conftest import _simulated
from .harness import GroundZero

pytestmark = pytest.mark.functional
FAST = {"GROUNDZERO_BIOS_POLL_SECONDS": "0.2", "GROUNDZERO_BIOS_APPLY_MINUTES": "0.05"}


@pytest.fixture
def wrong_bios(tmp_path: Path) -> Iterator[GroundZero]:
    """An R740xd whose BIOS has processor virtualization off and legacy boot mode."""
    gz = _simulated(tmp_path, GROUNDZERO_SIMULATE_FAULTS='["bios-wrong"]', **FAST)
    gz.start()
    yield gz
    gz.stop()


@pytest.fixture
def bios_job_fails(tmp_path: Path) -> Iterator[GroundZero]:
    """Same, and the BIOS configuration job never applies the change."""
    gz = _simulated(tmp_path, GROUNDZERO_SIMULATE_FAULTS='["bios-wrong", "bios-not-applied"]', **FAST)
    gz.start()
    yield gz
    gz.stop()


def _writes(gz: GroundZero, job_id: str) -> list[str]:
    out = gz.home / f"{job_id}.json"
    assert gz.cli("jobs", "diag", job_id, "--out", str(out)).code == 0
    events = json.loads(out.read_text())["events"]
    writes = [e for e in events if e.get("event") == "redfish" and e.get("method") != "GET"]
    return [f"{e['method']} {e['path']}" for e in writes if "Sessions" not in e.get("path", "")]


def test_configure_bios_fixes_what_preflight_flagged(wrong_bios: GroundZero) -> None:
    gz = wrong_bios
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    before = gz.cli("preflight", "esxi1", timeout=120)
    assert before.code == 2 and "Run Configure BIOS" in before.output  # fails on VT and boot mode

    refused = gz.cli("run", "esxi1", "bios.configure")
    assert refused.code != 0 and 'exactly "configure bios esxi1"' in refused.output
    assert "ProcVirtualization → Enabled" in refused.output and "BootMode → Uefi" in refused.output

    run = gz.cli("run", "esxi1", "bios.configure", "--confirm", "configure bios esxi1", timeout=120)
    assert run.code == 0, run.output
    job_id = run.output.split("as job ")[1].split()[0]
    writes = _writes(gz, job_id)
    assert writes == [  # one pending-settings write and one reset: nothing is ever sent twice
        "PATCH /redfish/v1/Systems/System.Embedded.1/Bios/Settings",
        "POST /redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset",
    ]
    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]["id"]
        out = api.get(f"/api/v1/hosts/{host}/outputs/bios").json()
        assert out["applied"] == {"ProcVirtualization": "Enabled", "BootMode": "Uefi"}
        inv = api.get(f"/api/v1/hosts/{host}/outputs/inventory").json()
        assert inv["bios"]["cpu_virtualization"] is True and inv["bios"]["boot_mode"] == "Uefi"  # re-read

    after = gz.cli("preflight", "esxi1", timeout=120)
    assert after.code == 0, after.output
    again = gz.cli("run", "esxi1", "bios.configure", timeout=120)  # nothing left to change: no phrase needed
    assert again.code == 0, again.output
    with gz.api() as api:
        assert api.get(f"/api/v1/hosts/{host}/outputs/bios").json()["changes"] == []  # and no second reboot


def test_a_bios_that_never_applies_the_change_fails_clearly(bios_job_fails: GroundZero) -> None:
    gz = bios_job_fails
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("run", "esxi1", "discover", timeout=120).code == 0
    run = gz.cli("run", "esxi1", "bios.configure", "--confirm", "configure bios esxi1", timeout=120)
    assert run.code != 0
    assert "did not apply the change" in run.output and "Job Queue" in run.output
