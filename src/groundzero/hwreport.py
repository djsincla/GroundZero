"""gz-hwreport: a hardware report straight from a server's BMC. Nothing to set up, nothing stored.

    gz-hwreport 192.0.2.5                     one server: report in ./hwreport-<date>/
    gz-hwreport 192.0.2.5 192.0.2.6 192.0.2.7   several: a report each, plus a page comparing them
    gz-hwreport -f bmcs.txt -o reports       BMCs from a file: "address" or "address username" per line

It reads the BMC over Redfish (GET requests only, plus the session login and logout) with the same
collector GroundZero uses: firmware versions, processors, memory modules, drives, RAID volumes, network
adapters and ports, PCIe devices (storage controllers, HBAs, NICs), power supplies, BIOS and BMC. Each
server gets one self-contained HTML page (opens anywhere, prints to PDF) and a JSON file.

The BMC password comes from GZ_BMC_PASSWORD, or is asked for once. BMC certificates are usually
self-signed, so they aren't checked unless --verify-tls is given.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import html
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from groundzero import __version__
from groundzero.core.reports import Comparison, Configuration, HostReport, compare
from groundzero.inventory.collect import collect_inventory
from groundzero.inventory.models import HostInventory
from groundzero.redfish.client import RedfishClient
from groundzero.redfish.errors import RedfishError
from groundzero.redfish.storage import StorageLayout, read_storage_layout


@dataclass
class Target:
    address: str
    username: str = "root"


@dataclass
class Result:
    target: Target
    name: str = ""
    inventory: HostInventory | None = None
    storage: StorageLayout | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _say(message: str, *, err: bool = False) -> None:
    (sys.stderr if err else sys.stdout).write(message + "\n")


# ── reading ──────────────────────────────────────────────────────────────
async def read_one(target: Target, password: str, *, verify_tls: bool, replay: Path | None) -> Result:
    result = Result(target, name=target.address)
    try:
        transport = None
        if replay is not None:  # a recorded BMC (tests and demos)
            from groundzero.redfish.capture import load_recording, replay_transport

            transport = replay_transport(load_recording(replay))
        client = RedfishClient(
            target.address, target.username, password, verify_tls=verify_tls, transport=transport
        )
        async with client:
            identity, inventory = await collect_inventory(client)
            result.inventory = inventory
            result.storage = await read_storage_layout(
                client, identity.system_path, dell=identity.vendor.value == "dell"
            )
        result.name = inventory.bmc.hostname or target.address
    except (RedfishError, OSError, ValueError) as exc:  # one BMC failing never stops the others
        result.error = f"{type(exc).__name__}: {exc}"
    return result


async def read_all(
    targets: list[Target], password: str, *, verify_tls: bool, parallel: int, replay: Path | None
) -> list[Result]:
    gate = asyncio.Semaphore(parallel)

    async def one(target: Target) -> Result:
        async with gate:
            _say(f"Reading {target.address} …", err=True)
            return await read_one(target, password, verify_tls=verify_tls, replay=replay)

    return list(await asyncio.gather(*(one(t) for t in targets)))


# ── HTML ─────────────────────────────────────────────────────────────────
_CSS = """
:root { --line: #dde1e6; --muted: #5d6570; --warn: #fef3c7; --fail: #b42318; --pass: #067647; }
* { box-sizing: border-box; }
body { font: 14px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif; color: #17191c; margin: 0;
  background: #f5f6f8; }
main { max-width: 1100px; margin: 0 auto; padding: 28px 20px 60px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 15px; margin: 0 0 10px; }
.sub { color: var(--muted); margin: 0 0 20px; }
section { background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px;
  margin: 0 0 14px;
  break-inside: avoid; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: var(--muted); font-weight: 600; padding: 6px 8px;
  border-bottom: 1px solid var(--line); }
td { padding: 6px 8px; border-bottom: 1px solid #eef0f3; vertical-align: top; }
tr:last-child td { border-bottom: 0; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 18px; margin: 0; }
dt { color: var(--muted); } dd { margin: 0; }
.ok { color: var(--pass); } .bad { color: var(--fail); font-weight: 600; }
tr.differs td { background: var(--warn); } tr.differs td:first-child { font-weight: 600; }
.error { color: var(--fail); }
footer { color: var(--muted); font-size: 12px; margin-top: 24px; }
@media print { body { background: #fff; } section { border-color: #ccc; } }
"""


def _e(value: Any) -> str:
    return html.escape("—" if value in (None, "") else str(value))


def _table(headers: list[str], rows: list[list[Any]], mono: tuple[int, ...] = ()) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>"
        + "".join(f"<td{' class=mono' if i in mono else ''}>{_e(c)}</td>" for i, c in enumerate(r))
        + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _section(title: str, content: str, key: str) -> str:
    return f'<section data-section="{key}"><h2>{_e(title)}</h2>{content}</section>' if content else ""


def _health(value: str | None) -> str:
    return value or ""


def _page(title: str, sub: str, body: str) -> str:
    stamp = f"gz-hwreport {__version__} · {datetime.now(UTC):%Y-%m-%d %H:%M} UTC"
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width'>"
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body><main><h1>{_e(title)}</h1>"
        f"<p class=sub>{_e(sub)}</p>{body}<footer>{_e(stamp)} · read-only from the BMC over Redfish</footer>"
        f"</main></body></html>"
    )


def server_html(result: Result) -> str:
    inv = result.inventory
    if inv is None:
        return _page(
            result.name, result.target.address, f"<section><p class=error>{_e(result.error)}</p></section>"
        )
    s = inv.system
    system = (
        "<dl>"
        + "".join(
            f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>"
            for k, v in (
                ("Model", f"{s.manufacturer} {s.model}"),
                ("Service tag", s.service_tag),
                ("Asset tag", s.asset_tag),
                ("BIOS", s.bios_version),
                ("Boot mode", inv.bios.boot_mode),
                ("Virtualization", {True: "on", False: "off"}.get(inv.bios.cpu_virtualization)),  # type: ignore[arg-type]
                (
                    "BMC",
                    " · ".join(x for x in (inv.bmc.vendor, inv.bmc.firmware_version, inv.bmc.hostname) if x),
                ),
                ("BMC address", result.target.address),
                ("Power", s.power_state),
                ("Health", s.health),
            )
            if v
        )
        + "</dl>"
    )
    storage_rows = []
    for c in result.storage.controllers if result.storage else []:
        volumes = ", ".join(f"{v.name or v.id} {v.raid} {v.capacity_gb:g} GB" for v in c.raid_volumes) or "—"
        storage_rows.append([c.model or c.id, c.kind, c.mode, len(c.drives), volumes])
    firmware = sorted(inv.firmware, key=lambda f: f.name)
    parts = [
        _section("System", system, "system"),
        _section(
            "Processors",
            _table(
                ["Socket", "Model", "Cores", "Threads"],
                [[p.socket, p.model, p.cores, p.threads] for p in inv.processors],
            ),
            "processors",
        ),
        _section(
            f"Memory · {inv.memory.total_gib:g} GiB in {inv.memory.dimm_count} DIMMs",
            _table(
                ["Slot", "Size", "Type", "Speed", "Maker", "Part", "Health"],
                [
                    [
                        m.slot or m.id,
                        f"{m.capacity_mib // 1024} GiB",
                        m.type,
                        f"{m.speed_mhz} MHz" if m.speed_mhz else None,
                        m.manufacturer,
                        m.part_number,
                        _health(m.health),
                    ]
                    for m in inv.memory.modules
                ],
                (5,),
            ),
            "memory",
        ),
        _section(
            "Storage controllers and RAID volumes",
            _table(["Controller", "Kind", "Mode", "Drives", "RAID volumes"], storage_rows),
            "storage",
        ),
        _section(
            "Drives",
            _table(
                ["Drive", "Model", "Size", "Type", "Firmware", "Controller"],
                [
                    [
                        d.id.split(":")[0],
                        d.model,
                        f"{d.capacity_bytes / 1e9:.0f} GB",
                        " ".join(x for x in (d.media_type, d.protocol) if x),
                        d.firmware_version,
                        d.controller,
                    ]
                    for d in inv.drives
                ],
                (0, 4),
            ),
            "drives",
        ),
        _section(
            "Network adapters",
            _table(
                ["Adapter", "Maker", "Ports", "Firmware", "Health"],
                [
                    [a.model or a.name, a.manufacturer, a.ports, a.firmware_version, _health(a.health)]
                    for a in inv.network_adapters
                ],
                (3,),
            ),
            "adapters",
        ),
        _section(
            "Network ports",
            _table(
                ["Port", "Link", "Speed"],
                [
                    [n.id, n.link_status, f"{n.speed_mbps / 1000:g} Gb/s" if n.speed_mbps else None]
                    for n in inv.network_ports
                ],
                (0,),
            ),
            "ports",
        ),
        _section(
            "PCIe devices",
            _table(
                ["Device", "Kind", "Maker", "Firmware", "Health"],
                [
                    [x.name, x.device_class, x.manufacturer, x.firmware_version, _health(x.health)]
                    for x in sorted(inv.pcie_devices, key=lambda d: d.device_class or "")
                ],
                (3,),
            ),
            "pcie",
        ),
        _section(
            "Power supplies",
            _table(
                ["Supply", "Model", "Capacity", "Firmware", "Health"],
                [
                    [
                        p.name,
                        p.model,
                        f"{p.capacity_watts:g} W" if p.capacity_watts else None,
                        p.firmware_version,
                        _health(p.health),
                    ]
                    for p in inv.power_supplies
                ],
                (3,),
            ),
            "psu",
        ),
        _section(
            f"Firmware · {len(firmware)} components",
            _table(["Component", "Version"], [[f.name, f.version] for f in firmware], (1,)),
            "firmware",
        ),
    ]
    title = f"{result.name}: hardware report"
    return _page(
        title, f"{s.manufacturer} {s.model} · read {inv.collected_at:%Y-%m-%d %H:%M} UTC", "".join(parts)
    )


def _as_report(result: Result) -> HostReport:
    inv = result.inventory
    model = f"{inv.system.manufacturer} {inv.system.model}" if inv else None
    return HostReport(
        generated_at=datetime.now(UTC),
        host_id=result.target.address,
        name=result.name,
        bmc_address=result.target.address,
        model=model,
        service_tag=inv.system.service_tag if inv else None,
        inventory=inv,
        configuration=Configuration(),
    )


def comparison_html(results: list[Result], files: dict[str, str]) -> str:
    good = [r for r in results if r.inventory is not None]
    names = [r.name for r in good]
    rows: list[Comparison] = compare([_as_report(r) for r in good]) if good else []
    rows = [c for c in rows if any(v is not None for v in c.values.values())]  # e.g. OS: never read here
    differs = [c for c in rows if c.differs]

    def table(items: list[Comparison]) -> str:
        head = "<th>Item</th>" + "".join(f"<th>{_e(n)}</th>" for n in names)
        body = "".join(
            f'<tr class="{"differs" if c.differs else ""}"><td>{_e(c.item)}</td>'
            + "".join(f"<td class=mono>{_e(c.values.get(n))}</td>" for n in names)
            + "</tr>"
            for c in items
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>" if items else ""

    def link(r: Result) -> str:
        file = files.get(r.target.address)
        return f'<a href="{html.escape(file)}">{_e(r.name)}</a>' if file else _e(r.name)

    def model(r: Result) -> str:
        return _e(f"{r.inventory.system.manufacturer} {r.inventory.system.model}" if r.inventory else r.error)

    servers = (
        "<table><thead><tr><th>Server</th><th>BMC</th><th>Model</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{link(r)}</td><td class=mono>{_e(r.target.address)}</td><td>{model(r)}</td></tr>"
            for r in results
        )
        + "</tbody></table>"
    )
    failed = "".join(
        f"<li class=error>{_e(r.target.address)}: {_e(r.error)}</li>" for r in results if r.error
    )
    body = (
        _section("Servers", servers, "servers")
        + (_section("Couldn't be read", f"<ul>{failed}</ul>", "failed") if failed else "")
        + _section(
            f"Differences · {len(differs)}" if differs else "No differences",
            table(differs) or "<p>Every compared item is the same on every server.</p>",
            "differences",
        )
        + _section(
            f"The same on every server · {len(rows) - len(differs)}",
            table([c for c in rows if not c.differs]),
            "same",
        )
    )
    return _page("Hardware comparison", f"{len(good)} of {len(results)} servers read", body)


# ── command line ─────────────────────────────────────────────────────────
def _targets(args: argparse.Namespace) -> list[Target]:
    targets = [Target(a, args.user) for a in args.bmc]
    if args.file:
        for line in Path(args.file).read_text().splitlines():
            words = line.split("#", 1)[0].split()
            if words:
                targets.append(Target(words[0], words[1] if len(words) > 1 else args.user))
    return targets


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gz-hwreport",
        description="A hardware report straight from a server's BMC (read-only).",
        epilog="The BMC password comes from GZ_BMC_PASSWORD, or is asked for once.",
    )
    parser.add_argument("bmc", nargs="*", help="BMC addresses (iDRAC, iLO, XCC, ...)")
    parser.add_argument("-f", "--file", help='a file of BMCs, one per line: "address" or "address username"')
    parser.add_argument(
        "-u", "--user", default=os.environ.get("GZ_BMC_USERNAME", "root"), help="BMC username (default root)"
    )
    parser.add_argument("-o", "--out", type=Path, help="output folder (default ./hwreport-<date>)")
    parser.add_argument("--verify-tls", action="store_true", help="check the BMC's TLS certificate")
    parser.add_argument("--parallel", type=int, default=4, help="BMCs read at once (default 4)")
    parser.add_argument("--version", action="version", version=f"gz-hwreport {__version__}")
    parser.add_argument("--replay", type=Path, help=argparse.SUPPRESS)  # a recorded BMC, for tests and demos
    args = parser.parse_args(argv)
    targets = _targets(args)
    if not targets:
        parser.error("give at least one BMC address, or -f FILE")
    password = os.environ.get("GZ_BMC_PASSWORD") or ("" if args.replay else getpass.getpass("BMC password: "))
    results = asyncio.run(
        read_all(
            targets, password, verify_tls=args.verify_tls, parallel=max(1, args.parallel), replay=args.replay
        )
    )

    names = [r.name for r in results]
    for r in results:  # two servers reporting the same name: tell them apart by address
        if names.count(r.name) > 1:
            r.name = f"{r.name} ({r.target.address})"
    out: Path = args.out or Path(f"hwreport-{datetime.now():%Y%m%d-%H%M}")
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    used: set[str] = set()
    for r in results:
        if r.inventory is None:
            _say(f"  {r.target.address}: {r.error}", err=True)
            continue
        stem = _slug(r.name)
        while stem in used:
            stem += "_"
        used.add(stem)
        (out / f"{stem}.html").write_text(server_html(r))
        data = {
            "bmc": r.target.address,
            "inventory": r.inventory.model_dump(mode="json"),
            "storage": r.storage.model_dump(mode="json") if r.storage else None,
        }
        (out / f"{stem}.json").write_text(json.dumps(data, indent=2) + "\n")
        files[r.target.address] = f"{stem}.html"
        _say(f"  {r.name}: {out / (stem + '.html')}")
    if len(results) > 1:
        (out / "index.html").write_text(comparison_html(results, files))
        _say(f"  comparison: {out / 'index.html'}")
    failed = sum(1 for r in results if r.inventory is None)
    _say(f"{len(results) - failed} of {len(results)} servers read into {out}")
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
