"""Verify DNS: the records a server will need exist on the DNS servers it will use, before it is installed."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.dnscheck import DnsCheck, check
from groundzero.modules.base import Deps, Inputs, Module, Prepared, Stage
from groundzero.osconfig import OsConfigError
from groundzero.osconfig.esxi import EsxiHostValues, EsxiPlugin, EsxiSettings


class DnsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str | None = Field(default=None, description="DNS domain; default: the host's cluster's")
    servers: list[str] | None = Field(
        default=None, description="DNS servers; default: the cluster's config set's"
    )


def dns_target(deps: Deps, host: Host, params: DnsParams) -> tuple[str, str, list[str]]:
    """(FQDN, IP, DNS servers) for this server: from its cluster, or given."""
    values = deps.store.get_host_values(host.id, EsxiPlugin.family)
    if values is None:
        raise OsConfigError(f"{host.name} has no hostname and IP yet: add it to a cluster or set its values")
    hv = EsxiHostValues.model_validate(values)
    cluster = deps.cluster_for_host(host.id)
    domain = params.domain or (cluster.dns_domain if cluster else None)
    servers = params.servers
    if servers is None and cluster is not None:
        servers = EsxiSettings.model_validate(deps.get_config_set(cluster.config_set_id).settings).nameservers
    if not domain or not servers:
        raise OsConfigError(f"{host.name} is not in a cluster: give the DNS domain and servers (params)")
    return f"{hv.hostname}.{domain}", hv.ip, list(servers)


class VerifyDns(Module):
    id = "dns.verify"
    title = "Verify DNS"
    stage = Stage.OS
    description = (
        "Ask the DNS servers the server will use for its forward (A) and reverse (PTR) records, and check "
        "they match its hostname and IP. Clusters can require it to pass before members are installed."
    )
    produces = "dns"
    optional = True
    Params = DnsParams

    def summarize(self, data: dict[str, Any]) -> str:
        if data.get("ok"):
            return f"{data['fqdn']} ↔ {data['ip']} on {', '.join(data.get('servers', []))}"
        return "; ".join(data.get("problems") or ["records do not match"])

    def prepare(
        self, deps: Deps, host: Host, params: DnsParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        fqdn, ip, servers = dns_target(deps, host, params)

        async def run(ctx: JobContext) -> dict[str, Any]:
            async with ctx.step("lookup", f"Look up {fqdn} and {ip}") as step:
                result = await check(deps.dns, fqdn, ip, servers)
                deps.save_output(host.id, "dns", ctx.job.id, result)
                step.message = self.summarize(result.model_dump())
                if not result.ok:
                    raise OsConfigError("DNS is not ready: " + "; ".join(result.problems))
            return {"dns": result.model_dump(mode="json")}

        return Prepared(run, {"fqdn": fqdn, "ip": ip, "servers": servers})


def require_dns(deps: Deps, host: Host, inputs: Inputs, hostname: str, ip: str) -> None:
    """For members of a cluster that requires it: a passing DNS check for exactly this hostname and IP."""
    from groundzero.core.services import ConflictError  # avoid an import cycle

    cluster = deps.cluster_for_host(host.id)
    if cluster is None or not cluster.require_dns:
        return  # the check is an option: only clusters that ask for it gate the install
    fqdn = f"{hostname}.{cluster.dns_domain}"
    result = inputs.get("dns", DnsCheck)
    if result is None or result.fqdn.lower() != fqdn.lower() or result.ip != ip:
        raise ConflictError(
            f"{host.name} is in cluster {cluster.name}: run “Verify DNS” for {fqdn} ({ip}) first"
        )
    if not result.ok:
        raise ConflictError(
            f"DNS is not ready for {fqdn}: {'; '.join(result.problems)}. "
            "Fix the records and run “Verify DNS” again"
        )
