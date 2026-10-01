"""API-facing domain models for hosts and jobs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, SecretStr


class HostCreate(BaseModel):
    bmc_address: str = Field(description="BMC IP address or hostname, optionally with :port")
    username: str
    password: SecretStr
    name: str | None = Field(default=None, description="Friendly name; defaults to the BMC address")
    verify_tls: bool = Field(default=False, description="Verify the BMC TLS certificate")


class Host(BaseModel):
    id: str
    name: str
    bmc_address: str
    username: str
    verify_tls: bool
    vendor: str | None = None
    model: str | None = None
    created_at: datetime


class JobKind(StrEnum):
    INVENTORY = "inventory"
    PREFLIGHT = "preflight"
    OS_NETWORK = "os_network"


class OsAccessSet(BaseModel):
    """How to reach the operating system (hypervisor) currently installed on a host."""

    address: str = Field(description="OS management IP or hostname, e.g. the ESXi vmk0 address")
    username: str = "root"
    password: SecretStr
    verify_tls: bool = False


class OsAccess(BaseModel):
    address: str
    username: str
    verify_tls: bool


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class JobError(BaseModel):
    type: str
    message: str


class Job(BaseModel):
    id: str
    kind: JobKind
    host_id: str
    status: JobStatus
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: JobError | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class BmcAudit(BaseModel):
    """Every request a job sent to the BMC, so callers can verify what was (not) changed."""

    requests: int
    non_get: list[str] = Field(default_factory=list, description='e.g. "POST /redfish/v1/..."')


class JobEvent(BaseModel):
    job_id: str
    status: JobStatus
    progress: float
    message: str
    at: datetime
