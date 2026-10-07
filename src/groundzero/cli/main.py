"""`groundzero` command line: runs the API server and acts as a thin client of it.

Everything except `serve`, `token` and `dev` goes through the REST API — the CLI has no privileged path.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
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


def _print_version(value: bool) -> None:
    if value:
        from groundzero import __version__

        console.print(f"GroundZero {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_print_version, is_eager=True, help="Show the version, then exit"),
    ] = False,
) -> None:
    """GroundZero: bare metal → ESXi → VMware Holodeck."""


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


def _call_optional(method: str, path: str) -> Any:
    """Like _call, but a 404 returns None instead of exiting."""
    try:
        with _client() as client:
            resp = client.request(method, path)
    except httpx.ConnectError:
        return None
    return resp.json() if resp.status_code == 200 else None


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
    detach: Annotated[
        bool,
        typer.Option(
            help="Run in the background (survives closing the terminal); stop with `groundzero stop`"
        ),
    ] = False,
) -> None:
    """Run the GroundZero API (localhost) and the HTTPS media endpoint BMCs install from."""
    settings = Settings()
    if host:
        settings.bind_host = host
    if port:
        settings.port = port
    if detach:
        _serve_detached(settings, host, port)
        return
    asyncio.run(_serve(settings))


def _pid_file(settings: Settings) -> Path:
    return settings.home / "serve.pid"


def _running_pid(settings: Settings) -> int | None:
    """The detached server's pid, if it is still running (a stale pid file is removed)."""
    path = _pid_file(settings)
    try:
        pid = int(path.read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return None
    return pid


def _serve_detached(settings: Settings, host: str | None, port: int | None) -> None:
    settings.ensure_home()
    if pid := _running_pid(settings):
        _fail(f"GroundZero is already running in the background (pid {pid}); `groundzero stop` first")
    args = [sys.executable, "-c", "from groundzero.cli.main import app; app()", "serve"]
    args += [*(["--host", host] if host else []), *(["--port", str(port)] if port else [])]
    log = settings.home / "serve.log"
    with log.open("ab") as out:
        proc = subprocess.Popen(
            args, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True
        )
    _pid_file(settings).write_text(str(proc.pid))
    url = f"http://{settings.bind_host}:{settings.port}"
    for _ in range(100):  # wait until the API answers, so the next command works
        if proc.poll() is not None:
            _pid_file(settings).unlink(missing_ok=True)
            _fail(f"GroundZero exited at startup; see {log}")
        try:
            httpx.get(f"{url}/healthz", timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.2)
    console.print(f"GroundZero running in the background (pid {proc.pid}) at {url}; log: {log}")


@app.command()
def stop() -> None:
    """Stop the GroundZero server started with `serve --detach`."""
    settings = Settings()
    pid = _running_pid(settings)
    if pid is None:
        _fail("No background GroundZero server is running")
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.1)
    else:
        _fail(f"GroundZero (pid {pid}) did not stop; it may still be finishing a job")
    _pid_file(settings).unlink(missing_ok=True)
    console.print(f"Stopped GroundZero (pid {pid})")


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


@app.command()
def ui() -> None:
    """Open the web UI in your browser, signed in (the token travels in the URL fragment only)."""
    import webbrowser

    settings = Settings()
    url = os.environ.get("GROUNDZERO_URL", f"http://{settings.bind_host}:{settings.port}")
    webbrowser.open(f"{url}/#token={settings.resolve_api_token()}")
    console.print(f"Opened {url}")


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


@hosts_app.command("certs")
def hosts_certs(host: str) -> None:
    """Show the pinned BMC/OS certificates (credentials are only ever sent to these)."""
    h = _resolve_host(host)
    table = Table("Role", "Address", "SHA-256 fingerprint", "Pinned")
    for c in _call("GET", f"/hosts/{h['id']}/certificates"):
        table.add_row(*(Text(v) for v in (c["role"], c["address"], c["fingerprint"], c["pinned_at"][:19])))
    console.print(table)


