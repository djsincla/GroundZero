"""`groundzero` command line: runs the API server and acts as a thin client of it.

Everything except `serve`, `token` and `dev` goes through the REST API — the CLI has no privileged path.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, NoReturn

import httpx
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from groundzero.core.config import Settings

app = typer.Typer(help="GroundZero: bare metal → ESXi → VMware Holodeck.", no_args_is_help=True)
hosts_app = typer.Typer(help="Manage BMC targets.", no_args_is_help=True)
jobs_app = typer.Typer(help="Inspect and cancel jobs.", no_args_is_help=True)
token_app = typer.Typer(help="API token.", no_args_is_help=True)
dev_app = typer.Typer(help="Developer utilities.", no_args_is_help=True)
os_app = typer.Typer(help="The OS (hypervisor) installed on a host.", no_args_is_help=True)
app.add_typer(hosts_app, name="hosts")
app.add_typer(jobs_app, name="jobs")
app.add_typer(token_app, name="token")
app.add_typer(dev_app, name="dev")
app.add_typer(os_app, name="os")

console = Console()
EXIT_PREFLIGHT_FAILED = 2
_STATUS_STYLE = {"pass": "green", "warn": "yellow", "fail": "red", "unknown": "magenta"}


# ── API client ───────────────────────────────────────────────────────────
def _fail(message: str) -> NoReturn:
    console.print(f"[red]error:[/red] {escape(message)}")
    raise typer.Exit(1)


def _client() -> httpx.Client:
    settings = Settings()
    url = os.environ.get("GROUNDZERO_URL", f"http://{settings.bind_host}:{settings.port}")
    token = settings.resolve_api_token()
    return httpx.Client(base_url=url + "/api/v1", headers={"Authorization": f"Bearer {token}"}, timeout=30)


def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        with _client() as client:
            resp = client.request(method, path, **kwargs)
    except httpx.ConnectError:
        _fail("cannot reach the GroundZero API — is `groundzero serve` running?")
    if resp.status_code >= 400:
        try:
            problem = resp.json()
            _fail(f"{problem.get('title', resp.status_code)}: {problem.get('detail', '')}")
        except ValueError:
            _fail(f"HTTP {resp.status_code}")
    return resp.json() if resp.content else None


def _resolve_host(ref: str) -> dict[str, Any]:
    hosts: list[dict[str, Any]] = _call("GET", "/hosts")
    for host in hosts:
        if ref in (host["id"], host["name"], host["bmc_address"]):
            return host
    _fail(f"no host matches '{ref}' (use id, name or BMC address)")


def _wait(job: dict[str, Any]) -> dict[str, Any]:
    last = ""
    while job["status"] in ("queued", "running"):
        line = f"[{job['progress'] * 100:3.0f}%] {job['message'] or job['status']}"
        if line != last:
            console.print(line, style="dim")
            last = line
        time.sleep(1)
        job = _call("GET", f"/jobs/{job['id']}")
    if job["status"] != "succeeded":
        err = job.get("error") or {}
        _fail(f"job {job['id']} {job['status']}: {err.get('message', '')}")
    return job


def _bmc_credentials(user: str | None) -> tuple[str, str]:
    """BMC credentials from GROUNDZERO_BMC_USERNAME/PASSWORD (env or git-ignored .env), else a prompt."""
    settings = Settings()
    username = user or settings.bmc_username or "root"
    if settings.bmc_password is not None:
        return username, settings.bmc_password.get_secret_value()
    return username, typer.prompt("BMC password", hide_input=True)


def _esxi_credentials(user: str | None) -> tuple[str, str]:
    """ESXi credentials from GROUNDZERO_ESXI_USERNAME/PASSWORD (env or git-ignored .env), else a prompt."""
    settings = Settings()
    username = user or settings.esxi_username or "root"
    if settings.esxi_password is not None:
        return username, settings.esxi_password.get_secret_value()
    return username, typer.prompt("ESXi password", hide_input=True)


# ── server ───────────────────────────────────────────────────────────────
@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="API bind address (default 127.0.0.1)")] = None,
    port: Annotated[int | None, typer.Option(help="API port (default 7182)")] = None,
) -> None:
    """Run the GroundZero API (localhost) and the HTTPS media endpoint BMCs install from."""
    settings = Settings()
    if host:
        settings.bind_host = host
    if port:
        settings.port = port
    asyncio.run(_serve(settings))


async def _serve(settings: Settings) -> None:
    import contextlib
    import socket

    import uvicorn

    from groundzero.api.app import create_app
    from groundzero.media.registry import MediaRegistry
    from groundzero.media.server import create_media_app, ensure_tls_certificate

    class _NoSignals(uvicorn.Server):
        @contextlib.contextmanager
        def capture_signals(self) -> Iterator[None]:  # the API server owns Ctrl-C
            yield

    registry = MediaRegistry()
    api = uvicorn.Server(
        uvicorn.Config(create_app(settings, media=registry), host=settings.bind_host, port=settings.port)
    )
    console.print(f"GroundZero API   http://{settings.bind_host}:{settings.port}  (docs: /docs)")

    media: uvicorn.Server | None = None
    try:
        with socket.socket() as probe:  # fail soft: the API is useful even if the media port is taken
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((settings.media_bind_host, settings.media_port))
    except OSError as exc:
        console.print(f"[yellow]media endpoint disabled: cannot bind :{settings.media_port} ({exc})[/yellow]")
    else:
        settings.ensure_home()
        cert, key = ensure_tls_certificate(settings.home / "tls", [])
        media = _NoSignals(
            uvicorn.Config(
                create_media_app(registry),
                host=settings.media_bind_host,
                port=settings.media_port,
                ssl_certfile=str(cert),
                ssl_keyfile=str(key),
                log_level="warning",
            )
        )
        console.print(f"GroundZero media https://{settings.media_bind_host}:{settings.media_port}/media/...")

    media_task = asyncio.create_task(media.serve()) if media else None
    try:
        await api.serve()
    finally:
        if media and media_task:
            media.should_exit = True
            await media_task


@token_app.command("show")
def token_show() -> None:
    """Print the API bearer token."""
    typer.echo(Settings().resolve_api_token())


# ── hosts ────────────────────────────────────────────────────────────────
@hosts_app.command("add")
def hosts_add(
    bmc: Annotated[str, typer.Option(help="BMC address, e.g. 10.0.0.50")],
    user: Annotated[str | None, typer.Option(help="BMC username (default: .env or root)")] = None,
    name: Annotated[str | None, typer.Option(help="Friendly name")] = None,
    verify_tls: Annotated[bool, typer.Option(help="Verify BMC TLS certificate")] = False,
) -> None:
    """Register a BMC target. Password comes from .env or a prompt, never from argv."""
    user, password = _bmc_credentials(user)
    host = _call(
        "POST",
        "/hosts",
        json={
            "bmc_address": bmc,
            "username": user,
            "password": password,
            "name": name,
            "verify_tls": verify_tls,
        },
    )
    console.print(f"Added host [bold]{escape(host['name'])}[/bold] ({host['id']})")


@hosts_app.command("list")
def hosts_list() -> None:
    """List registered hosts."""
    table = Table("ID", "Name", "BMC", "Vendor", "Model")
    for h in _call("GET", "/hosts"):
        cells = (h["id"], h["name"], h["bmc_address"], h["vendor"] or "-", h["model"] or "-")
        table.add_row(*(Text(v) for v in cells))
    console.print(table)


@hosts_app.command("rm")
def hosts_rm(host: str) -> None:
    """Remove a host and its history."""
    h = _resolve_host(host)
    _call("DELETE", f"/hosts/{h['id']}")
    console.print(f"Removed {escape(h['name'])}")


# ── inventory / preflight ────────────────────────────────────────────────
@app.command()
def inventory(
    host: str, wait: Annotated[bool, typer.Option(help="Wait and print the result")] = True
) -> None:
    """Collect hardware inventory from a host's BMC (read-only)."""
    h = _resolve_host(host)
    job = _call("POST", f"/hosts/{h['id']}/inventory")
    if not wait:
        console.print(f"Started job {job['id']}")
        return
    _wait(job)
    inv = _call("GET", f"/hosts/{h['id']}/inventory")
    console.print_json(data=inv)


