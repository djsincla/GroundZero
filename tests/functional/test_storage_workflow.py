"""Black-box: Configure storage through server and CLI, on a simulated R740xd whose PERC has drives."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from .conftest import _simulated
from .harness import GroundZero

pytestmark = pytest.mark.functional
# Successful runs return as soon as the changes read back, so a roomy deadline costs nothing (and a busy
# machine doesn't fail them); only the never-applies test uses a short one.
FAST = {"GROUNDZERO_STORAGE_POLL_SECONDS": "0.2", "GROUNDZERO_STORAGE_APPLY_MINUTES": "1"}
SHORT = {"GROUNDZERO_STORAGE_POLL_SECONDS": "0.2", "GROUNDZERO_STORAGE_APPLY_MINUTES": "0.05"}
PERC = "RAID.Slot.6-1"


@pytest.fixture
def perc(tmp_path: Path) -> Iterator[GroundZero]:
    gz = _simulated(tmp_path, GROUNDZERO_SIMULATE_FAULTS='["perc-drives"]', **FAST)
    gz.start()
    yield gz
    gz.stop()


def _writes(gz: GroundZero, job_id: str) -> list[str]:
    out = gz.home / f"{job_id}.json"
    assert gz.cli("jobs", "diag", job_id, "--out", str(out)).code == 0
    events = json.loads(out.read_text())["events"]
    writes = [e for e in events if e.get("event") == "redfish" and e.get("method") != "GET"]
    return [
        f"{e['method']} {e['path'].rsplit('/', 2)[-1]}" for e in writes if "Sessions" not in e.get("path", "")
    ]


def _ready(gz: GroundZero) -> tuple[str, dict[str, Any]]:
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    assert gz.cli("run", "esxi1", "storage.read", timeout=120).code == 0
    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]["id"]
        captured = api.post(f"/api/v1/hosts/{host}/storage-profiles/capture", json={"name": "lab"})
        assert captured.status_code == 201, captured.text
        profile = captured.json()
    return host, profile


def test_add_a_raid5_and_a_spare_on_the_perc(perc: GroundZero) -> None:
    gz = perc
    host, profile = _ready(gz)
    assert profile["source"] == "captured from esxi1"
    assert [c["kind"] for c in profile["controllers"]] == ["raid", "boot"]  # the PERC's mode is settable here
    perc_rule = {
        "kind": "raid",
        "model": "H730P",
        "mode": "RAID",
        "hot_spares": 1,
        "volumes": [
            {"name": "data", "raid": "RAID5", "drives": {"count": 3, "media": "SSD", "protocol": "SAS"}}
        ],
    }
    body = {**profile, "controllers": [perc_rule, profile["controllers"][1]]}
    with gz.api() as api:
        assert api.put(f"/api/v1/storage-profiles/{profile['id']}", json=body).status_code == 200
        plan = api.get(f"/api/v1/hosts/{host}/storage-plan", params={"profile_id": profile["id"]}).json()
        assert plan["problems"] == [] and [a["kind"] for a in plan["actions"]] == [
            "create_volume",
            "assign_spare",
        ]
        assert plan["boot_volume"] == "Disk.Virtual.0:AHCI.Slot.1-1"

    params = ["-p", f"profile_id={profile['id']}"]
    refused = gz.cli("run", "esxi1", "storage.configure", *params)
    assert refused.code != 0 and 'exactly "configure storage esxi1"' in refused.output
    run = gz.cli(
        "run", "esxi1", "storage.configure", *params, "--confirm", "configure storage esxi1", timeout=120
    )
    assert run.code == 0, run.output
    job_id = run.output.split("as job ")[1].split()[0]
    assert _writes(gz, job_id) == [
        "POST Volumes",
        "POST DellRaidService.AssignSpare",
        "POST ComputerSystem.Reset",
    ]  # one reset for both

    with gz.api() as api:
        storage = api.get(f"/api/v1/hosts/{host}/outputs/storage").json()
        perc_now = next(c for c in storage["controllers"] if c["id"] == PERC)
        volume = next(v for v in perc_now["volumes"] if v["name"] == "data")
        assert volume["raid"] == "RAID5" and len(volume["drives"]) == 3
        assert sum(1 for d in perc_now["drives"] if d["hotspare"] == "Global") == 1
        assert storage["boot_volume"]["name"] == "boss"  # still where the OS goes
        result = api.get(f"/api/v1/hosts/{host}/outputs/storage_config").json()
        assert result["profile_name"] == "lab" and len(result["actions"]) == 2
        task = next(
            t
            for s in api.get(f"/api/v1/hosts/{host}/pipeline").json()["stages"]
            for t in s["tasks"]
            if t["id"] == "storage.configure"
        )
        assert task["state"] == "done"
        again = api.get(f"/api/v1/hosts/{host}/storage-plan", params={"profile_id": profile["id"]}).json()
        assert again["actions"] == []


def test_the_boot_volume_is_protected(perc: GroundZero) -> None:
    gz = perc
    host, _ = _ready(gz)
    wipe = {"name": "wipe", "controllers": [{"kind": "boot", "remove_other_volumes": True}]}
    with gz.api() as api:
        wipe_id = api.post("/api/v1/storage-profiles", json=wipe).json()["id"]
    run = gz.cli(
        "run",
        "esxi1",
        "storage.configure",
        "-p",
        f"profile_id={wipe_id}",
        "--confirm",
        "configure storage esxi1",
    )
    assert run.code != 0 and "the boot volume the OS runs from" in run.output
    shown = gz.cli("storage-profile", "plan", "esxi1", "wipe")
    assert "Can't go ahead" in shown.output and "the boot volume the OS runs from" in shown.output
    assert "Delete boss" in gz.cli("storage-profile", "plan", "esxi1", "wipe", "--allow-boot-volume").output
    assert "wipe" in gz.cli("storage-profile", "list").output
    with gz.api() as api:
        plan = api.get(
            f"/api/v1/hosts/{host}/storage-plan", params={"profile_id": wipe_id, "allow_boot_volume": True}
        ).json()
        assert plan["actions"][0]["kind"] == "delete_volume" and plan["actions"][0]["destroys_data"]


def test_changes_that_never_apply_fail_clearly(tmp_path: Path) -> None:
    gz = _simulated(tmp_path, GROUNDZERO_SIMULATE_FAULTS='["perc-drives", "storage-not-applied"]', **SHORT)
    gz.start()
    try:
        _ready(gz)
        rule = {"kind": "raid", "volumes": [{"name": "data", "raid": "RAID1", "drives": {"count": 2}}]}
        with gz.api() as api:
            pid = api.post("/api/v1/storage-profiles", json={"name": "mirror", "controllers": [rule]}).json()[
                "id"
            ]
        run = gz.cli(
            "run",
            "esxi1",
            "storage.configure",
            "-p",
            f"profile_id={pid}",
            "--confirm",
            "configure storage esxi1",
            timeout=120,
        )
        assert run.code != 0 and "weren't all in place" in run.output and "Job Queue" in run.output
    finally:
        gz.stop()
