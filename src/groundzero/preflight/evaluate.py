"""Evaluate a HostInventory against a requirements profile (e.g. Holodeck 9)."""

from __future__ import annotations

import tomllib
from datetime import datetime
from enum import StrEnum
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field

from groundzero.core.store import utcnow
from groundzero.inventory.models import HostInventory

_GB = 1000**3
_TB = 1000**4


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class Category(StrEnum):
    COMPUTE = "compute"
    MEMORY = "memory"
    STORAGE = "storage"
    NETWORK = "network"
    BIOS = "bios"
    BMC = "bmc"


class Check(BaseModel):
    id: str
    category: Category
    title: str
    status: CheckStatus
    observed: str
    required: str
    remediation: str | None = None


class Variant(BaseModel):
    id: str
    title: str
    cores: int
    memory_gb: float
    disk_tb: float


class Profile(BaseModel):
    id: str
    title: str
    source: str
    default_variant: str
    holorouter: dict[str, float]
    host: dict[str, Any]
    host_network: dict[str, Any] = Field(default_factory=dict)
    variants: dict[str, Variant]


class PreflightSummary(BaseModel):
    passed: int = 0
    warnings: int = 0
    failed: int = 0
    unknown: int = 0


class PreflightReport(BaseModel):
    profile: str
    variant: str
    variant_title: str
    source: str
    generated_at: datetime
    overall: CheckStatus
    summary: PreflightSummary
    checks: list[Check] = Field(default_factory=list)


class UnknownProfileError(ValueError):
    error_type = "unknown_profile"


def available_profiles() -> list[str]:
    files = resources.files("groundzero.preflight").joinpath("profiles").iterdir()
    return sorted(f.name.removesuffix(".toml") for f in files if f.name.endswith(".toml"))


def load_profile(profile_id: str) -> Profile:
    if profile_id not in available_profiles():
        raise UnknownProfileError(f"Unknown preflight profile '{profile_id}'")
    text = resources.files("groundzero.preflight").joinpath(f"profiles/{profile_id}.toml").read_text()
    data = tomllib.loads(text)
    data["variants"] = {k: {"id": k, **v} for k, v in data["variants"].items()}
    return Profile.model_validate(data)


def _fmt_tb(num_bytes: int) -> str:
    return f"{num_bytes / _TB:.2f} TB"


def _compute(inv: HostInventory, need_cores: int) -> list[Check]:
    checks: list[Check] = []
    cores, threads = inv.total_cores, inv.total_threads
    if cores >= need_cores:
        status, fix = CheckStatus.PASS, None
    elif threads >= need_cores:
        status = CheckStatus.WARN
        fix = "Physical cores are below the Holodeck guidance; nested VMs will rely on hyper-threads."
    else:
        status, fix = CheckStatus.FAIL, "Choose a smaller variant or a host with more CPU cores."
    checks.append(
        Check(
            id="cpu.cores",
            category=Category.COMPUTE,
            title="CPU cores",
            status=status if cores else CheckStatus.UNKNOWN,
            observed=f"{cores} cores / {threads} threads across {len(inv.processors)} socket(s)",
            required=f">= {need_cores} cores (incl. Holorouter)",
            remediation=fix,
        )
    )
    return checks


def _memory(inv: HostInventory, need_gb: float) -> Check:
    have_gb = inv.memory.total_gib * (1024**3) / _GB
    ok = have_gb >= need_gb
    return Check(
        id="memory.total",
        category=Category.MEMORY,
        title="Installed memory",
        status=(CheckStatus.PASS if ok else CheckStatus.FAIL) if have_gb else CheckStatus.UNKNOWN,
        observed=f"{inv.memory.total_gib:.0f} GiB ({inv.memory.dimm_count} DIMMs)",
        required=f">= {need_gb:.0f} GB (incl. Holorouter)",
        remediation=None if ok else "Add memory or choose a smaller variant.",
    )


