"""The task pipeline: states, staleness after a reinstall and the recommended next step (pure logic)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from groundzero.core.models import Job, JobError, JobStatus
from groundzero.core.store import OutputMeta
from groundzero.core.tasks import Pipeline, evaluate_pipeline

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
NETWORK = {"product": "VMware ESXi 9.1.1", "address": "192.0.2.101",
           "vmkernel": [{"ip": "192.0.2.101", "services": ["management"]}]}  # fmt: skip
PREFLIGHT = {"overall": "warn", "summary": {"passed": 12, "warnings": 1, "failed": 0}}
VCF = {"overall": "warn", "summary": {"passed": 0, "warnings": 1, "failed": 0}, "cpu_override_required": True}


def _job(job_id: str, task: str, status: JobStatus, minutes: int, **params: Any) -> Job:
    at = T0 + timedelta(minutes=minutes)
    error = JobError(type="x", message="boom") if status is JobStatus.FAILED else None
    return Job(id=job_id, task=task, host_id="h", status=status, params=params, created_at=at,
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


def p_optional(p: Pipeline, task: str) -> bool:
    return next(t.optional for s in p.stages for t in s.tasks if t.id == task)


def _state(p: Pipeline, task: str) -> str:
    return next(t.state for s in p.stages for t in s.tasks if t.id == task)


def test_a_new_host_starts_with_preflight() -> None:
    p = _pipeline([], {}, os_access=False)
    assert p.next.task == "preflight"
    assert _state(p, "os.read") == "blocked"
    assert _state(p, "host.assess") == "blocked"
    assert _state(p, "host.prep") == "blocked"
    assert _state(p, "holodeck.router") == "blocked"
    assert _state(p, "holodeck.stage") == "planned"
    assert [s.id for s in p.stages] == ["hardware", "os", "readiness", "prep", "appliances", "holodeck"]


def test_without_os_access_the_next_step_is_deploying_an_os() -> None:
    jobs = [_job("p1", "preflight", JobStatus.SUCCEEDED, 1)]
    early = _pipeline(
        jobs, {"preflight": _out("p1", 1, PREFLIGHT), "inventory": _out("p1", 1, {})}, os_access=False
    )
    assert early.next.task == "os.custom"  # VCF 9 readiness is optional: it never blocks the next step
    assert _state(early, "vcf.readiness") == "ready" and p_optional(early, "vcf.readiness")
    jobs.append(_job("v1", "vcf.readiness", JobStatus.SUCCEEDED, 2))
    outputs = {
        "preflight": _out("p1", 1, PREFLIGHT),
        "inventory": _out("p1", 1, {}),
        "vcf_readiness": _out("v1", 2, VCF),
    }
    p = _pipeline(jobs, outputs, os_access=False)
    assert _state(p, "vcf.readiness") == "done"
    assert next(t for t in p.stages[0].tasks if t.id == "vcf.readiness").output.summary == (  # type: ignore[union-attr]
        "warn: 0 passed, 1 warnings, 0 failed · CPU override needed for ESXi 9"
    )
    assert _state(p, "preflight") == "done"
    assert p.next.task == "os.custom" and "Deploy" in p.next.title
    os_read = next(t for t in p.stages[1].tasks if t.id == "os.read")
    assert os_read.blocked_by == ["Set OS access, or deploy an OS"]


def test_outputs_feed_the_next_task_and_go_stale_after_a_reinstall() -> None:
    jobs = [
        _job("p1", "preflight", JobStatus.SUCCEEDED, 1),
        _job("a1", "host.assess", JobStatus.SUCCEEDED, 2),
    ]
    readiness = {
        "ready": False,
        "variant_title": "VCF 9.0",
        "overall": "fail",
        "summary": {"failed": 3},
        "plan": [1, 2],
    }
    outputs = {"preflight": _out("p1", 1, PREFLIGHT), "vcf_readiness": _out("p1", 1, VCF),
               "readiness": _out("a1", 2, readiness, epoch=0),
               "os_network": _out("a1", 2, NETWORK, epoch=0)}  # fmt: skip
    p = _pipeline(jobs, outputs)
    assert _state(p, "host.assess") == "done" and _state(p, "os.read") == "done"
    assess = next(t for t in p.stages[2].tasks if t.id == "host.assess")
    assert assess.output is not None and assess.output.summary == "3 to fix for VCF 9.0 · 2 planned actions"
    assert p.next.task == "host.prep"  # the readiness output is its input

    reinstalled = _pipeline(jobs, outputs, epoch=1)  # an install bumped the OS epoch
    assert _state(reinstalled, "host.assess") == "stale" and _state(reinstalled, "os.read") == "stale"
    assert reinstalled.next.task == "host.assess" and "reinstalled" in reinstalled.next.reason
    assert next(s for s in reinstalled.stages if s.id == "readiness").state == "stale"


def test_a_failed_run_is_shown_and_offered_again() -> None:
    jobs = [_job("p1", "preflight", JobStatus.FAILED, 1)]
    p = _pipeline(jobs, {})
    assert _state(p, "preflight") == "failed"
    assert p.next.task == "preflight" and "boom" in p.next.reason


def test_a_running_task_is_reported_and_nothing_else_is_suggested() -> None:
    p = _pipeline([_job("p1", "preflight", JobStatus.RUNNING, 1)], {})
    assert _state(p, "preflight") == "running"
    assert p.next.task is None and "running" in p.next.reason


def test_the_two_os_deployments_are_attributed_to_the_task_that_ran() -> None:
    report = {"iso_version": "9.1.1", "iso_build": "25714478", "installed_build": "25714478",
              "validation": [{"ok": True}]}  # fmt: skip
    jobs = [_job("i1", "os.custom", JobStatus.SUCCEEDED, 1, config_set_id="cs1")]
    p = _pipeline(jobs, {"install": _out("i1", 1, report)})
    assert _state(p, "os.custom") == "done"
    assert _state(p, "os.reimage") == "ready"  # did not run; not "done"
    custom = next(t for t in p.stages[1].tasks if t.id == "os.custom")
    assert (
        custom.output is not None
        and custom.output.summary == "ESXi 9.1.1 build 25714478 installed and validated"
    )


def test_an_installed_os_stage_is_done_even_though_alternatives_can_run() -> None:
    """Regression (user report): the OS stage showed "ready" with the OS installed, validated and read."""
    report = {"iso_version": "9.1.1", "iso_build": "1", "installed_build": "1", "validation": [{"ok": True}]}
    jobs = [
        _job("i1", "os.reimage", JobStatus.SUCCEEDED, 1),
        _job("n1", "os.read", JobStatus.SUCCEEDED, 2),
        _job("c1", "os.capture", JobStatus.SUCCEEDED, 3, name="lab"),
    ]
    p = _pipeline(jobs, {"install": _out("i1", 1, report), "os_network": _out("n1", 2, NETWORK)})
    os_stage = next(s for s in p.stages if s.id == "os")
    assert os_stage.state == "done"
    assert _state(p, "os.custom") == "ready"  # still offered as an alternative
    assert _state(p, "os.capture") == "done"  # its last run succeeded

    reinstalled = _pipeline(
        jobs, {"install": _out("i1", 1, report), "os_network": _out("n1", 2, NETWORK)}, epoch=1
    )
    assert (
        next(s for s in reinstalled.stages if s.id == "os").state == "done"
    )  # the install itself is current


def test_an_os_stage_with_nothing_run_yet_is_ready() -> None:
    assert next(s for s in _pipeline([], {}, os_access=False).stages if s.id == "os").state == "ready"


def test_install_history_says_what_went_into_the_custom_iso() -> None:
    """User report: the esxi1 install used a custom ISO with the lab's parameters; the history must say so."""
    spec = {"network": {"vlan_id": 100, "install_nic": "vmnic0", "extra_uplinks": ["vmnic1"]},
            "ntp_servers": ["pool.ntp.org"], "preserve_vmfs": True, "allow_legacy_cpu": True}  # fmt: skip
    report = {"iso_version": "9.1.1", "iso_build": "25714478", "installed_build": "25714478",
              "validation": [{"ok": True}], "spec": spec}  # fmt: skip
    p = _pipeline([_job("i1", "os.reimage", JobStatus.SUCCEEDED, 1)], {"install": _out("i1", 1, report)})
    reimage = next(t for t in p.stages[1].tasks if t.id == "os.reimage")
    assert reimage.title == "Deploy OS · custom ISO from current settings"
    assert reimage.output is not None and reimage.output.summary == (
        "ESXi 9.1.1 build 25714478 installed and validated · custom ISO: VLAN 100, vmnic0 + vmnic1, "
        "NTP pool.ntp.org, VMFS kept, CPU override"
    )
    assert (
        next(t for t in p.stages[1].tasks if t.id == "os.custom").title
        == "Deploy OS · custom ISO from a config set"
    )


