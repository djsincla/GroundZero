"""Holodeck settings as a config-set family: everything a Holodeck deployment needs, filled in the UI.

Not an OS installer (``install_supported`` is False). The shared settings describe the Holodeck
deployment and the Holorouter's network; per-server values hold the instance ID and the Holorouter's
own IP. Secrets (Holorouter password, Broadcom download token, offline depot password) are encrypted
and never returned.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from groundzero.osconfig.base import IsoMeta


def _ipv4(value: str) -> str:
    ipaddress.IPv4Address(value)
    return value


class HolodeckSettings(BaseModel):
    """A Holodeck deployment (shared, reusable across hosts)."""

    version: str = Field(
        default="9.1.1.0",
        title="VCF version",
        description="Holodeck -Version; the VCF Installer OVA and ESX ISO must match it",
    )
    vsan_mode: Literal["ESA", "OSA"] = Field(default="ESA", title="vSAN mode")
    management_only: bool = Field(
        default=True,
        title="Management domain only",
        description="Skip the workload domain (faster: about 4-5 hours)",
    )
    site: Literal["a", "b"] = Field(default="a", title="Site")
    depot_type: Literal["Online", "Offline"] = Field(
        default="Online", title="Depot", description="Online needs a Broadcom download token"
    )
    offline_depot_host: str | None = Field(
        default=None,
        title="Offline depot host",
        description="Offline Depot Appliance IP or FQDN (Offline only)",
    )
    offline_depot_protocol: Literal["http", "https"] = Field(default="http", title="Offline depot protocol")
    offline_depot_port: int | None = Field(default=None, ge=1, le=65535, title="Offline depot port")
    offline_depot_username: str | None = Field(default=None, title="Offline depot user")
    cidr: str | None = Field(
        default=None, title="Nested network CIDR (/20)", description="Default 10.1.0.0/20 (site A)"
    )
    vlan_range_start: int | None = Field(
        default=None,
        ge=1,
        le=4094,
        title="First nested VLAN",
        description="Default 10 (site A uses 16 consecutive VLANs)",
    )
    dns_domain: str | None = Field(default=None, title="Nested DNS domain", description="Default vcf.lab")
    holorouter_prefix: int = Field(
        default=24,
        ge=8,
        le=30,
        title="Holorouter network prefix",
        description="CIDR prefix of the Holorouter's management network",
    )
    holorouter_gateway: str = Field(title="Holorouter gateway")
    holorouter_dns: str = Field(title="Holorouter DNS server")
    holorouter_dns_domain: str | None = Field(
        default=None,
        title="Holorouter DNS domain",
        description="Optional; Holodeck's documentation uses site-a.vcf.lab",
    )
    holorouter_ntp: str = Field(default="pool.ntp.org", title="Holorouter NTP server")
    webtop: bool = Field(default=True, title="Webtop UI", description="Browser desktop on the Holorouter")
    gitops: bool = Field(
        default=False,
        title="GitOps (GitLab)",
        description="Installs GitLab on the Holorouter (uses extra resources)",
    )

    @field_validator("holorouter_gateway")
    @classmethod
    def _gw(cls, v: str) -> str:
        return _ipv4(v)

    @field_validator("cidr")
    @classmethod
    def _cidr(cls, v: str | None) -> str | None:
        if v is not None:
            net = ipaddress.IPv4Network(v, strict=True)
            if net.prefixlen != 20:
                raise ValueError("Holodeck needs a /20 network")
        return v


class HolodeckHostValues(BaseModel):
    """This host's Holodeck instance."""

    instance_id: str = Field(
        default="holo1",
        title="Instance ID",
        pattern=r"^[a-z][a-z0-9-]{0,14}$",
        description="Prefix for every nested VM (lowercase, up to 15 characters)",
    )
    holorouter_ip: str = Field(
        title="Holorouter IP", description="One free IP on the external port group's network"
    )
    holorouter_hostname: str = Field(default="holorouter", title="Holorouter hostname")

    @field_validator("holorouter_ip")
    @classmethod
    def _ip(cls, v: str) -> str:
        return _ipv4(v)


class HolodeckPlugin:
    family: ClassVar[str] = "holodeck"
    title: ClassVar[str] = "VMware Holodeck"
    install_supported: ClassVar[bool] = False
    settings_model: ClassVar[type[BaseModel]] = HolodeckSettings
    host_values_model: ClassVar[type[BaseModel]] = HolodeckHostValues
    secret_fields: ClassVar[tuple[str, ...]] = (
        "holorouter_password",
        "download_token",
        "offline_depot_password",
    )

    @staticmethod
    def detect_iso(path: Path) -> IsoMeta | None:
        return None  # Holodeck uses OVAs (detected by the image repository), not an installer ISO
