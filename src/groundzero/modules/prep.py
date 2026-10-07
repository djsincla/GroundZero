"""Readiness and preparation: assess the installed ESXi for Holodeck, apply the fixes, prove jumbo frames."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.esxi.models import EsxiStorage, JumboResult
from groundzero.modules.base import OS_ACCESS, Deps, Inputs, Module, Prepared, Stage
from groundzero.modules.outputs import HostPrep
from groundzero.osconfig import OsConfigError
from groundzero.preflight.evaluate import PreflightReport, UnknownProfileError, load_profile
from groundzero.readiness import ReadinessReport, assess

ASSESS_STEPS = [
    ("connect", "Connect to the OS"),
    ("network", "Read network and NTP"),
    ("storage", "Read disks and datastores"),
    ("evaluate", "Evaluate Holodeck readiness"),
]


def current_jumbo(inputs: Inputs) -> dict[str, Any] | None:
    """The last jumbo-frame result, if it was measured on the installed OS."""
    jumbo = inputs.get("jumbo", JumboResult, current=True)
    return jumbo.model_dump(mode="json") if jumbo else None


def _readiness(inputs: Inputs) -> ReadinessReport:
    return inputs.require("readiness", ReadinessReport, "Assess Holodeck readiness first")


class AssessParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    variant: str | None = Field(default=None, description="Holodeck variant; default: the preflight's")


class Assess(Module):
    id = "host.assess"
    title = "Assess Holodeck readiness"
    stage = Stage.READINESS
    description = "Compare drives, datastores, network and NTP with what Holodeck needs, and plan the fixes."
    produces = "readiness"
    also_produces = ("os_network", "os_storage")
    requires = ("preflight", OS_ACCESS)
    uses = ("jumbo",)
    os_bound = True
    Params = AssessParams

    @classmethod
    def params_schema(cls) -> dict[str, Any]:
        from groundzero.modules.hardware import with_variant_choices

        return with_variant_choices(super().params_schema(), profiles=False)

    def summarize(self, data: dict[str, Any]) -> str:
        if data.get("ready"):
            return f"Ready for {data['variant_title']}" + (
                " (with warnings)" if data["overall"] == "warn" else ""
            )
        fixes = len(data.get("plan", []))
        return f"{data['summary']['failed']} to fix for {data['variant_title']} · {fixes} planned actions"

    def prepare(
        self, deps: Deps, host: Host, params: AssessParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        """Read the installed OS live and assess it against Holodeck's needs (read-only)."""
        access, password = deps.os_access(host.id)
        preflight = inputs.get("preflight", PreflightReport)
        profile = load_profile(preflight.profile if preflight else "holodeck-9")
        variant = params.variant or (preflight.variant if preflight else profile.default_variant)
        if variant not in profile.variants:
            raise UnknownProfileError(f"Unknown variant '{variant}'; choose from {sorted(profile.variants)}")
        jumbo = current_jumbo(inputs)

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(ASSESS_STEPS)
            async with ctx.step("connect", "Connect to the OS"):
                target = await asyncio.to_thread(deps.os_target, host.id, access)
            async with ctx.step("network", "Read network and NTP"):
                ctx.progress(0.3, f"Reading network configuration from {access.address}")
                network = await deps.esxi.read_network(target, password)
            async with ctx.step("storage", "Read disks and datastores"):
                ctx.progress(0.6, f"Reading disks and datastores from {access.address}")
                storage = await deps.esxi.read_storage(target, password)
            deps.save_output(host.id, "os_network", ctx.job.id, network)
            deps.save_output(host.id, "os_storage", ctx.job.id, storage)
            async with ctx.step("evaluate", "Evaluate Holodeck readiness"):
                report = assess(
                    profile=profile,
                    variant=variant,
                    network=network,
                    storage=storage,
                    preflight=preflight,
                    jumbo=jumbo,
                )
                deps.save_output(host.id, "readiness", ctx.job.id, report)
            return {"readiness": report.model_dump(mode="json")}

        return Prepared(run, {"variant": variant})


class PrepParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checks: list[str] | None = Field(
        default=None, description="Check ids from the readiness plan to fix; default: the recommended ones"
    )


