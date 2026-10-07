"""Typed outputs: what each output kind contains. A module's output is the next module's input.

Existing domain models are reused; ``HostPrep`` and ``HolorouterDeployment`` were plain dicts before.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from groundzero.dnscheck import DnsCheck
from groundzero.esxi.models import ChangeRecord, EsxiNetworkConfig, EsxiStorage, JumboResult
from groundzero.install.job import InstallReport
from groundzero.inventory.models import HostInventory
from groundzero.preflight.evaluate import PreflightReport
from groundzero.readiness import ReadinessReport
from groundzero.redfish.bios import BiosChange
from groundzero.vcf_readiness.validate import VcfReadinessReport


class BiosResult(BaseModel):
    """What Configure BIOS changed (or found already right)."""

    changes: list[BiosChange] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list, description="Settings this BIOS does not expose")
    applied: dict[str, Any] = Field(default_factory=dict, description="The values read back after the reboot")


class HostPrep(BaseModel):
    """What Prepare host changed, and the port groups and datastore Holodeck will use."""

    model_config = ConfigDict(extra="allow")

    applied: list[ChangeRecord]
    vswitch: str | None = None
    trunk_portgroup: str | None = None
    external_portgroup: str | None = None
    datastore: str | None = None
    ready: bool = False


class HolorouterDeployment(BaseModel):
    """The deployed Holorouter: what later Holodeck steps connect to."""

    model_config = ConfigDict(extra="allow")

    vm_name: str = Field(title="VM name")
    ip: str = Field(title="IP address", description="Where later Holodeck steps reach it (SSH)")
    hostname: str = Field(title="Hostname")
    version: str | None = Field(default=None, title="Version")
    image: str = Field(title="OVA file")
    profile_id: str | None = Field(default=None, title="Appliance profile")
    config_set_id: str | None = Field(default=None, title="Config set")  # deployments before profiles
    datastore: str | None = Field(default=None, title="Datastore")
    networks: dict[str, str] = {}
    created: bool = Field(default=True, title="Deployed by GroundZero")
    webtop_url: str | None = Field(default=None, title="Webtop URL")


class ApplianceDeployment(BaseModel):
    """A deployed appliance (any OVA). Saved as "appliance" (the latest) and "appliance:<vm name>"."""

    model_config = ConfigDict(extra="allow")

    vm_name: str = Field(title="VM name")
    product: str | None = Field(default=None, title="Product")
    version: str | None = Field(default=None, title="Version")
    image: str = Field(title="OVA file")
    profile_id: str | None = Field(default=None, title="Appliance profile")
    ip: str | None = Field(default=None, title="IP address")
    datastore: str | None = Field(default=None, title="Datastore")
    networks: dict[str, str] = {}
    created: bool = Field(default=True, title="Deployed by GroundZero")
    replaced: bool = Field(default=False, title="Replaced an existing VM")
    powered_on: bool = Field(default=True, title="Powered on")


OUTPUTS: dict[str, type[BaseModel]] = {
    "inventory": HostInventory,
    "preflight": PreflightReport,
    "vcf_readiness": VcfReadinessReport,
    "os_network": EsxiNetworkConfig,
    "os_storage": EsxiStorage,
    "install": InstallReport,
    "readiness": ReadinessReport,
    "host_prep": HostPrep,
    "jumbo": JumboResult,
    "holorouter": HolorouterDeployment,
    "appliance": ApplianceDeployment,
    "bios": BiosResult,
    "dns": DnsCheck,
}
