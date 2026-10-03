"""The task catalog and the per-host pipeline: from bare metal to a running Holodeck.

A *task* is a named unit of work (one job when it runs). It declares what it ``requires`` (outputs of
earlier tasks, or prerequisites such as OS access) and the output kind it ``produces``. Outputs are
stored per host (the ``results`` table) and are the inputs of later tasks.

Outputs that describe the installed OS (``os_bound``) are stamped with the host's OS epoch, which every
successful install increments, so after a reinstall they show as *stale* and must be produced again
before tasks that depend on them can run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from groundzero.core.models import Job, JobStatus
from groundzero.core.store import OutputMeta


class Stage(StrEnum):
    HARDWARE = "hardware"
    OS = "os"
    READINESS = "readiness"
    PREP = "prep"
    HOLODECK = "holodeck"


STAGE_TITLES = {
    Stage.HARDWARE: "Hardware",
    Stage.OS: "Operating system",
    Stage.READINESS: "Holodeck readiness",
    Stage.PREP: "Host preparation",
    Stage.HOLODECK: "Holodeck",
}

OS_ACCESS = "os_access"  # a prerequisite that is not a task output


@dataclass(frozen=True)
class TaskSpec:
    id: str
    title: str
    stage: Stage
    description: str
    produces: str | None
    requires: tuple[str, ...] = ()
    os_bound: bool = False  # the output describes the installed OS: stale after a reinstall
    optional: bool = False  # not on the recommended path (alternatives, utilities)
    destructive: bool = False
    available: bool = True  # False: designed, not implemented yet (shown as planned)


CATALOG: tuple[TaskSpec, ...] = (
    TaskSpec("discover", "Discover hardware", Stage.HARDWARE,
             "Read the server's hardware inventory over Redfish (read-only).",
             produces="inventory", optional=True),
    TaskSpec("preflight", "Holodeck preflight", Stage.HARDWARE,
             "Check CPU, memory, disks, NICs, BIOS and BMC against the Holodeck requirements (read-only).",
             produces="preflight"),
    TaskSpec("os.reimage", "Deploy OS", Stage.OS,
             "Reinstall ESXi from a stock ISO, keeping this server's current network identity "
             "(read from the running OS).",
             produces="install", requires=(OS_ACCESS,), optional=True, destructive=True),
    TaskSpec("os.custom", "Deploy custom OS", Stage.OS,
             "Install ESXi from a stock ISO using a config set and this server's own values.",
             produces="install", optional=True, destructive=True),
    TaskSpec("os.read", "Read installed OS", Stage.OS,
             "Read the running hypervisor's network, NTP and storage (read-only).",
             produces="os_network", requires=(OS_ACCESS,), os_bound=True),
    TaskSpec("os.capture", "Capture config set", Stage.OS,
             "Save the running hypervisor's settings as a reusable config set (read-only).",
             produces=None, requires=(OS_ACCESS,), optional=True),
    TaskSpec("host.assess", "Assess Holodeck readiness", Stage.READINESS,
             "Compare drives, datastores, network and NTP with what Holodeck needs, and plan the fixes.",
             produces="readiness", requires=("inventory", "os_network"), os_bound=True, available=False),
    TaskSpec("host.prep", "Prepare host", Stage.PREP,
             "Apply the planned fixes: MTU, trunk and external port groups, NTP, Holodeck datastore.",
             produces="host_prep", requires=("readiness",), os_bound=True, destructive=True, available=False),
    TaskSpec("net.verify_jumbo", "Verify jumbo frames", Stage.PREP,
             "Send 9000-byte frames out of one uplink and back in the other through the physical switch.",
             produces="jumbo", requires=("host_prep",), os_bound=True, available=False),
    TaskSpec("holodeck.router", "Deploy Holorouter", Stage.HOLODECK,
             "Deploy and start the Holorouter appliance on the prepared datastore and port groups.",
             produces="holorouter", requires=("readiness", "host_prep"), os_bound=True, available=False),
    TaskSpec("holodeck.stage", "Stage binaries", Stage.HOLODECK,
             "Copy the ESX ISO and VCF Installer OVA to the Holorouter.",
             produces="staged", requires=("holorouter",), os_bound=True, available=False),
    TaskSpec("holodeck.deploy", "Deploy Holodeck", Stage.HOLODECK,
             "Run New-HoloDeckConfig and New-HoloDeckInstance on the Holorouter and follow the deployment.",
             produces="holodeck", requires=("staged",), os_bound=True, available=False),
)  # fmt: skip

TASKS = {t.id: t for t in CATALOG}
# Which task to point at when an output is missing. "install" has two producers and is never required.
PRODUCER: dict[str, TaskSpec] = {}
for _t in CATALOG:
    if _t.produces and _t.produces not in PRODUCER:
        PRODUCER[_t.produces] = _t


# ── API models ───────────────────────────────────────────────────────────
TaskStateName = Literal["done", "stale", "ready", "blocked", "running", "failed", "planned"]


class TaskInfo(BaseModel):
    id: str
    title: str
    stage: Stage
    description: str
    produces: str | None
    requires: list[str]
    optional: bool
    destructive: bool
    available: bool


class JobRef(BaseModel):
    id: str
    status: JobStatus
    finished_at: datetime | None
    error: str | None = None


class OutputInfo(BaseModel):
    kind: str
    job_id: str
    produced_at: datetime
    fresh: bool = Field(description="False when the OS was reinstalled after this output was produced")
    summary: str


class TaskState(TaskInfo):
    state: TaskStateName
    blocked_by: list[str] = Field(default_factory=list)
    last_job: JobRef | None = None
    output: OutputInfo | None = None


class PipelineStage(BaseModel):
    id: Stage
    title: str
    state: TaskStateName
    tasks: list[TaskState]


class NextStep(BaseModel):
    task: str | None = Field(description="Task to run next, or null when there is nothing to run now")
    title: str
    reason: str


class Pipeline(BaseModel):
    host_id: str
    os_epoch: int
    stages: list[PipelineStage]
    next: NextStep


class TaskRun(BaseModel):
    """Start a task. ``params`` are task-specific (e.g. iso_id, config_set_id for OS deployment)."""

    params: dict[str, Any] = Field(default_factory=dict)
    confirm: str | None = Field(default=None, description="Typed confirmation for destructive tasks")


def info(spec: TaskSpec) -> TaskInfo:
    return TaskInfo(
        id=spec.id, title=spec.title, stage=spec.stage, description=spec.description,
        produces=spec.produces, requires=list(spec.requires), optional=spec.optional,
        destructive=spec.destructive, available=spec.available,
    )  # fmt: skip


# ── pipeline evaluation ─────────────────────────────────────────────────
def summarize(kind: str, data: dict[str, Any]) -> str:
    """One line describing an output, for the pipeline view."""
    try:
        if kind == "inventory":
            cores = sum(p.get("cores", 0) for p in data.get("processors", []))
            return f"{data['system']['model']} · {cores} cores · {round(data['memory']['total_gib'])} GiB"
        if kind == "preflight":
            s = data["summary"]
            return f"{data['overall']}: {s['passed']} passed, {s['warnings']} warnings, {s['failed']} failed"
        if kind == "install":
            target = f"ESXi {data.get('iso_version')} build {data.get('iso_build')}"
            if data.get("installed_build") and all(c.get("ok") for c in data.get("validation", [])):
                return f"{target} installed and validated"
            return f"{target}: did not complete (still on {data.get('previous_build') or '?'})"
        if kind == "os_network":
            mgmt = next((v for v in data.get("vmkernel", []) if "management" in v.get("services", [])), None)
            return f"{data['product']} at {(mgmt or {}).get('ip') or data.get('address')}"
    except (KeyError, TypeError):
        pass
    return kind


def evaluate_pipeline(
    *,
    host_id: str,
    os_epoch: int,
    jobs: list[Job],
    outputs: dict[str, OutputMeta | None],
    has_os_access: bool,
) -> Pipeline:
    """Pure function: the state of every task for one host, and the recommended next step."""
    jobs_by_id = {j.id: j for j in jobs}
    last_job: dict[str, Job] = {}
    for j in jobs:  # newest first
        last_job.setdefault(j.task, j)

    def fresh(spec: TaskSpec | None, meta: OutputMeta) -> bool:
        return not (spec and spec.os_bound) or meta.epoch >= os_epoch

    states: dict[str, TaskState] = {}
    for spec in CATALOG:
        blocked: list[str] = []
        for req in spec.requires:
            if req == OS_ACCESS:
                if not has_os_access:
                    blocked.append("Set OS access, or deploy an OS")
                continue
            producer = PRODUCER.get(req)
            meta = outputs.get(req)
            title = producer.title if producer else req
            if meta is None:
                blocked.append(f"Run “{title}” first")
            elif not fresh(producer, meta):
                blocked.append(f"Run “{title}” again (the OS was reinstalled)")

        output: OutputInfo | None = None
        meta = outputs.get(spec.produces) if spec.produces else None
        if meta is not None:
            producing = jobs_by_id.get(meta.job_id)
            siblings = [t for t in CATALOG if t.produces == spec.produces and t.id != spec.id]
            # Shared output kinds (both OS deployments produce "install"): attribute to the task that ran.
            if not (producing and siblings and producing.task != spec.id and producing.task in TASKS):
                output = OutputInfo(
                    kind=spec.produces or "", job_id=meta.job_id, produced_at=meta.created_at,
                    fresh=fresh(spec, meta), summary=summarize(spec.produces or "", meta.data),
                )  # fmt: skip

        job = last_job.get(spec.id)
        ref = None
        if job is not None:
            ref = JobRef(id=job.id, status=job.status, finished_at=job.finished_at,
                         error=job.error.message if job.error else None)  # fmt: skip

        state: TaskStateName
        if not spec.available:
            state = "planned"
        elif job is not None and not job.status.is_terminal:
            state = "running"
        elif (
            job is not None
            and job.status in (JobStatus.FAILED, JobStatus.CANCELLED)
            and (output is None or (job.finished_at is not None and job.finished_at > output.produced_at))
        ):
            state = "failed"
        elif output is not None and output.fresh:
            state = "done"
        elif output is not None:
            state = "stale"
        elif blocked:
            state = "blocked"
        else:
            state = "ready"
        states[spec.id] = TaskState(**info(spec).model_dump(), state=state, blocked_by=blocked,
                                    last_job=ref, output=output)  # fmt: skip

    stages = []
    for stage in Stage:
        tasks = [states[t.id] for t in CATALOG if t.stage is stage]
        stages.append(
            PipelineStage(id=stage, title=STAGE_TITLES[stage], state=_stage_state(tasks), tasks=tasks)
        )
    return Pipeline(host_id=host_id, os_epoch=os_epoch, stages=stages, next=_next(states, has_os_access))


def _stage_state(tasks: list[TaskState]) -> TaskStateName:
    if any(t.state == "running" for t in tasks):
        return "running"
    core = [t for t in tasks if not t.optional and t.available] or [t for t in tasks if t.available]
    if not core:
        return "planned"
    for state in ("failed", "stale", "blocked", "ready"):
        if any(t.state == state for t in core):
            return state
    return "done"


def _next(states: dict[str, TaskState], has_os_access: bool) -> NextStep:
    running = [s for s in states.values() if s.state == "running"]
    if running:
        return NextStep(task=None, title=running[0].title, reason=f"{running[0].title} is running")
    for spec in CATALOG:
        s = states[spec.id]
        if spec.optional or not spec.available:
            continue
        if s.state == "ready":
            return NextStep(task=spec.id, title=spec.title, reason=spec.description)
        if s.state == "stale":
            return NextStep(task=spec.id, title=spec.title, reason="The OS was reinstalled; read it again.")
        if s.state == "failed":
            error = s.last_job.error if s.last_job else None
            return NextStep(
                task=spec.id, title=spec.title, reason=f"The last run failed: {error or 'see the job'}"
            )
        if s.state == "blocked":
            if spec.requires and OS_ACCESS in spec.requires and not has_os_access:
                return NextStep(task="os.custom", title="Deploy custom OS",
                                reason="GroundZero can't reach an OS on this server yet. Deploy one, "
                                "or set OS access if one is already installed.")  # fmt: skip
            return NextStep(task=None, title=spec.title, reason="; ".join(s.blocked_by))
    planned = next((t for t in CATALOG if not t.available), None)
    if planned:
        return NextStep(
            task=None,
            title=planned.title,
            reason=f"All available steps are done. Next in the pipeline: {planned.title} (coming).",
        )
    return NextStep(task=None, title="Done", reason="Every step is done.")