@app.command()
def preflight(
    host: str,
    profile: Annotated[str, typer.Option(help="Requirements profile")] = "holodeck-9",
    variant: Annotated[str | None, typer.Option(help="Profile variant, e.g. vcf-9.0-esa-single")] = None,
    wait: Annotated[bool, typer.Option(help="Wait and print the report")] = True,
) -> None:
    """Check a host against Holodeck requirements (read-only). Exit code 2 when the result is FAIL."""
    h = _resolve_host(host)
    job = _call("POST", f"/hosts/{h['id']}/preflight", json={"profile": profile, "variant": variant})
    if not wait:
        console.print(f"Started job {job['id']}")
        return
    _wait(job)
    report = _call("GET", f"/hosts/{h['id']}/preflight")
    _print_report(report, h["name"])
    if report["overall"] == "fail":
        raise typer.Exit(EXIT_PREFLIGHT_FAILED)


def _print_report(report: dict[str, Any], host_name: str) -> None:
    style = _STATUS_STYLE[report["overall"]]
    console.print(
        f"\n[bold]{escape(host_name)}[/bold] vs {escape(report['profile'])} / "
        f"{escape(report['variant_title'])}: "
        f"[{style}]{report['overall'].upper()}[/{style}]"
    )
    table = Table("Status", "Check", "Observed", "Required", "Remediation", show_lines=False)
    for c in report["checks"]:
        s = _STATUS_STYLE[c["status"]]
        # Data cells are Text, not markup: BMC strings like "[protocols n/a]" must print verbatim.
        cells = (c["title"], c["observed"], c["required"], c["remediation"] or "")
        table.add_row(f"[{s}]{c['status']}[/{s}]", *(Text(v) for v in cells))
    console.print(table)
    s = report["summary"]
    console.print(
        f"{s['passed']} passed, {s['warnings']} warnings, {s['failed']} failed, {s['unknown']} unknown"
    )
    console.print(f"Requirements source: {report['source']}", style="dim")