@hosts_app.command("trust")
def hosts_trust(
    host: str,
    role: Annotated[str, typer.Argument(help="bmc or os")],
    yes: Annotated[bool, typer.Option("--yes", help="Skip the confirmation")] = False,
) -> None:
    """Re-trust the certificate a BMC/OS presents now. Only after a legitimate change (reinstall, renewal)."""
    h = _resolve_host(host)
    if not yes:
        typer.confirm(f"Replace the pinned {role} certificate for {h['name']}?", abort=True)
    c = _call("POST", f"/hosts/{h['id']}/certificates/{role}/trust")
    console.print(f"Pinned {escape(c['address'])}: {c['fingerprint']}")


# ── pipeline and tasks ───────────────────────────────────────────────────
_STATE_STYLE = {"done": "green", "not_needed": "green", "running": "cyan", "failed": "red", "stale": "yellow",
                "blocked": "magenta", "ready": "white", "planned": "dim"}  # fmt: skip


@app.command()
def pipeline(host: str) -> None:
    """Where a host is on the way from bare metal to Holodeck, and the recommended next step."""
    h = _resolve_host(host)
    p = _call("GET", f"/hosts/{h['id']}/pipeline")
    table = Table("Stage", "Task", "State", "Output / needs")
    for stage in p["stages"]:
        for i, t in enumerate(stage["tasks"]):
            detail = (t["output"]["summary"] if t["output"]
                      else t.get("not_needed") or "; ".join(t["blocked_by"]))  # fmt: skip
            table.add_row(
                Text(stage["title"] if i == 0 else ""), Text(t["id"]),
                Text(t["state"], style=_STATE_STYLE.get(t["state"], "")), Text(detail or ""),
            )  # fmt: skip
    console.print(table)
    nxt = p["next"]
    hint = f"  →  groundzero run {h['name']} {nxt['task']}" if nxt["task"] else ""
    console.print(Text(f"Next: {nxt['title']}. {nxt['reason']}{hint}"))


@app.command("run")
def run_task(
    host: str,
    task: Annotated[str, typer.Argument(help="Task id from `groundzero pipeline` (e.g. preflight, os.read)")],
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="Task parameter KEY=VALUE (repeatable; VALUE may be JSON)"),
    ] = None,
    confirm: Annotated[str | None, typer.Option(help="Typed confirmation for destructive tasks")] = None,
    wait: Annotated[bool, typer.Option(help="Follow the job until it finishes")] = True,
) -> None:
    """Run one pipeline task on a host. Parameters are listed per task by GET /tasks (params_schema)."""
    h = _resolve_host(host)
    body: dict[str, Any] = {"params": _parse_params(param or [])}
    if confirm is not None:
        body["confirm"] = confirm
    job = _call("POST", f"/hosts/{h['id']}/tasks/{task}", json=body)
    console.print(f"Started {task} as job {job['id']}")
    if wait:
        job = _wait(job)
        for step in job.get("steps", []):
            console.print(Text(f"  {step['status']:<9} {step['title']}"))


def _parse_params(pairs: list[str]) -> dict[str, Any]:
    """KEY=VALUE pairs; VALUE is parsed as JSON when it is valid JSON (numbers, booleans, lists)."""
    params: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            _fail(f"--param must be KEY=VALUE, got {pair!r}")
        try:
            params[key] = json.loads(value)
        except ValueError:
            params[key] = value
    return params


def _start_task(
    host_id: str, task: str, params: dict[str, Any] | None = None, confirm: str | None = None
) -> Any:
    body: dict[str, Any] = {"params": params or {}}
    if confirm is not None:
        body["confirm"] = confirm
    return _call("POST", f"/hosts/{host_id}/tasks/{task}", json=body)


