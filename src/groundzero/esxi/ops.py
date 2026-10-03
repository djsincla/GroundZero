"""The ESXi operations GroundZero needs, behind one interface (live vSphere API or simulation)."""

from __future__ import annotations

import time
from collections.abc import Awaitable
from typing import Protocol

from pydantic import BaseModel

from groundzero.core import diagnostics
from groundzero.core.models import OsAccess
from groundzero.esxi.models import EsxiAbout, EsxiNetworkConfig, EsxiStorage
from groundzero.esxi.reader import probe_about, read_network, read_storage


class EsxiOps(Protocol):
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig: ...

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage: ...

    async def probe(self, address: str) -> EsxiAbout | None: ...


class OsTarget(OsAccess):
    """OsAccess plus the pinned certificate to trust (internal; never serialised to the API)."""

    pinned_pem: str | None = None


def _pin(access: OsAccess) -> str | None:
    return access.pinned_pem if isinstance(access, OsTarget) else None


async def _traced[T](op: str, address: str, call: Awaitable[T]) -> T:
    """Run an ESXi operation, recording it (outcome and timing) in the job's diagnostics."""
    started = time.monotonic()
    try:
        result = await call
    except Exception as exc:
        diagnostics.record("esxi", op=op, address=address, error=f"{type(exc).__name__}: {exc}",
                           ms=round((time.monotonic() - started) * 1000))  # fmt: skip
        raise
    summary = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
    diagnostics.record("esxi", op=op, address=address, ms=round((time.monotonic() - started) * 1000),
                       result=diagnostics.truncate(summary))  # fmt: skip
    return result


class LiveEsxiOps:
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
        diagnostics.add_secret(password)
        return await _traced("read_network", access.address, read_network(
            access.address, access.username, password, verify_tls=access.verify_tls, pinned_pem=_pin(access)
        ))  # fmt: skip

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage:
        diagnostics.add_secret(password)
        return await _traced("read_storage", access.address, read_storage(
            access.address, access.username, password, verify_tls=access.verify_tls, pinned_pem=_pin(access)
        ))  # fmt: skip

    async def probe(self, address: str) -> EsxiAbout | None:
        return await _traced("probe", address, probe_about(address))
