"""The unified container bundle: build the image, run it (simulated BMC), check state survives a restart.

Opt-in (`uv run pytest -m container`): needs Podman (or GZ_ENGINE=docker) and builds the image.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.functional.harness import ESXI1_CAPTURE, R740XD_CAPTURE, REPO_ROOT, free_port

pytestmark = pytest.mark.container

ENGINE = os.environ.get("GZ_ENGINE", "podman")
SCRIPT = REPO_ROOT / "scripts" / "gz-container"
IMAGE = "localhost/groundzero:test"


def _run(*args: str, env: dict[str, str] | None = None, timeout: float = 120) -> str:
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    assert done.returncode == 0, f"{' '.join(args)}\n{done.stdout}\n{done.stderr}"
    return done.stdout.strip()


@pytest.fixture(scope="module")
def image() -> str:
    if not shutil.which(ENGINE):
        pytest.skip(f"{ENGINE} is not installed")
    _run(str(SCRIPT), "build", env={**os.environ, "GZ_IMAGE": IMAGE}, timeout=1200)
    return IMAGE


@pytest.fixture
def bundle(image: str, tmp_path: Path) -> Iterator[tuple[dict[str, str], int]]:
    tag = uuid.uuid4().hex[:8]
    api_port = free_port()
    env = {
        **os.environ,
        "GZ_ENGINE": ENGINE,
        "GZ_IMAGE": image,
        "GZ_NAME": f"gz-test-{tag}",
        "GZ_VOLUME": f"gz-test-{tag}",
        "GZ_API_PORT": str(api_port),
        "GZ_MEDIA_PORT": str(free_port()),
        "GROUNDZERO_ISO_REPOSITORY": str(tmp_path),
        "GROUNDZERO_MEDIA_PUBLIC_URL": "https://192.0.2.10",  # no BMC to route to in the test
    }
    yield env, api_port
    subprocess.run([ENGINE, "rm", "-f", env["GZ_NAME"]], capture_output=True, check=False)
    subprocess.run([ENGINE, "volume", "rm", "-f", env["GZ_VOLUME"]], capture_output=True, check=False)


def _up(env: dict[str, str], api_port: int) -> httpx.Client:
    _run(str(SCRIPT), "up", env=env)
    for _ in range(60):
        try:
            if httpx.get(f"http://127.0.0.1:{api_port}/healthz", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise AssertionError(_run(ENGINE, "logs", env["GZ_NAME"]))
    token = _run(str(SCRIPT), "token", env=env)
    return httpx.Client(
        base_url=f"http://127.0.0.1:{api_port}", headers={"Authorization": f"Bearer {token}"}, timeout=30
    )


def test_bundle_serves_ui_api_and_keeps_state_across_restarts(bundle: tuple[dict[str, str], int]) -> None:
    env, api_port = bundle
    # Simulated hardware, mounted read-only, so the bundle can be exercised end to end without a lab
    sim = [
        "-e", "GROUNDZERO_SIMULATE_BMC_DIR=/sim/bmc", "-e", "GROUNDZERO_BMC_PASSWORD=simulated",
        "-e", "GROUNDZERO_SIMULATE_ESXI_DIR=/sim/esxi",
        "-v", f"{R740XD_CAPTURE}:/sim/bmc:ro", "-v", f"{ESXI1_CAPTURE}:/sim/esxi:ro",
    ]  # fmt: skip
    env["GZ_EXTRA_ARGS"] = " ".join(sim)
    with _up(env, api_port) as api:
        assert api.get("/healthz").json()["mode"] == "simulated"
        assert "GroundZero" in api.get("/").text  # the web UI ships in the image
        assert api.get("/ui/app.js").status_code == 200
        host = api.post(
            "/api/v1/hosts",
            json={"bmc_address": "198.51.100.11", "username": "root", "password": "x", "name": "r1"},
        ).json()
        job = api.post(f"/api/v1/hosts/{host['id']}/preflight", json={}).json()
        for _ in range(120):
            job = api.get(f"/api/v1/jobs/{job['id']}").json()
            if job["status"] not in ("queued", "running"):
                break
            time.sleep(0.5)
        assert job["status"] == "succeeded", job
        token = api.headers["Authorization"]

    # Recreate the container: the database, token and encryption key live in the volume
    with _up(env, api_port) as api:
        assert api.headers["Authorization"] == token
        hosts = api.get("/api/v1/hosts").json()
        assert [h["name"] for h in hosts] == ["r1"]
        assert api.get(f"/api/v1/hosts/{hosts[0]['id']}/preflight").status_code == 200

    user = _run(ENGINE, "exec", env["GZ_NAME"], "id", "-u")
    assert user != "0", "the bundle must not run as root"
