"""Reports: a server's hardware and configuration on one page, and a cluster's members side by side.

Everything comes from what GroundZero already recorded (the latest inventory, the pipeline's outputs, the
spec and its last run); building a report reads nothing from the servers. Each report is JSON (for tools)
or CSV (one row per component, for spreadsheets); the web UI renders the JSON as a printable page.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from groundzero.inventory.models import HostInventory

if TYPE_CHECKING:
    from groundzero.core.services import Services


class TaskLine(BaseModel):
    task: str
    title: str
    state: str
    summary: str | None = None
    at: datetime | None = None


class Configuration(BaseModel):
    spec: str | None = Field(default=None, description="The spec the server follows, and where from")
    last_run: str | None = None
    os: str | None = Field(default=None, description="The installed OS, as last read")
    hostname: str | None = None
    management_ip: str | None = None
    boot_volume: str | None = None
    readiness: str | None = None
    tasks: list[TaskLine] = Field(
        default_factory=list, description="Every pipeline task, its state and result"
    )


class HostReport(BaseModel):
    generated_at: datetime
    host_id: str
    name: str
    bmc_address: str
    model: str | None = None
    service_tag: str | None = None
    inventory_at: datetime | None = Field(default=None, description="When the hardware was last read")
    inventory: HostInventory | None = Field(default=None, description="null: Discover hardware hasn't run")
    configuration: Configuration


class Comparison(BaseModel):
    item: str = Field(description="What's compared, e.g. BIOS or 'Firmware: PERC H730P Adapter'")
    values: dict[str, str | None] = Field(description="Server name → value")
    differs: bool


class ClusterReport(BaseModel):
    generated_at: datetime
    cluster_id: str
    name: str
    members: list[HostReport]
    comparison: list[Comparison]
    differences: int = Field(description="How many compared items aren't the same on every member")


# ── building ─────────────────────────────────────────────────────────────
def utcnow() -> datetime:
    return datetime.now(UTC)


def host_report(services: Services, host_id: str) -> HostReport:
    # Imported here so the standalone hardware report (groundzero.hwreport) stays light.
    from groundzero.esxi.models import EsxiNetworkConfig
    from groundzero.modules.base import Inputs
    from groundzero.modules.outputs import StorageReport
    from groundzero.readiness import ReadinessReport

    host = services.get_host(host_id)
    inputs = Inputs(services.store, host_id)
    inventory = inputs.get("inventory", HostInventory)
    inventory_meta = inputs.meta("inventory")
    network = inputs.get("os_network", EsxiNetworkConfig, current=True)
    storage = inputs.get("storage", StorageReport)
    readiness = inputs.get("readiness", ReadinessReport, current=True)
    pipeline = services.pipeline(host_id)
    runs = services.store.list_runs(host_id=host_id, limit=1)
    mgmt = next((v for v in network.vmkernel if "management" in v.services), None) if network else None
    b = storage.boot_volume if storage else None
    config = Configuration(
        spec=f"{pipeline.spec.name} ({'its own' if pipeline.spec.source == 'host' else 'from its cluster'})"
        if pipeline.spec
        else None,
        last_run=f"{runs[0].spec_name}: {runs[0].status} ({runs[0].created_at:%Y-%m-%d %H:%M})"
        if runs
        else None,
        os=network.product if network else None,
        hostname=network.hostname if network else None,
        management_ip=mgmt.ip if mgmt else None,
        boot_volume=" · ".join(
            x for x in (b.name or b.volume_id, b.raid, f"{b.capacity_gb:g} GB", b.controller_model) if x
        )
        if b
        else None,
        readiness=f"{readiness.overall.value}: {readiness.variant_title}" if readiness else None,
        tasks=[
            TaskLine(
                task=t.id,
                title=t.title,
                state=t.state,
                summary=t.output.summary if t.output else t.not_needed,
                at=t.output.produced_at if t.output else None,
            )
            for stage in pipeline.stages
            for t in stage.tasks
            if t.available
        ],
    )
    return HostReport(
        generated_at=utcnow(),
        host_id=host.id,
        name=host.name,
        bmc_address=host.bmc_address,
        model=" ".join(x for x in (host.vendor, host.model) if x) or None,
        service_tag=inventory.system.service_tag if inventory else None,
        inventory_at=inventory_meta.created_at if inventory_meta else None,
        inventory=inventory,
        configuration=config,
    )


def cluster_report(services: Services, cluster_id: str) -> ClusterReport:
    cluster = services.get_cluster(cluster_id)
    members = [host_report(services, m.host_id) for m in cluster.members]
    comparison = compare(members)
    return ClusterReport(
        generated_at=utcnow(),
        cluster_id=cluster.id,
        name=cluster.name,
        members=members,
        comparison=comparison,
        differences=sum(c.differs for c in comparison),
    )


def compare(members: list[HostReport]) -> list[Comparison]:
    """Each item that should match across members, with every member's value (missing: None)."""
    rows: dict[str, dict[str, str | None]] = {}
    for report in members:
        for item, value in _comparable(report).items():
            rows.setdefault(item, {})[report.name] = value
    comparison = []
    for item, values in rows.items():
        full = {r.name: values.get(r.name) for r in members}
        comparison.append(Comparison(item=item, values=full, differs=len(set(full.values())) > 1))
    return comparison


