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


@pytest.fixture(autouse=True)
def _no_real_tls_handshakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process tests must never reach real lab hosts (it would pass on the lab network, fail in CI)."""
    import ssl

    real = ssl.get_server_certificate

    def guarded(addr: tuple[str, int], *args: Any, **kwargs: Any) -> str:
        if addr[0] not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"test tried a TLS handshake with {addr[0]}:{addr[1]}")
        return real(addr, *args, **kwargs)

    monkeypatch.setattr(ssl, "get_server_certificate", guarded)
