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


def test_a_bios_that_is_already_right_is_marked_not_needed(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("run", "esxi1", "discover", timeout=120).code == 0
    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]["id"]
        p = api.get(f"/api/v1/hosts/{host}/pipeline").json()
        bios = next(t for s in p["stages"] for t in s["tasks"] if t["id"] == "bios.configure")
        assert bios["state"] == "not_needed" and bios["last_job"] is None  # judged from the inventory
        assert bios["not_needed"].startswith("Already on: processor virtualization")
        assert p["next"]["task"] == "preflight"
        assert api.get(f"/api/v1/hosts/{host}/outputs/bios").status_code == 404  # nothing was recorded
    shown = gz.cli("pipeline", "esxi1")
    assert "not_needed" in shown.output and "Already on" in shown.output


def test_configure_bios_is_next_after_discover_when_the_bios_is_wrong(wrong_bios: GroundZero) -> None:
    gz = wrong_bios
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("run", "esxi1", "discover", timeout=120).code == 0
    shown = gz.cli("pipeline", "esxi1")
    assert "Next: Configure BIOS" in shown.output and "run esxi1 bios.configure" in shown.output


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


def test_capture_a_bios_profile_change_it_and_apply_it(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]["id"]
        early = api.post(f"/api/v1/hosts/{host}/bios-profiles/capture", json={"name": "lab"})
        assert early.status_code == 409 and "Discover the hardware first" in early.text
    assert gz.cli("run", "esxi1", "discover", timeout=120).code == 0
    with gz.api() as api:
        captured = api.post(f"/api/v1/hosts/{host}/bios-profiles/capture", json={"name": "lab"})
        assert captured.status_code == 201, captured.text
        profile = captured.json()
        assert profile["source"] == "captured from esxi1" and profile["model"] == "PowerEdge R740xd"
        assert profile["attributes"]["LogicalProc"] == "Enabled" and "AssetTag" not in profile["attributes"]
        registry = api.get(f"/api/v1/hosts/{host}/bios-registry").json()
        assert (
            registry["key"] == profile["registry"]
            and registry["key"] == "PowerEdge R740xd|BiosAttributeRegistry.v1_0_3"
        )
        assert all(not a["read_only"] for a in registry["attributes"])  # the editor only offers settable ones

        body = {**profile, "attributes": {"LogicalProc": "Maybe", "SystemModelName": "x"}}
        refused = api.put(f"/api/v1/bios-profiles/{profile['id']}", json=body)
        assert refused.status_code == 422
        assert {tuple(e["loc"]) for e in refused.json()["errors"]} == {
            ("attributes", "LogicalProc"),
            ("attributes", "SystemModelName"),
        }

        lean = {
            "name": "No HT",
            "registry": profile["registry"],
            "attributes": {"LogicalProc": "Disabled", "NumLock": "On"},
        }
        no_ht = api.post("/api/v1/bios-profiles", json=lean).json()
        plan = api.get(f"/api/v1/hosts/{host}/bios-plan", params={"profile_id": no_ht["id"]}).json()
        assert [(c["attribute"], c["before"], c["after"]) for c in plan["changes"]] == [
            ("LogicalProc", "Enabled", "Disabled")
        ]

    run = gz.cli(
        "run",
        "esxi1",
        "bios.configure",
        "-p",
        f"profile_id={no_ht['id']}",
        "--confirm",
        "configure bios esxi1",
        timeout=120,
    )
    assert run.code == 0, run.output
    job_id = run.output.split("as job ")[1].split()[0]
    assert _writes(gz, job_id) == [
        "PATCH /redfish/v1/Systems/System.Embedded.1/Bios/Settings",
        "POST /redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset",
    ]
    with gz.api() as api:
        assert api.get(f"/api/v1/hosts/{host}/outputs/bios").json()["applied"] == {"LogicalProc": "Disabled"}
        spec = api.post(
            "/api/v1/specs",
            json={
                "name": "No HT",
                "steps": [{"task": "bios.configure", "params": {"profile_id": no_ht["id"]}}],
            },
        ).json()
        api.put(f"/api/v1/hosts/{host}/spec", json={"spec_id": spec["id"]})
        state = next(
            t
            for s in api.get(f"/api/v1/hosts/{host}/pipeline").json()["stages"]
            for t in s["tasks"]
            if t["id"] == "bios.configure"
        )
        assert state["state"] == "done"  # applied, and the inventory read afterwards still matches
        changed = {**lean, "attributes": {"LogicalProc": "Disabled", "NumLock": "Off"}}
        assert api.put(f"/api/v1/bios-profiles/{no_ht['id']}", json=changed).status_code == 200
        state = next(
            t
            for s in api.get(f"/api/v1/hosts/{host}/pipeline").json()["stages"]
            for t in s["tasks"]
            if t["id"] == "bios.configure"
        )
        assert state["state"] == "ready"  # the profile moved on: due again
        in_use = api.delete(f"/api/v1/bios-profiles/{no_ht['id']}")
        assert in_use.status_code == 409 and "spec No HT" in in_use.text


def test_import_a_dell_scp_as_a_bios_profile(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("run", "esxi1", "discover", timeout=120).code == 0
    scp = {
        "SystemConfiguration": {
            "Components": [
                {
                    "FQDD": "BIOS.Setup.1-1",
                    "Attributes": [
                        {"Name": "SysProfile", "Value": "PerfOptimized"},
                        {"Name": "SystemModelName", "Value": "PowerEdge R740xd"},
                        {"Name": "ControlledTurboMinusBin", "Value": "1"},
                    ],
                }
            ]
        }
    }
    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]["id"]
        key = api.get(f"/api/v1/hosts/{host}/bios-registry").json()["key"]
        imported = api.post(
            "/api/v1/bios-profiles/import", json={"name": "perf", "registry": key, "content": json.dumps(scp)}
        )
        assert imported.status_code == 201, imported.text
        assert imported.json()["attributes"] == {"SysProfile": "PerfOptimized", "ControlledTurboMinusBin": 1}
        assert imported.json()["source"] == "imported"  # the read-only model name was left out
        bad = api.post("/api/v1/bios-profiles/import", json={"name": "x", "registry": key, "content": "nope"})
        assert bad.status_code == 422 and "Not JSON" in bad.text

    path = gz.home / "scp.json"
    path.write_text(json.dumps(scp))
    cli = gz.cli("bios-profile", "import", str(path), "--name", "perf-cli", "--host", "esxi1")
    assert cli.code == 0 and "Imported 2 settings as perf-cli" in cli.output
    captured = gz.cli("bios-profile", "capture", "esxi1", "--name", "vt", "--keep", "ProcVirtualization")
    assert captured.code == 0 and "Captured 1 setting from esxi1" in captured.output
    listing = gz.cli("bios-profile", "list").output
    assert "perf-cli" in listing and "captured from esxi1" in listing
