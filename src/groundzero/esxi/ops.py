"""The ESXi operations GroundZero needs, behind one interface (live vSphere API or simulation)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel

from groundzero.core import diagnostics
from groundzero.core.models import OsAccess
from groundzero.esxi import jumbo, writer
from groundzero.esxi.models import ChangeRecord, EsxiAbout, EsxiNetworkConfig, EsxiStorage, JumboResult
from groundzero.esxi.reader import EsxiError, connect_host, probe_about, read_network, read_storage


class EsxiOps(Protocol):
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig: ...

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage: ...

    async def probe(self, address: str) -> EsxiAbout | None: ...

    async def apply(
        self, access: OsAccess, password: str, action: str, params: dict[str, Any]
    ) -> ChangeRecord:
        """Apply one host-prep action: set_mtu, ensure_portgroup, configure_ntp or create_datastore."""
        ...

    async def verify_jumbo(
        self,
        access: OsAccess,
        password: str,
        *,
        vswitch: str,
        uplinks: tuple[str, str],
        vlan: int,
        mtu: int,
        pinned_ssh_key: str | None,
        log: Callable[[str], None],
    ) -> JumboResult: ...


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
        diagnostics.record(
            "esxi",
            op=op,
            address=address,
            error=f"{type(exc).__name__}: {exc}",
            ms=round((time.monotonic() - started) * 1000),
        )
        raise
    summary = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
    diagnostics.record(
        "esxi",
        op=op,
        address=address,
        ms=round((time.monotonic() - started) * 1000),
        result=diagnostics.truncate(summary),
    )
    return result


class LiveEsxiOps:
    async def read_network(self, access: OsAccess, password: str) -> EsxiNetworkConfig:
        diagnostics.add_secret(password)
        return await _traced(
            "read_network",
            access.address,
            read_network(
                access.address,
                access.username,
                password,
                verify_tls=access.verify_tls,
                pinned_pem=_pin(access),
            ),
        )

    async def read_storage(self, access: OsAccess, password: str) -> EsxiStorage:
        diagnostics.add_secret(password)
        return await _traced(
            "read_storage",
            access.address,
            read_storage(
                access.address,
                access.username,
                password,
                verify_tls=access.verify_tls,
                pinned_pem=_pin(access),
            ),
        )

    async def probe(self, address: str) -> EsxiAbout | None:
        return await _traced("probe", address, probe_about(address))

    async def apply(
        self, access: OsAccess, password: str, action: str, params: dict[str, Any]
    ) -> ChangeRecord:
        diagnostics.add_secret(password)

        def run() -> ChangeRecord:
            with connect_host(
                access.address, access.username, password, access.verify_tls, _pin(access)
            ) as host:
                if action == "set_mtu":
                    return writer.set_vswitch_mtu(host, params["vswitch"], int(params["mtu"]))
                if action == "ensure_portgroup":
                    keys = ("allow_promiscuous", "mac_changes", "forged_transmits")
                    security: dict[str, bool] = {k: bool(params[k]) for k in keys if k in params}
                    return writer.ensure_portgroup(
                        host, params["name"], params["vswitch"], int(params["vlan"]), security or None
                    )
                if action == "configure_ntp":
                    return writer.configure_ntp(host, list(params["servers"]), params.get("policy", "on"))
                if action == "create_datastore":
                    return writer.create_vmfs_datastore(host, params["disk"], params["name"])
                raise EsxiError(f"Unknown host-prep action {action}")

        return await _traced(action, access.address, asyncio.to_thread(run))

    async def verify_jumbo(
        self,
        access: OsAccess,
        password: str,
        *,
        vswitch: str,
        uplinks: tuple[str, str],
        vlan: int,
        mtu: int,
        pinned_ssh_key: str | None,
        log: Callable[[str], None],
    ) -> JumboResult:
        diagnostics.add_secret(password)

        def run() -> JumboResult:
            with connect_host(
                access.address, access.username, password, access.verify_tls, _pin(access)
            ) as host:
                return jumbo.verify_jumbo(
                    host,
                    access.address,
                    access.username,
                    password,
                    vswitch=vswitch,
                    uplinks=uplinks,
                    vlan=vlan,
                    mtu=mtu,
                    pinned_ssh_key=pinned_ssh_key,
                    log=log,
                )

        return await _traced("verify_jumbo", access.address, asyncio.to_thread(run))
