"""Typed view of an ESXi host's network configuration (what a reinstall must preserve)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VmkInterface(BaseModel):
    device: str  # vmk0
    portgroup: str | None = None
    ip: str | None = None
    netmask: str | None = None
    dhcp: bool = False
    mac: str | None = None
    mtu: int | None = None
    services: list[str] = Field(default_factory=list, description="management, vmotion, vsan, ...")


class SecurityPolicy(BaseModel):
    """Effective L2 security policy. Holodeck trunks need all three set to Accept (True)."""

    allow_promiscuous: bool | None = None
    mac_changes: bool | None = None
    forged_transmits: bool | None = None

    @property
    def accepts_all(self) -> bool:
        return bool(self.allow_promiscuous and self.mac_changes and self.forged_transmits)


class PortGroup(BaseModel):
    name: str
    vlan_id: int = 0
    vswitch: str
    active_uplinks: list[str] = Field(default_factory=list, description="Effective (computed) teaming order")
    standby_uplinks: list[str] = Field(default_factory=list)
    security: SecurityPolicy = Field(
        default_factory=SecurityPolicy, description="Effective (computed) policy"
    )

    @property
    def is_trunk(self) -> bool:
        return self.vlan_id == 4095


class VSwitch(BaseModel):
    name: str
    mtu: int | None = None
    uplinks: list[str] = Field(default_factory=list)  # vmnic0, vmnic1
    active_uplinks: list[str] = Field(default_factory=list)
    standby_uplinks: list[str] = Field(default_factory=list)
    security: SecurityPolicy = Field(default_factory=SecurityPolicy)
    portgroups: list[str] = Field(default_factory=list)


class PhysicalNic(BaseModel):
    device: str  # vmnic0
    mac: str | None = None
    speed_mbps: int | None = None  # None = link down
    driver: str | None = None
    pci: str | None = None
    switch: str | None = Field(default=None, description="Neighbour switch from CDP/LLDP")
    switch_port: str | None = None


class EsxiNetworkConfig(BaseModel):
    address: str = Field(description="Address GroundZero used to reach the host")
    product: str
    version: str
    build: str
    hostname: str | None = None
    domain: str | None = None
    default_gateway: str | None = None
    dns_servers: list[str] = Field(default_factory=list)
    search_domains: list[str] = Field(default_factory=list)
    dns_from_dhcp: bool = False
    ntp_servers: list[str] = Field(default_factory=list)
    ntp_running: bool | None = Field(default=None, description="ntpd service running (None: not read)")
    ntp_policy: str | None = Field(default=None, description='ntpd startup policy: "on", "off", "automatic"')
    vmkernel: list[VmkInterface] = Field(default_factory=list)
    vswitches: list[VSwitch] = Field(default_factory=list)
    portgroups: list[PortGroup] = Field(default_factory=list)
    physical_nics: list[PhysicalNic] = Field(default_factory=list)

    @property
    def management(self) -> VmkInterface | None:
        for vmk in self.vmkernel:
            if "management" in vmk.services:
                return vmk
        return self.vmkernel[0] if self.vmkernel else None

    def management_portgroup(self) -> PortGroup | None:
        mgmt = self.management
        return next((p for p in self.portgroups if mgmt and p.name == mgmt.portgroup), None)

    def management_uplinks(self) -> list[str]:
        """Active physical NICs carrying the management vmkernel (effective teaming)."""
        pg = self.management_portgroup()
        return pg.active_uplinks if pg else []

    def management_vlan(self) -> int:
        pg = self.management_portgroup()
        return pg.vlan_id if pg else 0

    def install_nic(self) -> str | None:
        """The vmnic whose MAC the management vmk inherited at install time (ESXi uses it for vmk0)."""
        mgmt = self.management
        if mgmt and mgmt.mac:
            match = next((n for n in self.physical_nics if n.mac and n.mac.lower() == mgmt.mac.lower()), None)
            if match:
                return match.device
        uplinks = self.management_uplinks()
        return uplinks[0] if uplinks else None


class Datastore(BaseModel):
    name: str
    type: str
    capacity_gb: float
    free_gb: float | None = None
    ssd: bool | None = Field(default=None, description="Backed by flash (SSD/NVMe)")
    local: bool | None = None
    disks: list[str] = Field(default_factory=list)


class EsxiDisk(BaseModel):
    """A local or attached disk as ESXi sees it (canonical name is what VMFS and kickstart use)."""

    name: str = Field(description="Canonical name, e.g. t10.NVMe____... or naa.5000...")
    display_name: str | None = None
    vendor: str | None = None
    model: str | None = None
    capacity_gb: float
    ssd: bool | None = None
    local: bool | None = None
    is_boot: bool = False
    datastores: list[str] = Field(default_factory=list, description="Datastores with an extent on this disk")
    partitions: int | None = Field(default=None, description="Partitions on the disk (None: not read)")

    @property
    def unused(self) -> bool:
        """No datastore, not the boot disk, and no partitions of any kind: safe to propose formatting."""
        return not self.is_boot and not self.datastores and self.partitions == 0


class EsxiStorage(BaseModel):
    boot_disk: str | None = Field(
        default=None, description="Disk holding OSDATA/bootbanks (the install disk)"
    )
    datastores: list[Datastore] = Field(default_factory=list)
    disks: list[EsxiDisk] = Field(default_factory=list)

    @property
    def vmfs_names(self) -> list[str]:
        return sorted(d.name for d in self.datastores if d.type == "VMFS")


class EsxiAbout(BaseModel):
    product: str
    version: str
    build: str
