"""Black-box: a spec run through the real server and CLI on a simulated R740xd whose BIOS is wrong.

Discover → Configure BIOS → Read storage → Preflight → Deploy OS, approved once with the run's phrase:
the BIOS change and the install need no phrases of their own, and a second run skips everything."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from .conftest import _simulated
from .harness import GroundZero

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isofactory import make_stock_iso

pytestmark = pytest.mark.functional
ISO = "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso"


@pytest.fixture
def wrong_bios(tmp_path: Path) -> Iterator[GroundZero]:
    gz = _simulated(
        tmp_path,
        GROUNDZERO_SIMULATE_FAULTS='["bios-wrong"]',
        GROUNDZERO_BIOS_POLL_SECONDS="0.2",
        GROUNDZERO_BIOS_APPLY_MINUTES="0.05",
    )
    gz.start()
    yield gz
    gz.stop()


def test_a_spec_runs_from_bare_metal_to_an_installed_os(wrong_bios: GroundZero) -> None:
    gz = wrong_bios
    make_stock_iso(gz.home / "isos" / ISO)
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]["id"]
        image = next(i["id"] for i in api.post("/api/v1/images/rescan").json() if i["filename"] == ISO)
        settings = {
            "netmask": "255.255.255.0",
            "gateway": "192.0.2.1",
            "nameservers": ["192.0.2.53"],
            "install_disk": {"mode": "boot-volume"},
        }
        body = {"name": "lab", "os_family": "esxi", "settings": settings, "root_password": "simulated"}
        config = api.post("/api/v1/config-sets", json=body).json()
        values = {"hostname": "esxi1", "ip": "192.0.2.101"}
        assert api.put(f"/api/v1/hosts/{host}/host-values/esxi", json=values).status_code == 200

    spec = {
        "name": "Lab host",
        "steps": [
            {"task": "preflight"},
            {"task": "os.custom", "params": {"iso_id": image, "config_set_id": config["id"]}},
            {"task": "discover"},
            {"task": "storage.read"},
            {"task": "bios.configure"},
        ],
    }
    path = gz.home / "spec.json"
    path.write_text(json.dumps(spec))
    saved = gz.cli("spec", "save", str(path))
    assert saved.code == 0, saved.output
    assert (
        "discover → bios.configure → storage.read → preflight → os.custom" in saved.output
    )  # pipeline order
    assert gz.cli("spec", "assign", "esxi1", "Lab host").code == 0
    assert "Next in Lab host" in gz.cli("pipeline", "esxi1").output

    preview = gz.cli("run-spec", "esxi1")
    assert preview.code == 1 and 'Start it with --confirm "run Lab host on esxi1"' in preview.output
    assert "run (changes the server)" in preview.output  # the install is destructive

    run = gz.cli("run-spec", "esxi1", "--confirm", "run Lab host on esxi1", timeout=300)
    assert run.code == 0, run.output
    assert "esxi1: bios.configure succeeded" in run.output and "esxi1: os.custom succeeded" in run.output
    with gz.api() as api:
        runs = api.get(f"/api/v1/hosts/{host}/runs").json()
        assert [s["status"] for s in runs[0]["steps"]] == ["succeeded"] * 5
        bios = api.get(f"/api/v1/hosts/{host}/outputs/bios").json()
        assert bios["applied"] == {"ProcVirtualization": "Enabled", "BootMode": "Uefi"}
        install = api.get(f"/api/v1/hosts/{host}/outputs/install").json()
        assert install["spec"]["install_firstdisk"] == "DELLBOSS"  # the boot volume Read storage found
        pipeline = api.get(f"/api/v1/hosts/{host}/pipeline").json()
        assert pipeline["next"]["title"] == "Done" and pipeline["spec"]["name"] == "Lab host"

    again = gz.cli("run-spec", "esxi1", "--confirm", "run Lab host on esxi1", timeout=120)
    assert again.code == 0, again.output
    assert again.output.count("skipped") == 5


def test_a_failed_step_stops_the_run(tmp_path: Path) -> None:
    gz = _simulated(
        tmp_path,
        GROUNDZERO_SIMULATE_FAULTS='["bios-wrong", "bios-not-applied"]',
        GROUNDZERO_BIOS_POLL_SECONDS="0.2",
        GROUNDZERO_BIOS_APPLY_MINUTES="0.05",
    )
    gz.start()
    try:
        assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
        path = gz.home / "spec.json"
        path.write_text(
            json.dumps(
                {
                    "name": "BIOS",
                    "steps": [{"task": "discover"}, {"task": "bios.configure"}, {"task": "preflight"}],
                }
            )
        )
        assert gz.cli("spec", "save", str(path)).code == 0
        assert gz.cli("spec", "assign", "esxi1", "BIOS").code == 0
        run = gz.cli("run-spec", "esxi1", "--confirm", "run BIOS on esxi1", timeout=120)
        assert run.code == 2
        assert "esxi1: bios.configure failed" in run.output and "did not apply the change" in run.output
        assert "esxi1: preflight cancelled" in run.output
    finally:
        gz.stop()