# ── inventory / preflight ────────────────────────────────────────────────
@app.command()
def inventory(
    host: str, wait: Annotated[bool, typer.Option(help="Wait and print the result")] = True
) -> None:
    """Collect hardware inventory from a host's BMC (read-only)."""
    h = _resolve_host(host)
    job = _start_task(h["id"], "discover")
    if not wait:
        console.print(f"Started job {job['id']}")
        return
    _wait(job)
    inv = _call("GET", f"/hosts/{h['id']}/outputs/inventory")
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
    job = _start_task(h["id"], "preflight", {"profile": profile, "variant": variant})
    if not wait:
        console.print(f"Started job {job['id']}")
        return
    _wait(job)
    report = _call("GET", f"/hosts/{h['id']}/outputs/preflight")
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
    _wait(_start_task(h["id"], "os.read"))
    _print_os_network(_call("GET", f"/hosts/{h['id']}/outputs/os_network"))


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


# ── install ──────────────────────────────────────────────────────────────
@app.command()
def install(
    host: str,
    iso: Annotated[
        str, typer.Option(help="Stock ISO: repository id or filename (see `images list`), or a path")
    ],
    config: Annotated[
        str | None, typer.Option(help="Config set name or id (default: capture from the running OS)")
    ] = None,
    hostname: Annotated[str | None, typer.Option(help="Per-server hostname (with --config)")] = None,
    ip: Annotated[str | None, typer.Option(help="Per-server management IP (with --config)")] = None,
    ntp: Annotated[list[str] | None, typer.Option(help="NTP server (repeatable; without --config)")] = None,
    wipe_install_disk_vmfs: Annotated[
        bool, typer.Option(help="Overwrite the install disk's VMFS (without --config; default: preserve)")
    ] = False,
    allow_legacy_cpu: Annotated[
        bool | None, typer.Option(help="Force the CPU override on/off (without --config)")
    ] = None,
    confirm: Annotated[
        str | None, typer.Option(help='Non-interactive confirmation: "install <host name>"')
    ] = None,
    timeout_minutes: Annotated[
        int, typer.Option(help="Give up if the new build is not up after this long (10-240)")
    ] = 90,
) -> None:
    """Install ESXi on a host via its BMC (DESTRUCTIVE for the boot disk's system partitions)."""
    h = _resolve_host(host)
    body: dict[str, Any] = {"timeout_minutes": timeout_minutes}
    if Path(iso).is_file():
        body["iso_path"] = str(Path(iso).resolve())
    else:
        body["iso_id"] = _resolve_iso(iso)["id"]
    if config:
        body["config_set_id"] = _resolve_config_set(config)["id"]
        if hostname or ip:
            stored = _call_optional("GET", f"/hosts/{h['id']}/host-values/esxi") or {}
            body["host_values"] = {**stored, **{k: v for k, v in (("hostname", hostname), ("ip", ip)) if v}}
    else:
        body.update({"wipe_install_disk_vmfs": wipe_install_disk_vmfs, "allow_legacy_cpu": allow_legacy_cpu})
        if ntp:
            body["ntp_servers"] = ntp
    expected = f"install {h['name']}"
    if confirm is None:
        preview_body = {**body, "confirm": "-"}
        if config:
            preview = _call("POST", f"/hosts/{h['id']}/install/preview", json=preview_body)
            console.print(Text(preview["kickstart"]), style="dim")
            for note in preview["notes"]:
                console.print(Text(f"note: {note}"), style="dim")
        console.print(Text(f"This installs ESXi on {h['name']} (BMC {h['bmc_address']})."), style="yellow")
        confirm = typer.prompt(f'Type "{expected}" to continue')
    job = _start_task(h["id"], "os.custom" if config else "os.reimage", body, confirm)
    console.print(f"Install job {job['id']} started")
    try:
        _wait(job)
    finally:
        report = _call_optional("GET", f"/hosts/{h['id']}/outputs/install")
        if report:
            _print_install(report)


def _resolve_iso(ref: str) -> dict[str, Any]:
    isos: list[dict[str, Any]] = _call("GET", "/images") or _call("POST", "/images/rescan")
    for image in isos:
        if ref in (image["id"], image["filename"]):
            return image
    _fail(f"no image matches '{ref}' in the repository (run `groundzero images list` to rescan)")


