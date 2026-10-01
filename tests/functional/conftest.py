from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from .harness import ESXI1_CAPTURE, R740XD_CAPTURE, GroundZero


def _simulated(tmp_path: Path, **extra: str) -> GroundZero:
    gz = GroundZero(
        home=tmp_path,
        extra_env={
            "GROUNDZERO_SIMULATE_BMC_DIR": str(R740XD_CAPTURE),
            "GROUNDZERO_BMC_PASSWORD": "simulated",
            "GROUNDZERO_SIMULATE_ESXI_DIR": str(ESXI1_CAPTURE),
            "GROUNDZERO_ESXI_PASSWORD": "simulated",
            "GROUNDZERO_INSTALL_POLL_SECONDS": "0.2",
            "GROUNDZERO_INSTALLER_BOOT_MINUTES": "0.5",
            **extra,
        },
    )
    gz.extra_env["GROUNDZERO_MEDIA_PUBLIC_URL"] = gz.media_url  # simulated BMC fetches from localhost
    return gz


@pytest.fixture
def simulated_r740xd(tmp_path: Path) -> Iterator[GroundZero]:
    """A running server whose BMC is the recorded Dell R740xd and whose OS is the recorded esxi1."""
    gz = _simulated(tmp_path)
    gz.start()
    yield gz
    gz.stop()


@pytest.fixture
def simulated_r740xd_ignoring_boot_once(tmp_path: Path) -> Iterator[GroundZero]:
    """Same, but the simulated iDRAC silently ignores one-time boot requests."""
    gz = _simulated(tmp_path, GROUNDZERO_SIMULATE_FAULTS='["ignore-boot-once"]')
    gz.start()
    yield gz
    gz.stop()


@pytest.fixture
def simulated_r740xd_slow_insert(tmp_path: Path) -> Iterator[GroundZero]:
    """The simulated iDRAC completes InsertMedia but its HTTP response times out (seen live)."""
    gz = _simulated(tmp_path, GROUNDZERO_SIMULATE_FAULTS='["slow-insert"]')
    gz.start()
    yield gz
    gz.stop()