class Prep(Module):
    id = "host.prep"
    title = "Prepare host"
    stage = Stage.PREP
    description = "Apply the planned fixes: MTU, trunk and external port groups, NTP, Holodeck datastore."
    produces = "host_prep"
    also_produces = ("os_network", "os_storage", "readiness")
    requires = ("readiness",)
    uses = ("preflight", "jumbo")
    os_bound = True
    destructive = True
    Params = PrepParams

    def summarize(self, data: dict[str, Any]) -> str:
        changed = [c for c in data.get("applied", []) if c.get("changed")]
        return f"{len(changed)} change(s) applied · datastore {data.get('datastore') or '?'}"

    def prepare(
        self, deps: Deps, host: Host, params: PrepParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        """Apply planned readiness fixes (by check id; default: the recommended ones), then re-assess."""
        from groundzero.core.services import ConfirmationError

        access, password = deps.os_access(host.id)
        report = _readiness(inputs)
        plan = [a for a in report.plan if a.task == "host.prep"]
        by_check = {a.check: a for a in plan}
        if params.checks is None:
            selected = [a for a in plan if a.recommended]
        else:
            unknown = [c for c in params.checks if c not in by_check]
            if unknown:
                raise OsConfigError(
                    f"Not in the current plan: {', '.join(unknown)}. Assess again to refresh it."
                )
            selected = [by_check[c] for c in params.checks]
        if not selected:
            raise OsConfigError("Nothing selected to apply")
        for action in selected:
            if action.destructive and confirm != action.confirm_phrase:
                raise ConfirmationError(
                    f'“{action.title}” erases a disk: confirm with exactly "{action.confirm_phrase}"',
                    action.confirm_phrase,
                )

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [(a.check, a.title) for a in selected] + [("reassess", "Read the host again and re-assess")]
            )
            target = await asyncio.to_thread(deps.os_target, host.id, access)
            applied = []
            for i, action in enumerate(selected):
                async with ctx.step(action.check, action.title) as step:
                    ctx.progress(0.1 + 0.7 * i / len(selected), action.title)
                    record = await deps.esxi.apply(target, password, action.id, action.params)
                    step.message = (
                        f"{record.before} → {record.after}" if record.changed else f"already {record.after}"
                    )
                    applied.append(record)
            async with ctx.step("reassess", "Read the host again and re-assess"):
                network = await deps.esxi.read_network(target, password)
                storage = await deps.esxi.read_storage(target, password)
                deps.save_output(host.id, "os_network", ctx.job.id, network)
                deps.save_output(host.id, "os_storage", ctx.job.id, storage)
                after = deps.reassess(host.id, network, storage, ctx.job.id)
            vswitch = after.target_vswitch
            trunk = next(
                (
                    pg.name
                    for pg in network.portgroups
                    if pg.is_trunk and pg.vswitch == vswitch and pg.security.accepts_all
                ),
                None,
            )
            external = next((pg.name for pg in network.portgroups if pg.name == "Holodeck-External"), None)
            result = HostPrep(
                applied=applied,
                vswitch=vswitch,
                trunk_portgroup=trunk,
                external_portgroup=external,
                datastore=after.storage.datastore if after.storage.kind == "existing" else None,
                ready=after.ready,
            )
            deps.save_output(host.id, "host_prep", ctx.job.id, result)
            return {"host_prep": result.model_dump(mode="json"), "readiness": after.model_dump(mode="json")}

        return Prepared(run, {"checks": [a.check for a in selected]})


class VerifyJumbo(Module):
    id = "net.verify_jumbo"
    title = "Verify jumbo frames"
    stage = Stage.PREP
    description = "Send 9000-byte frames out of one uplink and back in the other through the physical switch."
    produces = "jumbo"
    also_produces = ("readiness",)
    requires = ("host_prep",)
    uses = ("readiness", "os_storage")
    os_bound = True

    def summarize(self, data: dict[str, Any]) -> str:
        return str(data.get("summary", "jumbo"))

    def prepare(self, deps: Deps, host: Host, params: Any, inputs: Inputs, confirm: str | None) -> Prepared:
        """Loop test 9000-byte frames through the physical switch (temporary changes, always reverted)."""
        access, password = deps.os_access(host.id)
        target_vswitch = _readiness(inputs).target_vswitch
        pinned = deps.store.get_pin(host.id, "os-ssh")

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [
                    ("read", "Read the network"),
                    ("loop", "Loop test through the switch"),
                    ("reassess", "Update the readiness report"),
                ]
            )
            target = await asyncio.to_thread(deps.os_target, host.id, access)
            async with ctx.step("read", "Read the network"):
                network = await deps.esxi.read_network(target, password)
                vswitch = next((v for v in network.vswitches if v.name == target_vswitch), None)
                if vswitch is None or len(vswitch.uplinks) < 2:
                    raise OsConfigError("The jumbo-frame test needs a standard switch with two uplinks")
                # Management stays on the NIC whose MAC vmk0 uses; the other uplink is borrowed for the test.
                keep = network.install_nic()
                keep = keep if keep in vswitch.uplinks else vswitch.uplinks[0]
                borrow = next(u for u in vswitch.uplinks if u != keep)
                uplinks = (keep, borrow)
                vlan = network.management_vlan()
            async with ctx.step("loop", "Loop test through the switch") as step:
                result = await deps.esxi.verify_jumbo(
                    target,
                    password,
                    vswitch=vswitch.name,
                    uplinks=uplinks,
                    vlan=vlan,
                    mtu=9000,
                    pinned_ssh_key=pinned[1] if pinned else None,
                    log=lambda m: ctx.progress(0.5, m),
                )
                if result.ssh_host_key and not pinned:
                    deps.store.set_pin(host.id, "os-ssh", access.address, result.ssh_host_key)
                deps.save_output(host.id, "jumbo", ctx.job.id, result)
                step.message = result.summary
            async with ctx.step("reassess", "Update the readiness report"):
                storage = inputs.get("os_storage", EsxiStorage)
                if storage is not None:
                    deps.reassess(host.id, network, storage, ctx.job.id)
            if not result.restored:
                raise OsConfigError(f"The network configuration was not fully restored:\n{result.diff}")
            if not result.ok:
                raise OsConfigError(result.summary)
            return {"jumbo": result.model_dump(mode="json")}

        return Prepared(run)