@app.command()
def profiles() -> None:
    """List preflight profiles and variants."""
    for p in _call("GET", "/profiles"):
        console.print(f"[bold]{p['id']}[/bold] — {p['title']} (default: {p['default_variant']})")
        for v in p["variants"]:
            console.print(
                f"  {v['id']:<22} {v['cores']:>3} cores  {v['memory_gb']:>5.0f} GB  {v['disk_tb']} TB"
            )


# ── installed OS ─────────────────────────────────────────────────────────
@os_app.command("set")
def os_set(
    host: str,
    address: Annotated[str, typer.Option(help="OS management address, e.g. ESXi vmk0 IP")],
    user: Annotated[str | None, typer.Option(help="OS username (default: .env or root)")] = None,
    verify_tls: bool = False,
) -> None:
    """Record how to reach the hypervisor currently installed on a host."""
    h = _resolve_host(host)
    user, password = _esxi_credentials(user)
    body = {"address": address, "username": user, "password": password, "verify_tls": verify_tls}
    _call("PUT", f"/hosts/{h['id']}/os", json=body)
    console.print(f"OS access for {escape(h['name'])} set to {escape(address)}")


@os_app.command("network")
def os_network(host: str) -> None:
    """Read the installed hypervisor's network configuration (read-only)."""
    h = _resolve_host(host)
    _wait(_call("POST", f"/hosts/{h['id']}/os/network"))
    _print_os_network(_call("GET", f"/hosts/{h['id']}/os/network"))