def _comparable(report: HostReport) -> dict[str, str | None]:
    """What should be the same on every member of a cluster."""
    inv = report.inventory
    out: dict[str, str | None] = {"Model": report.model}
    if inv is None:
        return out | {"Hardware": "not read"}
    out |= {
        "BIOS": inv.system.bios_version,
        "BMC firmware": inv.bmc.firmware_version,
        "Processors": ", ".join(sorted({p.model for p in inv.processors})) + f" x {len(inv.processors)}",
        "Memory": f"{inv.memory.total_gib:g} GiB in {inv.memory.dimm_count} DIMMs",
        "Drives": f"{len(inv.drives)}",
        "Network adapters": ", ".join(sorted(a.model or a.name or a.id for a in inv.network_adapters))
        or None,
        "Power supplies": ", ".join(sorted(p.model or p.name for p in inv.power_supplies)) or None,
        "Virtualization in BIOS": _on(inv.bios.cpu_virtualization),
        "Boot mode": inv.bios.boot_mode,
        "OS": report.configuration.os,
    }
    for fw in inv.firmware:
        out[f"Firmware: {fw.name}"] = fw.version
    return out


def _on(value: bool | None) -> str | None:
    return None if value is None else "on" if value else "off"


# ── CSV: one row per component ───────────────────────────────────────────
_COLUMNS = ["server", "section", "component", "model", "version", "detail", "health"]


def host_rows(report: HostReport) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(
        section: str, component: str, model: Any = "", version: Any = "", detail: Any = "", health: Any = ""
    ) -> None:
        rows.append(
            {
                "server": report.name,
                "section": section,
                "component": component,
                "model": model or "",
                "version": version or "",
                "detail": detail or "",
                "health": health or "",
            }
        )

    inv = report.inventory
    add(
        "server",
        "System",
        report.model,
        detail=f"service tag {report.service_tag or '?'} · BMC {report.bmc_address}",
    )
    if inv is not None:
        add(
            "server", "BIOS", version=inv.system.bios_version, detail=f"boot mode {inv.bios.boot_mode or '?'}"
        )
        add("server", "BMC", inv.bmc.vendor, inv.bmc.firmware_version, inv.bmc.hostname)
        for p in inv.processors:
            add("processor", p.socket or "CPU", p.model, detail=f"{p.cores} cores, {p.threads} threads")
        for m in inv.memory.modules:
            add(
                "memory",
                m.slot or m.id,
                m.part_number,
                detail=f"{m.capacity_mib // 1024} GiB {m.type or ''} {m.speed_mhz or ''} MHz".strip(),
                health=m.health,
            )
        for d in inv.drives:
            add(
                "drive",
                d.id,
                d.model,
                d.firmware_version,
                f"{d.capacity_bytes / 1e9:.0f} GB {d.media_type or ''} {d.protocol or ''} "
                f"on {d.controller or '?'}",
            )
        for a in inv.network_adapters:
            add("network adapter", a.id, a.model, a.firmware_version, f"{a.ports} ports", a.health)
        for n in inv.network_ports:
            add("network port", n.id, detail=f"{n.link_status or '?'} {n.speed_mbps or ''} Mb/s".strip())
        for x in inv.pcie_devices:
            add(
                f"pcie {x.device_class or ''}".strip(),
                x.id,
                x.name,
                x.firmware_version,
                x.manufacturer,
                x.health,
            )
        for s in inv.power_supplies:
            add("power supply", s.name, s.model, s.firmware_version, f"{s.capacity_watts or '?'} W", s.health)
        for f in inv.firmware:
            add(
                "firmware",
                f.name,
                version=f.version,
                detail="updateable" if f.updateable else "",
                health=f.health,
            )
    c = report.configuration
    for label, value in (
        ("Spec", c.spec),
        ("Last run", c.last_run),
        ("OS", c.os),
        ("Hostname", c.hostname),
        ("Management IP", c.management_ip),
        ("Boot volume", c.boot_volume),
        ("Readiness", c.readiness),
    ):
        if value:
            add("configuration", label, detail=value)
    for t in c.tasks:
        add("task", t.title, detail=t.summary, health=t.state)
    return rows


def to_csv(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns or _COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def cluster_csv(report: ClusterReport) -> str:
    names = [m.name for m in report.members]
    rows = [{"item": c.item, "differs": "yes" if c.differs else "", **c.values} for c in report.comparison]
    return to_csv(rows, ["item", "differs", *names])