def _resolve_config_set(ref: str) -> dict[str, Any]:
    for cs in _call("GET", "/config-sets"):
        if ref in (cs["id"], cs["name"]):
            return dict(cs)
    _fail(f"no config set matches '{ref}'")


# ── config sets & ISO repository ─────────────────────────────────────────
config_app = typer.Typer(help="Config sets: shared OS settings applied at install.", no_args_is_help=True)
images_app = typer.Typer(
    help="Stock installer ISOs and appliance OVAs in the repository folder.", no_args_is_help=True
)
app.add_typer(config_app, name="config")
app.add_typer(images_app, name="images")


@config_app.command("list")
def config_list() -> None:
    table = Table("Name", "OS", "Source", "Password", "Updated")
    for cs in _call("GET", "/config-sets"):
        cells = (
            cs["name"],
            cs["os_family"],
            cs["source"],
            "set" if cs["has_root_password"] else "-",
            cs["updated_at"][:16],
        )
        table.add_row(*(Text(c) for c in cells))
    console.print(table)


@config_app.command("show")
def config_show(name: str) -> None:
    console.print_json(data=_resolve_config_set(name))


@config_app.command("capture")
def config_capture(host: str, name: Annotated[str, typer.Option(help="Name for the new config set")]) -> None:
    """Create a config set (and the host's per-server values) from its running OS. Read-only."""
    h = _resolve_host(host)
    job = _wait(_start_task(h["id"], "os.capture", {"name": name}))
    console.print(f"Captured config set {escape(name)} ({job['result']['config_set_id']})")


@config_app.command("delete")
def config_delete(name: str) -> None:
    cs = _resolve_config_set(name)
    _call("DELETE", f"/config-sets/{cs['id']}")
    console.print(f"Deleted config set {escape(cs['name'])}")


