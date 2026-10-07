"""Pipeline modules: one class per task, registered here in pipeline order."""

from __future__ import annotations

from groundzero.modules.appliances import ApplianceAdopt, ApplianceCapture, ApplianceDeploy
from groundzero.modules.base import Module
from groundzero.modules.bios import ConfigureBios
from groundzero.modules.dns import VerifyDns
from groundzero.modules.hardware import Discover, Preflight, VcfReadiness
from groundzero.modules.holodeck import DeployHolodeck, Holorouter, StageBinaries
from groundzero.modules.os import OsCapture, OsCustom, OsRead, OsReimage
from groundzero.modules.prep import Assess, Prep, VerifyJumbo
from groundzero.modules.storage import ReadStorage

MODULES: tuple[Module, ...] = (
    Discover(),
    ConfigureBios(),  # before preflight, so preflight passes first time
    ReadStorage(),
    Preflight(),
    VcfReadiness(),
    OsReimage(),
    VerifyDns(),
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
