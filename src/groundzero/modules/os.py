"""Operating system stage: deploy ESXi (two ways), read it, capture its settings as a config set."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import ConfigSetWrite, Host
from groundzero.install.job import InstallConfig, Installer, InstallRequest, InstallTimings
from groundzero.modules.base import OS_ACCESS, Deps, Inputs, Module, Prepared, Stage
from groundzero.modules.dns import require_dns
from groundzero.modules.outputs import StorageReport
from groundzero.osconfig import OsConfigError
from groundzero.osconfig.esxi import EsxiHostValues, EsxiPlugin, EsxiSettings
from groundzero.preflight.evaluate import UnknownProfileError, load_profile


class InstallParams(InstallRequest):
    """An install request without the confirmation (that travels separately, as for every task)."""

    model_config = ConfigDict(extra="ignore")

    confirm: str = Field(default="", exclude=True)
    skip_dns_check: bool = Field(
        default=False, description="Install even if the cluster requires a passing DNS check"
    )


def resolve_iso(deps: Deps, req: InstallRequest) -> Path:
    from groundzero.core.services import NotFoundError

    if req.iso_id:
        resolved = deps.isos.resolve(req.iso_id)
        if resolved is None:
            raise NotFoundError(
                f"ISO {req.iso_id} is not in the repository; rescan or check {deps.settings.iso_dir}"
            )
        image, path = resolved
        if image.os_family != EsxiPlugin.family:
            raise OsConfigError(f"{image.filename} is not an ESXi installer ISO")
        return path
    if req.iso_path and Path(req.iso_path).is_file():
        return Path(req.iso_path)
    raise NotFoundError(f"ISO not found: {req.iso_path or req.iso_id}")


def install_config(
    deps: Deps, host: Host, req: InstallRequest, os_password: str | None
) -> InstallConfig | None:
    """The config set + this server's values + root password, or None to keep the current settings."""
    if req.config_set_id is None:
        return None
    config_set = deps.get_config_set(req.config_set_id)
    if config_set.os_family != EsxiPlugin.family:
        raise OsConfigError(f"Config set '{config_set.name}' is for {config_set.os_family}, not ESXi")
    raw_values = req.host_values or deps.store.get_host_values(host.id, EsxiPlugin.family)
    if raw_values is None:
        raise OsConfigError(
            f"Per-server values (hostname, ip) are needed for {host.name}: pass host_values, "
            "set them for the host, or capture from its running OS"
        )
    values = EsxiHostValues.model_validate(deps.validate_values(EsxiHostValues, raw_values, "host_values"))
    root_password = deps.config_set_secrets(config_set.id).get("root_password") or os_password
    if not root_password:
        raise OsConfigError(
            f"Config set '{config_set.name}' has no root password and the host has no OS access"
        )
    settings = EsxiSettings.model_validate(config_set.settings)
    boot_volume_match = None
    if settings.install_disk.mode == "boot-volume":
        storage = Inputs(deps.store, host.id).get("storage", StorageReport)
        if storage is None or storage.boot_volume is None or not storage.boot_volume.install_match:
            found = storage.boot_volume if storage else None
            raise OsConfigError(
                f"Config set '{config_set.name}' installs to the boot volume, but "
                + (
                    f"the installer can't be told how to find {found.name or found.volume_id} "
                    f"on {found.controller_model}: use a first-match or exact disk rule"
                    if found
                    else f"no boot volume has been read on {host.name}: run Read storage first"
                )
            )
        boot_volume_match = storage.boot_volume.install_match
    return InstallConfig(
        settings=settings, values=values, root_password=root_password, boot_volume_match=boot_volume_match
    )


