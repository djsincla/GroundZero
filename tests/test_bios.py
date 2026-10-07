"""Configure BIOS: planning the attribute changes (vendor names and value styles)."""

from __future__ import annotations

from groundzero.redfish import bios
from groundzero.redfish.detect import Vendor
from groundzero.redfish.oem import profile_for

DELL = profile_for(Vendor.DELL)
GENERIC = profile_for(Vendor.GENERIC)


def test_dell_turns_on_proc_virtualization_once_for_vtx_and_vtd() -> None:
    attrs = {"ProcVirtualization": "Disabled", "BootMode": "Bios", "SriovGlobalEnable": "Enabled"}
    changes, unsupported = bios.plan_changes(attrs, DELL, ["cpu_virtualization", "iommu", "boot_mode"])
    assert [(c.attribute, c.before, c.after) for c in changes] == [
        ("ProcVirtualization", "Disabled", "Enabled"),  # on Dell this one attribute covers VT-x and VT-d
        ("BootMode", "Bios", "Uefi"),
    ]
    assert unsupported == []


def test_settings_that_are_already_right_are_left_alone() -> None:
    attrs = {"ProcVirtualization": "Enabled", "BootMode": "Uefi"}
    assert bios.plan_changes(attrs, DELL, ["cpu_virtualization", "iommu", "boot_mode"]) == ([], [])


def test_the_bios_value_style_is_kept_and_missing_settings_are_reported() -> None:
    attrs = {"IntelVT": "DISABLE", "BootModeSelect": "LEGACY"}
    changes, unsupported = bios.plan_changes(attrs, GENERIC, ["cpu_virtualization", "iommu", "boot_mode"])
    assert [(c.attribute, c.after) for c in changes] == [("IntelVT", "ENABLE"), ("BootModeSelect", "UEFI")]
    assert unsupported == ["iommu"]  # no IOMMU attribute on this BIOS: verify it by hand


def test_only_what_the_inventory_shows_as_wrong_is_changed_by_default() -> None:
    assert bios.wanted_from_inventory(False, True, "Uefi") == ["cpu_virtualization"]
    assert bios.wanted_from_inventory(None, None, None) == []  # unknown is not wrong
    assert bios.wanted_from_inventory(True, False, "Bios") == ["iommu", "boot_mode"]
