"""Per-job diagnostics: redaction, secret scrubbing and capture of every BMC exchange."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from conftest import make_client

from groundzero.core import diagnostics
from groundzero.core.jobs import JobContext, JobRunner
from groundzero.core.models import JobKind, JobStatus, JobStepStatus
from groundzero.core.store import Store


def test_redaction_of_keys_media_tokens_and_known_secrets() -> None:
    diag = diagnostics.Diagnostics("j")
    diag.add_secret("hunter22")
    diag.record("x", body={"UserName": "root", "Password": "p", "passed": 12, "Oem": {"X-Auth-Token": "t"}},
                url="https://10.0.0.1/media/0123abcd/esxi.iso", note="password is hunter22")  # fmt: skip
    event = diag.export()["events"][0]
    assert event["body"] == {"UserName": "root", "Password": "«redacted»", "passed": 12,
                             "Oem": {"X-Auth-Token": "«redacted»"}}  # fmt: skip
    assert event["url"] == "https://10.0.0.1/media/«token»/esxi.iso"
    assert "hunter22" not in json.dumps(diag.export())


def test_recording_outside_a_job_is_a_no_op() -> None:
    diagnostics.record("x", a=1)  # must not raise
    assert diagnostics.current.get() is None


def test_a_job_records_redfish_exchanges_steps_and_errors_without_secrets(
    tmp_path: Path, idrac9: dict[str, dict[str, Any]]
) -> None:
    store = Store(tmp_path / "db.sqlite3")
    host = store.add_host(name="h", bmc_address="bmc.test", username="root", secret=b"x", verify_tls=False)

    async def scenario() -> None:
        runner = JobRunner(store, 2)

        async def work(ctx: JobContext) -> dict[str, Any]:
            ctx.plan([("read", "Read the system"), ("fail", "Do something that fails")])
            async with ctx.step("read", "Read the system"), make_client(idrac9) as client:
                await client.get_json("/redfish/v1/Systems/System.Embedded.1")
            async with ctx.step("fail", "Do something that fails"):
                raise RuntimeError("the BMC said no")
            return {}

        job = runner.submit(kind=JobKind.INVENTORY, host_id=host.id, params={}, func=work)
        await runner.wait(job.id)

    asyncio.run(scenario())
    job = store.list_jobs(host_id=host.id)[0]
    assert job.status is JobStatus.FAILED
    assert [(s.key, s.status) for s in job.steps] == [
        ("read", JobStepStatus.SUCCEEDED),
        ("fail", JobStepStatus.FAILED),
    ]
    assert job.steps[1].message == "the BMC said no" and job.steps[1].finished_at is not None

    bundle = store.get_diagnostics(job.id)
    assert bundle is not None
    text = json.dumps(bundle)
    assert "calvin" not in text  # the BMC password given to the client
    redfish = [e for e in bundle["events"] if e["event"] == "redfish"]
    system = next(e for e in redfish if e["path"] == "/redfish/v1/Systems/System.Embedded.1")
    assert system["status"] == 200 and system["method"] == "GET" and "ms" in system
    assert system["response"]["Model"]  # the body is kept for debugging other vendors
    error = next(e for e in bundle["events"] if e["event"] == "error")
    assert "the BMC said no" in error["message"] and "Traceback" in error["traceback"]


def test_existing_databases_gain_the_new_columns(tmp_path: Path) -> None:
    db = tmp_path / "old.sqlite3"
    with sqlite3.connect(db) as conn:  # the shape before tasks/epochs existed
        conn.executescript(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, host_id TEXT NOT NULL,"
            " status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',"
            " params TEXT NOT NULL DEFAULT '{}', result TEXT, error TEXT, created_at TEXT NOT NULL,"
            " started_at TEXT, finished_at TEXT);"
            "INSERT INTO jobs (id, kind, host_id, status, created_at) VALUES"
            " ('j1', 'inventory', 'h', 'succeeded', '2026-10-01T00:00:00+00:00');"
        )
    store = Store(db)
    job = store.get_job("j1")
    assert job is not None and job.steps == [] and job.task == "discover"
