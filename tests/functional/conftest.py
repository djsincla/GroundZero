from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from .harness import R740XD_CAPTURE, GroundZero


@pytest.fixture
def simulated_r740xd(tmp_path: Path) -> Iterator[GroundZero]:
    """A running server whose BMCs are the recorded Dell R740xd (no hardware needed)."""
    gz = GroundZero(
        home=tmp_path,
        extra_env={
            "GROUNDZERO_SIMULATE_BMC_DIR": str(R740XD_CAPTURE),
            "GROUNDZERO_BMC_PASSWORD": "simulated",
        },
    )
    gz.start()
    yield gz
    gz.stop()
