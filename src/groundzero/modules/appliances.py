"""Appliances: deploy any OVA, with its inputs from a saved profile plus per-deployment overrides.

The descriptor of the chosen OVA decides what is valid (see groundzero.ova). Appliances apply their OVF
settings on first boot only, so changing a deployed appliance means ``replace``: delete it and deploy it
fresh, confirmed with a typed phrase. The Holorouter (groundzero.modules.holodeck) uses the same code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage
from groundzero.esxi.ovf import OvaDeployResult
from groundzero.esxi.vms import VmInfo
from groundzero.isos import Image
from groundzero.modules.base import OS_ACCESS, Deps, Inputs, Module, Prepared, Stage
from groundzero.modules.outputs import ApplianceDeployment, HolorouterDeployment, HostPrep
from groundzero.osconfig import OsConfigError
from groundzero.ova.descriptor import DescriptorError, OvfDescriptor, environment_values, read_ova_descriptor
from groundzero.ova.profiles import ApplianceProfile, ApplianceProfileWrite, check_values

VM_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$"
_IP_KEYS = ("ip", "ip0", "ip_address", "ipaddress", "mgmt_ip", "management_ip")


@dataclass
class AppliancePlan:
    """Everything a deployment needs, resolved and checked before the job is queued."""

    image: Image
    path: Path
    desc: OvfDescriptor
    vm_name: str
    datastore: str
    networks: dict[str, str]
    properties: dict[str, str] = field(repr=False)  # includes passwords: never logged or stored on the job
    profile_id: str | None
    address: str | None


def guess_address(desc: OvfDescriptor, values: dict[str, Any]) -> str | None:
    """The appliance's IP, if one of its properties is plainly the IP (e.g. network.ip, vami.ip0.X)."""
    for p in desc.properties:
        if p.key.lower() in _IP_KEYS and values.get(p.qualified_key):
            return str(values[p.qualified_key])
    return None


def plan_appliance(
    deps: Deps,
    inputs: Inputs,
    *,
    image: Image,
    path: Path,
    vm_name: str,
    profile_id: str | None,
    values: dict[str, Any],
    secrets: dict[str, str],
    networks: dict[str, str],
    datastore: str | None,
    address: str | None,
) -> AppliancePlan:
    """Merge profile and overrides, check them against the OVA, and settle networks and datastore."""
    from groundzero.core.services import NotFoundError, SettingsValidationError  # avoid an import cycle

    desc = read_ova_descriptor(path)
    base_values: dict[str, Any] = {}
    base_secrets: dict[str, str] = {}
    base_networks: dict[str, str] = {}
    if profile_id:
        profile = deps.get_appliance_profile(profile_id)
        if desc.product and profile.product != desc.product:
            raise OsConfigError(f"Profile {profile.name} is for {profile.product}, not {desc.product}")
        base_values, base_networks = dict(profile.values), dict(profile.networks)
        base_secrets = deps.appliance_profile_secrets(profile_id)
    merged_values, merged_secrets, errors = check_values(
        desc, {**base_values, **values}, {**base_secrets, **secrets}, {**base_networks, **networks}
    )
    mapped = {**base_networks, **networks}
    for net in desc.networks:
        if not mapped.get(net.name):
            errors.append(
                {"loc": ["networks", net.name], "msg": "choose a port group for it", "type": "missing"}
            )
    portgroups = inputs.get("os_network", EsxiNetworkConfig, current=True)
    if portgroups is not None:
        known = {pg.name for pg in portgroups.portgroups}
        for name, pg in mapped.items():
            if pg and pg not in known:
                errors.append(
                    {"loc": ["networks", name], "msg": f"no port group {pg!r} on the host", "type": "network"}
                )
    if errors:
        raise SettingsValidationError("params", errors)
    if not datastore:
        prep = inputs.get("host_prep", HostPrep, current=True)
        storage = inputs.get("os_storage", EsxiStorage, current=True)
        vmfs = [d for d in (storage.datastores if storage else []) if d.type == "VMFS"]
        datastore = (prep.datastore if prep else None) or (
            max(vmfs, key=lambda d: d.free_gb or 0).name if vmfs else None
        )
        if not datastore:
            raise NotFoundError("Choose a datastore (params.datastore), or run “Read installed OS” first")
    properties = environment_values(desc, {**merged_values, **merged_secrets})
    return AppliancePlan(
        image=image,
        path=path,
        desc=desc,
        vm_name=vm_name,
        datastore=datastore,
        networks={k: v for k, v in mapped.items() if v},
        properties=properties,
        profile_id=profile_id,
        address=address or guess_address(desc, merged_values),
    )