@app.command("hwreport", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def hwreport(ctx: typer.Context) -> None:
    """A hardware report straight from BMCs, no server needed (the same as gz-hwreport; try --help there).

    groundzero hwreport 192.0.2.5 192.0.2.6 -o reports
    """
    from groundzero.hwreport import main as hwreport_main

    raise typer.Exit(hwreport_main(list(ctx.args)))


# ── BIOS profiles ────────────────────────────────────────────────────────
bios_app = typer.Typer(
    help="BIOS profiles: saved BIOS settings that Configure BIOS applies.", no_args_is_help=True
)
app.add_typer(bios_app, name="bios-profile")


def _resolve_bios_profile(ref: str) -> dict[str, Any]:
    for profile in _call("GET", "/bios-profiles"):
        if ref in (profile["id"], profile["name"]):
            return dict(profile)
    _fail(f"no BIOS profile matches '{ref}' (see `groundzero bios-profile list`)")


def _settings(profile: dict[str, Any]) -> str:
    n = len(profile["attributes"])
    return f"{n} setting{'' if n == 1 else 's'}"


@bios_app.command("list")
def bios_list() -> None:
    table = Table("Name", "Model", "Settings", "Source", "Updated")
    for p in _call("GET", "/bios-profiles"):
        cells = (p["name"], p["model"] or "-", str(len(p["attributes"])), p["source"], p["updated_at"][:16])
        table.add_row(*(Text(c) for c in cells))
    console.print(table)


@bios_app.command("show")
def bios_show(name: str) -> None:
    console.print_json(data=_resolve_bios_profile(name))


@bios_app.command("capture")
def bios_capture(
    host: str,
    name: Annotated[str, typer.Option(help="Name for the new profile")],
    keep: Annotated[list[str] | None, typer.Option(help="Only these attributes (repeatable)")] = None,
) -> None:
    """A profile from the server's current BIOS settings (its latest inventory; run discover first)."""
    h = _resolve_host(host)
    profile = _call(
        "POST", f"/hosts/{h['id']}/bios-profiles/capture", json={"name": name, "attributes": keep}
    )
    console.print(f"Captured {_settings(profile)} from {escape(h['name'])} as {escape(name)}")


@bios_app.command("import")
def bios_import(
    file: Annotated[
        Path, typer.Argument(help="JSON: {attribute: value}, or a Dell Server Configuration Profile")
    ],
    name: Annotated[str, typer.Option(help="Name for the new profile")],
    host: Annotated[str, typer.Option(help="A server whose BIOS the file is checked against")],
) -> None:
    h = _resolve_host(host)
    registry = _call("GET", f"/hosts/{h['id']}/bios-registry")
    body = {"name": name, "registry": registry["key"], "content": file.read_text()}
    profile = _call("POST", "/bios-profiles/import", json=body)
    console.print(f"Imported {_settings(profile)} as {escape(name)}")


@bios_app.command("delete")
def bios_delete(name: str) -> None:
    profile = _resolve_bios_profile(name)
    _call("DELETE", f"/bios-profiles/{profile['id']}")
    console.print(f"Deleted BIOS profile {escape(profile['name'])}")


# ── storage profiles ─────────────────────────────────────────────────────
storage_app = typer.Typer(
    help="Storage profiles: RAID volumes, controller mode, drive state, hot spares.", no_args_is_help=True
)
app.add_typer(storage_app, name="storage-profile")


def _resolve_storage_profile(ref: str) -> dict[str, Any]:
    for profile in _call("GET", "/storage-profiles"):
        if ref in (profile["id"], profile["name"]):
            return dict(profile)
    _fail(f"no storage profile matches '{ref}' (see `groundzero storage-profile list`)")


@storage_app.command("list")
def storage_list() -> None:
    table = Table("Name", "Controllers", "Source", "Updated")
    for p in _call("GET", "/storage-profiles"):
        rules = "; ".join(
            f"{c['kind']}: " + (", ".join(f"{v['name']} {v['raid']}" for v in c["volumes"]) or "as is")
            for c in p["controllers"]
        )
        table.add_row(Text(p["name"]), Text(rules), Text(p["source"]), Text(p["updated_at"][:16]))
    console.print(table)


@storage_app.command("show")
def storage_show(name: str) -> None:
    console.print_json(data=_resolve_storage_profile(name))


@storage_app.command("save")
def storage_save(file: Annotated[Path, typer.Argument(help='JSON: {"name", "controllers": [...]}')]) -> None:
    """Create a storage profile from a JSON file, or replace the one of the same name."""
    body = json.loads(file.read_text())
    existing = next((p for p in _call("GET", "/storage-profiles") if p["name"] == body.get("name")), None)
    if existing:
        profile = _call("PUT", f"/storage-profiles/{existing['id']}", json=body)
    else:
        profile = _call("POST", "/storage-profiles", json=body)
    console.print(f"{'Updated' if existing else 'Created'} storage profile {escape(profile['name'])}")


@storage_app.command("capture")
def storage_capture(host: str, name: Annotated[str, typer.Option(help="Name for the new profile")]) -> None:
    """A profile describing the server's layout as Read storage last saw it."""
    h = _resolve_host(host)
    profile = _call("POST", f"/hosts/{h['id']}/storage-profiles/capture", json={"name": name})
    console.print(f"Saved {escape(profile['name'])} from {escape(h['name'])}")


@storage_app.command("plan")
def storage_plan(
    host: str,
    profile: str,
    allow_boot_volume: Annotated[bool, typer.Option(help="Allow changes to the boot volume")] = False,
) -> None:
    """What applying the profile would change on the server (nothing is read or changed)."""
    h = _resolve_host(host)
    p = _resolve_storage_profile(profile)
    plan = _call(
        "GET",
        f"/hosts/{h['id']}/storage-plan",
        params={"profile_id": p["id"], "allow_boot_volume": allow_boot_volume},
    )
    for problem in plan["problems"]:
        console.print(f"Can't go ahead: {problem}", style="red")
    for action in plan["actions"]:
        console.print(action["title"], style="red" if action["destroys_data"] else "")
    if not plan["actions"] and not plan["problems"]:
        console.print("Already matches: nothing to change")


@storage_app.command("delete")
def storage_delete(name: str) -> None:
    profile = _resolve_storage_profile(name)
    _call("DELETE", f"/storage-profiles/{profile['id']}")
    console.print(f"Deleted storage profile {escape(profile['name'])}")


# ── specs: the jobs picked for a server or a cluster, run as one ─────────
spec_app = typer.Typer(help="Specs: the jobs you pick for a server or cluster.", no_args_is_help=True)
app.add_typer(spec_app, name="spec")
_STEP_STYLE = {"succeeded": "green", "skipped": "dim", "failed": "red", "cancelled": "yellow",
               "running": "cyan", "pending": "white", "run": "white", "skip": "dim",
               "blocked": "red"}  # fmt: skip


def _resolve_spec(ref: str) -> dict[str, Any]:
    for spec in _call("GET", "/specs"):
        if ref in (spec["id"], spec["name"]):
            return dict(spec)
    _fail(f"no spec matches '{ref}' (see `groundzero spec list`)")


def _resolve_cluster(ref: str) -> dict[str, Any]:
    for cluster in _call("GET", "/clusters"):
        if ref in (cluster["id"], cluster["name"]):
            return dict(cluster)
    _fail(f"no cluster matches '{ref}'")


@spec_app.command("list")
def spec_list() -> None:
    table = Table("Name", "Steps", "Updated")
    for spec in _call("GET", "/specs"):
        table.add_row(Text(spec["name"]), Text(" → ".join(s["task"] for s in spec["steps"])),
                      Text(spec["updated_at"][:16]))  # fmt: skip
    console.print(table)


@spec_app.command("show")
def spec_show(name: str) -> None:
    console.print_json(data=_resolve_spec(name))


@spec_app.command("save")
def spec_save(
    file: Annotated[
        Path, typer.Argument(help='JSON: {"name", "description", "steps": [{"task", "params"}]}')
    ],
) -> None:
    """Create a spec from a JSON file, or replace the spec of the same name."""
    body = json.loads(file.read_text())
    existing = next((s for s in _call("GET", "/specs") if s["name"] == body.get("name")), None)
    spec = (
        _call("PUT", f"/specs/{existing['id']}", json=body)
        if existing
        else _call("POST", "/specs", json=body)
    )
    console.print(f"{'Updated' if existing else 'Created'} spec {escape(spec['name'])}: "
                  + " → ".join(s["task"] for s in spec["steps"]))  # fmt: skip


@spec_app.command("delete")
def spec_delete(name: str) -> None:
    spec = _resolve_spec(name)
    _call("DELETE", f"/specs/{spec['id']}")
    console.print(f"Deleted spec {escape(spec['name'])}")


@spec_app.command("assign")
def spec_assign(
    host: str,
    spec: Annotated[str | None, typer.Argument(help="Spec name; leave out with --clear")] = None,
    clear: Annotated[bool, typer.Option(help="Drop the server's own spec (its cluster's applies)")] = False,
) -> None:
    """Give a server its own spec. It overrides the spec of the cluster it's in."""
    if (spec is None) != clear:
        _fail("give a spec name, or --clear")
    h = _resolve_host(host)
    spec_id = None if clear else _resolve_spec(spec or "")["id"]
    effective = _call("PUT", f"/hosts/{h['id']}/spec", json={"spec_id": spec_id})
    if effective:
        console.print(
            f"{escape(h['name'])} runs {escape(effective['spec']['name'])} (from its {effective['source']})"
        )
    else:
        console.print(f"{escape(h['name'])} has no spec")


def _print_preview(preview: dict[str, Any]) -> None:
    table = Table("Step", "Action", "Why")
    for step in preview["steps"]:
        action = step["action"] + (" (changes the server)" if step["destructive"] else "")
        table.add_row(Text(step["task"]), Text(action, style=_STEP_STYLE.get(step["action"], "")),
                      Text(step["reason"] or ""))  # fmt: skip
    console.print(
        f"{escape(preview['host_name'])}: {escape(preview['spec_name'])} (from its {preview['source']})"
    )
    console.print(table)


def _follow_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str], str] = {}
    while True:
        runs = [_call("GET", f"/runs/{r['id']}") for r in runs]
        for run in runs:
            for step in run["steps"]:
                key = (run["id"], step["task"])
                if seen.get(key) != step["status"] and step["status"] != "pending":
                    seen[key] = step["status"]
                    console.print(Text(f"{run['host_name']}: {step['task']} {step['status']}"
                                       + (f" ({step['reason']})" if step["reason"] else ""),
                                       style=_STEP_STYLE.get(step["status"], "")))  # fmt: skip
        if all(r["status"] != "running" for r in runs):
            return runs
        time.sleep(1)


