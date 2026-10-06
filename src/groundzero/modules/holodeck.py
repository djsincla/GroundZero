"""Holodeck stage: the Holorouter appliance, then (planned) staging binaries and the Holodeck deploy."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.modules.base import Deps, Inputs, Module, Prepared, Stage
from groundzero.modules.outputs import HolorouterDeployment, HostPrep
from groundzero.osconfig import OsConfigError
from groundzero.osconfig.holodeck import HolodeckHostValues, HolodeckPlugin, HolodeckSettings
from groundzero.readiness import ReadinessReport


class HolorouterParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    config_set_id: str = Field(default="", description="Holodeck config set (GET /config-sets)")
    reapply: bool = Field(default=False, description="Power-cycle an existing VM to write its settings again")


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
        """Deploy the Holorouter OVA on the prepared datastore and port groups, then wait for SSH."""
        from groundzero.core.services import ConflictError, NotFoundError

        access, password = deps.os_access(host.id)
        if not params.config_set_id:
            raise OsConfigError("Choose a Holodeck config set (params.config_set_id)")
        config_set = deps.get_config_set(params.config_set_id)
        if config_set.os_family != HolodeckPlugin.family:
            raise OsConfigError(f"{config_set.name} is not a Holodeck config set")
        stored_values = deps.store.get_host_values(host.id, HolodeckPlugin.family)
        if stored_values is None:
            raise OsConfigError("Set this host's Holodeck values first (Holorouter IP, instance ID)")
        settings = HolodeckSettings.model_validate(config_set.settings)
        values = HolodeckHostValues.model_validate(stored_values)
        secrets = deps.config_set_secrets(config_set.id)
        if not secrets.get("holorouter_password"):
            raise OsConfigError(f"Set the Holorouter password in config set {config_set.name}")
        readiness = inputs.require("readiness", ReadinessReport, "Assess Holodeck readiness first")
        if not readiness.ready:
            raise ConflictError("The host is not ready for Holodeck yet; see the readiness report")
        prep = inputs.get("host_prep", HostPrep)
        if prep is None or not prep.trunk_portgroup or not prep.external_portgroup:
            raise ConflictError("Prepare host must have created the trunk and external port groups")
        datastore = prep.datastore or readiness.storage.datastore
        images = [i for i in deps.isos.list() if i.os_family == "holorouter"]
        if not images:
            raise NotFoundError(f"No Holorouter OVA in the image repository ({deps.settings.iso_dir})")
        image = max(images, key=lambda i: (i.version or "", i.build or ""))
        resolved = deps.isos.resolve(image.id)
        assert resolved is not None
        ova = resolved[1]
        bools = {True: "True", False: "False"}
        properties = {
            "hostname": values.holorouter_hostname,
            "password": secrets["holorouter_password"],
            "ip": values.holorouter_ip,
            "mask": str(settings.holorouter_prefix),
            "gateway": settings.holorouter_gateway,
            "dns_server": settings.holorouter_dns,
            "ntp_server": settings.holorouter_ntp,
            **({"dns_domain": settings.holorouter_dns_domain} if settings.holorouter_dns_domain else {}),
            "ssh_enabled": "True",
            "webtop_enabled": bools[settings.webtop],
            "gitops_enabled": bools[settings.gitops],
        }
        networks = {
            "VM Management Network": prep.external_portgroup,
            "Trunk Portgroup for Site A": prep.trunk_portgroup,
            "Trunk Portgroup for Site B": prep.trunk_portgroup,
        }
        vm_name = f"{values.instance_id}-holorouter"

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [("deploy", f"Deploy {image.filename}"), ("ssh", "Wait for the Holorouter to answer on SSH")]
            )
            loop = asyncio.get_running_loop()

            def progress(fraction: float, message: str) -> None:  # called from the upload thread
                loop.call_soon_threadsafe(ctx.progress, fraction, message)

            target = await asyncio.to_thread(deps.os_target, host.id, access)
            async with ctx.step("deploy", f"Deploy {image.filename}") as step:
                result = await deps.esxi.deploy_ova(
                    target,
                    password,
                    ova,
                    vm_name=vm_name,
                    datastore=datastore or "",
                    networks=networks,
                    properties=properties,
                    progress=progress,
                    reapply=params.reapply,
                )
                step.message = (
                    f"uploaded {result.uploaded_bytes / 1e9:.2f} GB in {result.seconds / 60:.0f} min"
                    if result.created
                    else result.message
                )
                if not result.settings_applied:
                    raise OsConfigError(result.message)
            async with ctx.step("ssh", "Wait for the Holorouter to answer on SSH") as step:
                await deps.wait_for_port(values.holorouter_ip, 22, minutes=20, ctx=ctx)
                step.message = f"{values.holorouter_ip}:22 answers"
            output = HolorouterDeployment(
                vm_name=vm_name,
                ip=values.holorouter_ip,
                hostname=values.holorouter_hostname,
                version=image.version,
                image=image.filename,
                config_set_id=config_set.id,
                datastore=datastore,
                networks=networks,
                created=result.created,
                webtop_url=f"http://{values.holorouter_ip}:30000" if settings.webtop else None,
            )
            deps.save_output(host.id, "holorouter", ctx.job.id, output)
            return {"holorouter": output.model_dump(mode="json")}

        return Prepared(
            run,
            {
                "config_set_id": config_set.id,
                "vm_name": vm_name,
                "image": image.filename,
                "reapply": params.reapply,
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
