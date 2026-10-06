"""Live functional tests against a real lab BMC. Opt-in: `uv run pytest -m live`.

Configure in the git-ignored .env (never commit credentials):
    GROUNDZERO_LIVE_BMC=198.51.100.11
    GROUNDZERO_BMC_USERNAME=root
    GROUNDZERO_BMC_PASSWORD=...
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from tests.functional.harness import REPO_ROOT, GroundZero

pytestmark = pytest.mark.live


class LiveLab(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GROUNDZERO_", env_file=REPO_ROOT / ".env", extra="ignore")

    live_bmc: str | None = None
    bmc_username: str = "root"
    bmc_password: str | None = None


@pytest.fixture
def live(tmp_path: Path) -> Iterator[tuple[GroundZero, str]]:
    lab = LiveLab()
    if not (lab.live_bmc and lab.bmc_password):
        pytest.skip("set GROUNDZERO_LIVE_BMC / GROUNDZERO_BMC_PASSWORD in .env to run live tests")
    gz = GroundZero(
        home=tmp_path,
        extra_env={"GROUNDZERO_BMC_USERNAME": lab.bmc_username, "GROUNDZERO_BMC_PASSWORD": lab.bmc_password},
    )
    gz.start()
    yield gz, lab.live_bmc
    gz.stop()


def test_live_preflight_is_read_only(live: tuple[GroundZero, str]) -> None:
    gz, bmc = live
    added = gz.cli("hosts", "add", "--bmc", bmc, "--name", "lab")
    assert added.code == 0, added.output

    result = gz.cli("preflight", "lab", timeout=600)
    assert result.code in (0, 2), result.output  # the report must be produced either way
    assert "lab vs holodeck-9" in result.output
    assert "0 unknown" in result.output, "every check should be answerable on a supported BMC"

    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]
        job = api.get("/api/v1/jobs", params={"host_id": host["id"]}).json()[0]
    assert host["vendor"] != "generic"
    writes = [c for c in job["result"]["audit"]["non_get"] if "/Sessions" not in c]
    assert writes == [], f"preflight changed BMC state: {writes}"


class LiveEsxi(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GROUNDZERO_", env_file=REPO_ROOT / ".env", extra="ignore")

    live_esxi: str | None = None
    esxi_username: str = "root"
    esxi_password: str | None = None


def test_live_esxi_network_read(tmp_path: Path) -> None:
    lab, esxi = LiveLab(), LiveEsxi()
    if not (lab.live_bmc and lab.bmc_password and esxi.live_esxi and esxi.esxi_password):
        pytest.skip("set GROUNDZERO_LIVE_ESXI / GROUNDZERO_ESXI_PASSWORD (and the BMC vars) in .env")
    gz = GroundZero(
        home=tmp_path,
        extra_env={
            "GROUNDZERO_BMC_USERNAME": lab.bmc_username,
            "GROUNDZERO_BMC_PASSWORD": lab.bmc_password,
            "GROUNDZERO_ESXI_USERNAME": esxi.esxi_username,
            "GROUNDZERO_ESXI_PASSWORD": esxi.esxi_password,
        },
    )
    gz.start()
    try:
        assert gz.cli("hosts", "add", "--bmc", lab.live_bmc, "--name", "lab").code == 0
        assert gz.cli("os", "set", "lab", "--address", esxi.live_esxi).code == 0
        result = gz.cli("os", "network", "lab", timeout=180)
        assert result.code == 0, result.output
        with gz.api() as api:
            host = api.get("/api/v1/hosts").json()[0]
            cfg = api.get(f"/api/v1/hosts/{host['id']}/outputs/os_network").json()
        mgmt = next(v for v in cfg["vmkernel"] if "management" in v["services"])
        assert mgmt["ip"] == esxi.live_esxi
    finally:
        gz.stop()


def test_live_bmc_certificate_is_pinned(live: tuple[GroundZero, str]) -> None:
    gz, bmc = live
    assert gz.cli("hosts", "add", "--bmc", bmc, "--name", "lab").code == 0
    assert gz.cli("inventory", "lab", timeout=300).code == 0  # first contact pins, then reads via the pin
    certs = gz.cli("hosts", "certs", "lab")
    assert certs.code == 0 and "bmc" in certs.output, certs.output
    with gz.api() as api:
        host = api.get("/api/v1/hosts").json()[0]
        pins = api.get(f"/api/v1/hosts/{host['id']}/certificates").json()
    assert [p["role"] for p in pins] == ["bmc"] and len(pins[0]["fingerprint"]) == 95
    assert gz.cli("inventory", "lab", timeout=300).code == 0  # reuse: same cert accepted
