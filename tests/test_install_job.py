from __future__ import annotations

from pathlib import Path

import pytest

from groundzero.esxi.models import EsxiAbout, EsxiNetworkConfig, EsxiStorage
from groundzero.install.job import (
    InstallError,
    InstallRequest,
    derive_spec,
    installer_boot_threshold,
    validate_install,
)

ESXI1 = Path(__file__).parent / "fixtures" / "esxi1"


@pytest.fixture
def network() -> EsxiNetworkConfig:
    return EsxiNetworkConfig.model_validate_json((ESXI1 / "network.json").read_text())


@pytest.fixture
def storage() -> EsxiStorage:
    return EsxiStorage.model_validate_json((ESXI1 / "storage.json").read_text())


def _req(**kw: object) -> InstallRequest:
    return InstallRequest.model_validate({"iso_path": "/x.iso", "confirm": "install esxi1", **kw})


def test_spec_derived_from_running_host(network: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    spec = derive_spec(network, storage, _req(), legacy_cpu=True, password="pw")
    assert spec.install_disk == storage.boot_disk and spec.preserve_vmfs
    assert spec.network.hostname == "esxi1" and spec.network.vlan_id == 100
    assert (spec.network.install_nic, spec.network.extra_uplinks) == ("vmnic0", ["vmnic1"])
    assert spec.ntp_servers == ["pool.ntp.org"] and spec.root_password_hash.startswith("$6$")


def test_dhcp_or_unknown_boot_disk_is_refused(network: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    dhcp = network.model_copy(deep=True)
    dhcp.vmkernel[0].dhcp = True
    with pytest.raises(InstallError, match="static IPv4"):
        derive_spec(dhcp, storage, _req(), legacy_cpu=False, password="pw")
    with pytest.raises(InstallError, match="boot disk"):
        derive_spec(
            network, storage.model_copy(update={"boot_disk": None}), _req(), legacy_cpu=False, password="pw"
        )


def test_validation_catches_lost_datastore_and_wrong_build(
    network: EsxiNetworkConfig, storage: EsxiStorage
) -> None:
    spec = derive_spec(network, storage, _req(), legacy_cpu=True, password="pw")
    after = network.model_copy(update={"ntp_servers": ["pool.ntp.org"]})
    lost = storage.model_copy(
        update={"datastores": [d for d in storage.datastores if d.name != "localHolodeck"]}
    )
    about = EsxiAbout(product="ESXi", version="9.1.1", build="25714478")
    checks = {c.name: c for c in validate_install(spec, "25714478", about, after, lost, storage)}
    assert not checks["datastores"].ok and "localHolodeck" in checks["datastores"].observed
    assert checks["esxi.build"].ok and checks["mgmt.vlan"].ok
    wrong = {c.name: c for c in validate_install(spec, "99999999", about, after, storage, storage)}
    assert not wrong["esxi.build"].ok and wrong["datastores"].ok


def test_wipe_expects_only_install_disk_vmfs_gone(network: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    spec = derive_spec(network, storage, _req(wipe_install_disk_vmfs=True), legacy_cpu=True, password="pw")
    without_boss = storage.model_copy(
        update={"datastores": [d for d in storage.datastores if d.name != "boss"]}
    )
    about = EsxiAbout(product="ESXi", version="9.1.1", build="1")
    after = network.model_copy(update={"ntp_servers": ["pool.ntp.org"]})
    checks = {c.name: c for c in validate_install(spec, "1", about, after, without_boss, storage)}
    assert checks["datastores"].ok


def test_installer_boot_threshold() -> None:
    assert installer_boot_threshold(733 * 2**20) == 32 * 2**20  # real ISO: 32 MiB proves the installer runs
    assert installer_boot_threshold(1000) == 500
