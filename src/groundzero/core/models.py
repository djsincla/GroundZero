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
    INSTALL = "install"
    OS_CAPTURE = "os_capture"


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


class ConfigSetWrite(BaseModel):
    """Create or replace a config set. ``settings`` is validated against the OS family's schema."""

    name: str = Field(min_length=1, max_length=80)
    os_family: str = Field(description="OS family, see GET /os-families")
    settings: dict[str, Any]
    root_password: SecretStr | None = Field(
        default=None,
        description="Root/admin password set by the install. On update, omit to keep the stored one.",
    )


class ConfigSet(BaseModel):
    id: str
    name: str
    os_family: str
    settings: dict[str, Any]
    has_root_password: bool
    source: str = Field(description='"manual" or "captured from <host> (<address>)"')
    created_at: datetime
    updated_at: datetime


class OsCaptureRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="Name for the new config set")