class _DeployOs(Module):
    stage = Stage.OS
    produces = "install"
    also_produces = ("os_network",)
    uses = ("dns", "storage")
    optional = True
    destructive = True
    Params = InstallParams

    def summarize(self, data: dict[str, Any]) -> str:
        target = f"ESXi {data.get('iso_version')} build {data.get('iso_build')}"
        if data.get("installed_build") and all(c.get("ok") for c in data.get("validation", [])):
            return f"{target} installed and validated" + _iso_settings(data.get("spec") or {})
        return f"{target}: did not complete (still on {data.get('previous_build') or '?'})"

    def prepare(
        self, deps: Deps, host: Host, params: InstallParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        """Reinstall ESXi on the host. Destructive: requires the exact confirmation phrase."""
        from groundzero.core.services import ConfirmationError, NotFoundError

        if self.id == "os.custom" and not params.config_set_id:
            raise OsConfigError(
                "Deploy OS · custom ISO from a config set needs a config set (params.config_set_id)"
            )
        if self.id == "os.reimage" and params.config_set_id:
            raise OsConfigError(
                "os.reimage builds the ISO from the current settings; use os.custom for a config set"
            )
        expected = f"install {host.name}"
        if confirm != expected:
            raise ConfirmationError(f'Confirmation must be exactly "{expected}"')
        req = InstallRequest.model_validate({**params.model_dump(), "confirm": confirm})
        req = req.model_copy(update={"iso_path": str(resolve_iso(deps, req))})
        profile = load_profile(req.profile)  # bad profile/variant is a 4xx, not a failed job
        if req.variant is not None and req.variant not in profile.variants:
            raise UnknownProfileError(
                f"Unknown variant '{req.variant}'; choose from {sorted(profile.variants)}"
            )
        stored = deps.stored_os_access(host.id)
        access = stored[0] if stored else None
        os_password = stored[1] if stored else None
        config = install_config(deps, host, req, os_password)
        if config is None and access is None:
            raise NotFoundError(
                f"No OS access configured for host {host.id}; set it, or install with a config set"
            )
        if config is not None and not params.skip_dns_check:
            require_dns(deps, host, inputs, config.values.hostname, config.values.ip)
        if config is not None:
            deps.store.set_host_values(host.id, EsxiPlugin.family, config.values.model_dump(mode="json"))
        s = deps.settings
        installer = Installer(
            host=host,
            bmc_password=deps.bmc_password(host.id),
            os_access=access,
            resolve_os=lambda a: deps.os_target(host.id, a),
            repin_os=lambda a: deps.os_target(host.id, a, repin=True),
            os_password=os_password,
            request=req,
            config=config,
            client_factory=deps.client_factory,
            esxi=deps.esxi,
            media=deps.media,
            media_dir=s.media_dir,
            media_base_url=s.media_public_url,
            media_port=s.media_port,
            timings=InstallTimings(
                poll_seconds=s.install_poll_seconds,
                action_timeout=s.redfish_action_timeout,
                media_settle_seconds=s.media_settle_seconds,
                cleanup_watch_seconds=s.media_cleanup_watch_seconds,
                media_attach_seconds=s.media_attach_seconds,
                installer_boot_minutes=s.installer_boot_minutes,
            ),
        )

        async def run(ctx: JobContext) -> dict[str, Any]:
            try:
                result = await installer.run(ctx)
                # A new OS: anything read from the previous one (network, readiness, prep) is now stale,
                # and it has a new SSH host key (the TLS certificate was re-pinned during the install).
                deps.store.bump_os_epoch(host.id)
                deps.store.delete_pin(host.id, "os-ssh")
                if installer.last_network is not None:
                    # Keep the host's "installed OS" view current without an extra read.
                    deps.save_output(host.id, "os_network", ctx.job.id, installer.last_network)
                if config is not None:  # the host now answers at the configured IP with the set's password
                    deps.save_os_access(host.id, installer.new_access, config.root_password)
            finally:
                if installer.last_report is not None:
                    deps.save_output(host.id, "install", ctx.job.id, installer.last_report)
            return result

        return Prepared(run, req.model_dump(exclude={"confirm", "host_values"}))


class OsReimage(_DeployOs):
    id = "os.reimage"
    title = "Deploy OS · custom ISO from current settings"
    description = (
        "Reinstall ESXi with a custom ISO built from a stock one. Settings come from the running OS "
        "(IP, VLAN, uplinks, boot disk) plus the options you choose (NTP, CPU override, VMFS)."
    )
    requires = (OS_ACCESS,)


class OsCustom(_DeployOs):
    id = "os.custom"
    title = "Deploy OS · custom ISO from a config set"
    description = (
        "Install ESXi with a custom ISO built from a stock one. Settings come from a saved config set "
        "plus this server's own values (hostname, IP); no running OS needed."
    )


def _iso_settings(spec: dict[str, Any]) -> str:
    """' · custom ISO: VLAN 100, vmnic0 + vmnic1, NTP pool.ntp.org, VMFS kept, CPU override'."""
    net = spec.get("network")
    if not net:
        return ""
    parts = [
        f"VLAN {net.get('vlan_id') or 'untagged'}",
        " + ".join([net.get("install_nic", "?"), *net.get("extra_uplinks", [])]),
    ]
    if spec.get("ntp_servers"):
        parts.append("NTP " + ", ".join(spec["ntp_servers"]))
    parts.append("VMFS kept" if spec.get("preserve_vmfs") else "VMFS overwritten")
    if spec.get("allow_legacy_cpu"):
        parts.append("CPU override")
    return " · custom ISO: " + ", ".join(parts)


class OsRead(Module):
    id = "os.read"
    title = "Read installed OS"
    stage = Stage.OS
    description = "Read the running hypervisor's network, NTP and storage (read-only)."
    produces = "os_network"
    also_produces = ("os_storage",)
    requires = (OS_ACCESS,)
    os_bound = True
    optional = True

    def summarize(self, data: dict[str, Any]) -> str:
        mgmt = next((v for v in data.get("vmkernel", []) if "management" in v.get("services", [])), None)
        return f"{data['product']} at {(mgmt or {}).get('ip') or data.get('address')}"

    def prepare(self, deps: Deps, host: Host, params: Any, inputs: Inputs, confirm: str | None) -> Prepared:
        access, password = deps.os_access(host.id)

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [
                    ("connect", "Connect to the OS"),
                    ("network", "Read network and NTP"),
                    ("storage", "Read disks and datastores"),
                ]
            )
            async with ctx.step("connect", "Connect to the OS"):
                target = await asyncio.to_thread(deps.os_target, host.id, access)
            async with ctx.step("network", "Read network and NTP"):
                ctx.progress(0.3, f"Reading network configuration from {access.address}")
                config = await deps.esxi.read_network(target, password)
            async with ctx.step("storage", "Read disks and datastores"):
                ctx.progress(0.7, f"Reading storage from {access.address}")
                storage = await deps.esxi.read_storage(target, password)
            deps.save_output(host.id, "os_network", ctx.job.id, config)
            deps.save_output(host.id, "os_storage", ctx.job.id, storage)
            return {
                "os_network": config.model_dump(mode="json"),
                "os_storage": storage.model_dump(mode="json"),
            }

        return Prepared(run)


class CaptureParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, description="Name for the new config set")


class OsCapture(Module):
    id = "os.capture"
    title = "Capture config set"
    stage = Stage.OS
    description = "Save the running hypervisor's settings as a reusable config set (read-only)."
    requires = (OS_ACCESS,)
    optional = True
    Params = CaptureParams

    def prepare(
        self, deps: Deps, host: Host, params: CaptureParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        from groundzero.core.services import ConflictError

        name = params.name
        if deps.store.find_config_set_by_name(name):
            raise ConflictError(f"A config set named '{name}' already exists")
        access, password = deps.os_access(host.id)

        async def run(ctx: JobContext) -> dict[str, Any]:
            async with ctx.step("read", "Read the running OS"):
                ctx.progress(0.2, f"Reading configuration from {access.address}")
                target = await asyncio.to_thread(deps.os_target, host.id, access)
                network = await deps.esxi.read_network(target, password)
                storage = await deps.esxi.read_storage(target, password)
            captured = EsxiPlugin.capture(network, storage)
            ctx.progress(0.8, "Saving config set")
            config_set = deps.create_config_set(
                ConfigSetWrite(
                    name=name, os_family=EsxiPlugin.family, settings=captured.settings, root_password=password
                ),
                source=f"captured from {host.name} ({access.address})",
            )
            deps.store.set_host_values(host.id, EsxiPlugin.family, captured.host_values)
            return {"config_set_id": config_set.id, "host_values": captured.host_values}

        return Prepared(run, {"name": name})
