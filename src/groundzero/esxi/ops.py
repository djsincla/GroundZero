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


class LiveEsxiOps:
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
        return await read_network(access.address, access.username, password, verify_tls=access.verify_tls)

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage:
        return await read_storage(access.address, access.username, password, verify_tls=access.verify_tls)

    async def probe(self, address: str) -> EsxiAbout | None:
        return await probe_about(address)
