"""SQLite persistence for hosts, jobs and results."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from groundzero.core.models import ConfigSet, Host, Job, JobError, JobKind, JobStatus, OsAccess

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hosts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    bmc_address TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    secret BLOB NOT NULL,
    verify_tls INTEGER NOT NULL,
    vendor TEXT,
    model TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    host_id TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_host ON jobs(host_id, created_at);
CREATE TABLE IF NOT EXISTS results (
    host_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    job_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS results_host ON results(host_id, kind, created_at);
CREATE TABLE IF NOT EXISTS os_access (
    host_id TEXT PRIMARY KEY,
    address TEXT NOT NULL,
    username TEXT NOT NULL,
    secret BLOB NOT NULL,
    verify_tls INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS config_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    os_family TEXT NOT NULL,
    settings TEXT NOT NULL,
    secrets BLOB,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pins (
    host_id TEXT NOT NULL,
    role TEXT NOT NULL,
    address TEXT NOT NULL,
    pem TEXT NOT NULL,
    pinned_at TEXT NOT NULL,
    PRIMARY KEY (host_id, role)
);
CREATE TABLE IF NOT EXISTS host_values (
    host_id TEXT NOT NULL,
    os_family TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (host_id, os_family)
);
"""


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Store:
    """Thread-safe repository over one SQLite connection."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._tx() as cur:
            cur.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        with self._lock, self._conn:
            yield self._conn.cursor()

    # ── hosts ────────────────────────────────────────────────────────────
    def add_host(
        self, *, name: str, bmc_address: str, username: str, secret: bytes, verify_tls: bool
    ) -> Host:
        host = Host(
            id=new_id(),
            name=name,
            bmc_address=bmc_address,
            username=username,
            verify_tls=verify_tls,
            created_at=utcnow(),
        )
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO hosts (id, name, bmc_address, username, secret, verify_tls, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (host.id, name, bmc_address, username, secret, int(verify_tls), host.created_at.isoformat()),
            )
        return host

    def get_host(self, host_id: str) -> Host | None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
        return _row_to_host(row) if row else None

    def find_host_by_address(self, bmc_address: str) -> Host | None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM hosts WHERE bmc_address = ?", (bmc_address,)).fetchone()
        return _row_to_host(row) if row else None

    def get_host_secret(self, host_id: str) -> bytes | None:
        with self._tx() as cur:
            row = cur.execute("SELECT secret FROM hosts WHERE id = ?", (host_id,)).fetchone()
        return bytes(row["secret"]) if row else None

    def list_hosts(self) -> list[Host]:
        with self._tx() as cur:
            rows = cur.execute("SELECT * FROM hosts ORDER BY created_at").fetchall()
        return [_row_to_host(r) for r in rows]

    def update_host_identity(self, host_id: str, *, vendor: str, model: str) -> None:
        with self._tx() as cur:
            cur.execute("UPDATE hosts SET vendor = ?, model = ? WHERE id = ?", (vendor, model, host_id))

    def delete_host(self, host_id: str) -> bool:
        with self._tx() as cur:
            cur.execute("DELETE FROM results WHERE host_id = ?", (host_id,))
            cur.execute("DELETE FROM os_access WHERE host_id = ?", (host_id,))
            cur.execute("DELETE FROM host_values WHERE host_id = ?", (host_id,))
            cur.execute("DELETE FROM pins WHERE host_id = ?", (host_id,))
            cur.execute("DELETE FROM jobs WHERE host_id = ?", (host_id,))
            deleted = cur.execute("DELETE FROM hosts WHERE id = ?", (host_id,)).rowcount
        return deleted > 0

    # ── OS access ──────────────────────────────────────────────────────
    def set_os_access(self, host_id: str, access: OsAccess, secret: bytes) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO os_access (host_id, address, username, secret, verify_tls)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(host_id) DO UPDATE SET address = excluded.address,"
                " username = excluded.username, secret = excluded.secret, verify_tls = excluded.verify_tls",
                (host_id, access.address, access.username, secret, int(access.verify_tls)),
            )

    def get_os_access(self, host_id: str) -> tuple[OsAccess, bytes] | None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM os_access WHERE host_id = ?", (host_id,)).fetchone()
        if not row:
            return None
        access = OsAccess(
            address=row["address"], username=row["username"], verify_tls=bool(row["verify_tls"])
        )
        return access, bytes(row["secret"])

    # ── config sets ──────────────────────────────────────────────────────
    def add_config_set(
        self, *, name: str, os_family: str, settings: dict[str, Any], secrets: bytes | None, source: str
    ) -> ConfigSet:
        now = utcnow()
        cs = ConfigSet(
            id=new_id(),
            name=name,
            os_family=os_family,
            settings=settings,
            has_root_password=secrets is not None,
            source=source,
            created_at=now,
            updated_at=now,
        )
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO config_sets"
                " (id, name, os_family, settings, secrets, source, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cs.id,
                    name,
                    os_family,
                    json.dumps(settings),
                    secrets,
                    source,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return cs

    def update_config_set(
        self, set_id: str, *, name: str, settings: dict[str, Any], secrets: bytes | None, keep_secrets: bool
    ) -> None:
        with self._tx() as cur:
            if keep_secrets:
                cur.execute(
                    "UPDATE config_sets SET name = ?, settings = ?, updated_at = ? WHERE id = ?",
                    (name, json.dumps(settings), utcnow().isoformat(), set_id),
                )
            else:
                cur.execute(
                    "UPDATE config_sets SET name = ?, settings = ?, secrets = ?, updated_at = ? WHERE id = ?",
                    (name, json.dumps(settings), secrets, utcnow().isoformat(), set_id),
                )

    def get_config_set(self, set_id: str) -> tuple[ConfigSet, bytes | None] | None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM config_sets WHERE id = ?", (set_id,)).fetchone()
        return (_row_to_config_set(row), row["secrets"]) if row else None

    def find_config_set_by_name(self, name: str) -> ConfigSet | None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM config_sets WHERE name = ?", (name,)).fetchone()
        return _row_to_config_set(row) if row else None

    def list_config_sets(self) -> list[ConfigSet]:
        with self._tx() as cur:
            rows = cur.execute("SELECT * FROM config_sets ORDER BY name").fetchall()
        return [_row_to_config_set(r) for r in rows]

    def delete_config_set(self, set_id: str) -> bool:
        with self._tx() as cur:
            return cur.execute("DELETE FROM config_sets WHERE id = ?", (set_id,)).rowcount > 0

    def set_host_values(self, host_id: str, os_family: str, data: dict[str, Any]) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO host_values (host_id, os_family, data, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(host_id, os_family)"
                " DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (host_id, os_family, json.dumps(data), utcnow().isoformat()),
            )

    def get_host_values(self, host_id: str, os_family: str) -> dict[str, Any] | None:
        with self._tx() as cur:
            row = cur.execute(
                "SELECT data FROM host_values WHERE host_id = ? AND os_family = ?", (host_id, os_family)
            ).fetchone()
        if not row:
            return None
        data: dict[str, Any] = json.loads(row["data"])
        return data

    # ── certificate pins ────────────────────────────────────────────────
    def set_pin(self, host_id: str, role: str, address: str, pem: str) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO pins (host_id, role, address, pem, pinned_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(host_id, role) DO UPDATE SET address = excluded.address, pem = excluded.pem,"
                " pinned_at = excluded.pinned_at",
                (host_id, role, address, pem, utcnow().isoformat()),
            )

    def get_pin(self, host_id: str, role: str) -> tuple[str, str, datetime] | None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM pins WHERE host_id = ? AND role = ?", (host_id, role)).fetchone()
        return (row["address"], row["pem"], datetime.fromisoformat(row["pinned_at"])) if row else None

    def list_pins(self, host_id: str) -> list[tuple[str, str, str, datetime]]:
        with self._tx() as cur:
            rows = cur.execute("SELECT * FROM pins WHERE host_id = ? ORDER BY role", (host_id,)).fetchall()
        return [(r["role"], r["address"], r["pem"], datetime.fromisoformat(r["pinned_at"])) for r in rows]

    # ── jobs ─────────────────────────────────────────────────────────────
    def create_job(self, *, kind: JobKind, host_id: str, params: dict[str, Any]) -> Job:
        job = Job(
            id=new_id(),
            kind=kind,
            host_id=host_id,
            status=JobStatus.QUEUED,
            params=params,
            created_at=utcnow(),
        )
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO jobs (id, kind, host_id, status, params, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    kind.value,
                    host_id,
                    job.status.value,
                    json.dumps(params),
                    job.created_at.isoformat(),
                ),
            )
        return job

    def save_job(self, job: Job) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE jobs SET status = ?, progress = ?, message = ?, result = ?, error = ?,"
                " started_at = ?, finished_at = ? WHERE id = ?",
                (
                    job.status.value,
                    job.progress,
                    job.message,
                    json.dumps(job.result) if job.result is not None else None,
                    job.error.model_dump_json() if job.error else None,
                    job.started_at.isoformat() if job.started_at else None,
                    job.finished_at.isoformat() if job.finished_at else None,
                    job.id,
                ),
            )

    def get_job(self, job_id: str) -> Job | None:
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self, *, host_id: str | None = None, limit: int = 50) -> list[Job]:
        sql = "SELECT * FROM jobs"
        args: tuple[Any, ...] = ()
        if host_id:
            sql += " WHERE host_id = ?"
            args = (host_id,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        with self._tx() as cur:
            rows = cur.execute(sql, (*args, limit)).fetchall()
        return [_row_to_job(r) for r in rows]

    def mark_interrupted(self) -> int:
        """Fail jobs left queued/running by a previous process."""
        err = JobError(
            type="interrupted", message="Server stopped while the job was in progress"
        ).model_dump_json()
        with self._tx() as cur:
            return cur.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE status IN (?, ?)",
                (
                    JobStatus.FAILED.value,
                    err,
                    utcnow().isoformat(),
                    JobStatus.QUEUED.value,
                    JobStatus.RUNNING.value,
                ),
            ).rowcount

    # ── results ──────────────────────────────────────────────────────────
    def save_result(self, *, host_id: str, kind: str, job_id: str, data: dict[str, Any]) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO results (host_id, kind, job_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (host_id, kind, job_id, json.dumps(data), utcnow().isoformat()),
            )

    def latest_result(self, *, host_id: str, kind: str) -> dict[str, Any] | None:
        with self._tx() as cur:
            row = cur.execute(
                "SELECT data FROM results WHERE host_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1",
                (host_id, kind),
            ).fetchone()
        if not row:
            return None
        data: dict[str, Any] = json.loads(row["data"])
        return data


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_host(row: sqlite3.Row) -> Host:
    return Host(
        id=row["id"],
        name=row["name"],
        bmc_address=row["bmc_address"],
        username=row["username"],
        verify_tls=bool(row["verify_tls"]),
        vendor=row["vendor"],
        model=row["model"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        kind=JobKind(row["kind"]),
        host_id=row["host_id"],
        status=JobStatus(row["status"]),
        progress=row["progress"],
        message=row["message"],
        params=json.loads(row["params"]),
        result=json.loads(row["result"]) if row["result"] else None,
        error=JobError.model_validate_json(row["error"]) if row["error"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        started_at=_dt(row["started_at"]),
        finished_at=_dt(row["finished_at"]),
    )


def _row_to_config_set(row: sqlite3.Row) -> ConfigSet:
    return ConfigSet(
        id=row["id"],
        name=row["name"],
        os_family=row["os_family"],
        settings=json.loads(row["settings"]),
        has_root_password=row["secrets"] is not None,
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
