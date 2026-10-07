"""Storage: read the server's controllers, RAID volumes and drives over Redfish (read-only).

The layout it records is what a later storage configuration is planned against, and its boot volume is
what the OS install targets.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.modules.base import Deps, Inputs, Lookup, Module, Prepared, Stage
from groundzero.modules.outputs import BootVolume, StorageConfigResult, StorageReport
from groundzero.redfish.capabilities import discover_capabilities
from groundzero.redfish.detect import detect
from groundzero.redfish.storage import StorageLayout, read_storage_layout
from groundzero.redfish.storage_config import StoragePlan, apply_plan, plan_storage


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def boot_volume(layout: StorageLayout, prefer: str | None = None) -> BootVolume | None:
    """The volume an OS install targets: ``prefer`` (a storage profile's boot volume, by name or id), else
    the one the controller marks as boot, else the volume on a boot card.

    Boot cards (Dell BOSS, M.2 adapters) exist to hold the hypervisor, so their RAID volume is the answer
    even when the BMC doesn't flag it.
    """
    named = [
        (c, v) for c in layout.controllers for v in c.raid_volumes if prefer and prefer in (v.name, v.id)
    ]
    candidates = (
        named
        or [(c, v) for c in layout.controllers for v in c.raid_volumes if v.boot]
        or [(c, v) for c in layout.controllers if c.kind == "boot" for v in c.raid_volumes]
    )
    if not candidates:
        return None
    controller, volume = candidates[0]
    model = controller.model or ""
    return BootVolume(
        controller_id=controller.id,
        controller_model=model or None,
        volume_id=volume.id,
        name=volume.name,
        raid=volume.raid,
        capacity_gb=volume.capacity_gb,
        drives=len(volume.drives),
        install_match="DELLBOSS" if "BOSS" in model.upper() else None,
    )


class ReadStorage(Module):
    id = "storage.read"
    title = "Read storage"
    stage = Stage.HARDWARE
    description = (
        "Read the storage controllers, RAID volumes and drives over Redfish (read-only), "
        "and find the boot volume the OS installs to."
    )
    produces = "storage"
    optional = True

    def summarize(self, data: dict[str, Any]) -> str:
        report = StorageReport.model_validate(data)
        drives = sum(len(c.drives) for c in report.controllers)
        volumes = sum(len(c.raid_volumes) for c in report.controllers)
        parts = [
            _count(len(report.controllers), "controller"),
            _count(volumes, "RAID volume"),
            _count(drives, "drive"),
        ]
        b = report.boot_volume
        if b:
            what = " ".join(x for x in (b.name or b.volume_id, b.raid, f"{b.capacity_gb:g} GB") if x)
            parts.append(f"boot: {what} on {b.controller_model or b.controller_id}")
        else:
            parts.append("no boot volume found")
        return " · ".join(parts)

    def prepare(self, deps: Deps, host: Host, params: Any, inputs: Inputs, confirm: str | None) -> Prepared:
        async def run(ctx: JobContext) -> dict[str, Any]:
            async with ctx.step("read", "Read the storage layout from the BMC") as step:
                async with deps.client_factory(host, deps.bmc_password(host.id)) as client:
                    identity = await detect(client)
                    layout = await read_storage_layout(
                        client, identity.system_path, dell=identity.vendor.value == "dell"
                    )
                report = StorageReport(**layout.model_dump(), boot_volume=boot_volume(layout))
                step.message = self.summarize(report.model_dump(mode="json"))
            deps.save_output(host.id, "storage", ctx.job.id, report)
            return {"storage": report.model_dump(mode="json")}

        return Prepared(run)


class StorageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(description="The storage profile to apply")
    allow_boot_volume: bool = Field(
        default=False, description="Let the plan delete the boot volume the OS runs from (its data is lost)"
    )


class ConfigureStorage(Module):
    id = "storage.configure"
    title = "Configure storage"
    stage = Stage.HARDWARE
    description = (
        "Apply a storage profile: RAID volumes, controller mode, drive state and hot spares. Shows what "
        "changes first; anything deleted loses its data, and the boot volume is never touched unless you "
        "allow it. Restarts the server if a change waits for a reset."
    )
    produces = "storage_config"
    requires = ("storage",)
    also_produces = ("storage",)
    optional = True
    rechecks = True  # once applied, due again if the layout drifts from the profile (never recommended alone)
    destructive = True
    Params = StorageParams

    def summarize(self, data: dict[str, Any]) -> str:
        changed = data.get("actions") or []
        name = data.get("profile_name") or "the profile"
        if not changed:
            return f"Already matched {name}: nothing changed"
        more = f" and {len(changed) - 3} more" if len(changed) > 3 else ""
        return f"Applied {name}: " + "; ".join(a["title"] for a in changed[:3]) + more

    def satisfied(
        self, outputs: dict[str, dict[str, Any]], params: dict[str, Any], lookup: Lookup | None = None
    ) -> str | None:
        layout = outputs.get("storage")
        profile_id = params.get("profile_id") or (outputs.get("storage_config") or {}).get("profile_id")
        if layout is None or not profile_id or lookup is None:
            return None
        profile = lookup("storage_profile", str(profile_id))
        if profile is None:
            return None
        report = StorageReport.model_validate(layout)
        protected = report.boot_volume.volume_id if report.boot_volume else None
        allow = bool(params.get("allow_boot_volume"))
        plan = plan_storage(report, profile, protected=protected, allow_boot_volume=allow)
        if plan.actions or plan.problems:
            return None
        return f"Matches {profile.name}"

    def prepare(
        self, deps: Deps, host: Host, params: StorageParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        from groundzero.core.services import ConfirmationError, ConflictError  # avoid an import cycle

        storage = inputs.require(
            "storage", StorageReport, "Read storage first: the plan starts from its layout"
        )
        profile = deps.get_storage_profile(params.profile_id)
        protected = storage.boot_volume.volume_id if storage.boot_volume else None
        allow = params.allow_boot_volume
        plan = plan_storage(storage, profile, protected=protected, allow_boot_volume=allow)
        if plan.problems:
            raise ConflictError(
                f"{profile.name} can't be applied to {host.name}: " + "; ".join(plan.problems)
            )
        phrase = f"configure storage {host.name}"
        if plan.actions and confirm != phrase:
            lost = plan.destroys
            what = (
                ("This loses data: " + "; ".join(lost))
                if lost
                else f"This makes {len(plan.actions)} change(s)"
            )
            raise ConfirmationError(f'{what}. Confirm with exactly "{phrase}"', phrase)
        s = deps.settings

        def remaining(layout: StorageLayout) -> StoragePlan:
            return plan_storage(layout, profile, protected=protected, allow_boot_volume=allow)

        async def run(ctx: JobContext) -> dict[str, Any]:
            if not plan.actions:
                async with ctx.step("check", "Compare the layout with the profile") as step:
                    step.message = f"Already matches {profile.name}"
                result = StorageConfigResult(
                    profile_id=profile.id, profile_name=profile.name, boot_volume=storage.boot_volume
                )
                deps.save_output(host.id, "storage_config", ctx.job.id, result)
                return {"storage_config": result.model_dump(mode="json")}
            ctx.plan(
                [
                    ("check", "Read the layout again and check the plan"),
                    ("apply", "Make the changes and wait for them"),
                ]
            )
            async with deps.client_factory(host, deps.bmc_password(host.id)) as client:
                async with ctx.step("check", "Read the layout again and check the plan") as step:
                    identity = await detect(client)
                    now = await read_storage_layout(
                        client, identity.system_path, dell=identity.vendor.value == "dell"
                    )
                    again = remaining(now)
                    if [a.title for a in again.actions] != [a.title for a in plan.actions] or again.problems:
                        raise ConflictError(
                            f"The storage on {host.name} changed since it was read: run Read storage again "
                            "and check the new plan before applying"
                        )
                    system = await client.get_json(identity.system_path)
                    manager = await client.get_json(identity.manager_path) if identity.manager_path else None
                    caps = await discover_capabilities(client, system, manager)
                    step.message = f"{len(plan.actions)} change(s), as planned"
                async with ctx.step("apply", "Make the changes and wait for them") as step:
                    after = await apply_plan(
                        client,
                        identity,
                        caps,
                        now,
                        plan,
                        done=lambda layout: not remaining(layout).actions,
                        apply_minutes=s.storage_apply_minutes,
                        poll_seconds=s.storage_poll_seconds,
                        log=lambda m: ctx.progress(0.5, m),
                    )
                    step.message = "; ".join(a.title for a in plan.actions)
            prefer = next((v.name for c in profile.controllers for v in c.volumes if v.boot), None)
            report = StorageReport(**after.model_dump(), boot_volume=boot_volume(after, prefer))
            deps.save_output(host.id, "storage", ctx.job.id, report)
            result = StorageConfigResult(
                profile_id=profile.id,
                profile_name=profile.name,
                actions=plan.actions,
                boot_volume=report.boot_volume,
            )
            deps.save_output(host.id, "storage_config", ctx.job.id, result)
            return {"storage_config": result.model_dump(mode="json")}

        recorded = {"profile_id": profile.id, "allow_boot_volume": allow}
        return Prepared(run, recorded | {"actions": [a.title for a in plan.actions]})
