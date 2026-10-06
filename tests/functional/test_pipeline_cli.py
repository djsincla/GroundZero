"""Black-box: the pipeline through the real CLI and server (simulated R740xd and ESXi)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import _simulated
from .harness import GroundZero

pytestmark = pytest.mark.functional


def test_version_flag(simulated_r740xd: GroundZero) -> None:
    result = simulated_r740xd.cli("--version")
    assert result.code == 0 and result.output.startswith("GroundZero ")


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
    assert "Next: Deploy OS · custom ISO from a config set" in p.output and "12 passed" in p.output
    assert gz.cli("run", "esxi1", "vcf.readiness", timeout=60).code == 0  # optional, still runnable

    out = gz.home / "diag.json"
    diag = gz.cli("jobs", "diag", job_id, "--out", str(out))
    assert diag.code == 0, diag.output
    bundle = json.loads(out.read_text())
    assert bundle["job"]["task"] == "preflight"
    assert sum(e["event"] == "redfish" for e in bundle["events"]) > 10


def test_run_passes_parameters_and_rejects_bad_ones(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "esxi1").code == 0
    bad = gz.cli("run", "esxi1", "preflight", "--param", "novalue")
    assert bad.code != 0 and "KEY=VALUE" in bad.output
    unknown = gz.cli("run", "esxi1", "preflight", "-p", "variant=nope")
    assert unknown.code != 0 and "Unknown variant" in unknown.output  # rejected before a job is queued
    run = gz.cli("run", "esxi1", "preflight", "-p", "variant=vcf-9.0-esa-single", timeout=120)
    assert run.code == 0, run.output
    with gz.api() as api:
        job = api.get("/api/v1/jobs").json()[0]
        assert job["task"] == "preflight" and job["params"]["variant"] == "vcf-9.0-esa-single"


def test_serve_detach_runs_in_the_background_until_stopped(tmp_path: Path) -> None:
    gz = _simulated(tmp_path)  # not started by the fixture: `serve --detach` starts it
    started = gz.cli("serve", "--detach", timeout=60)
    try:
        assert started.code == 0 and "running in the background" in started.output, started.output
        assert (tmp_path / "serve.pid").exists()
        assert gz.cli("hosts", "list").code == 0  # the API answers after the CLI returned
        again = gz.cli("serve", "--detach")
        assert again.code != 0 and "already running" in again.output
    finally:
        stopped = gz.cli("stop", timeout=30)
    assert stopped.code == 0 and "Stopped GroundZero" in stopped.output
    assert not (tmp_path / "serve.pid").exists()
    assert gz.cli("hosts", "list").code != 0  # nothing answers any more
    assert gz.cli("stop").code != 0
