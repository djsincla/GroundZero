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


def catalog() -> tuple[TaskSpec, ...]:
    """Every task, in pipeline order: one per module (see groundzero.modules)."""
    from groundzero.modules import MODULES

    return tuple(m.spec() for m in MODULES)


def producers(specs: tuple[TaskSpec, ...]) -> dict[str, TaskSpec]:
    """Which task to point at when an output is missing. "install" has two producers and is never required."""
    found: dict[str, TaskSpec] = {}
    for spec in specs:
        if spec.produces and spec.produces not in found:
            found[spec.produces] = spec
    return found


def summarize(task_id: str, kind: str, data: dict[str, Any]) -> str:
    """One line describing an output, for the pipeline view (the producing module's own wording)."""
    from groundzero.modules import REGISTRY

    module = REGISTRY.get(task_id)
    try:
        return module.summarize(data) if module else kind
    except (KeyError, TypeError):
        return kind


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
    params_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema of the task's parameters (POST .../tasks/{id} params)"
    )


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


def info(spec: TaskSpec, params_schema: dict[str, Any] | None = None) -> TaskInfo:
    return TaskInfo(
        id=spec.id,
        title=spec.title,
        stage=spec.stage,
        description=spec.description,
        produces=spec.produces,
        requires=list(spec.requires),
        optional=spec.optional,
        destructive=spec.destructive,
        available=spec.available,
        params_schema=params_schema or {},
    )


# ── pipeline evaluation ─────────────────────────────────────────────────
def evaluate_pipeline(
    *,
    host_id: str,
    os_epoch: int,
    jobs: list[Job],
    outputs: dict[str, OutputMeta | None],
    has_os_access: bool,
) -> Pipeline:
    """Pure function: the state of every task for one host, and the recommended next step."""
    specs = catalog()
    tasks_by_id = {t.id: t for t in specs}
    producer_of = producers(specs)
    jobs_by_id = {j.id: j for j in jobs}
    last_job: dict[str, Job] = {}
    for j in jobs:  # newest first
        last_job.setdefault(j.task, j)

    def fresh(spec: TaskSpec | None, meta: OutputMeta) -> bool:
        return not (spec and spec.os_bound) or meta.epoch >= os_epoch

    states: dict[str, TaskState] = {}
    for spec in specs:
        blocked: list[str] = []
        for req in spec.requires:
            if req == OS_ACCESS:
                if not has_os_access:
                    blocked.append("Set OS access, or deploy an OS")
                continue
            producer = producer_of.get(req)
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
            siblings = [t for t in specs if t.produces == spec.produces and t.id != spec.id]
            # Shared output kinds (both OS deployments produce "install"): attribute to the task that ran.
            if not (producing and siblings and producing.task != spec.id and producing.task in tasks_by_id):
                output = OutputInfo(
                    kind=spec.produces or "",
                    job_id=meta.job_id,
                    produced_at=meta.created_at,
                    fresh=fresh(spec, meta),
                    summary=summarize(spec.id, spec.produces or "", meta.data),
                )

        job = last_job.get(spec.id)
        ref = None
        if job is not None:
            ref = JobRef(
                id=job.id,
                status=job.status,
                finished_at=job.finished_at,
                error=job.error.message if job.error else None,
            )

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
        elif spec.produces is None and job is not None and job.status is JobStatus.SUCCEEDED:
            state = "done"  # e.g. capture: its result is a config set, not a host output
        elif output is not None:
            state = "stale"
        elif blocked:
            state = "blocked"
        else:
            state = "ready"
        states[spec.id] = TaskState(
            **info(spec).model_dump(), state=state, blocked_by=blocked, last_job=ref, output=output
        )

    stages = []
    for stage in Stage:
        tasks = [states[t.id] for t in specs if t.stage is stage]
        stages.append(
            PipelineStage(id=stage, title=STAGE_TITLES[stage], state=_stage_state(tasks), tasks=tasks)
        )
    return Pipeline(
        host_id=host_id, os_epoch=os_epoch, stages=stages, next=_next(specs, states, has_os_access)
    )


def _stage_state(tasks: list[TaskState]) -> TaskStateName:
    if any(t.state == "running" for t in tasks):
        return "running"
    available = [t for t in tasks if t.available]
    if not available:
        return "planned"
    core = [t for t in available if not t.optional]
    if not core:
        # Only alternatives/utilities (the OS stage): done once any of them has done its job. Runnable
        # alternatives such as a config-set deployment don't make an installed OS look unfinished.
        order: tuple[TaskStateName, ...] = ("done", "stale", "failed")
        for state in order:
            if any(t.state == state for t in available):
                return state
        return "ready"
    for state in ("failed", "stale", "blocked", "ready"):
        if any(t.state == state for t in core):
            return state
    return "done"


def _next(specs: tuple[TaskSpec, ...], states: dict[str, TaskState], has_os_access: bool) -> NextStep:
    running = [s for s in states.values() if s.state == "running"]
    if running:
        return NextStep(task=None, title=running[0].title, reason=f"{running[0].title} is running")
    for spec in specs:
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
                return NextStep(
                    task="os.custom",
                    title="Deploy OS · custom ISO from a config set",
                    reason="GroundZero can't reach an OS on this server yet. Deploy one, "
                    "or set OS access if one is already installed.",
                )
            return NextStep(task=None, title=spec.title, reason="; ".join(s.blocked_by))
    planned = next((t for t in specs if not t.available), None)
    if planned:
        return NextStep(
            task=None,
            title=planned.title,
            reason=f"All available steps are done. Next in the pipeline: {planned.title} (coming).",
        )
    return NextStep(task=None, title="Done", reason="Every step is done.")
