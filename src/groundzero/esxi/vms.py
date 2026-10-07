"""Read the VMs on a standalone ESXi host: their layout, guest IP and the OVF settings they were given.

The OVF settings an appliance received live in its ``.vmx`` as ``guestinfo.ovfEnv``. The vSphere API returns
that value empty (live finding), so the ``.vmx`` is read from the datastore over HTTPS instead, with the
host's pinned certificate. Values in a ``.vmx`` escape special characters as ``|XX`` (hex).
"""

from __future__ import annotations

import re
import ssl
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from groundzero.esxi.reader import EsxiError

OE = "http://schemas.dmtf.org/ovf/environment/1"


class VmNic(BaseModel):
    label: str = Field(description='e.g. "Network adapter 1"')
    portgroup: str | None = None
    mac: str | None = None
    connected: bool | None = None


class VmSummary(BaseModel):
    name: str
    power_state: str
    guest_ip: str | None = None


class VmInfo(VmSummary):
    guest_ips: list[str] = Field(default_factory=list)
    tools_running: bool = False
    cpus: int | None = None
    memory_mb: int | None = None
    datastore: str | None = None
    vmx_path: str | None = Field(
        default=None, description='e.g. "[localHolodeck] holo1-holorouter/holo1-holorouter.vmx"'
    )
    nics: list[VmNic] = Field(default_factory=list, description="In device order (the OVF's network order)")
    ovf_env: dict[str, str] = Field(
        default_factory=dict, description="The OVF properties it was deployed with (passwords included)"
    )


def decode_vmx_value(raw: str) -> str:
    return re.sub(r"\|([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), raw)


def parse_ovf_env(xml: str) -> dict[str, str]:
    """Property key → value from an OVF environment document."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "Property":
            key = el.get(f"{{{OE}}}key") or el.get("key")
            if key:
                out[key] = el.get(f"{{{OE}}}value") or el.get("value") or ""
    return out


def ovf_env_from_vmx(vmx: str) -> dict[str, str]:
    for line in vmx.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "guestinfo.ovfenv":
            return parse_ovf_env(decode_vmx_value(value.strip().strip('"')))
    return {}


def _ipv4(ips: list[str]) -> list[str]:
    """IPv4 addresses, without link-local ones, de-duplicated in order (Tools repeats the primary)."""
    seen: list[str] = []
    for ip in ips:
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) and not ip.startswith("169.254.") and ip not in seen:
            seen.append(ip)
    return seen


def _vms(host: Any) -> list[Any]:
    return list(host.vm or [])


def list_vms(host: Any) -> list[VmSummary]:
    return sorted(
        (
            VmSummary(
                name=vm.name,
                power_state=str(vm.runtime.powerState),
                guest_ip=next(
                    iter(_ipv4([vm.guest.ipAddress] if vm.guest and vm.guest.ipAddress else [])), None
                ),
            )
            for vm in _vms(host)
        ),
        key=lambda v: v.name,
    )


def read_vm(
    host: Any, address: str, username: str, password: str, ssl_context: ssl.SSLContext, name: str
) -> VmInfo:
    """Blocking. The VM's layout from the API, and its OVF settings from the ``.vmx`` on the datastore."""
    import pyVmomi

    vim: Any = pyVmomi.vim
    vm = next((v for v in _vms(host) if v.name == name), None)
    if vm is None:
        raise EsxiError(f"No VM named {name} on {address}")
    guest = vm.guest
    ips = _ipv4([ip for n in (guest.net or []) for ip in (n.ipAddress or [])] + [guest.ipAddress or ""])
    nics = [
        VmNic(
            label=d.deviceInfo.label,
            portgroup=getattr(d.backing, "deviceName", None),
            mac=getattr(d, "macAddress", None),
            connected=getattr(d.connectable, "connected", None) if d.connectable else None,
        )
        for d in vm.config.hardware.device
        if isinstance(d, vim.vm.device.VirtualEthernetCard)
    ]
    vmx_path = vm.config.files.vmPathName
    m = re.fullmatch(r"\[(?P<ds>[^\]]+)\] (?P<path>.+)", vmx_path or "")
    env: dict[str, str] = {}
    if m:
        url = f"https://{address}/folder/{quote(m['path'])}"
        try:
            with httpx.Client(verify=ssl_context, timeout=30, auth=(username, password)) as client:
                resp = client.get(url, params={"dcPath": "ha-datacenter", "dsName": m["ds"]})
        except httpx.HTTPError as exc:
            raise EsxiError(f"Could not read {vmx_path} from {address}: {exc}") from exc
        if resp.status_code != 200:
            raise EsxiError(f"Could not read {vmx_path} from {address}: HTTP {resp.status_code}")
        env = ovf_env_from_vmx(resp.text)
    return VmInfo(
        name=vm.name,
        power_state=str(vm.runtime.powerState),
        guest_ip=ips[0] if ips else None,
        guest_ips=ips,
        tools_running=str(guest.toolsRunningStatus) == "guestToolsRunning",
        cpus=vm.config.hardware.numCPU,
        memory_mb=vm.config.hardware.memoryMB,
        datastore=m["ds"] if m else None,
        vmx_path=vmx_path,
        nics=nics,
        ovf_env=env,
    )
