"""Read-only ESXi network inventory over the vSphere API (pyVmomi).

``extract_network`` is a pure function over the vSphere object shapes so it can be tested with plain
fakes; ``read_network`` handles the (blocking) connection and runs it in a worker thread.
"""

from __future__ import annotations

import asyncio
import ssl
from typing import Any

from groundzero.esxi.models import (
    Datastore,
    EsxiAbout,
    EsxiNetworkConfig,
    EsxiStorage,
    PhysicalNic,
    PortGroup,
    SecurityPolicy,
    VmkInterface,
    VSwitch,
)

_VNIC_SERVICES = ("management", "vmotion", "vsan", "faultToleranceLogging", "vSphereProvisioning")


class EsxiError(Exception):
    error_type = "esxi_error"


def _uplinks(vswitch: Any) -> list[str]:
    bridge = getattr(vswitch.spec, "bridge", None)
    return list(getattr(bridge, "nicDevice", None) or [])


def _nic_order(policy: Any) -> tuple[list[str], list[str]]:
    order = getattr(getattr(policy, "nicTeaming", None), "nicOrder", None)
    if order is None:
        return [], []
    return list(order.activeNic or []), list(order.standbyNic or [])


def _security(policy: Any) -> SecurityPolicy:
    sec = getattr(policy, "security", None)
    if sec is None:
        return SecurityPolicy()
    return SecurityPolicy(
        allow_promiscuous=sec.allowPromiscuous,
        mac_changes=sec.macChanges,
        forged_transmits=sec.forgedTransmits,
    )


def _neighbour(hint: Any) -> tuple[str | None, str | None]:
    if hint is None:
        return None, None
    if hint.connectedSwitchPort:
        return hint.connectedSwitchPort.devId, hint.connectedSwitchPort.portId
    if hint.lldpInfo:
        return hint.lldpInfo.chassisId, hint.lldpInfo.portId
    return None, None


def extract_network(
    address: str,
    about: Any,
    network: Any,
    ntp_servers: list[str],
    services_by_vnic: dict[str, list[str]],
    hints: dict[str, Any] | None = None,
) -> EsxiNetworkConfig:
    hints = hints or {}
    dns = network.dnsConfig
    route = network.ipRouteConfig
    portgroups = [
        PortGroup(
            name=pg.spec.name,
            vlan_id=int(pg.spec.vlanId or 0),
            vswitch=pg.spec.vswitchName,
            active_uplinks=_nic_order(pg.computedPolicy)[0],
            standby_uplinks=_nic_order(pg.computedPolicy)[1],
            security=_security(pg.computedPolicy),
        )
        for pg in network.portgroup or []
    ]
    vswitches = [
        VSwitch(
            name=vs.name,
            mtu=vs.mtu,
            uplinks=_uplinks(vs),
            active_uplinks=_nic_order(vs.spec.policy)[0],
            standby_uplinks=_nic_order(vs.spec.policy)[1],
            security=_security(vs.spec.policy),
            portgroups=[p.name for p in portgroups if p.vswitch == vs.name],
        )
        for vs in network.vswitch or []
    ]
    vmks = [
        VmkInterface(
            device=v.device,
            portgroup=v.portgroup or None,
            ip=v.spec.ip.ipAddress or None,
            netmask=v.spec.ip.subnetMask or None,
            dhcp=bool(v.spec.ip.dhcp),
            mac=v.spec.mac,
            mtu=v.spec.mtu,
            services=services_by_vnic.get(v.device, []),
        )
        for v in network.vnic or []
    ]
    pnics = [
        PhysicalNic(
            device=p.device,
            mac=p.mac,
            speed_mbps=p.linkSpeed.speedMb if p.linkSpeed else None,
            driver=p.driver,
            pci=p.pci,
            switch=_neighbour(hints.get(p.device))[0],
            switch_port=_neighbour(hints.get(p.device))[1],
        )
        for p in network.pnic or []
    ]
    return EsxiNetworkConfig(
        address=address,
        product=about.fullName,
        version=about.version,
        build=about.build,
        hostname=dns.hostName or None,
        domain=dns.domainName or None,
        default_gateway=route.defaultGateway or None,
        dns_servers=list(dns.address or []),
        search_domains=list(dns.searchDomain or []),
        dns_from_dhcp=bool(dns.dhcp),
        ntp_servers=ntp_servers,
        vmkernel=vmks,
        vswitches=vswitches,
        portgroups=portgroups,
        physical_nics=pnics,
    )


