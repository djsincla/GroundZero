from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage
from groundzero.install.kickstart import render_kickstart
from groundzero.osconfig import OsConfigError, plugin_for
from groundzero.osconfig.esxi import DiskRule, EsxiHostValues, EsxiPlugin, EsxiSettings

ESXI1 = Path(__file__).parent / "fixtures" / "esxi1"


@pytest.fixture
def captured() -> tuple[EsxiSettings, EsxiHostValues, EsxiStorage]:
    network = EsxiNetworkConfig.model_validate_json((ESXI1 / "network.json").read_text())
    storage = EsxiStorage.model_validate_json((ESXI1 / "storage.json").read_text())
    result = EsxiPlugin.capture(network, storage)
    return (
        EsxiSettings.model_validate(result.settings),
        EsxiHostValues.model_validate(result.host_values),
        storage,
    )


def test_capture_reproduces_the_lab_spec(captured: tuple[EsxiSettings, EsxiHostValues, EsxiStorage]) -> None:
    settings, values, _ = captured
    assert (settings.vlan_id, settings.install_nic, settings.extra_uplinks) == (100, "vmnic0", ["vmnic1"])
    assert settings.netmask == "255.255.255.0" and settings.install_disk.mode == "current-boot-disk"
    assert settings.ntp_servers == ["pool.ntp.org"]  # the fixture has no NTP; the lab default applies
    assert values.hostname == "esxi1"


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (
            DiskRule(mode="current-boot-disk"),
            "--disk=t10.ATA_____DELLBOSS_VD_____________________________SN01",
        ),
        (DiskRule(mode="first-match", value="DELLBOSS,local"), "--firstdisk=DELLBOSS,local"),
        (DiskRule(mode="exact", value="naa.600508b1001c"), "--disk=naa.600508b1001c"),
    ],
)
def test_disk_rules_render_into_the_kickstart(
    captured: tuple[EsxiSettings, EsxiHostValues, EsxiStorage], rule: DiskRule, expected: str
) -> None:
    settings, values, storage = captured
    spec = EsxiPlugin.build_spec(
        settings.model_copy(update={"install_disk": rule}),
        values,
        root_password="pw",
        legacy_cpu_detected=False,
        current_boot_disk=storage.boot_disk,
    )
    assert f"install {expected} --preservevmfs" in render_kickstart(spec)


def test_current_boot_disk_needs_the_running_os(
    captured: tuple[EsxiSettings, EsxiHostValues, EsxiStorage],
) -> None:
    settings, values, _ = captured
    with pytest.raises(OsConfigError, match="first-match or exact"):
        EsxiPlugin.build_spec(
            settings, values, root_password="pw", legacy_cpu_detected=False, current_boot_disk=None
        )


@pytest.mark.parametrize(
    ("mode", "detected", "expected"),
    [("auto", True, True), ("auto", False, False), ("on", False, True), ("off", True, False)],
)
def test_cpu_override_modes(
    captured: tuple[EsxiSettings, EsxiHostValues, EsxiStorage], mode: str, detected: bool, expected: bool
) -> None:
    settings, values, storage = captured
    spec = EsxiPlugin.build_spec(
        settings.model_copy(update={"cpu_override": mode}),
        values,
        root_password="pw",
        legacy_cpu_detected=detected,
        current_boot_disk=storage.boot_disk,
    )
    assert spec.allow_legacy_cpu is expected


def test_per_server_nic_overrides_win(captured: tuple[EsxiSettings, EsxiHostValues, EsxiStorage]) -> None:
    settings, values, storage = captured
    spec = EsxiPlugin.build_spec(
        settings,
        values.model_copy(update={"install_nic": "vmnic2", "extra_uplinks": []}),
        root_password="pw",
        legacy_cpu_detected=False,
        current_boot_disk=storage.boot_disk,
    )
    assert (spec.network.install_nic, spec.network.extra_uplinks) == ("vmnic2", [])


def test_settings_validation() -> None:
    with pytest.raises(ValidationError):
        DiskRule(mode="first-match")  # needs a value
    with pytest.raises(ValidationError):
        EsxiSettings(netmask="255.255.255.0", gateway="not-an-ip", nameservers=["8.8.8.8"])
    with pytest.raises(OsConfigError, match="Unknown OS family"):
        plugin_for("windows")


def test_detect_iso(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from isofactory import make_stock_iso

    esxi = make_stock_iso(tmp_path / "esxi.iso")
    meta = EsxiPlugin.detect_iso(esxi)
    assert meta is not None and (meta.version, meta.build) == ("9.1.1", "25714478")
    junk = tmp_path / "junk.iso"
    junk.write_bytes(b"not an iso")
    assert EsxiPlugin.detect_iso(junk) is None
