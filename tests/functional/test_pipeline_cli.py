"""Black-box: the pipeline through the real CLI and server (simulated R740xd and ESXi)."""

from __future__ import annotations

import json

import pytest

from .harness import GroundZero

pytestmark = pytest.mark.functional


def test_pipeline_run_and_diagnostics(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0

    p = gz.cli("pipeline", "esxi1")
    assert (
        p.code == 0
        and "Next: Holodeck preflight" in p.output
        and "groundzero run esxi1 preflight" in p.output
    )

    blocked = gz.cli("run", "esxi1", "os.read")
    assert blocked.code != 0 and "Set OS access" in blocked.output

    run = gz.cli("run", "esxi1", "preflight", timeout=120)
    assert run.code == 0, run.output
    assert "succeeded Read hardware inventory from the BMC" in " ".join(run.output.split())
    job_id = run.output.split("as job ")[1].split()[0]

    p = gz.cli("pipeline", "esxi1")
    assert "Next: Deploy custom OS" in p.output and "12 passed" in p.output

    out = gz.home / "diag.json"
    diag = gz.cli("jobs", "diag", job_id, "--out", str(out))
    assert diag.code == 0, diag.output
    bundle = json.loads(out.read_text())
    assert bundle["job"]["task"] == "preflight"
    assert sum(e["event"] == "redfish" for e in bundle["events"]) > 10