@app.command("run-spec")
def run_spec(
    host: Annotated[str | None, typer.Argument(help="Server to run its spec on")] = None,
    cluster: Annotated[str | None, typer.Option(help="Run every member of this cluster at once")] = None,
    confirm: Annotated[
        str | None, typer.Option(help="The phrase the preview shows; approves every step")
    ] = None,
    wait: Annotated[bool, typer.Option(help="Follow the run until it finishes")] = True,
) -> None:
    """Run a server's spec (or every member of a cluster). Without --confirm it only shows what would run."""
    if (host is None) == (cluster is None):
        _fail("give a server, or --cluster")
    if cluster is not None:
        c = _resolve_cluster(cluster)
        preview = _call("GET", f"/clusters/{c['id']}/runs/preview")
        for p in preview["hosts"]:
            _print_preview(p)
        if preview["without_spec"]:
            console.print(f"No spec, not run: {', '.join(preview['without_spec'])}", style="yellow")
        path = f"/clusters/{c['id']}/runs"
    else:
        h = _resolve_host(host or "")
        preview = _call("GET", f"/hosts/{h['id']}/runs/preview")
        _print_preview(preview)
        path = f"/hosts/{h['id']}/runs"
    if confirm is None:
        console.print(f'Start it with --confirm "{preview["phrase"]}"')
        raise typer.Exit(1)
    started = _call("POST", path, json={"confirm": confirm})
    runs = started if isinstance(started, list) else [started]
    console.print(f"Started {len(runs)} run(s): {', '.join(r['id'] for r in runs)}")
    if not wait:
        return
    finished = _follow_runs(runs)
    failed = [r for r in finished if r["status"] != "succeeded"]
    for run in failed:
        console.print(f"{run['host_name']}: {run['status']}: {run['error'] or ''}", style="red")
    if failed:
        raise typer.Exit(2)
    console.print(f"Done: {len(finished)} run(s) succeeded")


