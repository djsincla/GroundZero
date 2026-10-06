"""Hardware stage: read the server over its BMC (read-only)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.inventory.models import HostInventory
from groundzero.modules.base import Deps, Inputs, Module, Prepared, Stage
from groundzero.preflight.evaluate import UnknownProfileError, available_profiles, evaluate, load_profile
from groundzero.vcf_readiness.validate import validate as vcf_validate


class Discover(Module):
    id = "discover"
    title = "Discover hardware"
    stage = Stage.HARDWARE
    description = "Read the server's hardware inventory over Redfish (read-only)."
    produces = "inventory"
    optional = True

    def summarize(self, data: dict[str, Any]) -> str:
        cores = sum(p.get("cores", 0) for p in data.get("processors", []))
        return f"{data['system']['model']} · {cores} cores · {round(data['memory']['total_gib'])} GiB"

    def prepare(self, deps: Deps, host: Host, params: Any, inputs: Inputs, confirm: str | None) -> Prepared:
        async def run(ctx: JobContext) -> dict[str, Any]:
            async with ctx.step("collect", "Read hardware inventory from the BMC"):
                inventory, audit = await deps.collect_inventory(host, ctx)
            return {"inventory": inventory.model_dump(mode="json"), "audit": audit}

        return Prepared(run)


class PreflightParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile: str = Field(default="holodeck-9", description="Requirements profile id")
    variant: str | None = Field(
        default=None, description="Profile variant; defaults to the profile's default"
    )


def with_variant_choices(schema: dict[str, Any], *, profiles: bool) -> dict[str, Any]:
    """Offer the requirement profiles and their variants as choices (what GET /profiles used to list)."""
    variants = {v.id: v.title for p in available_profiles() for v in load_profile(p).variants.values()}
    props = schema.get("properties", {})
    if "variant" in props:
        props["variant"] = {
            "anyOf": [{"type": "string", "enum": list(variants)}, {"type": "null"}],
            "default": None,
            "title": "Variant",
            "description": "; ".join(f"{k}: {t}" for k, t in variants.items()),
        }
    if profiles and "profile" in props:
        props["profile"] = {**props["profile"], "enum": available_profiles()}
    return schema


class Preflight(Module):
    id = "preflight"
    title = "Holodeck preflight"
    stage = Stage.HARDWARE
    description = (
        "Check CPU, memory, disks, NICs, BIOS and BMC against the Holodeck requirements (read-only)."
    )
    produces = "preflight"
    also_produces = ("inventory",)
    Params = PreflightParams

    @classmethod
    def params_schema(cls) -> dict[str, Any]:
        return with_variant_choices(super().params_schema(), profiles=True)

    def summarize(self, data: dict[str, Any]) -> str:
        s = data["summary"]
        return f"{data['overall']}: {s['passed']} passed, {s['warnings']} warnings, {s['failed']} failed"

    def prepare(
        self, deps: Deps, host: Host, params: PreflightParams, inputs: Inputs, confirm: str | None
    ) -> Prepared:
        profile = params.profile
        spec = load_profile(profile)  # validate before queuing so bad input is a 4xx, not a failed job
        variant = params.variant or spec.default_variant
        if variant not in spec.variants:
            raise UnknownProfileError(f"Unknown variant '{variant}'; choose from {sorted(spec.variants)}")

        async def run(ctx: JobContext) -> dict[str, Any]:
            ctx.plan(
                [
                    ("collect", "Read hardware inventory from the BMC"),
                    ("evaluate", "Evaluate the requirements"),
                ]
            )
            async with ctx.step("collect", "Read hardware inventory from the BMC"):
                inventory, audit = await deps.collect_inventory(host, ctx)
            async with ctx.step("evaluate", "Evaluate the requirements"):
                ctx.progress(0.97, "Evaluating preflight checks")
                report = evaluate(inventory, profile, variant)
            deps.save_output(host.id, "preflight", ctx.job.id, report)
            return {"preflight": report.model_dump(mode="json"), "audit": audit}

        return Prepared(run, {"profile": profile, "variant": variant})


class VcfReadiness(Module):
    id = "vcf.readiness"
    title = "VCF 9 readiness"
    stage = Stage.HARDWARE
    description = (
        "Validate the hardware against the VCF 9 readiness rules from John Nicholson's VCF Readiness tool "
        "(CA, Inc. license; read-only)."
    )
    produces = "vcf_readiness"
    requires = ("inventory",)
    optional = True  # informative (e.g. whether ESXi 9 needs the CPU override); nothing depends on it

    def summarize(self, data: dict[str, Any]) -> str:
        s = data["summary"]
        note = " · CPU override needed for ESXi 9" if data.get("cpu_override_required") else ""
        counts = f"{s['passed']} passed, {s['warnings']} warnings, {s['failed']} failed"
        return f"{data['overall']}: {counts}{note}"

    def prepare(self, deps: Deps, host: Host, params: Any, inputs: Inputs, confirm: str | None) -> Prepared:
        """VCF 9 readiness (CA rules) on the latest hardware inventory. Read-only: no BMC calls."""
        inventory = inputs.require(
            "inventory", HostInventory, "Discover the hardware first (inventory or preflight)"
        )

        async def run(ctx: JobContext) -> dict[str, Any]:
            async with ctx.step("validate", "Validate against the VCF 9 readiness rules"):
                report = vcf_validate(inventory)
            deps.save_output(host.id, "vcf_readiness", ctx.job.id, report)
            return {"vcf_readiness": report.model_dump(mode="json")}

        return Prepared(run)
