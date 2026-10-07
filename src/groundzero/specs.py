"""Specs: the jobs you pick for a server or a cluster, each with its saved parameters, run as one.

A spec is a named list of pipeline tasks. It is assigned to a cluster (every member uses it) or to a single
server (which overrides its cluster's). A run works through the spec in pipeline order on one server: steps
already done, or not needed, are skipped; the rest start one after another and the run stops at the first
failure. A cluster run starts one such run per member, all at once.

Parameters are stored as you'd send them to POST /hosts/{id}/tasks/{task}. Strings may contain {host} (the
server's name in GroundZero) or {hostname} (its OS hostname), filled in per server when the run starts.
Secrets never go in a spec: they come from appliance profiles and config sets, which keep them sealed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PLACEHOLDERS = ("{host}", "{hostname}")
# Parameter names that would carry a secret into a spec: those belong in a profile or config set.
SECRET_PARAMS = ("secrets", "password", "token", "secret")


class SpecStep(BaseModel):
    task: str = Field(description="Task id (GET /tasks)")
    params: dict[str, Any] = Field(
        default_factory=dict, description="The task's parameters; strings may use {host} and {hostname}"
    )


class SpecWrite(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    description: str = Field(default="", max_length=500)
    steps: list[SpecStep] = Field(min_length=1, description="Kept in pipeline order, whatever order sent")


class Spec(SpecWrite):
    id: str
    created_at: datetime
    updated_at: datetime


class SpecAssignment(BaseModel):
    spec_id: str | None = Field(description="The spec for this server; null: use its cluster's, if any")


class EffectiveSpec(BaseModel):
    """The spec a server runs, and where it comes from."""

    spec: Spec
    source: Literal["host", "cluster"]
    cluster_id: str | None = None


def fill(value: Any, values: dict[str, str]) -> Any:
    """Replace {host} and {hostname} in every string of ``value`` (nothing else in braces is touched)."""
    if isinstance(value, str):
        for key, replacement in values.items():
            value = value.replace("{" + key + "}", replacement)
        return value
    if isinstance(value, list):
        return [fill(v, values) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, values) for k, v in value.items()}
    return value


def secret_params(params: dict[str, Any]) -> list[str]:
    """Parameter names that look like they carry a secret (non-empty values only)."""
    return [k for k, v in params.items() if v and any(s in k.lower() for s in SECRET_PARAMS)]


# ── runs ─────────────────────────────────────────────────────────────────
RunStatus = Literal["running", "succeeded", "failed", "cancelled"]
StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped", "cancelled"]


class RunStep(BaseModel):
    task: str
    title: str
    status: StepStatus = "pending"
    job_id: str | None = None
    reason: str | None = Field(default=None, description="Why it was skipped, or why it failed")


class Run(BaseModel):
    id: str
    host_id: str
    host_name: str
    spec_id: str
    spec_name: str
    cluster_id: str | None = Field(default=None, description="Set when started as part of a cluster run")
    status: RunStatus = "running"
    steps: list[RunStep]
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class RunStart(BaseModel):
    confirm: str = Field(description='Exactly "run <spec> on <host>" (a cluster: "run cluster <name>")')


class PreviewStep(BaseModel):
    task: str
    title: str
    action: Literal["run", "skip", "blocked"]
    reason: str | None = None
    destructive: bool = False
    params: dict[str, Any] = Field(
        default_factory=dict, description="As they'll be sent, placeholders filled"
    )


class RunPreview(BaseModel):
    host_id: str
    host_name: str
    spec_id: str
    spec_name: str
    source: Literal["host", "cluster"]
    phrase: str = Field(description="The confirmation that starts this run")
    steps: list[PreviewStep]
    destructive: list[str] = Field(
        default_factory=list, description="What may change or be lost, in words, for the confirmation dialog"
    )


class ClusterRunPreview(BaseModel):
    cluster_id: str
    cluster_name: str
    phrase: str
    hosts: list[RunPreview]
    without_spec: list[str] = Field(default_factory=list, description="Members with no spec: not run")
