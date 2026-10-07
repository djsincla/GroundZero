"""/api/v1 reports: a server's hardware and configuration, and a cluster's members compared (JSON or CSV).

Built from what GroundZero already recorded; nothing is read from the servers."""

from __future__ import annotations

from fastapi import APIRouter, Response

from groundzero.api.deps import ServicesDep
from groundzero.core import reports
from groundzero.core.reports import ClusterReport, HostReport

router = APIRouter(tags=["reports"])


def _csv(text: str, filename: str) -> Response:
    return Response(
        text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/hosts/{host_id}/report", response_model=HostReport)
def host_report(host_id: str, services: ServicesDep) -> HostReport:
    """The server's full hardware inventory (firmware, CPUs, memory modules, drives, adapters, PCIe devices,
    power supplies) and its configuration state (spec, last run, OS, boot volume, every task's result)."""
    return reports.host_report(services, host_id)


@router.get("/hosts/{host_id}/report.csv", response_class=Response)
def host_report_csv(host_id: str, services: ServicesDep) -> Response:
    """The same as one row per component: server, section, component, model, version, detail, health."""
    report = reports.host_report(services, host_id)
    return _csv(reports.to_csv(reports.host_rows(report)), f"{report.name}-report.csv")


@router.get("/clusters/{cluster_id}/report", response_model=ClusterReport)
def cluster_report(cluster_id: str, services: ServicesDep) -> ClusterReport:
    """Every member's report, and what should match across them (model, BIOS, firmware, memory, ...) with
    the items that differ flagged."""
    return reports.cluster_report(services, cluster_id)


@router.get("/clusters/{cluster_id}/report.csv", response_class=Response)
def cluster_report_csv(cluster_id: str, services: ServicesDep) -> Response:
    """The comparison as CSV: one row per item, one column per member, and whether it differs."""
    report = reports.cluster_report(services, cluster_id)
    return _csv(reports.cluster_csv(report), f"{report.name}-cluster-report.csv")


@router.get("/clusters/{cluster_id}/report-components.csv", response_class=Response)
def cluster_components_csv(cluster_id: str, services: ServicesDep) -> Response:
    """Every member's components in one sheet (the server reports' rows, one after another)."""
    report = reports.cluster_report(services, cluster_id)
    rows = [row for member in report.members for row in reports.host_rows(member)]
    return _csv(reports.to_csv(rows), f"{report.name}-components.csv")
