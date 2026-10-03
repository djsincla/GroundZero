"""The task pipeline: states, staleness after a reinstall and the recommended next step (pure logic)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from groundzero.core.models import Job, JobError, JobKind, JobStatus
from groundzero.core.store import OutputMeta
from groundzero.core.tasks import Pipeline, evaluate_pipeline

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
NETWORK = {"product": "VMware ESXi 9.1.1", "address": "192.0.2.101",
           "vmkernel": [{"ip": "192.0.2.101", "services": ["management"]}]}  # fmt: skip
PREFLIGHT = {"overall": "warn", "summary": {"passed": 12, "warnings": 1, "failed": 0}}


def _job(job_id: str, kind: JobKind, status: JobStatus, minutes: int, **params: Any) -> Job:
    at = T0 + timedelta(minutes=minutes)
    error = JobError(type="x", message="boom") if status is JobStatus.FAILED else None
    return Job(id=job_id, kind=kind, host_id="h", status=status, params=params, created_at=at,
               finished_at=None if status is JobStatus.RUNNING else at, error=error)  # fmt: skip


def _out(job_id: str, minutes: int, data: dict[str, Any], epoch: int = 0) -> OutputMeta:
    return OutputMeta(data, job_id, T0 + timedelta(minutes=minutes), epoch)


def _pipeline(
    jobs: list[Job], outputs: dict[str, OutputMeta], *, os_access: bool = True, epoch: int = 0
) -> Pipeline:
    return evaluate_pipeline(
        host_id="h", os_epoch=epoch, jobs=sorted(jobs, key=lambda j: j.created_at, reverse=True),
        outputs=outputs, has_os_access=os_access,
    )  # fmt: skip


def _state(p: Pipeline, task: str) -> str:
    return next(t.state for s in p.stages for t in s.tasks if t.id == task)


def test_a_new_host_starts_with_preflight() -> None:
    p = _pipeline([], {}, os_access=False)
    assert p.next.task == "preflight"
    assert _state(p, "os.read") == "blocked"
    assert _state(p, "host.assess") == "planned"
    assert [s.id for s in p.stages] == ["hardware", "os", "readiness", "prep", "holodeck"]


def test_without_os_access_the_next_step_is_deploying_an_os() -> None:
    jobs = [_job("p1", JobKind.PREFLIGHT, JobStatus.SUCCEEDED, 1)]
    p = _pipeline(
        jobs, {"preflight": _out("p1", 1, PREFLIGHT), "inventory": _out("p1", 1, {})}, os_access=False
    )
    assert _state(p, "preflight") == "done"
    assert p.next.task == "os.custom" and "Deploy" in p.next.title
    os_read = next(t for t in p.stages[1].tasks if t.id == "os.read")
    assert os_read.blocked_by == ["Set OS access, or deploy an OS"]


def test_outputs_feed_the_next_task_and_go_stale_after_a_reinstall() -> None:
    jobs = [
        _job("p1", JobKind.PREFLIGHT, JobStatus.SUCCEEDED, 1),
        _job("n1", JobKind.OS_NETWORK, JobStatus.SUCCEEDED, 2),
    ]
    outputs = {"preflight": _out("p1", 1, PREFLIGHT), "os_network": _out("n1", 2, NETWORK, epoch=0)}
    p = _pipeline(jobs, outputs)
    assert _state(p, "os.read") == "done"
    os_read = next(t for t in p.stages[1].tasks if t.id == "os.read")
    assert os_read.output is not None and os_read.output.summary == "VMware ESXi 9.1.1 at 192.0.2.101"
    assert p.next.task is None and "Assess Holodeck readiness" in p.next.reason  # the next stage is planned

    reinstalled = _pipeline(jobs, outputs, epoch=1)  # an install bumped the OS epoch
    assert _state(reinstalled, "os.read") == "stale"
    assert reinstalled.next.task == "os.read" and "reinstalled" in reinstalled.next.reason
    assert next(s for s in reinstalled.stages if s.id == "os").state == "stale"


def test_a_failed_run_is_shown_and_offered_again() -> None:
    jobs = [_job("p1", JobKind.PREFLIGHT, JobStatus.FAILED, 1)]
    p = _pipeline(jobs, {})
    assert _state(p, "preflight") == "failed"
    assert p.next.task == "preflight" and "boom" in p.next.reason


def test_a_running_task_is_reported_and_nothing_else_is_suggested() -> None:
    p = _pipeline([_job("p1", JobKind.PREFLIGHT, JobStatus.RUNNING, 1)], {})
    assert _state(p, "preflight") == "running"
    assert p.next.task is None and "running" in p.next.reason


def test_the_two_os_deployments_are_attributed_to_the_task_that_ran() -> None:
    report = {"iso_version": "9.1.1", "iso_build": "25714478", "installed_build": "25714478",
              "validation": [{"ok": True}]}  # fmt: skip
    jobs = [_job("i1", JobKind.INSTALL, JobStatus.SUCCEEDED, 1, config_set_id="cs1")]
    p = _pipeline(jobs, {"install": _out("i1", 1, report)})
    assert _state(p, "os.custom") == "done"
    assert _state(p, "os.reimage") == "ready"  # did not run; not "done"
    custom = next(t for t in p.stages[1].tasks if t.id == "os.custom")
    assert (
        custom.output is not None
        and custom.output.summary == "ESXi 9.1.1 build 25714478 installed and validated"
    )