def _read_network_blocking(address: str, username: str, password: str, verify_tls: bool) -> EsxiNetworkConfig:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim

    try:
        si = SmartConnect(host=address, user=username, pwd=password, sslContext=_ssl_context(verify_tls))
    except vim.fault.InvalidLogin as exc:
        raise EsxiError(f"ESXi rejected the credentials for {address}") from exc
    except (OSError, ssl.SSLError) as exc:
        raise EsxiError(f"Cannot connect to ESXi at {address}: {exc}") from exc
    try:
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
        hosts = list(view.view)
        view.Destroy()
        if not hosts:
            raise EsxiError(f"No HostSystem found at {address}")
        host = hosts[0]
        ntp = host.config.dateTimeInfo.ntpConfig if host.config.dateTimeInfo else None
        services: dict[str, list[str]] = {}
        vnic_mgr = host.configManager.virtualNicManager
        for service in _VNIC_SERVICES:
            try:
                cfg = vnic_mgr.QueryNetConfig(service)
            except vim.fault.HostConfigFault:
                continue
            if cfg is None:
                continue
            selected = set(cfg.selectedVnic or [])
            for candidate in cfg.candidateVnic or []:
                if candidate.key in selected:
                    services.setdefault(candidate.device, []).append(service)
        network = host.config.network
        devices = [p.device for p in network.pnic or []]
        try:
            hints = {h.device: h for h in host.configManager.networkSystem.QueryNetworkHint(device=devices)}
        except vim.fault.HostConfigFault:
            hints = {}
        ntp_servers = list(ntp.server or []) if ntp else []
        return extract_network(address, content.about, network, ntp_servers, services, hints)
    finally:
        Disconnect(si)


async def read_network(
    address: str, username: str, password: str, *, verify_tls: bool = False
) -> EsxiNetworkConfig:
    return await asyncio.to_thread(_read_network_blocking, address, username, password, verify_tls)


def extract_storage(mount_info: list[Any]) -> EsxiStorage:
    datastores: list[Datastore] = []
    boot_disk: str | None = None
    for mount in mount_info:
        volume = mount.volume
        disks = [extent.diskName for extent in getattr(volume, "extent", None) or []]
        if volume.name.startswith("OSDATA") and disks:
            boot_disk = disks[0]
        datastores.append(
            Datastore(
                name=volume.name, type=volume.type, capacity_gb=round(volume.capacity / 1e9, 1), disks=disks
            )
        )
    return EsxiStorage(boot_disk=boot_disk, datastores=datastores)


def _ssl_context(verify_tls: bool) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if not verify_tls:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _read_storage_blocking(address: str, username: str, password: str, verify_tls: bool) -> EsxiStorage:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim

    try:
        si = SmartConnect(host=address, user=username, pwd=password, sslContext=_ssl_context(verify_tls))
    except vim.fault.InvalidLogin as exc:
        raise EsxiError(f"ESXi rejected the credentials for {address}") from exc
    except (OSError, ssl.SSLError) as exc:
        raise EsxiError(f"Cannot connect to ESXi at {address}: {exc}") from exc
    try:
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
        host = view.view[0]
        view.Destroy()
        return extract_storage(list(host.config.fileSystemVolume.mountInfo or []))
    finally:
        Disconnect(si)


def _probe_about_blocking(address: str, timeout: float) -> EsxiAbout | None:
    """Anonymous version/build query (no login). None when the host is not answering."""
    from pyVim.connect import SmartStubAdapter
    from pyVmomi import vim

    try:
        stub = SmartStubAdapter(host=address, sslContext=_ssl_context(False), connectionPoolTimeout=timeout)
        about = vim.ServiceInstance("ServiceInstance", stub).RetrieveContent().about
    except Exception:  # noqa: BLE001 - any failure here simply means "not up (yet)"
        return None
    return EsxiAbout(product=about.fullName, version=about.version, build=about.build)


async def read_storage(
    address: str, username: str, password: str, *, verify_tls: bool = False
) -> EsxiStorage:
    return await asyncio.to_thread(_read_storage_blocking, address, username, password, verify_tls)


async def probe_about(address: str, *, timeout: float = 10.0) -> EsxiAbout | None:
    return await asyncio.to_thread(_probe_about_blocking, address, timeout)
