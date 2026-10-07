"""Spec runs: work through a server's spec one job at a time, or start every member of a cluster at once.

A run is approved once, with a typed phrase, after a preview that says which steps run, which are skipped
(done already, or not needed) and what the destructive ones change. Each step then goes through the same
``start_task`` as a job started by hand: its inputs are checked when it starts, so a step only runs once
the steps before it have produced what it needs. A destructive step still checks its own phrase; the run
supplies the phrase the step names, which the run's approval covers. The first failure stops the run.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from groundzero.core.jobs import HostBusyError
from groundzero.core.models import JobStatus
from groundzero.core.store import new_id, utcnow
from groundzero.core.tasks import OS_ACCESS, TaskRun, TaskState
from groundzero.modules import REGISTRY
from groundzero.specs import ClusterRunPreview, EffectiveSpec, PreviewStep, Run, RunPreview, RunStep

if TYPE_CHECKING:
    from groundzero.core.services import Services

logger = logging.getLogger(__name__)

# Output kinds a task makes besides its main one, plus OS access, which an OS deploy gives.
_GIVES_OS_ACCESS = ("os.custom", "os.reimage")


class RunOrchestrator:
    def __init__(self, services: Services) -> None:
        self.s = services
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._by_host: dict[str, str] = {}
        self._current_job: dict[str, str] = {}

    # ── preview and approval ─────────────────────────────────────────────
    def phrase(self, host_id: str) -> str:
        effective = self._effective(host_id)
        return f"run {effective.spec.name} on {self.s.get_host(host_id).name}"

    def preview(self, host_id: str) -> RunPreview:
        """What a run of this server's spec would do now: run, skip (and why), or blocked (and on what)."""
        from groundzero.core.services import ConflictError  # avoid an import cycle

        host = self.s.get_host(host_id)
        effective = self._effective(host_id)
        spec = effective.spec
        states = {t.id: t for stage in self.s.pipeline(host_id).stages for t in stage.tasks}
        will_make: set[str] = set()  # outputs earlier steps of this run will produce
        steps: list[PreviewStep] = []
        changes: list[str] = []
        for step in spec.steps:
            module = REGISTRY[step.task]
            state = states.get(step.task)
            params = self.s.spec_params(host_id, step)
            if state is None:
                raise ConflictError(f"Task {step.task} is no longer in the pipeline")
            action, reason = _plan(state, will_make)
            if action == "run":
                will_make.update(k for k in (module.produces, *module.also_produces) if k)
                if step.task in _GIVES_OS_ACCESS:
                    will_make.add(OS_ACCESS)
                if module.destructive:
                    changes.append(f"{module.title}: {module.description}")
            steps.append(
                PreviewStep(
                    task=step.task,
                    title=module.title,
                    action=action,
                    reason=reason,
                    destructive=module.destructive and action == "run",
                    params=params,
                )
            )
        return RunPreview(
            host_id=host.id,
            host_name=host.name,
            spec_id=spec.id,
            spec_name=spec.name,
            source=effective.source,
            phrase=f"run {spec.name} on {host.name}",
            steps=steps,
            destructive=changes,
        )

    def cluster_preview(self, cluster_id: str) -> ClusterRunPreview:
        cluster = self.s.get_cluster(cluster_id)
        previews, without = [], []
        for member in cluster.members:
            if self.s.effective_spec(member.host_id) is None:
                without.append(member.host_name)
            else:
                previews.append(self.preview(member.host_id))
        return ClusterRunPreview(
            cluster_id=cluster.id,
            cluster_name=cluster.name,
            phrase=f"run cluster {cluster.name}",
            hosts=previews,
            without_spec=without,
        )

    # ── starting, cancelling, reading ────────────────────────────────────
    def start(self, host_id: str, confirm: str, *, cluster_id: str | None = None) -> Run:
        from groundzero.core.services import ConfirmationError, ConflictError

        expected = self.phrase(host_id)
        if cluster_id is None and confirm != expected:
            raise ConfirmationError(
                f'The run approves every step, destructive ones too: confirm with exactly "{expected}"',
                expected,
            )
        return self._launch(host_id, cluster_id, ConflictError)

    def start_cluster(self, cluster_id: str, confirm: str) -> list[Run]:
        from groundzero.core.services import ConfirmationError, ConflictError

        preview = self.cluster_preview(cluster_id)
        if confirm != preview.phrase:
            raise ConfirmationError(
                f'This runs every member\'s spec, destructive steps too: confirm with "{preview.phrase}"',
                preview.phrase,
            )
        if not preview.hosts:
            raise ConflictError("No member of this cluster has a spec: give the cluster one first")
        busy = [p.host_name for p in preview.hosts if p.host_id in self._by_host]
        if busy:
            raise ConflictError(f"Already running on {', '.join(busy)}")
        return [self._launch(p.host_id, cluster_id, ConflictError) for p in preview.hosts]

    def _launch(self, host_id: str, cluster_id: str | None, conflict: type[Exception]) -> Run:
        if (active := self._by_host.get(host_id)) is not None:
            raise conflict(f"A run is already in progress on this server ({active})")
        host = self.s.get_host(host_id)
        spec = self._effective(host_id).spec
        run = Run(
            id=new_id(),
            host_id=host.id,
            host_name=host.name,
            spec_id=spec.id,
            spec_name=spec.name,
            cluster_id=cluster_id,
            steps=[RunStep(task=s.task, title=REGISTRY[s.task].title) for s in spec.steps],
            created_at=utcnow(),
        )
        self.s.store.save_run(run)
        self._by_host[host_id] = run.id
        self._tasks[run.id] = asyncio.create_task(self._drive(run), name=f"run-{run.id}")
        return run

    def cancel(self, run_id: str) -> Run:
        from groundzero.core.services import ConflictError

        run = self.get(run_id)
        task = self._tasks.get(run_id)
        if task is None or task.done():
            raise ConflictError(f"Run {run_id} is not in progress")
        if (job_id := self._current_job.get(run_id)) is not None:
            self.s.runner.cancel(job_id)
        task.cancel()
        return run

    def get(self, run_id: str) -> Run:
        from groundzero.core.services import NotFoundError

        run = self.s.store.get_run(run_id)
        if run is None:
            raise NotFoundError(f"Run {run_id} not found")
        return run

    async def wait(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── the run itself ───────────────────────────────────────────────────
    async def _drive(self, run: Run) -> None:
        from groundzero.core.services import ConfirmationError, SettingsValidationError

        spec = self._effective(run.host_id).spec
        params_by_task = {s.task: s for s in spec.steps}
        try:
            for step in run.steps:
                state = next(
                    t
                    for stage in self.s.pipeline(run.host_id).stages
                    for t in stage.tasks
                    if t.id == step.task
                )
                action, reason = _plan(state, set())
                if action == "skip":
                    step.status, step.reason = "skipped", reason
                    self.s.store.save_run(run)
                    continue
                if action == "blocked":
                    step.status, step.reason = "failed", reason
                    raise _Stop(f"{step.title} can't start: {reason}")
                step.status = "running"
                self.s.store.save_run(run)
                params = self.s.spec_params(run.host_id, params_by_task[step.task])
                try:
                    job_id = await self._submit(run.host_id, step.task, params)
                except ConfirmationError as exc:  # a step needing a phrase it didn't name: never guessed
                    step.status, step.reason = "failed", str(exc)
                    raise _Stop(str(exc)) from exc
                except SettingsValidationError as exc:
                    detail = "; ".join(_error_text(e) for e in exc.errors)
                    step.status, step.reason = "failed", detail
                    raise _Stop(f"{step.title}: {detail}") from exc
                except Exception as exc:  # a 4xx from start_task: missing input, bad parameter, ...
                    step.status, step.reason = "failed", str(exc)
                    raise _Stop(f"{step.title}: {exc}") from exc
                step.job_id = job_id
                self._current_job[run.id] = job_id
                self.s.store.save_run(run)
                await self.s.runner.wait(job_id)
                self._current_job.pop(run.id, None)
                job = self.s.store.get_job(job_id)
                if job is None or job.status is not JobStatus.SUCCEEDED:
                    message = job.error.message if job and job.error else (job.message if job else "lost")
                    if job is not None and job.status is JobStatus.CANCELLED:
                        step.status = "cancelled"
                        raise asyncio.CancelledError
                    step.status, step.reason = "failed", message
                    raise _Stop(f"{step.title} failed: {message}")
                step.status = "succeeded"
                self.s.store.save_run(run)
            run.status = "succeeded"
        except _Stop as stop:
            run.status, run.error = "failed", str(stop)
            _cancel_rest(run)
        except asyncio.CancelledError:
            run.status, run.error = "cancelled", "Cancelled"
            _cancel_rest(run)
        except Exception as exc:  # a bug: record it on the run rather than lose it
            logger.exception("Run %s failed", run.id)
            run.status, run.error = "failed", f"{type(exc).__name__}: {exc}"
            _cancel_rest(run)
        finally:
            run.finished_at = utcnow()
            self.s.store.save_run(run)
            self._by_host.pop(run.host_id, None)
            self._tasks.pop(run.id, None)
            self._current_job.pop(run.id, None)

    async def _submit(self, host_id: str, task: str, params: dict[str, object]) -> str:
        """Start one step through start_task. A destructive step names its phrase; the run supplies it."""
        from groundzero.core.services import ConfirmationError

        confirm: str | None = None
        while True:
            try:
                return self.s.start_task(host_id, task, TaskRun(params=params, confirm=confirm)).id
            except ConfirmationError as exc:
                if confirm is not None or not exc.phrase:
                    raise
                confirm = exc.phrase
            except HostBusyError as busy:  # a job started by hand: let it finish, then go on
                await self.s.runner.wait(busy.job_id)
                await asyncio.sleep(0.05)

    def _effective(self, host_id: str) -> EffectiveSpec:
        from groundzero.core.services import ConflictError

        effective = self.s.effective_spec(host_id)
        if effective is None:
            raise ConflictError(
                f"{self.s.get_host(host_id).name} has no spec: give it one, or a cluster with one"
            )
        return effective


def _error_text(error: dict[str, object]) -> str:
    loc = error.get("loc")
    where = ".".join(str(x) for x in loc) if isinstance(loc, list) else ""
    return f"{where}: {error.get('msg')}"


class _Stop(Exception):
    """End the run as failed, with this message."""


def _cancel_rest(run: Run) -> None:
    for step in run.steps:
        if step.status in ("pending", "running"):
            step.status = "cancelled"


def _plan(state: TaskState, will_make: set[str]) -> tuple[str, str | None]:
    """run, skip or blocked for one step, given what earlier steps of the run will produce."""
    if state.state == "done" and state.output is not None:
        return "skip", f"Done already: {state.output.summary}"
    if state.state == "done":
        return "skip", "Done already"
    if state.state == "not_needed":
        return "skip", f"Not needed: {state.not_needed}"
    if state.state == "blocked":
        missing = [i for i in state.inputs if i.required and i.status != "ok" and i.kind not in will_make]
        if missing:
            return "blocked", "; ".join(state.blocked_by)
        return "run", "After the steps before it"
    return "run", None
