"""BIOS registry and profiles: the R740xd's recorded registry, checks against it, imports and planning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from groundzero.inventory.models import BiosSettings
from groundzero.modules.bios import ConfigureBios, plan_bios
from groundzero.redfish.bios_profiles import BiosProfile, capture_defaults, parse_import
from groundzero.redfish.bios_registry import BiosRegistry, _base, parse_registry
from groundzero.redfish.capture import registry_values, sanitize

R740XD = Path(__file__).parent / "fixtures" / "dell-r740xd"


@pytest.fixture(scope="module")
def registry() -> BiosRegistry:
    return parse_registry(
        json.loads((R740XD / "redfish_v1_Systems_System.Embedded.1_Bios_BiosRegistry.json").read_text())
    )


@pytest.fixture(scope="module")
def current() -> dict[str, object]:
    return dict(
        json.loads((R740XD / "redfish_v1_Systems_System.Embedded.1_Bios.json").read_text())["Attributes"]
    )


def test_the_registry_describes_every_setting(registry: BiosRegistry) -> None:
    assert registry.id == "BiosAttributeRegistry.v1_0_3" and len(registry.attributes) == 641
    vt = registry.attributes["ProcVirtualization"]
    assert (vt.display, vt.type, vt.menu) == (
        "Virtualization Technology",
        "Enumeration",
        "Processor Settings",
    )
    assert [v.name for v in vt.values] == ["Enabled", "Disabled"] and vt.settable
    assert registry.attributes["SystemModelName"].read_only
    assert not registry.attributes["SetupPassword"].settable  # a password: never in a profile
    assert sum(a.settable for a in registry.attributes.values()) == 189


def test_the_idrac_lists_another_version_of_the_same_registry() -> None:
    assert (
        _base("BiosAttributeRegistry.v1_0_3")
        == _base("BiosAttributeRegistry.v1_0_0")
        == "BiosAttributeRegistry"
    )


def test_values_are_checked_against_the_registry(registry: BiosRegistry, current: dict[str, object]) -> None:
    problems = registry.check(
        {
            "LogicalProc": "Maybe",
            "SystemModelName": "x",
            "SetupPassword": "pw",
            "NoSuchThing": "1",
            "ControlledTurboMinusBin": 40,
            "IscsiDev1Con1VlanId": "7",
            "NumLock": "Off",
        }
    )
    assert {(name, kind) for name, _, kind in problems} == {
        ("LogicalProc", "enum"),
        ("SystemModelName", "read_only"),
        ("SetupPassword", "secret"),
        ("NoSuchThing", "unknown_attribute"),
        ("ControlledTurboMinusBin", "range"),
        ("IscsiDev1Con1VlanId", "int_type"),
    }
    settable = {
        k: v for k, v in current.items() if k in registry.attributes and registry.attributes[k].settable
    }
    assert registry.check(settable) == []  # the server's own settings are all valid


def test_a_capture_keeps_choices_not_per_server_text(
    registry: BiosRegistry, current: dict[str, object]
) -> None:
    keep = capture_defaults(registry, current)
    assert "ProcVirtualization" in keep and "SysProfile" in keep and "ControlledTurboMinusBin" in keep
    assert "AssetTag" not in keep and "IscsiInitiatorName" not in keep and "SystemModelName" not in keep


def test_import_reads_a_dell_scp_and_types_its_values(registry: BiosRegistry) -> None:
    scp = {
        "SystemConfiguration": {
            "Model": "PowerEdge R740xd",
            "Components": [
                {
                    "FQDD": "iDRAC.Embedded.1",
                    "Attributes": [{"Name": "IPv4.1#Address", "Value": "192.0.2.5"}],
                },
                {
                    "FQDD": "BIOS.Setup.1-1",
                    "Attributes": [
                        {"Name": "LogicalProc", "Value": "Disabled"},
                        {"Name": "ControlledTurboMinusBin", "Value": "2"},
                        {"Name": "#Comment", "Value": "documentation row"},
                    ],
                },
            ],
        }
    }
    assert parse_import(json.dumps(scp), registry) == {
        "LogicalProc": "Disabled",
        "ControlledTurboMinusBin": 2,
    }
    assert parse_import('{"Attributes": {"NumLock": "Off"}}', registry) == {"NumLock": "Off"}
    assert parse_import('{"NumLock": "Off"}', registry) == {"NumLock": "Off"}
    with pytest.raises(ValueError, match="Not JSON"):
        parse_import("NumLock=Off", registry)


def _profile(**attributes: str | int) -> BiosProfile:
    return BiosProfile(
        id="p1",
        name="Lab",
        registry="r",
        attributes=attributes,
        created_at="2026-10-07T00:00:00Z",
        updated_at="2026-10-07T00:00:00Z",
    )  # type: ignore[arg-type]


def test_a_profile_plans_only_what_differs_and_wins_over_the_baseline(current: dict[str, object]) -> None:
    bios = BiosSettings(
        cpu_virtualization=False,
        iommu=None,
        boot_mode="Bios",
        attributes={**current, "ProcVirtualization": "Disabled", "BootMode": "Bios"},
    )  # type: ignore[arg-type]
    changes, _ = plan_bios(
        "dell", bios, None, _profile(LogicalProc="Disabled", NumLock="On", BootMode="Bios")
    )
    assert {(c.attribute, c.before, c.after) for c in changes} == {
        ("ProcVirtualization", "Disabled", "Enabled"),  # the baseline
        ("LogicalProc", "Enabled", "Disabled"),  # the profile; NumLock is already On
    }  # the profile keeps legacy boot mode: its value wins over the baseline's UEFI


def test_not_needed_only_once_the_profile_matches(current: dict[str, object]) -> None:
    inventory = {
        "bios": {"cpu_virtualization": True, "iommu": True, "boot_mode": "Uefi", "attributes": current}
    }
    profile = _profile(LogicalProc="Disabled")
    lookup = {"p1": profile}.get
    module = ConfigureBios()
    assert module.satisfied({"inventory": inventory}, {"profile_id": "p1"}, lambda k, i: lookup(i)) is None
    matching = _profile(LogicalProc="Enabled", NumLock="On")
    said = module.satisfied({"inventory": inventory}, {"profile_id": "p1"}, lambda k, i: matching)
    assert said is not None and said.endswith("matches Lab (2 settings)")


def test_a_capture_keeps_registry_choices_that_sound_sensitive() -> None:
    responses = {
        "/reg": {
            "RegistryEntries": {
                "Attributes": [{"AttributeName": "SerialComm", "Value": [{"ValueName": "OnConRedirAuto"}]}]
            }
        }
    }
    body = {
        "Attributes": {
            "SerialComm": "OnConRedirAuto",
            "SystemServiceTag": "ABC1234",
            "SubNumaCluster": "Disabled",
        }
    }
    clean = sanitize(body, settings=registry_values(responses) | {"Disabled"})
    assert clean["Attributes"] == {
        "SerialComm": "OnConRedirAuto",
        "SystemServiceTag": "REDACTED",
        "SubNumaCluster": "Disabled",
    }


def test_an_unreachable_bmc_is_a_clear_502(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from groundzero.api.app import create_app
    from groundzero.core.config import Settings
    from groundzero.redfish.client import RedfishClient
    from groundzero.redfish.errors import RedfishTransportError

    class Unreachable(RedfishClient):
        async def __aenter__(self) -> RedfishClient:
            raise RedfishTransportError("POST /redfish/v1/SessionService/Sessions failed: ConnectTimeout")

    settings = Settings(home=tmp_path / "home", api_token="t", iso_repository=tmp_path / "isos")
    app = create_app(settings, client_factory=lambda host, pw: Unreachable("bmc.test", "root", pw))
    with TestClient(app) as api:
        api.headers["Authorization"] = "Bearer t"
        host = api.post(
            "/api/v1/hosts", json={"bmc_address": "bmc.test", "username": "root", "password": "x"}
        ).json()
        response = api.get(f"/api/v1/hosts/{host['id']}/bios-registry")
    assert response.status_code == 502 and response.json()["type"] == "urn:groundzero:problem:bmc_error"
    assert "ConnectTimeout" in response.json()["detail"]