@images_app.command("show")
def images_show(
    image: Annotated[str, typer.Argument(help="Image id or filename (see `images list`)")],
) -> None:
    """What an OVA is and every input (OVF property) it takes."""
    found = _resolve_iso(image)
    info = _call("GET", f"/images/{found['id']}/descriptor")
    d = info["descriptor"]
    size = " · ".join(
        x
        for x in (
            f"{d['cpus']} vCPU" if d["cpus"] else "",
            f"{d['memory_mb'] / 1024:g} GB RAM" if d["memory_mb"] else "",
        )
        if x
    )
    console.print(Text(f"{d['product'] or found['filename']} {d['version'] or ''}  {size}", style="bold"))
    console.print(Text("Networks: " + (", ".join(n["name"] for n in d["networks"]) or "-")))
    table = Table("Input (guest key)", "Type", "Label", "Default", "Set by you")
    for p in d["properties"]:
        kind = (
            p["type"]
            + (" (password)" if p["password"] else "")
            + (f" {p['choices']}" if p["choices"] else "")
        )
        default = "" if p["password"] else (p["default"] or "")
        table.add_row(
            *(
                Text(c)
                for c in (
                    p["qualified_key"],
                    kind,
                    p["label"] or "",
                    default,
                    "yes" if p["user_configurable"] else "no",
                )
            )
        )
    console.print(table)


