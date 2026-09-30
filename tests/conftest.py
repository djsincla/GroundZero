from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from synthetic_idrac9 import responses

from groundzero.redfish.capture import replay_transport
from groundzero.redfish.client import RedfishClient


@pytest.fixture
def idrac9() -> dict[str, dict[str, Any]]:
    return responses()


def make_client(data: dict[str, dict[str, Any]], **kwargs: Any) -> RedfishClient:
    return RedfishClient(
        "bmc.test", "root", "calvin", transport=replay_transport(data), retry_backoff=0, **kwargs
    )
