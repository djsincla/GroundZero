"""Pipeline modules: one class per task, registered here in pipeline order."""

from __future__ import annotations

from groundzero.modules.appliances import ApplianceAdopt, ApplianceCapture, ApplianceDeploy
from groundzero.modules.base import Module
from groundzero.modules.bios import ConfigureBios
from groundzero.modules.hardware import Discover, Preflight, VcfReadiness
from groundzero.modules.holodeck import DeployHolodeck, Holorouter, StageBinaries
from groundzero.modules.os import OsCapture, OsCustom, OsRead, OsReimage
from groundzero.modules.prep import Assess, Prep, VerifyJumbo

MODULES: tuple[Module, ...] = (
    Discover(),
    Preflight(),
    VcfReadiness(),
    ConfigureBios(),
    OsReimage(),
    OsCustom(),
    OsRead(),
    OsCapture(),
    Assess(),
    Prep(),
    VerifyJumbo(),
    ApplianceDeploy(),
    ApplianceCapture(),
    ApplianceAdopt(),
    Holorouter(),
    StageBinaries(),
    DeployHolodeck(),
)
REGISTRY: dict[str, Module] = {m.id: m for m in MODULES}
