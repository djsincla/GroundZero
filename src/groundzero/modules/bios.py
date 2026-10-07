"""Configure BIOS: set processor virtualization, the IOMMU and UEFI boot mode over Redfish (one reboot)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.inventory.models import BiosSettings, HostInventory
from groundzero.modules.base import Deps, Inputs, Module, Prepared, Stage
from groundzero.modules.outputs import BiosResult
from groundzero.redfish import bios
from groundzero.redfish.capabilities import discover_capabilities
from groundzero.redfish.detect import Vendor, detect
from groundzero.redfish.oem import profile_for


class BiosParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: list[bios.Setting] | None = Field(
        default=None, description="What to turn on; default: whatever the latest inventory shows as wrong"
    )


class ConfigureBios(Module):
    id = "bios.configure"
    title = "Configure BIOS"
    stage = Stage.HARDWARE
    description = (
        "Turn on processor virtualization, the IOMMU and UEFI boot mode where the inventory shows them off. "
        "Reboots the server once: anything running on it goes down with it."
    )
    produces = "bios"
    requires = ("inventory",)
    also_produces = ("inventory",)
    optional = True
    conditional = True  # recommended only when the inventory shows something off
    destructive = True
    Params = BiosParams

    def satisfied(self, outputs: dict[str, dict[str, Any]]) -> str | None:
        inventory = outputs.get("inventory")
        if inventory is None:
            return None
        b = BiosSettings.model_validate(inventory.get("bios") or {})
        if bios.wanted_from_inventory(b.cpu_virtualization, b.iommu, b.boot_mode):
            return None
        right = [
            title
            for title, ok in (
                ("processor virtualization", b.cpu_virtualization),
                ("IOMMU", b.iommu),
                ("UEFI boot mode", b.boot_mode is not None),
            )
            if ok
        ]
        unknown = [
            title
            for title, value in (
                ("processor virtualization", b.cpu_virtualization),
                ("IOMMU", b.iommu),
                ("boot mode", b.boot_mode),
            )
            if value is None
        ]
        said = f"Already on: {', '.join(right)}" if right else "Nothing to change"
        if unknown:
            said += f" (the BIOS doesn't report {', '.join(unknown)})"
        return said

    def summarize(self, data: dict[str, Any]) -> str:
        changes = data.get("changes") or []
        if not changes:
            return "Nothing to change: the BIOS settings were already right"
        return "Changed " + ", ".join(f"{c['attribute']} {c['before']} → {c['after']}" for c in changes)

    def prepare(
        self, deps: Deps, host: Host, params: BiosParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        from groundzero.core.services import ConfirmationError  # avoid an import cycle

        inventory = inputs.require(
            "inventory", HostInventory, "Discover the hardware first (inventory or preflight)"
        )
        b = inventory.bios
        wanted: list[str] = (
            [str(x) for x in params.settings]
            if params.settings is not None
            else bios.wanted_from_inventory(b.cpu_virtualization, b.iommu, b.boot_mode)
        )

        try:
            vendor = Vendor(host.vendor or "generic")
        except ValueError:
            vendor = Vendor.GENERIC
        profile = profile_for(vendor)
        changes, unsupported = bios.plan_changes(b.attributes, profile, wanted)
        phrase = f"configure bios {host.name}"
        if changes and confirm != phrase:
            listed = ", ".join(f"{c.attribute} → {c.after}" for c in changes)
            raise ConfirmationError(
                f'This sets {listed} and reboots {host.name}: confirm with exactly "{phrase}"'
            )
        s = deps.settings

        async def run(ctx: JobContext) -> dict[str, Any]:
            if not changes:
                async with ctx.step("check", "Check the BIOS settings") as step:
                    step.message = "Already right; nothing changed" + (
                        f" ({', '.join(unsupported)} not exposed by this BIOS)" if unsupported else ""
                    )
                result = BiosResult(unsupported=unsupported)
                deps.save_output(host.id, "bios", ctx.job.id, result)
                return {"bios": result.model_dump(mode="json")}
            ctx.plan(
                [
                    ("apply", "Write the settings and reboot"),
                    ("verify", "Wait for the BIOS to apply them"),
                    ("inventory", "Read the hardware inventory again"),
                ]
            )
            async with deps.client_factory(host, deps.bmc_password(host.id)) as client:
                async with ctx.step("apply", "Write the settings and reboot") as step:
                    identity = await detect(client)
                    system = await client.get_json(identity.system_path)
                    manager = await client.get_json(identity.manager_path) if identity.manager_path else None
                    caps = await discover_capabilities(client, system, manager)
                    step.message = ", ".join(f"{c.attribute} {c.before} → {c.after}" for c in changes)
                async with ctx.step("verify", "Wait for the BIOS to apply them") as step:
                    applied = await bios.apply_changes(
                        client,
                        identity,
                        caps,
                        changes,
                        apply_minutes=s.bios_apply_minutes,
                        poll_seconds=s.bios_poll_seconds,
                        log=lambda m: ctx.progress(0.5, m),
                    )
                    step.message = "applied: " + ", ".join(f"{k}={v}" for k, v in applied.items())
            async with ctx.step("inventory", "Read the hardware inventory again"):
                await deps.collect_inventory(
                    host, ctx
                )  # so preflight and everything after sees the new values
            result = BiosResult(changes=changes, unsupported=unsupported, applied=applied)
            deps.save_output(host.id, "bios", ctx.job.id, result)
            return {"bios": result.model_dump(mode="json")}

        return Prepared(run, {"settings": wanted, "changes": [c.attribute for c in changes]})