async def deploy_appliance(
    deps: Deps, host: Host, ctx: JobContext, plan: AppliancePlan, *, replace: bool
) -> OvaDeployResult:
    """Upload and start the appliance (the "deploy" step); raises if an existing VM lacks its settings."""
    access, password = deps.os_access(host.id)
    loop = asyncio.get_running_loop()

    def progress(fraction: float, message: str) -> None:  # called from the upload thread
        loop.call_soon_threadsafe(ctx.progress, fraction, message)

    target = await asyncio.to_thread(deps.os_target, host.id, access)
    async with ctx.step("deploy", f"Deploy {plan.image.filename}") as step:
        result = await deps.esxi.deploy_ova(
            target,
            password,
            plan.path,
            vm_name=plan.vm_name,
            datastore=plan.datastore,
            networks=plan.networks,
            properties=plan.properties,
            progress=progress,
            replace=replace,
        )
        verb = "replaced and uploaded" if result.replaced else "uploaded"
        step.message = (
            f"{verb} {result.uploaded_bytes / 1e9:.2f} GB in {result.seconds / 60:.0f} min"
            if result.created
            else result.message
        )
        if not result.settings_applied:
            raise OsConfigError(result.message)
    return result


def resolve_image(deps: Deps, image_id: str) -> tuple[Image, Path]:
    from groundzero.core.services import NotFoundError  # avoid an import cycle

    resolved = deps.isos.resolve(image_id)
    if resolved is None or resolved[0].kind != "ova":
        raise NotFoundError(f"OVA {image_id} is not in the image repository (GET /images)")
    return resolved


class DeployParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str = Field(description="The OVA to deploy (GET /images)")
    vm_name: str = Field(pattern=VM_NAME, description="Name of the VM on the host")
    profile_id: str | None = Field(default=None, description="Appliance profile with the OVA's values")
    values: dict[str, Any] = Field(default_factory=dict, description="Overrides of the profile's values")
    secrets: dict[str, str] = Field(
        default_factory=dict, description="Password overrides (never stored on the job)"
    )
    networks: dict[str, str] = Field(default_factory=dict, description="OVF network → port group overrides")
    datastore: str | None = Field(
        default=None, description="Default: Host preparation's, else the freest VMFS"
    )
    replace: bool = Field(
        default=False, description='Delete a VM of the same name first (confirm "replace <vm>")'
    )
    wait_port: int | None = Field(
        default=None, ge=1, le=65535, description="Wait until this TCP port answers"
    )
    address: str | None = Field(
        default=None, description="The appliance's IP (default: read from its values)"
    )


