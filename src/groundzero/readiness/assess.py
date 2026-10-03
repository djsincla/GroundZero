"""Readiness assessment (task ``host.assess``): a pure function from what GroundZero read to a report.

Inputs are the preflight output (hardware and the chosen Holodeck variant) and a live read of the
installed ESXi (network, NTP, disks, datastores). The profile (``preflight/profiles/holodeck-9.toml``)
holds the requirements. The output is a list of checks plus a *plan*: concrete, reviewable actions
that ``host.prep`` can apply. Nothing here changes the server.

Storage rule (agreed with the user): use an existing flash VMFS datastore with enough free space;
otherwise propose formatting the largest unused flash disk (no datastore, no partitions, not the boot
disk); otherwise fail with the options. A disk is never proposed unless its partitions could be read.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from groundzero.core.store import utcnow
from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage, VSwitch
from groundzero.preflight.evaluate import (
    Category,
    Check,
    CheckStatus,
    PreflightReport,
    PreflightSummary,
    Profile,
)

TRUNK_PORTGROUP = "Holodeck-Trunk"
EXTERNAL_PORTGROUP = "Holodeck-External"
DATASTORE_NAME = "holodeck"
DEFAULT_NTP = ["pool.ntp.org"]


class Action(BaseModel):
    """One fix ``host.prep`` can apply. ``params`` are exactly what it will do."""

    id: str = Field(description="set_mtu, ensure_portgroup, configure_ntp, create_datastore, verify_jumbo")
    check: str = Field(description="The check this action fixes")
    title: str
    why: str
    params: dict[str, Any] = Field(default_factory=dict)
    destructive: bool = False
    confirm_phrase: str | None = Field(default=None, description="Typed confirmation for destructive actions")
    recommended: bool = Field(default=True, description="Selected by default in the UI")


class StorageProposal(BaseModel):
    kind: Literal["existing", "format", "none"]
    required_gb: float
    datastore: str | None = None
    disk: str | None = Field(default=None, description="Canonical name of the disk to format (kind=format)")
    disk_label: str | None = None
    capacity_gb: float | None = None
    free_gb: float | None = None
    reason: str


class ReadinessReport(BaseModel):
    profile: str
    variant: str
    variant_title: str
    generated_at: datetime
    esxi: str = Field(description="Product and build that was assessed")
    overall: CheckStatus
    ready: bool = Field(description="True when nothing blocks the Holodeck deployment")
    summary: PreflightSummary
    checks: list[Check]
    plan: list[Action]
    storage: StorageProposal
    target_vswitch: str | None = None


def _version_tuple(text: str) -> tuple[int, ...]:
    """'8.0u3' → (8, 0, 3); '9.1.1' → (9, 1, 1); '9.0' → (9, 0)."""
    return tuple(int(n) for n in re.findall(r"\d+", text.lower().replace("u", ".")))


def _check_version(network: EsxiNetworkConfig, profile: Profile) -> Check:
    tested: list[str] = list(profile.host.get("supported_esxi", []))
    have = _version_tuple(network.version)
    required = "ESX " + " or ".join(tested) if tested else "any"
    status = CheckStatus.PASS
    remediation = None
    if tested:
        families = [_version_tuple(t) for t in tested]
        in_family = any(have[:2] == f[:2] and (len(f) < 3 or have[2:3] >= f[2:3]) for f in families)
        if not in_family:
            if have > max(families):
                status = CheckStatus.WARN
                remediation = "Newer than the versions Holodeck lists as tested; it is expected to work."
            else:
                status = CheckStatus.FAIL
                remediation = "Install a supported ESX version (Deploy OS)."
    return Check(
        id="esxi.version",
        category=Category.COMPUTE,
        title="ESX version",
        status=status,
        observed=f"{network.product} (build {network.build})",
        required=required,
        remediation=remediation,
    )


def _check_hardware(preflight: PreflightReport | None) -> Check:
    if preflight is None:
        return Check(
            id="hardware.preflight",
            category=Category.COMPUTE,
            title="Hardware preflight",
            status=CheckStatus.UNKNOWN,
            observed="not run",
            required="preflight passes",
            remediation="Run the Holodeck preflight.",
        )
    problems = [c.title for c in preflight.checks if c.status in (CheckStatus.FAIL, CheckStatus.WARN)]
    observed = f"{preflight.overall.value}: " + (", ".join(problems) if problems else "all checks passed")
    return Check(
        id="hardware.preflight",
        category=Category.COMPUTE,
        title="Hardware preflight",
        status=preflight.overall,
        observed=observed,
        required=f"{preflight.variant_title} requirements",
        remediation="See the preflight results." if problems else None,
    )


def _target_vswitch(network: EsxiNetworkConfig) -> VSwitch | None:
    """The standard switch Holodeck will use: one with an existing trunk, else the management switch."""
    trunk = next((p for p in network.portgroups if p.is_trunk), None)
    mgmt = network.management_portgroup()
    name = trunk.vswitch if trunk else (mgmt.vswitch if mgmt else None)
    if name is None and network.vswitches:
        name = max(network.vswitches, key=lambda v: len(v.uplinks)).name
    return next((v for v in network.vswitches if v.name == name), None)


def _check_ntp(network: EsxiNetworkConfig, plan: list[Action]) -> Check:
    servers = network.ntp_servers
    problems = []
    if not servers:
        problems.append("no NTP server")
    if network.ntp_running is False:
        problems.append("ntpd stopped")
    if network.ntp_policy not in (None, "on"):
        problems.append(f"startup policy '{network.ntp_policy}' (won't start after a reboot)")
    observed = (", ".join(servers) or "none") + (
        f" · running={network.ntp_running}, policy={network.ntp_policy}"
        if network.ntp_running is not None
        else ""
    )
    if problems:
        target = servers or DEFAULT_NTP
        plan.append(
            Action(
                id="configure_ntp",
                check="ntp",
                title=(
                    "Make NTP start with the host (startup policy on)"
                    if servers and network.ntp_running
                    else f"Configure NTP ({', '.join(target)}) and start it"
                ),
                why="Holodeck needs time in sync on the host; " + "; ".join(problems) + ".",
                params={"servers": target, "policy": "on"},
            )
        )
    return Check(
        id="ntp",
        category=Category.NETWORK,
        title="NTP",
        status=CheckStatus.FAIL if problems else CheckStatus.PASS,
        observed=observed,
        required="server configured, ntpd running, policy on",
        remediation="GroundZero can fix this." if problems else None,
    )


def _check_mtu(vswitch: VSwitch | None, mtu: int, plan: list[Action]) -> Check:
    if vswitch is None:
        return Check(
            id="network.mtu",
            category=Category.NETWORK,
            title="vSwitch MTU",
            status=CheckStatus.FAIL,
            observed="no standard switch found",
            required=f"MTU {mtu}",
            remediation="Create a standard switch with uplinks.",
        )
    ok = (vswitch.mtu or 1500) >= mtu
    if not ok:
        plan.append(
            Action(
                id="set_mtu",
                check="network.mtu",
                title=f"Set {vswitch.name} MTU to {mtu}",
                why="Nested NSX overlay traffic needs jumbo frames end to end. The physical switch "
                "ports must allow them too (checked by Verify jumbo frames).",
                params={"vswitch": vswitch.name, "mtu": mtu},
            )
        )
    return Check(
        id="network.mtu",
        category=Category.NETWORK,
        title="vSwitch MTU",
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        observed=f"{vswitch.name}: {vswitch.mtu or 1500}",
        required=f"≥ {mtu}",
        remediation=None if ok else "GroundZero can fix this.",
    )


def _check_uplinks(network: EsxiNetworkConfig, vswitch: VSwitch | None, min_mbps: int) -> Check:
    nics = {n.device: n for n in network.physical_nics}
    links = [nics[u] for u in (vswitch.uplinks if vswitch else []) if u in nics]
    up = [n for n in links if n.speed_mbps]
    observed = (
        ", ".join(f"{n.device} {n.speed_mbps // 1000 if n.speed_mbps else 0} GbE" for n in links) or "none"
    )
    if not up:
        status, fix = CheckStatus.FAIL, "Connect an uplink to the switch."
    elif any((n.speed_mbps or 0) < min_mbps for n in up):
        status, fix = CheckStatus.WARN, f"{min_mbps // 1000} GbE or faster is recommended."
    elif len(up) < 2:
        status, fix = CheckStatus.WARN, "Two uplinks are needed to verify jumbo frames through the switch."
    else:
        status, fix = CheckStatus.PASS, None
    return Check(
        id="network.uplinks",
        category=Category.NETWORK,
        title="Uplinks",
        status=status,
        observed=observed,
        required=f"link up, ≥ {min_mbps // 1000} GbE (two for the jumbo-frame test)",
        remediation=fix,
    )


def _check_trunk(network: EsxiNetworkConfig, vswitch: VSwitch | None, vlan: int, plan: list[Action]) -> Check:
    trunks = [
        p for p in network.portgroups if p.vlan_id == vlan and (vswitch is None or p.vswitch == vswitch.name)
    ]
    good = next((p for p in trunks if p.security.accepts_all), None)
    required = f"port group on VLAN {vlan} with Promiscuous, MAC changes and Forged transmits = Accept"
    if good:
        return Check(
            id="network.trunk",
            category=Category.NETWORK,
            title="Trunk port group",
            status=CheckStatus.PASS,
            observed=f"{good.name} (VLAN {good.vlan_id}, all Accept)",
            required=required,
        )
    if vswitch is None:
        return Check(
            id="network.trunk",
            category=Category.NETWORK,
            title="Trunk port group",
            status=CheckStatus.FAIL,
            observed="no standard switch found",
            required=required,
        )
    existing = trunks[0] if trunks else None
    verb = "Set security on" if existing else "Create"
    name = existing.name if existing else TRUNK_PORTGROUP
    plan.append(
        Action(
            id="ensure_portgroup",
            check="network.trunk",
            title=f"{verb} port group {name} (VLAN {vlan}) on {vswitch.name}",
            why="The Holorouter's Site A/B interfaces and the nested hosts use this trunk; nested "
            "switching needs Promiscuous mode, MAC address changes and Forged transmits accepted.",
            params={
                "name": name,
                "vswitch": vswitch.name,
                "vlan": vlan,
                "allow_promiscuous": True,
                "mac_changes": True,
                "forged_transmits": True,
            },
        )
    )
    observed = f"{existing.name}: security not all Accept" if existing else "none"
    return Check(
        id="network.trunk",
        category=Category.NETWORK,
        title="Trunk port group",
        status=CheckStatus.FAIL,
        observed=observed,
        required=required,
        remediation="GroundZero can fix this.",
    )


def _check_external(
    network: EsxiNetworkConfig, vswitch: VSwitch | None, vlan: int, plan: list[Action]
) -> Check:
    """The Holorouter's management NIC needs a port group on a network you can reach (one external IP)."""
    vmk_pgs = {v.portgroup for v in network.vmkernel}
    candidates = [
        p for p in network.portgroups if not p.is_trunk and p.name not in vmk_pgs and p.vlan_id != vlan
    ]
    named = next((p for p in candidates if p.name == EXTERNAL_PORTGROUP), None)
    required = "a VM port group on a network you can reach, with one free IP for the Holorouter"
    if named:
        return Check(
            id="network.external",
            category=Category.NETWORK,
            title="Holorouter external port group",
            status=CheckStatus.PASS,
            observed=f"{named.name} (VLAN {named.vlan_id})",
            required=required,
        )
    mgmt_vlan = network.management_vlan()
    if vswitch is not None:
        plan.append(
            Action(
                id="ensure_portgroup",
                check="network.external",
                title=f"Create port group {EXTERNAL_PORTGROUP} (VLAN {mgmt_vlan}) on {vswitch.name}",
                why=f"Puts the Holorouter on the management VLAN {mgmt_vlan}, which GroundZero already "
                "reaches. Skip this if you will use an existing port group instead.",
                params={"name": EXTERNAL_PORTGROUP, "vswitch": vswitch.name, "vlan": mgmt_vlan},
                recommended=not candidates,
            )
        )
    if candidates:
        listed = ", ".join(f"{p.name} (VLAN {p.vlan_id})" for p in candidates)
        return Check(
            id="network.external",
            category=Category.NETWORK,
            title="Holorouter external port group",
            status=CheckStatus.WARN,
            observed=listed,
            required=required,
            remediation="Confirm this VLAN reaches your network, or create "
            f"{EXTERNAL_PORTGROUP} on the management VLAN.",
        )
    return Check(
        id="network.external",
        category=Category.NETWORK,
        title="Holorouter external port group",
        status=CheckStatus.FAIL,
        observed="none",
        required=required,
        remediation="GroundZero can fix this.",
    )