def _storage(inv: HostInventory, need_bytes: int, media: str) -> list[Check]:
    data_drives = [d for d in inv.drives if not d.is_boot_device]
    flash = sum(d.capacity_bytes for d in data_drives if d.is_flash)
    spinning = sum(d.capacity_bytes for d in data_drives if not d.is_flash)
    if flash >= need_bytes:
        status, fix = CheckStatus.PASS, None
    elif flash + spinning >= need_bytes:
        status, fix = CheckStatus.WARN, f"Capacity is met only by including HDDs; Holodeck expects {media}."
    else:
        status, fix = CheckStatus.FAIL, "Add SSD/NVMe capacity for the ESXi datastore."
    if not inv.drives:
        status = CheckStatus.UNKNOWN
        fix = (
            "No drives visible via Redfish. Drives behind a RAID volume may be hidden; check the controller."
        )
    boot = [d for d in inv.drives if d.is_boot_device]
    return [
        Check(
            id="storage.capacity",
            category=Category.STORAGE,
            title="Datastore capacity (SSD/NVMe)",
            status=status,
            observed=(
                f"{_fmt_tb(flash)} flash, {_fmt_tb(spinning)} HDD across {len(data_drives)} data drive(s)"
            ),
            required=f">= {_fmt_tb(need_bytes)} {media} (incl. Holorouter)",
            remediation=fix,
        ),
        Check(
            id="storage.boot_device",
            category=Category.STORAGE,
            title="Dedicated ESXi boot device",
            status=CheckStatus.PASS if boot else CheckStatus.WARN,
            observed=", ".join(f"{d.model or d.id} on {d.controller}" for d in boot) or "none detected",
            required="Dedicated boot device (e.g. BOSS) recommended",
            remediation=None
            if boot
            else "ESXi will be installed on a data drive, reducing datastore capacity.",
        ),
    ]


def _network(inv: HostInventory, min_speed: int) -> Check:
    up = [p for p in inv.network_ports if p.link_up]
    fast = [p for p in up if (p.speed_mbps or 0) >= min_speed]
    if fast:
        status, fix = CheckStatus.PASS, None
    elif up:
        status, fix = (
            CheckStatus.WARN,
            f"No linked port at >= {min_speed // 1000} GbE; the trunk uplink may bottleneck.",
        )
    else:
        status, fix = (
            CheckStatus.FAIL,
            "No NIC has link. Cable a port to a switch trunk for the Holodeck uplink.",
        )
    if not inv.network_ports:
        status, fix = CheckStatus.UNKNOWN, "No Ethernet interfaces visible via Redfish."
    speeds = ", ".join(f"{p.id}: {p.speed_mbps or '?'} Mb/s" for p in up) or "no links up"
    return Check(
        id="network.uplink",
        category=Category.NETWORK,
        title="Network uplink",
        status=status,
        observed=f"{len(up)}/{len(inv.network_ports)} ports up ({speeds})",
        required=f">= 1 port with link, >= {min_speed // 1000} GbE recommended (trunk, MTU 9000)",
        remediation=fix,
    )


def _flag_check(check_id: str, title: str, value: bool | None, what: str) -> Check:
    if value is None:
        status, fix = CheckStatus.UNKNOWN, f"Could not read the {what} BIOS setting; verify it manually."
    elif value:
        status, fix = CheckStatus.PASS, None
    else:
        status, fix = CheckStatus.FAIL, f"Enable {what} in BIOS setup."
    return Check(
        id=check_id,
        category=Category.BIOS,
        title=title,
        status=status,
        observed={True: "Enabled", False: "Disabled", None: "Not reported"}[value],
        required="Enabled",
        remediation=fix,
    )


def _bios(inv: HostInventory) -> list[Check]:
    mode = (inv.bios.boot_mode or "").upper()
    if "UEFI" in mode:
        boot_status, boot_fix = CheckStatus.PASS, None
    elif mode:
        boot_status, boot_fix = (
            CheckStatus.FAIL,
            "Switch the BIOS boot mode to UEFI before installing ESXi 9.",
        )
    else:
        boot_status, boot_fix = CheckStatus.UNKNOWN, "Boot mode not reported; verify UEFI manually."
    return [
        _flag_check(
            "bios.cpu_virtualization",
            "CPU virtualization (VT-x / AMD-V)",
            inv.bios.cpu_virtualization,
            "processor virtualization",
        ),
        _flag_check("bios.iommu", "IOMMU (VT-d / AMD-Vi)", inv.bios.iommu, "VT-d / IOMMU"),
        Check(
            id="bios.boot_mode",
            category=Category.BIOS,
            title="Boot mode",
            status=boot_status,
            observed=inv.bios.boot_mode or "Not reported",
            required="UEFI",
            remediation=boot_fix,
        ),
    ]