GOOD_BIOS = {"bios": {"cpu_virtualization": True, "iommu": True, "boot_mode": "Uefi"}}
WRONG_BIOS = {"bios": {"cpu_virtualization": False, "iommu": True, "boot_mode": "Bios"}}


def test_configure_bios_comes_straight_after_discover() -> None:
    hardware = next(s for s in _pipeline([], {}).stages if s.id == "hardware")
    assert [t.id for t in hardware.tasks] == ["discover", "bios.configure", "storage.read", "preflight", "vcf.readiness"]


def test_a_bios_that_is_already_right_needs_nothing() -> None:
    jobs = [_job("d1", "discover", JobStatus.SUCCEEDED, 1)]
    p = _pipeline(jobs, {"inventory": _out("d1", 1, GOOD_BIOS)}, os_access=False)
    bios = next(t for t in p.stages[0].tasks if t.id == "bios.configure")
    assert bios.state == "not_needed" and bios.conditional and bios.last_job is None  # nothing was run
    assert bios.not_needed == "Already on: processor virtualization, IOMMU, UEFI boot mode"
    assert p.next.task == "preflight"


def test_a_bios_that_needs_changing_is_the_next_step() -> None:
    jobs = [_job("d1", "discover", JobStatus.SUCCEEDED, 1)]
    p = _pipeline(jobs, {"inventory": _out("d1", 1, WRONG_BIOS)}, os_access=False)
    assert _state(p, "bios.configure") == "ready"
    assert p.next.task == "bios.configure"
    assert p.stages[0].state == "ready"  # the hardware stage isn't finished while the BIOS is wrong

    fixed = [*jobs, _job("b1", "bios.configure", JobStatus.SUCCEEDED, 2)]
    after = _pipeline(fixed, {"inventory": _out("b1", 2, GOOD_BIOS), "bios": _out("b1", 2, {"changes": []})},
                      os_access=False)  # fmt: skip
    assert _state(after, "bios.configure") == "done" and after.next.task == "preflight"


def test_without_an_inventory_configure_bios_waits_and_preflight_leads() -> None:
    p = _pipeline([], {})
    assert _state(p, "bios.configure") == "blocked"
    assert p.next.task == "preflight"  # optional until the inventory shows it's needed