def propose_storage(storage: EsxiStorage, required_gb: float) -> StorageProposal:
    flash = [d for d in storage.datastores if d.type == "VMFS" and d.ssd and d.free_gb is not None]
    fitting = [d for d in flash if (d.free_gb or 0) >= required_gb]
    if fitting:
        best = max(fitting, key=lambda d: ("holodeck" in d.name.lower(), d.free_gb or 0))
        return StorageProposal(
            kind="existing",
            required_gb=required_gb,
            datastore=best.name,
            capacity_gb=best.capacity_gb,
            free_gb=best.free_gb,
            reason=f"Existing flash datastore {best.name} has {best.free_gb:,.0f} GB free.",
        )
    unused = [d for d in storage.disks if d.unused and d.ssd and d.capacity_gb * 0.98 >= required_gb]
    if unused:
        disk = max(unused, key=lambda d: d.capacity_gb)
        label = " ".join(x for x in (disk.vendor, disk.model) if x) or disk.display_name or disk.name
        return StorageProposal(
            kind="format",
            required_gb=required_gb,
            datastore=DATASTORE_NAME,
            disk=disk.name,
            disk_label=label,
            capacity_gb=disk.capacity_gb,
            reason=f"No flash datastore has {required_gb:,.0f} GB free; the largest unused flash "
            f"disk is {label} ({disk.capacity_gb:,.0f} GB, no partitions).",
        )
    biggest = max((d.free_gb or 0 for d in flash), default=0)
    return StorageProposal(
        kind="none",
        required_gb=required_gb,
        reason=f"No flash datastore with {required_gb:,.0f} GB free (largest: {biggest:,.0f} GB) "
        "and no unused flash disk that large. Choose a smaller variant, free space on a "
        "datastore, or empty a disk.",
    )