@images_app.command("list")
def images_list(rescan: Annotated[bool, typer.Option(help="Rescan the folder first")] = True) -> None:
    """ISOs and OVAs in the repository folder."""
    isos = _call("POST", "/images/rescan") if rescan else _call("GET", "/images")
    table = Table("ID", "File", "Kind", "Product / OS", "Version", "Build", "Size")
    for i in isos:
        cells = (
            i["id"],
            i["filename"],
            i["kind"],
            i.get("product") or i["os_family"] or "?",
            i["version"] or "-",
            i["build"] or "-",
            f"{i['size'] / 2**20:.0f} MiB",
        )
        table.add_row(*(Text(c) for c in cells))
    console.print(table)


def _print_install(report: dict[str, Any]) -> None:
    console.print(
        Text(
            f"ESXi {report['iso_version']} build {report['iso_build']} on {report['host']} "
            f"(was {report['previous_build'] or '?'}); media read {report['media_bytes_served'] // 2**20} MiB"
        )
    )
    table = Table("Check", "OK", "Expected", "Observed")
    for c in report["validation"]:
        table.add_row(
            Text(c["name"]), "yes" if c["ok"] else "[red]NO[/red]", Text(c["expected"]), Text(c["observed"])
        )
    if report["validation"]:
        console.print(table)
    audit = report.get("bmc_audit") or {}
    console.print(Text(f"BMC writes: {', '.join(audit.get('non_get', [])) or 'none'}"), style="dim")


# ── jobs ─────────────────────────────────────────────────────────────────
@jobs_app.command("list")
def jobs_list(limit: int = 20) -> None:
    table = Table("ID", "Task", "Host", "Status", "Progress", "Created")
    for j in _call("GET", "/jobs", params={"limit": limit}):
        table.add_row(
            j["id"], j["task"], j["host_id"], j["status"], f"{j['progress'] * 100:.0f}%", j["created_at"]
        )
    console.print(table)


@jobs_app.command("show")
def jobs_show(job_id: str) -> None:
    console.print_json(data=_call("GET", f"/jobs/{job_id}"))


@jobs_app.command("diag")
def jobs_diag(
    job_id: str,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write to this file instead of stdout")
    ] = None,
) -> None:
    """Redacted diagnostics bundle for a job (attach it to a bug report): steps, BMC identity, every
    Redfish/ESXi exchange. Passwords and tokens are removed."""
    bundle = _call("GET", f"/jobs/{job_id}/diagnostics")
    text = json.dumps(bundle, indent=2)
    if out is None:
        sys.stdout.write(text + "\n")
    else:
        out.write_text(text + "\n")
        console.print(f"Wrote {len(bundle.get('events', []))} events to {escape(str(out))}")


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
    from groundzero.redfish.bios_registry import fetch_registry
    from groundzero.redfish.capture import Recorder
    from groundzero.redfish.client import RedfishClient
    from groundzero.redfish.detect import detect
    from groundzero.redfish.storage import read_storage_layout

    user, password = _bmc_credentials(user)
    recorder = Recorder()

    async def run() -> list[tuple[str, str, int | None]]:
        client = RedfishClient(bmc, user, password, verify_tls=verify_tls, on_response=recorder)
        async with client:
            await collect_inventory(client, lambda _f, msg: console.print(msg, style="dim"))
            console.print("Reading the storage layout", style="dim")
            identity = await detect(client)
            await read_storage_layout(client, identity.system_path, dell=identity.vendor.value == "dell")
            console.print("Reading the BIOS attribute registry", style="dim")
            system = await client.get_json(identity.system_path)
            bios_path = (system.get("Bios") or {}).get("@odata.id") or f"{identity.system_path}/Bios"
            await fetch_registry(client, await client.get_json(bios_path))
        return [(r.method, r.path, r.status) for r in client.request_log]

    log = asyncio.run(run())
    count = recorder.write(out)
    non_get = [r for r in log if r[0] != "GET"]
    console.print(f"Wrote {count} sanitized responses to {out}")
    console.print(f"Requests: {len(log)} total; non-GET: {non_get or 'none'}")
