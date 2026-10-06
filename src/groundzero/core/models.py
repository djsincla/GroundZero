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


class JobStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class JobStep(BaseModel):
    """One named phase of a job (e.g. "Build installer ISO"), so progress and failures are legible."""

    key: str
    title: str
    status: JobStepStatus = JobStepStatus.PENDING
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Job(BaseModel):
    id: str
    task: str = Field(description="The pipeline task this job ran (see GET /tasks)")
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
    steps: list[JobStep] = Field(default_factory=list)


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
    steps: list[JobStep] = Field(default_factory=list)


class ConfigSetWrite(BaseModel):
    """Create or replace a config set. ``settings`` is validated against the OS family's schema."""

    name: str = Field(min_length=1, max_length=80)
    os_family: str = Field(description="OS family, see GET /os-families")
    settings: dict[str, Any]
    root_password: SecretStr | None = Field(
        default=None,
        description="Root/admin password set by the install. On update, omit to keep the stored one.",
    )
    secrets: dict[str, SecretStr] | None = Field(
        default=None,
        description="Secret fields of the family (see secret_fields in GET /os-families), e.g. "
        "holorouter_password, download_token. Write-only; on update, omitted ones are kept.",
    )

    def secret_values(self) -> dict[str, str]:
        values = {k: v.get_secret_value() for k, v in (self.secrets or {}).items() if v.get_secret_value()}
        if self.root_password and self.root_password.get_secret_value():
            values["root_password"] = self.root_password.get_secret_value()
        return values


class ConfigSet(BaseModel):
    id: str
    name: str
    os_family: str
    settings: dict[str, Any]
    has_root_password: bool
    secrets_set: list[str] = Field(
        default_factory=list, description="Names of the secrets stored (never values)"
    )
    source: str = Field(description='"manual" or "captured from <host> (<address>)"')
    created_at: datetime
    updated_at: datetime


class OsCaptureRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80, description="Name for the new config set")
