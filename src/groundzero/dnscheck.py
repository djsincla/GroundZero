"""DNS lookups against named servers (the cluster's own DNS), never the local resolver.

The machine running GroundZero often resolves through a VPN or a corporate resolver that knows nothing
about the lab, so a check that "works here" proves little. The servers the ESXi hosts will use are asked
directly: forward (A) for the FQDN and reverse (PTR) for the IP.
"""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Protocol

from pydantic import BaseModel, Field


class DnsCheck(BaseModel):
    """Forward and reverse records for one server, as the cluster's DNS servers see them."""

    fqdn: str
    ip: str
    servers: list[str]
    forward: list[str] = Field(default_factory=list, description="A records for the FQDN")
    reverse: list[str] = Field(default_factory=list, description="PTR names for the IP")
    forward_ok: bool = False
    reverse_ok: bool = False
    ok: bool = False
    problems: list[str] = Field(default_factory=list)


class DnsLookup(Protocol):
    async def forward(self, name: str, servers: list[str]) -> list[str]: ...
    async def reverse(self, ip: str, servers: list[str]) -> list[str]: ...


class LiveDns:
    """dnspython, asking exactly the given servers (no system resolver, no search domains)."""

    async def forward(self, name: str, servers: list[str]) -> list[str]:
        return await asyncio.to_thread(self._query, name, "A", servers)

    async def reverse(self, ip: str, servers: list[str]) -> list[str]:
        import dns.reversename

        return await asyncio.to_thread(
            self._query, dns.reversename.from_address(ip).to_text(), "PTR", servers
        )

    @staticmethod
    def _query(name: str, rdtype: str, servers: list[str]) -> list[str]:
        import dns.exception
        import dns.resolver

        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = servers
        resolver.lifetime = 5.0
        try:
            answer = resolver.resolve(name, rdtype, search=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except dns.exception.DNSException as exc:
            raise DnsServerError(
                f"No answer from {', '.join(servers)} for {name} ({type(exc).__name__})"
            ) from exc
        return [r.to_text().rstrip(".") for r in answer]


class StaticDns:
    """For the simulator and tests: FQDN -> IPv4, with the reverse records derived from it."""

    def __init__(self, records: dict[str, str]) -> None:
        self.records = {k.lower().rstrip("."): v for k, v in records.items()}

    async def forward(self, name: str, servers: list[str]) -> list[str]:
        ip = self.records.get(name.lower().rstrip("."))
        return [ip] if ip else []

    async def reverse(self, ip: str, servers: list[str]) -> list[str]:
        return [name for name, value in self.records.items() if value == ip]


class DnsServerError(RuntimeError):
    error_type = "dns_unreachable"


async def check(lookup: DnsLookup, fqdn: str, ip: str, servers: list[str]) -> DnsCheck:
    """Both directions must agree with what the server will be given: A(fqdn) = ip and PTR(ip) = fqdn."""
    ipaddress.IPv4Address(ip)
    forward = await lookup.forward(fqdn, servers)
    reverse = await lookup.reverse(ip, servers)
    result = DnsCheck(fqdn=fqdn, ip=ip, servers=servers, forward=forward, reverse=reverse)
    result.forward_ok = forward == [ip]
    result.reverse_ok = any(name.lower() == fqdn.lower() for name in reverse)
    if not forward:
        result.problems.append(f"{fqdn} has no A record")
    elif not result.forward_ok:
        result.problems.append(f"{fqdn} resolves to {', '.join(forward)}, not {ip}")
    if not reverse:
        result.problems.append(f"{ip} has no PTR record")
    elif not result.reverse_ok:
        result.problems.append(f"{ip} points back to {', '.join(reverse)}, not {fqdn}")
    result.ok = result.forward_ok and result.reverse_ok
    return result