def _check_storage(proposal: StorageProposal, plan: list[Action]) -> Check:
    required = f"flash VMFS datastore with ≥ {proposal.required_gb:,.0f} GB free"
    if proposal.kind == "existing":
        return Check(
            id="storage.datastore",
            category=Category.STORAGE,
            title="Holodeck datastore",
            status=CheckStatus.PASS,
            observed=proposal.reason,
            required=required,
        )
    if proposal.kind == "format" and proposal.disk:
        plan.append(
            Action(
                id="create_datastore",
                check="storage.datastore",
                title=f"Create datastore '{proposal.datastore}' on {proposal.disk_label}",
                why=proposal.reason + " Formatting erases the disk.",
                params={"disk": proposal.disk, "name": proposal.datastore},
                destructive=True,
                confirm_phrase=f"format {proposal.disk_label}",
            )
        )
        return Check(
            id="storage.datastore",
            category=Category.STORAGE,
            title="Holodeck datastore",
            status=CheckStatus.FAIL,
            observed=proposal.reason,
            required=required,
            remediation="GroundZero can create it (erases that disk; you confirm first).",
        )
    return Check(
        id="storage.datastore",
        category=Category.STORAGE,
        title="Holodeck datastore",
        status=CheckStatus.FAIL,
        observed=proposal.reason,
        required=required,
        remediation="Free capacity or pick a smaller variant, then assess again.",
    )


