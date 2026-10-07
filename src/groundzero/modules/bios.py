"""Configure BIOS: set processor virtualization, the IOMMU and UEFI boot mode over Redfish (one reboot)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.inventory.models import BiosSettings, HostInventory
from groundzero.modules.base import Deps, Inputs, Lookup, Module, Prepared, Stage
from groundzero.modules.outputs import BiosResult
from groundzero.redfish import bios
from groundzero.redfish.bios import BiosChange
from groundzero.redfish.bios_profiles import BiosProfile
from groundzero.redfish.capabilities import discover_capabilities
from groundzero.redfish.detect import Vendor, detect
from groundzero.redfish.oem import profile_for


class BiosParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: list[bios.Setting] | None = Field(
        default=None, description="What to turn on; default: whatever the latest inventory shows as wrong"
    )
    profile_id: str | None = Field(
        default=None,
        description="A BIOS profile to apply as well: its settings that differ from now are written",
    )


def plan_bios(
    vendor: str | None, current: BiosSettings, settings: Sequence[str] | None, profile: BiosProfile | None
) -> tuple[list[BiosChange], list[str]]:
    """What Configure BIOS would write: the baseline (virtualization, IOMMU, UEFI) where it's off, and a
    profile's settings where they differ. A profile's own value wins for an attribute both touch."""
    wanted = (
        [str(x) for x in settings]
        if settings is not None
        else bios.wanted_from_inventory(current.cpu_virtualization, current.iommu, current.boot_mode)
    )
    try:
        oem = profile_for(Vendor(vendor or "generic"))
    except ValueError:
        oem = profile_for(Vendor.GENERIC)
    changes, unsupported = bios.plan_changes(current.attributes, oem, wanted)
    if profile is not None:
        changes = [c for c in changes if c.attribute not in profile.attributes]
        changes += [
            BiosChange(attribute=name, before=current.attributes.get(name), after=value)
            for name, value in profile.attributes.items()
            if current.attributes.get(name) != value
        ]
    return changes, unsupported


class ConfigureBios(Module):
    id = "bios.configure"
    title = "Configure BIOS"
    stage = Stage.HARDWARE
    description = (
        "Turn on processor virtualization, the IOMMU and UEFI boot mode where the inventory shows them off, "
        "and apply a BIOS profile if one is given. Reboots the server once: anything running on it goes "
        "down with it."
    )
    produces = "bios"
    requires = ("inventory",)
    also_produces = ("inventory",)
    optional = True
    conditional = True  # recommended only when the inventory shows something off
    destructive = True
    Params = BiosParams

    def satisfied(
        self, outputs: dict[str, dict[str, Any]], params: dict[str, Any], lookup: Lookup | None = None
    ) -> str | None:
        inventory = outputs.get("inventory")
        if inventory is None:
            return None
        b = BiosSettings.model_validate(inventory.get("bios") or {})
        if bios.wanted_from_inventory(b.cpu_virtualization, b.iommu, b.boot_mode):
            return None
        profile = None
        if params.get("profile_id"):
            profile = lookup("bios_profile", str(params["profile_id"])) if lookup else None
            if profile is None or any(b.attributes.get(k) != v for k, v in profile.attributes.items()):
                return None  # the profile's settings aren't all there yet (or it's gone: let the run say so)
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
        if profile is not None:
            said += f"; matches {profile.name} ({len(profile.attributes)} settings)"
        if unknown:
            said += f" (the BIOS doesn't report {', '.join(unknown)})"
        return said

    def summarize(self, data: dict[str, Any]) -> str:
        changes = data.get("changes") or []
        if not changes:
            return "Nothing to change: the BIOS settings were already right"
        shown = ", ".join(f"{c['attribute']} {c['before']} → {c['after']}" for c in changes[:4])
        return "Changed " + shown + (f" and {len(changes) - 4} more" if len(changes) > 4 else "")

    def prepare(
        self, deps: Deps, host: Host, params: BiosParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        from groundzero.core.services import ConfirmationError, ConflictError  # avoid an import cycle

        inventory = inputs.require(
            "inventory", HostInventory, "Discover the hardware first (inventory or preflight)"
        )
        profile = deps.get_bios_profile(params.profile_id) if params.profile_id else None
        if profile is not None and profile.model and host.model and profile.model != host.model:
            raise ConflictError(
                f"BIOS profile '{profile.name}' was made for a {profile.model}; {host.name} is a {host.model}"
            )
        changes, unsupported = plan_bios(host.vendor, inventory.bios, params.settings, profile)
        phrase = f"configure bios {host.name}"
        if changes and confirm != phrase:
            listed = ", ".join(f"{c.attribute} → {c.after}" for c in changes[:6])
            more = f" and {len(changes) - 6} more" if len(changes) > 6 else ""
            raise ConfirmationError(
                f'This sets {listed}{more} and reboots {host.name}: confirm with exactly "{phrase}"', phrase
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

        recorded = {"settings": params.settings, "profile_id": params.profile_id}
        return Prepared(run, recorded | {"changes": [c.attribute for c in changes]})
