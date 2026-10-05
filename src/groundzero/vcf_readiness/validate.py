# SPDX-License-Identifier: LicenseRef-CA-Inc
# Copyright (c) CA, Inc. All rights reserved. See LICENSE.md in this directory.
"""VCF 9 readiness validation (task ``vcf.readiness``): the VCF Readiness rules applied to a host.

Input is the hardware inventory GroundZero read over Redfish (that reading is GroundZero's own
Apache-licensed code); the judgement of whether the hardware is ready for VCF 9 lives here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from groundzero.core.store import utcnow
from groundzero.inventory.models import HostInventory
from groundzero.preflight.evaluate import Category, Check, CheckStatus, PreflightSummary
from groundzero.vcf_readiness.cpu import CpuSupport, classify_cpu

RULES_SOURCE = "VCF Readiness Assessment Tool v9.7.3 rules (CA, Inc.)"


class VcfReadinessReport(BaseModel):
    generated_at: datetime
    rules: str = RULES_SOURCE
    overall: CheckStatus
    summary: PreflightSummary
    cpu_override_required: bool = Field(
        description="ESXi 9 installs need the CPU support override (allowLegacyCPU) on this hardware"
    )
    checks: list[Check]


_CPU_STATUS = {
    CpuSupport.SUPPORTED: (CheckStatus.PASS, None),
    CpuSupport.OVERRIDE_REQUIRED: (
        CheckStatus.WARN,
        "Deprecated for ESXi 9 (install needs the CPU support override). Holodeck also supports an "
        "ESXi 8.0u3 host.",
    ),
    CpuSupport.UNSUPPORTED: (CheckStatus.FAIL, "CPU generation is not supported by ESXi 9."),
    CpuSupport.UNKNOWN: (CheckStatus.UNKNOWN, "Verify CPU support in the Broadcom Compatibility Guide."),
}


def cpu_check(inventory: HostInventory) -> tuple[Check, CpuSupport]:
    # Sockets are homogeneous in practice, so the first CPU represents the host.
    if not inventory.processors:
        return (
            Check(
                id="cpu.generation",
                category=Category.COMPUTE,
                title="CPU generation",
                status=CheckStatus.UNKNOWN,
                observed="no processors reported",
                required="CPU supported by ESXi 8.0u3 / 9.0",
            ),
            CpuSupport.UNKNOWN,
        )
    cpu = inventory.processors[0]
    cls = classify_cpu(cpu.model)
    status, fix = _CPU_STATUS[cls.support]
    check = Check(
        id="cpu.generation",
        category=Category.COMPUTE,
        title="CPU generation",
        status=status,
        observed=f"{cpu.model} — {cls.family}",
        required="CPU supported by ESXi 8.0u3 / 9.0",
        remediation=fix,
    )
    return check, cls.support


def validate(inventory: HostInventory) -> VcfReadinessReport:
    check, support = cpu_check(inventory)
    checks = [check]
    summary = PreflightSummary(
        passed=sum(c.status is CheckStatus.PASS for c in checks),
        warnings=sum(c.status is CheckStatus.WARN for c in checks),
        failed=sum(c.status is CheckStatus.FAIL for c in checks),
        unknown=sum(c.status is CheckStatus.UNKNOWN for c in checks),
    )
    overall = (
        CheckStatus.FAIL
        if summary.failed
        else CheckStatus.WARN
        if summary.warnings
        else CheckStatus.UNKNOWN
        if summary.unknown
        else CheckStatus.PASS
    )
    return VcfReadinessReport(
        generated_at=utcnow(),
        overall=overall,
        summary=summary,
        checks=checks,
        cpu_override_required=support is CpuSupport.OVERRIDE_REQUIRED,
    )
