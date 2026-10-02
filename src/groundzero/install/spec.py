"""What to install, as data. The kickstart and ISO are rendered from this; nothing is hand-edited."""

from __future__ import annotations

import ipaddress
import re

from pydantic import BaseModel, Field, field_validator, model_validator

_HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_VMNIC = re.compile(r"^vmnic\d+$")
_DISK = re.compile(r"^[A-Za-z0-9._:-]+$")  # canonical device names (t10..., naa..., mpx...)
_FIRSTDISK = re.compile(r"^[A-Za-z0-9._-]+(,[A-Za-z0-9._-]+)*$")  # e.g. DELLBOSS,local


class ManagementNetwork(BaseModel):
    hostname: str
    ip: str
    netmask: str
    gateway: str
    nameservers: list[str] = Field(min_length=1)
    vlan_id: int = Field(default=0, ge=0, le=4094)
    install_nic: str = Field(description="vmnic the installer configures the management network on")
    extra_uplinks: list[str] = Field(
        default_factory=list, description="Added as active uplinks on first boot"
    )

    @field_validator("hostname")
    @classmethod
    def _hostname(cls, v: str) -> str:
        if not _HOSTNAME.match(v):
            raise ValueError(f"invalid short hostname: {v!r}")
        return v

    @field_validator("ip", "netmask", "gateway")
    @classmethod
    def _ipv4(cls, v: str) -> str:
        ipaddress.IPv4Address(v)
        return v

    @field_validator("nameservers")
    @classmethod
    def _nameservers(cls, v: list[str]) -> list[str]:
        for ns in v:
            ipaddress.IPv4Address(ns)
        return v

    @field_validator("install_nic")
    @classmethod
    def _nic(cls, v: str) -> str:
        if not _VMNIC.match(v):
            raise ValueError(f"invalid vmnic: {v!r}")
        return v

    @field_validator("extra_uplinks")
    @classmethod
    def _uplinks(cls, v: list[str]) -> list[str]:
        for nic in v:
            cls._nic(nic)
        return v


class InstallSpec(BaseModel):
    install_disk: str | None = Field(
        default=None, description="Canonical device name of the target disk (kickstart --disk)"
    )
    install_firstdisk: str | None = Field(
        default=None,
        description="Comma-separated vendor/model/driver matches, first hit wins (kickstart --firstdisk), "
        "e.g. 'DELLBOSS' or 'DELLBOSS,local'",
    )
    preserve_vmfs: bool = Field(
        default=True, description="Keep an existing VMFS datastore on the install disk"
    )
    allow_legacy_cpu: bool = Field(default=False, description="Add allowLegacyCPU=true (deprecated CPUs)")
    root_password_hash: str = Field(description="SHA-512 crypt hash ($6$...)")
    network: ManagementNetwork
    ntp_servers: list[str] = Field(default_factory=list)

    @field_validator("install_disk")
    @classmethod
    def _disk(cls, v: str | None) -> str | None:
        if v is not None and not _DISK.match(v):
            raise ValueError(f"invalid disk name: {v!r}")
        return v

    @field_validator("install_firstdisk")
    @classmethod
    def _firstdisk(cls, v: str | None) -> str | None:
        if v is not None and not _FIRSTDISK.match(v):
            raise ValueError(f"invalid --firstdisk match list: {v!r}")
        return v

    @model_validator(mode="after")
    def _one_disk_target(self) -> InstallSpec:
        if (self.install_disk is None) == (self.install_firstdisk is None):
            raise ValueError("set exactly one of install_disk or install_firstdisk")
        return self

    @field_validator("root_password_hash")
    @classmethod
    def _hash(cls, v: str) -> str:
        if not v.startswith("$6$"):
            raise ValueError("root password must be a SHA-512 crypt hash")
        return v

    @field_validator("ntp_servers")
    @classmethod
    def _ntp(cls, v: list[str]) -> list[str]:
        for server in v:
            if not re.match(r"^[A-Za-z0-9.-]+$", server):
                raise ValueError(f"invalid NTP server: {server!r}")
        return v

    @property
    def kernel_options(self) -> list[str]:
        opts = ["ks=cdrom:/KS.CFG"]
        if self.allow_legacy_cpu:
            opts.append("allowLegacyCPU=true")
        return opts