def _bmc(inv: HostInventory) -> list[Check]:
    caps = inv.capabilities
    cd_slots = [s for s in caps.virtual_media if s.is_cd and s.insert_target]
    http_ok = any(
        any(p.upper() in ("HTTP", "HTTPS") for p in s.transfer_protocols) or not s.transfer_protocols
        for s in cd_slots
    )
    if cd_slots and http_ok:
        vm_status, vm_fix = CheckStatus.PASS, None
    elif cd_slots:
        vm_status, vm_fix = CheckStatus.WARN, "Virtual CD found but HTTP/HTTPS transfer is not advertised."
    else:
        vm_status, vm_fix = (
            CheckStatus.FAIL,
            "No Redfish virtual CD with InsertMedia; update BMC firmware or license.",
        )
    targets = {t.upper() for t in caps.boot_override.allowed_targets}
    boot_status = (
        CheckStatus.PASS if "CD" in targets else (CheckStatus.UNKNOWN if not targets else CheckStatus.FAIL)
    )
    resets = set(caps.reset.allowed_types)
    reset_ok = bool(resets & {"ForceRestart", "PowerCycle", "GracefulRestart"}) and "On" in resets
    lic = inv.bmc.license
    if lic is None:
        lic_status, lic_obs = CheckStatus.UNKNOWN, "Not reported"
    else:
        lic_obs = lic.name
        lic_status = {True: CheckStatus.PASS, False: CheckStatus.FAIL, None: CheckStatus.UNKNOWN}[
            lic.supports_virtual_media
        ]
    return [
        Check(
            id="bmc.virtual_media",
            category=Category.BMC,
            title="Redfish virtual media (CD)",
            status=vm_status,
            observed=", ".join(
                f"{s.path} [{'/'.join(s.transfer_protocols) or 'protocols n/a'}]" for s in cd_slots
            )
            or "none",
            required="Virtual CD slot with InsertMedia over HTTP(S)",
            remediation=vm_fix,
        ),
        Check(
            id="bmc.boot_override",
            category=Category.BMC,
            title="One-time boot to virtual CD",
            status=boot_status,
            observed=", ".join(caps.boot_override.allowed_targets) or "allowable targets not reported",
            required="BootSourceOverrideTarget supports 'Cd'",
            remediation=None
            if boot_status == CheckStatus.PASS
            else "Verify boot override support on this BMC.",
        ),
        Check(
            id="bmc.reset",
            category=Category.BMC,
            title="Remote power control",
            status=CheckStatus.PASS
            if reset_ok
            else (CheckStatus.UNKNOWN if not resets else CheckStatus.FAIL),
            observed=", ".join(sorted(resets)) or "not reported",
            required="ComputerSystem.Reset with On and a restart type",
            remediation=None if reset_ok else "Verify ComputerSystem.Reset support on this BMC.",
        ),
        Check(
            id="bmc.license",
            category=Category.BMC,
            title="BMC license allows virtual media",
            status=lic_status,
            observed=lic_obs,
            required="License tier that includes remote virtual media (e.g. iDRAC Enterprise/Datacenter)",
            remediation=None if lic_status == CheckStatus.PASS else "Confirm or upgrade the BMC license.",
        ),
    ]


def _overall(checks: list[Check]) -> tuple[CheckStatus, PreflightSummary]:
    summary = PreflightSummary(
        passed=sum(c.status == CheckStatus.PASS for c in checks),
        warnings=sum(c.status == CheckStatus.WARN for c in checks),
        failed=sum(c.status == CheckStatus.FAIL for c in checks),
        unknown=sum(c.status == CheckStatus.UNKNOWN for c in checks),
    )
    if summary.failed:
        return CheckStatus.FAIL, summary
    if summary.warnings or summary.unknown:
        return CheckStatus.WARN, summary
    return CheckStatus.PASS, summary


def evaluate(inventory: HostInventory, profile_id: str, variant_id: str | None = None) -> PreflightReport:
    profile = load_profile(profile_id)
    variant_id = variant_id or profile.default_variant
    variant = profile.variants.get(variant_id)
    if variant is None:
        raise UnknownProfileError(
            f"Unknown variant '{variant_id}' for {profile_id}; choose from {sorted(profile.variants)}"
        )
    router = profile.holorouter
    need_cores = variant.cores + int(router.get("cores", 0))
    need_mem = variant.memory_gb + router.get("memory_gb", 0)
    need_disk = int(variant.disk_tb * _TB + router.get("disk_gb", 0) * _GB)

    checks = [
        *_compute(inventory, need_cores),
        _memory(inventory, need_mem),
        *_storage(inventory, need_disk, str(profile.host.get("storage_media", "SSD/NVMe"))),
        _network(inventory, int(profile.host.get("min_nic_speed_mbps", 10000))),
        *_bios(inventory),
        *_bmc(inventory),
    ]
    overall, summary = _overall(checks)
    return PreflightReport(
        profile=profile.id,
        variant=variant.id,
        variant_title=variant.title,
        source=profile.source,
        generated_at=utcnow(),
        overall=overall,
        summary=summary,
        checks=checks,
    )
