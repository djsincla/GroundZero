"""Cluster mode: servers named after their BMC, addressed from a pool, optionally checked in DNS.

A cluster ties an ESXi config set (VLAN, gateway, DNS servers, NTP, disk rule) to an IP range and a DNS
domain. Adding a server derives its ESXi hostname from the BMC's own name (``idrac-esx01`` with the prefix
``idrac-`` stripped becomes ``esx01``) and gives it the next address in the range that nothing else uses.
Those become the server's per-host values, so the normal OS deployment picks them up. The DNS check is an
option per cluster (``require_dns``): when it is on, members are installed only once Verify DNS passes.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class ClusterWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    config_set_id: str = Field(description="The ESXi config set every member is installed with")
    ip_first: str = Field(title="First IP", description="First address of the range, e.g. 192.0.2.101")
    ip_last: str = Field(title="Last IP", description="Last address of the range, e.g. 192.0.2.120")
    dns_domain: str = Field(
        title="DNS domain", description="e.g. lab.example: members are <hostname>.<domain>"
    )
    strip_prefix: str = Field(default="", description="Removed from the BMC name, e.g. idrac-")
    strip_suffix: str = Field(default="", description="Removed from the BMC name, e.g. -idrac")
    require_dns: bool = Field(
        default=False,
        title="Require a passing DNS check before install",
        description="Off: run Verify DNS when you want. On: members are installed only once it passes.",
    )
    spec_id: str | None = Field(
        default=None, title="Spec", description="The jobs every member runs (a member's own spec wins)"
    )

    @field_validator("ip_first", "ip_last")
    @classmethod
    def _ipv4(cls, v: str) -> str:
        return str(ipaddress.IPv4Address(v))

    @field_validator("dns_domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        v = v.strip().strip(".").lower()
        if not v or not all(_HOSTNAME.match(label) for label in v.split(".")):
            raise ValueError("not a valid DNS domain")
        return v

    @model_validator(mode="after")
    def _range(self) -> ClusterWrite:
        first, last = ipaddress.IPv4Address(self.ip_first), ipaddress.IPv4Address(self.ip_last)
        if last < first:
            raise ValueError("the last IP comes before the first")
        if int(last) - int(first) > 1023:
            raise ValueError("the range is larger than 1024 addresses")
        return self


class ClusterMember(BaseModel):
    host_id: str
    host_name: str = Field(description="The host as registered in GroundZero")
    bmc_hostname: str | None = Field(default=None, description="The BMC's own name the hostname came from")
    hostname: str
    ip: str
    added_at: datetime

    def fqdn(self, domain: str) -> str:
        return f"{self.hostname}.{domain}"


class Cluster(ClusterWrite):
    id: str
    members: list[ClusterMember] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def derive_hostname(source: str, prefix: str, suffix: str) -> str:
    """The ESXi hostname from the BMC's name: prefix/suffix removed (case-insensitive), lower case."""
    name = source.strip().split(".")[0]
    if prefix and name.lower().startswith(prefix.lower()):
        name = name[len(prefix) :]
    if suffix and name.lower().endswith(suffix.lower()):
        name = name[: len(name) - len(suffix)]
    name = name.lower()
    if not _HOSTNAME.match(name):
        raise ValueError(f"'{name}' (from '{source}') is not a valid hostname; adjust the prefix/suffix")
    return name


def next_free_ip(first: str, last: str, used: set[str]) -> str | None:
    start, end = int(ipaddress.IPv4Address(first)), int(ipaddress.IPv4Address(last))
    for n in range(start, end + 1):
        candidate = str(ipaddress.IPv4Address(n))
        if candidate not in used:
            return candidate
    return None
