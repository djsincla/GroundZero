"""ESXi changes for host preparation, over the vSphere API (pyVmomi). Blocking: run in a worker thread.

Every function is idempotent: it reads the live state first, does nothing when the target is already
satisfied, and returns a ``ChangeRecord`` with what it found and what it left. Formatting a disk is
refused unless the disk is *still* unused (no datastore, no partitions) at the moment of the change.
"""

from __future__ import annotations

from typing import Any

from groundzero.esxi.models import ChangeRecord
from groundzero.esxi.reader import EsxiError

_SECURITY_FIELDS = (
    ("allow_promiscuous", "allowPromiscuous"),
    ("mac_changes", "macChanges"),
    ("forged_transmits", "forgedTransmits"),
)


def set_vswitch_mtu(host: Any, vswitch: str, mtu: int) -> ChangeRecord:
    ns = host.configManager.networkSystem
    current = next((v for v in ns.networkInfo.vswitch or [] if v.name == vswitch), None)
    if current is None:
        raise EsxiError(f"No standard switch named {vswitch}")
    before = f"MTU {current.mtu}"
    if current.mtu == mtu:
        return ChangeRecord(action="set_mtu", target=vswitch, changed=False, before=before, after=before)
    spec = current.spec
    spec.mtu = mtu
    ns.UpdateVirtualSwitch(vswitchName=vswitch, spec=spec)
    return ChangeRecord(action="set_mtu", target=vswitch, changed=True, before=before, after=f"MTU {mtu}")


def _security_text(policy: Any) -> str:
    sec = getattr(policy, "security", None) if policy else None
    if sec is None:
        return "security inherited"
    return ", ".join(f"{label}={_flag(getattr(sec, attr))}" for label, attr in _SECURITY_FIELDS)


def _flag(value: bool | None) -> str:
    return "inherit" if value is None else "Accept" if value else "Reject"


def ensure_portgroup(
    host: Any, name: str, vswitch: str, vlan: int, security: dict[str, bool] | None = None
) -> ChangeRecord:
    """Create the port group, or bring an existing one to this VLAN/switch/security."""
    import pyVmomi

    vim: Any = pyVmomi.vim  # untyped library

    ns = host.configManager.networkSystem
    existing = next((p for p in ns.networkInfo.portgroup or [] if p.spec.name == name), None)
    target = f"{name} on {vswitch}"
    # Compare against the live spec *before* building the new one (building mutates policy objects).
    before = "absent"
    if existing is not None:
        if existing.spec.vswitchName != vswitch:
            raise EsxiError(f"Port group {name} exists on {existing.spec.vswitchName}, not {vswitch}")
        before = f"VLAN {existing.spec.vlanId} on {vswitch}, {_security_text(existing.spec.policy)}"
        current = getattr(existing.spec.policy, "security", None)
        same_sec = security is None or all(
            getattr(current, attr, None) == security[key] for key, attr in _SECURITY_FIELDS if key in security
        )
        if existing.spec.vlanId == vlan and same_sec:
            return ChangeRecord(
                action="ensure_portgroup", target=target, changed=False, before=before, after=before
            )
    policy = existing.spec.policy if existing else vim.host.NetworkPolicy()
    if security:
        sec = policy.security or vim.host.NetworkPolicy.SecurityPolicy()
        for key, attr in _SECURITY_FIELDS:
            if key in security:
                setattr(sec, attr, security[key])
        policy.security = sec
    after = f"VLAN {vlan}, {_security_text(policy)}"
    if existing is None:
        spec = vim.host.PortGroup.Specification(name=name, vlanId=vlan, vswitchName=vswitch, policy=policy)
        ns.AddPortGroup(portgrp=spec)
    else:
        spec = existing.spec
        spec.vlanId = vlan
        spec.policy = policy
        ns.UpdatePortGroup(pgName=name, portgrp=spec)
    return ChangeRecord(action="ensure_portgroup", target=target, changed=True, before=before, after=after)


def configure_ntp(host: Any, servers: list[str], policy: str = "on") -> ChangeRecord:
    import pyVmomi

    vim: Any = pyVmomi.vim  # untyped library

    current = list(host.config.dateTimeInfo.ntpConfig.server or []) if host.config.dateTimeInfo else []
    svc = host.configManager.serviceSystem
    ntpd = next((s for s in svc.serviceInfo.service or [] if s.key == "ntpd"), None)
    if ntpd is None:
        raise EsxiError("This host has no ntpd service")
    before = f"servers={','.join(current) or 'none'} running={ntpd.running} policy={ntpd.policy}"
    changed = False
    if current != servers:
        host.configManager.dateTimeSystem.UpdateDateTimeConfig(
            config=vim.host.DateTimeConfig(ntpConfig=vim.host.NtpConfig(server=servers))
        )
        changed = True
    if ntpd.policy != policy:
        svc.UpdateServicePolicy(id="ntpd", policy=policy)
        changed = True
    if not ntpd.running:
        svc.StartService(id="ntpd")
        changed = True
    elif current != servers:
        svc.RestartService(id="ntpd")
    after = f"servers={','.join(servers)} running=True policy={policy}"
    return ChangeRecord(
        action="configure_ntp",
        target="ntpd",
        changed=changed,
        before=before,
        after=after if changed else before,
    )


def create_vmfs_datastore(host: Any, disk: str, name: str) -> ChangeRecord:
    """Format an unused disk as a VMFS datastore. Refuses if the disk gained a datastore or partitions."""
    ds_sys = host.configManager.datastoreSystem
    for ds in host.datastore or []:
        if ds.summary.name == name:
            vmfs = getattr(ds.info, "vmfs", None)
            extents = [e.diskName for e in (vmfs.extent if vmfs else [])]
            if disk in extents:
                return ChangeRecord(
                    action="create_datastore",
                    target=name,
                    changed=False,
                    before=f"{name} already on {disk}",
                    after=f"{name} on {disk}",
                )
            raise EsxiError(f"A datastore named {name} already exists on another disk")
    candidates = {d.canonicalName: d for d in ds_sys.QueryAvailableDisksForVmfs() or []}
    lun = candidates.get(disk)
    if lun is None:
        raise EsxiError(f"Disk {disk} is no longer available for a new datastore; assess again")
    info = host.configManager.storageSystem.RetrieveDiskPartitionInfo(devicePath=[lun.devicePath])
    if info and info[0].spec.partition:
        raise EsxiError(
            f"Disk {disk} now has {len(info[0].spec.partition)} partitions; refusing to format it"
        )
    options = ds_sys.QueryVmfsDatastoreCreateOptions(devicePath=lun.devicePath)
    if not options:
        raise EsxiError(f"ESXi offered no way to create a VMFS datastore on {disk}")
    spec = options[0].spec
    spec.vmfs.volumeName = name
    ds_sys.CreateVmfsDatastore(spec=spec)
    return ChangeRecord(
        action="create_datastore",
        target=name,
        changed=True,
        before=f"{disk}: unused",
        after=f"VMFS datastore {name} on {disk}",
    )