def _check_jumbo(jumbo: dict[str, Any] | None, plan: list[Action]) -> Check:
    required = "9000-byte frames pass through the physical switch between both uplinks"
    if jumbo and jumbo.get("ok"):
        return Check(
            id="network.jumbo",
            category=Category.NETWORK,
            title="Jumbo frames through the switch",
            status=CheckStatus.PASS,
            observed=str(jumbo.get("summary", "verified")),
            required=required,
        )
    plan.append(
        Action(
            id="verify_jumbo",
            check="network.jumbo",
            title="Verify jumbo frames through the switch",
            why="An MTU of 9000 on the host is not enough if the physical switch ports drop jumbo "
            "frames; this sends 9000-byte frames out of one uplink and back in the other.",
            params={},
        )
    )
    observed = str(jumbo.get("summary")) if jumbo else "not verified yet"
    return Check(
        id="network.jumbo",
        category=Category.NETWORK,
        title="Jumbo frames through the switch",
        status=CheckStatus.FAIL if jumbo else CheckStatus.UNKNOWN,
        observed=observed,
        required=required,
        remediation="Run Verify jumbo frames after the MTU is 9000.",
    )


def assess(
    *,
    profile: Profile,
    variant: str,
    network: EsxiNetworkConfig,
    storage: EsxiStorage,
    preflight: PreflightReport | None,
    jumbo: dict[str, Any] | None = None,
) -> ReadinessReport:
    spec = profile.variants[variant]
    req = profile.host_network
    plan: list[Action] = []
    vswitch = _target_vswitch(network)
    trunk_vlan = int(req.get("trunk_portgroup_vlan", 4095))
    required_gb = round(spec.disk_tb * 1000 + profile.holorouter.get("disk_gb", 0), 1)
    proposal = propose_storage(storage, required_gb)
    checks = [
        _check_hardware(preflight),
        _check_version(network, profile),
        _check_storage(proposal, plan),
        _check_ntp(network, plan),
        _check_mtu(vswitch, int(req.get("vswitch_mtu", 9000)), plan),
        _check_uplinks(network, vswitch, int(profile.host.get("min_nic_speed_mbps", 10000))),
        _check_trunk(network, vswitch, trunk_vlan, plan),
        _check_external(network, vswitch, trunk_vlan, plan),
        _check_jumbo(jumbo, plan),
    ]
    summary = PreflightSummary(
        passed=sum(c.status is CheckStatus.PASS for c in checks),
        warnings=sum(c.status is CheckStatus.WARN for c in checks),
        failed=sum(c.status is CheckStatus.FAIL for c in checks),
        unknown=sum(c.status is CheckStatus.UNKNOWN for c in checks),
    )
    overall = (
        CheckStatus.FAIL
        if summary.failed
        else CheckStatus.WARN
        if summary.warnings or summary.unknown
        else CheckStatus.PASS
    )
    return ReadinessReport(
        profile=profile.id,
        variant=variant,
        variant_title=spec.title,
        generated_at=utcnow(),
        esxi=f"{network.product} (build {network.build})",
        overall=overall,
        ready=summary.failed == 0,
        summary=summary,
        checks=checks,
        plan=plan,
        storage=proposal,
        target_vswitch=vswitch.name if vswitch else None,
    )
