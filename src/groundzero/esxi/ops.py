"""The ESXi operations GroundZero needs, behind one interface (live vSphere API or simulation)."""

from __future__ import annotations

from typing import Protocol

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


class LiveEsxiOps:
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
        return await read_network(
            access.address, access.username, password, verify_tls=access.verify_tls, pinned_pem=_pin(access)
        )

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage:
        return await read_storage(
            access.address, access.username, password, verify_tls=access.verify_tls, pinned_pem=_pin(access)
        )

    async def probe(self, address: str) -> EsxiAbout | None:
        return await probe_about(address)
