"""ESXi plugin: config-set settings, per-server values, capture from a running host, install spec."""

from __future__ import annotations

import contextlib
import ipaddress
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage
from groundzero.install.crypt import sha512_crypt
from groundzero.install.iso import inspect_iso
from groundzero.install.spec import InstallSpec, ManagementNetwork
from groundzero.osconfig.base import CaptureResult, IsoMeta


class OsConfigError(ValueError):
    error_type = "os_config_invalid"


class DiskRule(BaseModel):
    """Which disk ESXi is installed on; rules keep a config set reusable across servers."""

    mode: Literal["current-boot-disk", "first-match", "exact"] = Field(
        default="current-boot-disk",
        description="current-boot-disk: the disk the running OS boots from (needs the OS reachable); "
        "first-match: first disk whose vendor/model/driver matches (kickstart --firstdisk, e.g. DELLBOSS); "
        "exact: a canonical device name",
    )
    value: str | None = Field(default=None, description="Match list for first-match, device name for exact")

    @model_validator(mode="after")
    def _value_required(self) -> DiskRule:
        if self.mode != "current-boot-disk" and not self.value:
            raise ValueError(f"disk rule '{self.mode}' needs a value")
        return self


class EsxiSettings(BaseModel):
    """Shared ESXi settings stored in a config set."""

    netmask: str = Field(description="Management network mask, e.g. 255.255.255.0")
    gateway: str = Field(description="Default gateway")
    nameservers: list[str] = Field(min_length=1, description="DNS servers")
    vlan_id: int = Field(default=0, ge=0, le=4094, description="Management VLAN (0 = untagged)")
    install_nic: str = Field(default="vmnic0", description="vmnic the installer configures for management")
    extra_uplinks: list[str] = Field(
        default_factory=list, description="Added as active uplinks on first boot"
    )
    ntp_servers: list[str] = Field(default_factory=lambda: ["pool.ntp.org"], description="NTP servers")
    install_disk: DiskRule = Field(default_factory=DiskRule, description="Install target")
    preserve_vmfs: bool = Field(
        default=True, description="Keep an existing VMFS datastore on the install disk"
    )
    cpu_override: Literal["auto", "on", "off"] = Field(
        default="auto", description="allowLegacyCPU for deprecated CPUs (auto: from preflight)"
    )

    @field_validator("netmask", "gateway")
    @classmethod
    def _ipv4(cls, v: str) -> str:
        ipaddress.IPv4Address(v)
        return v


class EsxiHostValues(BaseModel):
    """Per-server values (prefilled from capture or the last install; editable at install time)."""

    hostname: str = Field(description="Short hostname")
    ip: str = Field(description="Management IPv4 address")
    install_nic: str | None = Field(default=None, description="Override the config set's install NIC")
    extra_uplinks: list[str] | None = Field(
        default=None, description="Override the config set's extra uplinks"
    )

    @field_validator("ip")
    @classmethod
    def _ipv4(cls, v: str) -> str:
        ipaddress.IPv4Address(v)
        return v


class EsxiPlugin:
    family: ClassVar[str] = "esxi"
    title: ClassVar[str] = "VMware ESXi"
    install_supported: ClassVar[bool] = True
    settings_model: ClassVar[type[BaseModel]] = EsxiSettings
    host_values_model: ClassVar[type[BaseModel]] = EsxiHostValues
    secret_fields: ClassVar[tuple[str, ...]] = ("root_password",)

    @staticmethod
    def detect_iso(path: Path) -> IsoMeta | None:
        """An ESXi installer has a UEFI BOOT.CFG loading b.b00 plus .DISCINFO naming ESXi."""
        import io

        import pycdlib

        iso = pycdlib.PyCdlib()
        try:
            iso.open(str(path))
            buf = io.BytesIO()
            iso.get_file_from_iso_fp(buf, iso_path="/EFI/BOOT/BOOT.CFG;1")
            if "kernel=/b.b00" not in buf.getvalue().decode(errors="replace"):
                return None
        except Exception:  # noqa: BLE001 - "not an ESXi ISO" for any read/parse failure
            return None
        finally:
            with contextlib.suppress(Exception):
                iso.close()
        info = inspect_iso(path)
        return IsoMeta(version=info.version, build=info.build)

    @staticmethod
    def capture(network: EsxiNetworkConfig, storage: EsxiStorage) -> CaptureResult:
        """Running ESXi → shared settings + this server's values (what a reinstall must keep)."""
        mgmt = network.management
        if mgmt is None or not mgmt.ip or not mgmt.netmask or mgmt.dhcp:
            raise OsConfigError("The management vmk has no static IPv4 configuration to capture")
        if not network.hostname or not network.default_gateway or not network.dns_servers:
            raise OsConfigError("The host is missing a hostname, gateway or DNS servers")
        install_nic = network.install_nic() or "vmnic0"
        settings = EsxiSettings(
            netmask=mgmt.netmask,
            gateway=network.default_gateway,
            nameservers=network.dns_servers,
            vlan_id=network.management_vlan(),
            install_nic=install_nic,
            extra_uplinks=[n for n in network.management_uplinks() if n != install_nic],
            ntp_servers=network.ntp_servers or ["pool.ntp.org"],
            install_disk=DiskRule(mode="current-boot-disk"),
        )
        values = EsxiHostValues(hostname=network.hostname, ip=mgmt.ip)
        return CaptureResult(
            settings=settings.model_dump(mode="json"), host_values=values.model_dump(mode="json")
        )

    @staticmethod
    def build_spec(
        settings: EsxiSettings,
        values: EsxiHostValues,
        *,
        root_password: str,
        legacy_cpu_detected: bool,
        current_boot_disk: str | None,
    ) -> InstallSpec:
        rule = settings.install_disk
        disk = firstdisk = None
        if rule.mode == "current-boot-disk":
            if not current_boot_disk:
                raise OsConfigError(
                    "The config set installs to the current boot disk, but the running OS could not be read. "
                    "Use a first-match or exact disk rule to install without a running OS."
                )
            disk = current_boot_disk
        elif rule.mode == "exact":
            disk = rule.value
        else:
            firstdisk = rule.value
        legacy = {"on": True, "off": False, "auto": legacy_cpu_detected}[settings.cpu_override]
        return InstallSpec(
            install_disk=disk,
            install_firstdisk=firstdisk,
            preserve_vmfs=settings.preserve_vmfs,
            allow_legacy_cpu=legacy,
            root_password_hash=sha512_crypt(root_password),
            network=ManagementNetwork(
                hostname=values.hostname,
                ip=values.ip,
                netmask=settings.netmask,
                gateway=settings.gateway,
                nameservers=settings.nameservers,
                vlan_id=settings.vlan_id,
                install_nic=values.install_nic or settings.install_nic,
                extra_uplinks=values.extra_uplinks
                if values.extra_uplinks is not None
                else settings.extra_uplinks,
            ),
            ntp_servers=settings.ntp_servers,
        )
