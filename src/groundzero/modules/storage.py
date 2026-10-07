"""Storage: read the server's controllers, RAID volumes and drives over Redfish (read-only).

The layout it records is what a later storage configuration is planned against, and its boot volume is
what the OS install targets.
"""

from __future__ import annotations

from typing import Any

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host
from groundzero.modules.base import Deps, Inputs, Module, Prepared, Stage
from groundzero.modules.outputs import BootVolume, StorageReport
from groundzero.redfish.detect import detect
from groundzero.redfish.storage import StorageLayout, read_storage_layout


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def boot_volume(layout: StorageLayout) -> BootVolume | None:
    """The volume an OS install targets: the one marked as boot, else the volume on a boot card.

    Boot cards (Dell BOSS, M.2 adapters) exist to hold the hypervisor, so their RAID volume is the answer
    even when the BMC doesn't flag it.
    """
    candidates = [(c, v) for c in layout.controllers for v in c.raid_volumes if v.boot] or [
        (c, v) for c in layout.controllers if c.kind == "boot" for v in c.raid_volumes
    ]
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
