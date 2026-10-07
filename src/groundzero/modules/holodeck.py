"""Holodeck stage: the Holorouter appliance, then (planned) staging binaries and the Holodeck deploy."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.modules.appliances import deploy_appliance, plan_appliance, resolve_image
from groundzero.modules.base import Deps, Inputs, Module, Prepared, Stage
from groundzero.modules.outputs import HolorouterDeployment, HostPrep
from groundzero.osconfig import OsConfigError
from groundzero.osconfig.holodeck import HolodeckHostValues, HolodeckPlugin
from groundzero.readiness import ReadinessReport


class HolorouterParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile_id: str = Field(default="", description="HoloRouter appliance profile (GET /appliance-profiles)")
    image_id: str | None = Field(
        default=None, description="Holorouter OVA; default: the newest in the repository"
    )
    values: dict[str, Any] = Field(default_factory=dict, description="Overrides of the profile's values")
    replace: bool = Field(
        default=False, description='Delete an existing Holorouter VM first (confirm "replace <vm>")'
    )


class Holorouter(Module):
    id = "holodeck.router"
    title = "Deploy Holorouter"
    stage = Stage.HOLODECK
    description = "Deploy and start the Holorouter appliance on the prepared datastore and port groups."
    produces = "holorouter"
    requires = ("readiness", "host_prep")
    os_bound = True
    Params = HolorouterParams

    def summarize(self, data: dict[str, Any]) -> str:
        return f"{data.get('vm_name')} at {data.get('ip')} · Holorouter {data.get('version')}"

    def prepare(
        self, deps: Deps, host: Host, params: HolorouterParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        """The Holorouter is an appliance deployment with Holodeck's networks and this host's IP."""
        from groundzero.core.services import ConfirmationError, ConflictError, NotFoundError  # import cycle

        deps.os_access(host.id)
        if not params.profile_id:
            raise OsConfigError("Choose a HoloRouter appliance profile (params.profile_id)")
        stored_values = deps.store.get_host_values(host.id, HolodeckPlugin.family)
        if stored_values is None:
            raise OsConfigError("Set this host's Holodeck values first (Holorouter IP, instance ID)")
        values = HolodeckHostValues.model_validate(stored_values)
        vm_name = f"{values.instance_id}-holorouter"
        if params.replace and confirm != f"replace {vm_name}":
            raise ConfirmationError(
                f'Replacing deletes the Holorouter first: confirm with exactly "replace {vm_name}"',
                f"replace {vm_name}",
            )
        readiness = inputs.require("readiness", ReadinessReport, "Assess Holodeck readiness first")
        if not readiness.ready:
            raise ConflictError("The host is not ready for Holodeck yet; see the readiness report")
        prep = inputs.get("host_prep", HostPrep)
        if prep is None or not prep.trunk_portgroup or not prep.external_portgroup:
            raise ConflictError("Prepare host must have created the trunk and external port groups")
        if params.image_id:
            image, path = resolve_image(deps, params.image_id)
        else:
            images = [i for i in deps.isos.list() if i.os_family == "holorouter"]
            if not images:
                raise NotFoundError(f"No Holorouter OVA in the image repository ({deps.settings.iso_dir})")
            image, path = resolve_image(deps, max(images, key=lambda i: (i.version or "", i.build or "")).id)
        plan = plan_appliance(
            deps,
            inputs,
            image=image,
            path=path,
            vm_name=vm_name,
            profile_id=params.profile_id,
            # this host's Holorouter: its own IP and hostname; SSH on, so GroundZero can reach it
            values={
                "network.ip": values.holorouter_ip,
                "network.hostname": values.holorouter_hostname,
                "extra.ssh_enabled": True,
                **params.values,
            },
            secrets={},
            networks={
                "VM Management Network": prep.external_portgroup,
                "Trunk Portgroup for Site A": prep.trunk_portgroup,
                "Trunk Portgroup for Site B": prep.trunk_portgroup,
            },
            datastore=prep.datastore or readiness.storage.datastore,
            address=values.holorouter_ip,
        )
        if "network.password" not in plan.properties or not plan.properties["network.password"]:
            raise OsConfigError("The HoloRouter profile has no password; set it in the profile")
        webtop = plan.properties.get("extra.webtop_enabled", "").lower() == "true"

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [("deploy", f"Deploy {image.filename}"), ("ssh", "Wait for the Holorouter to answer on SSH")]
            )
            result = await deploy_appliance(deps, host, ctx, plan, replace=params.replace)
            async with ctx.step("ssh", "Wait for the Holorouter to answer on SSH") as step:
                await deps.wait_for_port(values.holorouter_ip, 22, minutes=20, ctx=ctx)
                step.message = f"{values.holorouter_ip}:22 answers"
            output = HolorouterDeployment(
                vm_name=vm_name,
                ip=values.holorouter_ip,
                hostname=values.holorouter_hostname,
                version=image.version,
                image=image.filename,
                profile_id=params.profile_id,
                datastore=plan.datastore,
                networks=plan.networks,
                created=result.created,
                webtop_url=f"http://{values.holorouter_ip}:30000" if webtop else None,
            )
            deps.save_output(host.id, "holorouter", ctx.job.id, output)
            return {"holorouter": output.model_dump(mode="json")}

        return Prepared(
            run,
            {
                "profile_id": params.profile_id,
                "vm_name": vm_name,
                "image": image.filename,
                "replace": params.replace,
            },
        )


class StageBinaries(Module):
    id = "holodeck.stage"
    title = "Stage binaries"
    stage = Stage.HOLODECK
    description = "Copy the ESX ISO and VCF Installer OVA to the Holorouter."
    produces = "staged"
    requires = ("holorouter",)
    os_bound = True
    available = False


class DeployHolodeck(Module):
    id = "holodeck.deploy"
    title = "Deploy Holodeck"
    stage = Stage.HOLODECK
    description = (
        "Run New-HoloDeckConfig and New-HoloDeckInstance on the Holorouter and follow the deployment."
    )
    produces = "holodeck"
    requires = ("staged",)
    os_bound = True
    available = False
