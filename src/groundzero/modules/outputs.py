"""Typed outputs: what each output kind contains. A module's output is the next module's input.

Existing domain models are reused; ``HostPrep`` and ``HolorouterDeployment`` were plain dicts before.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from groundzero.esxi.models import ChangeRecord, EsxiNetworkConfig, EsxiStorage, JumboResult
from groundzero.install.job import InstallReport
from groundzero.inventory.models import HostInventory
from groundzero.preflight.evaluate import PreflightReport
from groundzero.readiness import ReadinessReport
from groundzero.vcf_readiness.validate import VcfReadinessReport


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

    vm_name: str
    ip: str
    hostname: str
    version: str | None = None
    image: str
    profile_id: str | None = None
    config_set_id: str | None = None  # deployments before appliance profiles
    datastore: str | None = None
    networks: dict[str, str] = {}
    created: bool = True
    webtop_url: str | None = None


class ApplianceDeployment(BaseModel):
    """A deployed appliance (any OVA). Saved as "appliance" (the latest) and "appliance:<vm name>"."""

    model_config = ConfigDict(extra="allow")

    vm_name: str
    product: str | None = None
    version: str | None = None
    image: str
    profile_id: str | None = None
    ip: str | None = None
    datastore: str | None = None
    networks: dict[str, str] = {}
    created: bool = True
    replaced: bool = False
    powered_on: bool = True


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
}