class ApplianceDeploy(Module):
    id = "appliance.deploy"
    title = "Deploy appliance"
    stage = Stage.APPLIANCES
    description = "Deploy any OVA with a saved profile and per-deployment values; repeat for each appliance."
    produces = "appliance"
    requires = (OS_ACCESS,)
    uses = ("os_network", "os_storage", "host_prep")
    os_bound = True
    optional = True
    Params = DeployParams

    def summarize(self, data: dict[str, Any]) -> str:
        where = f" at {data['ip']}" if data.get("ip") else ""
        what = f"{data.get('product') or data.get('image')} {data.get('version') or ''}".strip()
        return f"{data['vm_name']}{where} · {what}"

    def prepare(
        self, deps: Deps, host: Host, params: DeployParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        from groundzero.core.services import ConfirmationError  # avoid an import cycle

        if params.replace and confirm != f"replace {params.vm_name}":
            raise ConfirmationError(
                f'Replacing deletes the VM first: confirm with exactly "replace {params.vm_name}"'
            )
        deps.os_access(host.id)  # a clear 404 before anything else
        image, path = resolve_image(deps, params.image_id)
        plan = plan_appliance(
            deps,
            inputs,
            image=image,
            path=path,
            vm_name=params.vm_name,
            profile_id=params.profile_id,
            values=params.values,
            secrets=params.secrets,
            networks=params.networks,
            datastore=params.datastore,
            address=params.address,
        )

        async def run(ctx: JobContext) -> dict[str, Any]:
            steps = [("deploy", f"Deploy {image.filename}")]
            if params.wait_port and plan.address:
                steps.append(("wait", f"Wait for {plan.address}:{params.wait_port}"))
            ctx.plan(steps)
            result = await deploy_appliance(deps, host, ctx, plan, replace=params.replace)
            if params.wait_port and plan.address:
                async with ctx.step("wait", f"Wait for {plan.address}:{params.wait_port}") as step:
                    await deps.wait_for_port(plan.address, params.wait_port, minutes=20, ctx=ctx)
                    step.message = f"{plan.address}:{params.wait_port} answers"
            output = ApplianceDeployment(
                vm_name=plan.vm_name,
                product=plan.desc.product,
                version=plan.desc.version or image.version,
                image=image.filename,
                profile_id=plan.profile_id,
                ip=plan.address,
                datastore=plan.datastore,
                networks=plan.networks,
                created=result.created,
                replaced=result.replaced,
                powered_on=result.powered_on,
            )
            deps.save_output(host.id, "appliance", ctx.job.id, output)
            deps.save_output(host.id, f"appliance:{plan.vm_name}", ctx.job.id, output)
            return {"appliance": output.model_dump(mode="json")}

        return Prepared(run, params.model_dump(exclude={"secrets"}) | {"datastore": plan.datastore})


def match_ova(deps: Deps, env: dict[str, str]) -> tuple[Image, OvfDescriptor] | None:
    """The repository OVA whose properties best explain a VM's OVF settings (newest wins a tie)."""
    best: tuple[float, tuple[str, str], Image, OvfDescriptor] | None = None
    for image in deps.isos.list():
        if image.kind != "ova":
            continue
        resolved = deps.isos.resolve(image.id)
        if resolved is None:
            continue
        try:
            desc = read_ova_descriptor(resolved[1])
        except DescriptorError:
            continue
        declared = {p.qualified_key for p in desc.properties}
        if not declared or not env:
            continue
        known = len(set(env) & declared) / len(set(env))  # how much of the VM's settings this OVA declares
        if known < 0.9:
            continue
        rank = (known, (image.version or "", image.build or ""))
        if best is None or rank > (best[0], best[1]):
            best = (known, rank[1], image, desc)
    return (best[2], best[3]) if best else None


def identify(deps: Deps, vm: VmInfo, chosen: tuple[Image, Path] | None) -> tuple[Image, OvfDescriptor]:
    """The OVA a VM came from: the one chosen, else matched by its OVF settings."""
    if chosen is not None:
        return chosen[0], read_ova_descriptor(chosen[1])
    if not vm.ovf_env:
        raise OsConfigError(f"{vm.name} has no OVF settings to read; choose its OVA (params.image_id)")
    found = match_ova(deps, vm.ovf_env)
    if found is None:
        raise OsConfigError(
            f"No OVA in the image repository declares {vm.name}'s settings; "
            "add its OVA and rescan, or choose one (params.image_id)"
        )
    return found


def capture_profile(
    deps: Deps, host: Host, vm: VmInfo, chosen: tuple[Image, Path] | None, name: str
) -> tuple[ApplianceProfile, list[str], str]:
    """Save a VM's user-configurable OVF values and networks as a profile. Passwords are never copied."""
    image, desc = identify(deps, vm, chosen)
    by_key = {p.qualified_key: p for p in desc.properties}
    values = {
        k: v
        for k, v in vm.ovf_env.items()
        if k in by_key and by_key[k].user_configurable and not by_key[k].password and v != ""
    }
    networks = {
        n.name: nic.portgroup for n, nic in zip(desc.networks, vm.nics, strict=False) if nic.portgroup
    }
    profile = deps.save_appliance_profile(
        ApplianceProfileWrite(name=name, image_id=image.id, values=values, networks=networks),
        source=f"captured from {vm.name} on {host.name}",
    )
    skipped = sorted(k for k, p in by_key.items() if p.password and vm.ovf_env.get(k))
    return profile, skipped, f"{len(values)} values, {len(networks)} networks"


class CaptureParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vm_name: str = Field(description="A VM on the host (one you deployed, or one GroundZero did)")
    name: str = Field(min_length=1, max_length=80, description="Name for the new appliance profile")
    image_id: str | None = Field(
        default=None, description="The OVA it came from; default: matched by the VM's OVF settings"
    )


class ApplianceCapture(Module):
    id = "appliance.capture"
    title = "Capture appliance profile"
    stage = Stage.APPLIANCES
    description = "Read a VM's OVF settings and networks (read-only) and save them as an appliance profile."
    requires = (OS_ACCESS,)
    optional = True
    Params = CaptureParams

    def prepare(
        self, deps: Deps, host: Host, params: CaptureParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        from groundzero.core.services import ConflictError  # avoid an import cycle

        if deps.store.find_appliance_profile_by_name(params.name):
            raise ConflictError(f"An appliance profile named '{params.name}' already exists")
        access, password = deps.os_access(host.id)
        chosen = resolve_image(deps, params.image_id) if params.image_id else None

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan([("read", f"Read {params.vm_name}"), ("save", "Save the profile")])
            async with ctx.step("read", f"Read {params.vm_name}") as step:
                target = await asyncio.to_thread(deps.os_target, host.id, access)
                vm = await deps.esxi.read_vm(target, password, params.vm_name)
                step.message = f"{len(vm.ovf_env)} OVF settings, {len(vm.nics)} network adapters"
            async with ctx.step("save", "Save the profile") as step:
                profile, skipped, counts = capture_profile(deps, host, vm, chosen, params.name)
                step.message = f"{profile.name}: {counts}" + (
                    f"; passwords not copied ({', '.join(skipped)})" if skipped else ""
                )
            return {"profile_id": profile.id, "product": profile.product, "passwords_not_copied": skipped}

        return Prepared(run, params.model_dump())


class AdoptParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vm_name: str = Field(description="A VM already on the host, e.g. one you deployed by hand")
    role: Literal["appliance", "holorouter"] = Field(
        default="appliance", description="holorouter: record it as the Holorouter that Holodeck steps use"
    )
    profile_name: str | None = Field(default=None, description="Also capture its settings as this profile")
    image_id: str | None = Field(default=None, description="The OVA it came from; default: matched")


class ApplianceAdopt(Module):
    id = "appliance.adopt"
    title = "Adopt existing VM"
    stage = Stage.APPLIANCES
    description = (
        "Record a VM that is already on the host (read-only), so later steps use it as if GroundZero had "
        "deployed it."
    )
    requires = (OS_ACCESS,)
    also_produces = ("holorouter",)
    produces = "appliance"
    os_bound = True
    optional = True
    Params = AdoptParams

    def summarize(self, data: dict[str, Any]) -> str:
        return ApplianceDeploy().summarize(data)

    def prepare(
        self, deps: Deps, host: Host, params: AdoptParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        from groundzero.core.services import ConflictError  # avoid an import cycle

        if params.profile_name and deps.store.find_appliance_profile_by_name(params.profile_name):
            raise ConflictError(f"An appliance profile named '{params.profile_name}' already exists")
        access, password = deps.os_access(host.id)
        chosen = resolve_image(deps, params.image_id) if params.image_id else None

        async def run(ctx: JobContext) -> dict[str, Any]:
            steps = [("read", f"Read {params.vm_name}")]
            if params.role == "holorouter":
                steps.append(("ssh", "Check that it answers on SSH"))
            steps.append(("record", "Record it"))
            ctx.plan(steps)
            async with ctx.step("read", f"Read {params.vm_name}") as step:
                target = await asyncio.to_thread(deps.os_target, host.id, access)
                vm = await deps.esxi.read_vm(target, password, params.vm_name)
                found = None
                if chosen is not None or vm.ovf_env:
                    try:
                        found = identify(deps, vm, chosen)
                    except OsConfigError:
                        found = None  # still adoptable: it just isn't one of the repository's OVAs
                address = vm.ovf_env.get("network.ip") or vm.guest_ip
                step.message = f"{vm.power_state}, {address or 'no IP reported'}" + (
                    f", {found[1].product}" if found else ""
                )
            if params.role == "holorouter":
                if not address:
                    raise OsConfigError(f"{params.vm_name} reports no IP (is VMware Tools running?)")
                async with ctx.step("ssh", "Check that it answers on SSH") as step:
                    await deps.wait_for_port(address, 22, minutes=2, ctx=ctx)
                    step.message = f"{address}:22 answers"
            async with ctx.step("record", "Record it") as step:
                image, desc = found if found else (None, None)
                ds_networks = (
                    {n.name: nic.portgroup for n, nic in zip(desc.networks, vm.nics, strict=False)}
                    if desc
                    else {nic.label: nic.portgroup for nic in vm.nics}
                )
                output = ApplianceDeployment(
                    vm_name=vm.name,
                    product=desc.product if desc else None,
                    version=(desc.version or image.version) if desc and image else None,
                    image=image.filename if image else "",
                    ip=address,
                    datastore=vm.datastore,
                    networks={k: v for k, v in ds_networks.items() if v},
                    created=False,
                    powered_on=vm.power_state == "poweredOn",
                )
                deps.save_output(host.id, "appliance", ctx.job.id, output, source="adopted")
                deps.save_output(host.id, f"appliance:{vm.name}", ctx.job.id, output, source="adopted")
                result: dict[str, Any] = {"appliance": output.model_dump(mode="json")}
                if params.role == "holorouter":
                    router = HolorouterDeployment(
                        vm_name=vm.name,
                        ip=address or "",
                        hostname=vm.ovf_env.get("network.hostname") or vm.name,
                        version=output.version,
                        image=output.image,
                        datastore=vm.datastore,
                        networks=output.networks,
                        created=False,
                        webtop_url=f"http://{address}:30000"
                        if vm.ovf_env.get("extra.webtop_enabled", "").lower() == "true"
                        else None,
                    )
                    deps.save_output(host.id, "holorouter", ctx.job.id, router, source="adopted")
                    result["holorouter"] = router.model_dump(mode="json")
                step.message = (
                    f"recorded as {'the Holorouter' if params.role == 'holorouter' else 'an appliance'}"
                )
                if params.profile_name:
                    profile, _skipped, counts = capture_profile(deps, host, vm, chosen, params.profile_name)
                    step.message += f"; profile {profile.name} ({counts})"
                    result["profile_id"] = profile.id
            return result

        return Prepared(run, params.model_dump())