def _print_os_network(cfg: dict[str, Any]) -> None:
    console.print(
        Text(f"{cfg['product']} at {cfg['address']} (hostname {cfg['hostname'] or '-'})", style="bold")
    )
    console.print(
        Text(
            f"gateway {cfg['default_gateway'] or '-'}  dns {', '.join(cfg['dns_servers']) or '-'}  "
            f"search {', '.join(cfg['search_domains']) or '-'}  ntp {', '.join(cfg['ntp_servers']) or 'NONE'}"
        )
    )
    vmks = Table("vmk", "IP", "Portgroup", "VLAN", "Active uplinks", "Standby", "MTU", "Services")
    pgs = {p["name"]: p for p in cfg["portgroups"]}
    for v in cfg["vmkernel"]:
        pg = pgs.get(v["portgroup"] or "", {})
        ip = "dhcp" if v["dhcp"] else f"{v['ip']}/{v['netmask']}"
        cells = (
            v["device"],
            ip,
            v["portgroup"] or "-",
            str(pg.get("vlan_id", "-")),
            ", ".join(pg.get("active_uplinks", [])),
            ", ".join(pg.get("standby_uplinks", [])) or "-",
            str(v["mtu"]),
            ", ".join(v["services"]),
        )
        vmks.add_row(*(Text(c) for c in cells))
    console.print(vmks)
    nics = Table("vmnic", "Speed", "Switch", "Port", "Driver", "MAC")
    for n in cfg["physical_nics"]:
        speed = f"{n['speed_mbps']} Mb/s" if n["speed_mbps"] else "down"
        nic_cells = (
            n["device"],
            speed,
            n["switch"] or "-",
            n["switch_port"] or "-",
            n["driver"] or "-",
            n["mac"] or "-",
        )
        nics.add_row(*(Text(c) for c in nic_cells))
    console.print(nics)
    for vs in cfg["vswitches"]:
        console.print(Text(f"{vs['name']}: MTU {vs['mtu']}, uplinks {', '.join(vs['uplinks'])}"))


# ── jobs ─────────────────────────────────────────────────────────────────
@jobs_app.command("list")
def jobs_list(limit: int = 20) -> None:
    table = Table("ID", "Kind", "Host", "Status", "Progress", "Created")
    for j in _call("GET", "/jobs", params={"limit": limit}):
        table.add_row(
            j["id"], j["kind"], j["host_id"], j["status"], f"{j['progress'] * 100:.0f}%", j["created_at"]
        )
    console.print(table)


@jobs_app.command("show")
def jobs_show(job_id: str) -> None:
    console.print_json(data=_call("GET", f"/jobs/{job_id}"))


@jobs_app.command("cancel")
def jobs_cancel(job_id: str) -> None:
    _call("POST", f"/jobs/{job_id}/cancel")
    console.print(f"Cancellation requested for {job_id}")


# ── dev ──────────────────────────────────────────────────────────────────
@dev_app.command("capture-esxi")
def dev_capture_esxi(
    address: Annotated[str, typer.Option(help="ESXi management address")],
    out: Annotated[Path, typer.Option(help="Output JSON, e.g. tests/fixtures/esxi1-network.json")],
    user: Annotated[str | None, typer.Option(help="ESXi username (default: .env or root)")] = None,
) -> None:
    """Record an ESXi network config with IPs/MACs pseudonymized consistently (read-only)."""
    from groundzero.esxi.reader import read_network
    from groundzero.redfish.capture import Pseudonymizer, pseudonymize

    user, password = _esxi_credentials(user)
    config = asyncio.run(read_network(address, user, password))
    clean = pseudonymize(config.model_dump(mode="json"), Pseudonymizer())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n")
    console.print(f"Wrote {out}")


@dev_app.command("capture")
def dev_capture(
    bmc: Annotated[str, typer.Option(help="BMC address")],
    out: Annotated[Path, typer.Option(help="Fixture directory, e.g. tests/fixtures/dell-r740xd")],
    user: Annotated[str | None, typer.Option(help="BMC username (default: .env or root)")] = None,
    verify_tls: bool = False,
) -> None:
    """Record sanitized, read-only Redfish responses for test fixtures (talks to the BMC directly)."""
    from groundzero.inventory.collect import collect_inventory
    from groundzero.redfish.capture import Recorder
    from groundzero.redfish.client import RedfishClient

    user, password = _bmc_credentials(user)
    recorder = Recorder()

    async def run() -> list[tuple[str, str, int | None]]:
        client = RedfishClient(bmc, user, password, verify_tls=verify_tls, on_response=recorder)
        async with client:
            await collect_inventory(client, lambda _f, msg: console.print(msg, style="dim"))
        return [(r.method, r.path, r.status) for r in client.request_log]

    log = asyncio.run(run())
    count = recorder.write(out)
    non_get = [r for r in log if r[0] != "GET"]
    console.print(f"Wrote {count} sanitized responses to {out}")
    console.print(f"Requests: {len(log)} total; non-GET: {non_get or 'none'}")
