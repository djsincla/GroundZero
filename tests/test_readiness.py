"""Readiness rules: storage proposal, network/NTP checks and the fix plan (pure logic, esxi1 fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage, PortGroup, SecurityPolicy
from groundzero.preflight.evaluate import CheckStatus, load_profile
from groundzero.readiness import ReadinessReport, assess
from groundzero.readiness.assess import propose_storage

ESXI1 = Path(__file__).parent / "fixtures" / "esxi1"
PROFILE = load_profile("holodeck-9")


@pytest.fixture
def configured() -> EsxiNetworkConfig:
    """esxi1 before the reinstall: an earlier Holodeck's trunk port groups, but MTU 1500 and no NTP."""
    return EsxiNetworkConfig.model_validate_json((ESXI1 / "network.json").read_text())


@pytest.fixture
def network(configured: EsxiNetworkConfig) -> EsxiNetworkConfig:
    """esxi1 as freshly installed (matches the live read after the 9.1.1 install)."""
    pgs = [p for p in configured.portgroups if p.name == "Management Network"]
    pgs.append(PortGroup(name="VM Network", vlan_id=0, vswitch="vSwitch0"))
    switches = [v.model_copy(update={"portgroups": [p.name for p in pgs]}) for v in configured.vswitches]
    return configured.model_copy(
        update={
            "version": "9.1.1",
            "build": "25714478",
            "portgroups": pgs,
            "vswitches": switches,
            "ntp_servers": ["pool.ntp.org"],
            "ntp_running": True,
            "ntp_policy": "off",
        }
    )


@pytest.fixture
def storage() -> EsxiStorage:
    return EsxiStorage.model_validate_json((ESXI1 / "storage.json").read_text())


def _assess(network: EsxiNetworkConfig, storage: EsxiStorage, **kw: object) -> ReadinessReport:
    return assess(profile=PROFILE, variant=str(kw.pop("variant", "vcf-9.0-esa-single")), network=network,
                  storage=storage, preflight=None, **kw)  # type: ignore[arg-type]  # fmt: skip


def _check(report: ReadinessReport, check_id: str) -> CheckStatus:
    return next(c.status for c in report.checks if c.id == check_id)


def _ready_network(network: EsxiNetworkConfig) -> EsxiNetworkConfig:
    accept = SecurityPolicy(allow_promiscuous=True, mac_changes=True, forged_transmits=True)
    pgs = [*network.portgroups,
           PortGroup(name="Holodeck-Trunk", vlan_id=4095, vswitch="vSwitch0", security=accept),
           PortGroup(name="Holodeck-External", vlan_id=100, vswitch="vSwitch0")]  # fmt: skip
    switches = [v.model_copy(update={"mtu": 9000}) for v in network.vswitches]
    ntp = {"ntp_servers": ["pool.ntp.org"], "ntp_running": True, "ntp_policy": "on"}
    return network.model_copy(update={"portgroups": pgs, "vswitches": switches, **ntp})


def test_esxi1_as_installed_gets_a_plan(network: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    r = _assess(network, storage)
    assert not r.ready and r.overall is CheckStatus.FAIL
    assert r.storage.kind == "existing" and r.storage.datastore == "localHolodeck"  # 3.9 TB free flash
    assert _check(r, "storage.datastore") is CheckStatus.PASS
    assert _check(r, "network.mtu") is CheckStatus.FAIL
    assert _check(r, "network.trunk") is CheckStatus.FAIL
    assert _check(r, "network.external") is CheckStatus.WARN  # VM Network (VLAN 0) exists: confirm it
    assert _check(r, "network.jumbo") is CheckStatus.UNKNOWN
    actions = {(a.id, a.check): a for a in r.plan}
    assert actions[("set_mtu", "network.mtu")].params == {"vswitch": "vSwitch0", "mtu": 9000}
    trunk = actions[("ensure_portgroup", "network.trunk")]
    assert trunk.params["vlan"] == 4095 and trunk.params["allow_promiscuous"] and trunk.recommended
    external = actions[("ensure_portgroup", "network.external")]
    assert external.params["vlan"] == 100 and not external.recommended  # optional: an existing PG may do
    assert actions[("configure_ntp", "ntp")].title.startswith("Make NTP start with the host")
    assert ("verify_jumbo", "network.jumbo") in actions
    assert not any(a.destructive for a in r.plan)


def test_a_prepared_host_is_ready(network: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    r = _assess(_ready_network(network), storage, jumbo={"ok": True, "summary": "9000 bytes vmnic0 → vmnic1"})
    assert r.ready and r.plan == []
    assert all(
        c.status in (CheckStatus.PASS, CheckStatus.WARN) for c in r.checks if c.id != "hardware.preflight"
    )
    assert _check(r, "hardware.preflight") is CheckStatus.UNKNOWN  # no preflight given to this unit test


def test_an_earlier_holodeck_trunk_is_recognised(configured: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    r = _assess(configured, storage)
    assert _check(r, "network.trunk") is CheckStatus.PASS  # HoloDeckSite* on VLAN 4095, all Accept
    assert not any(a.check == "network.trunk" for a in r.plan)
    assert _check(r, "network.mtu") is CheckStatus.FAIL
    ntp = next(a for a in r.plan if a.id == "configure_ntp")
    assert ntp.title == "Configure NTP (pool.ntp.org) and start it" and ntp.params["servers"] == [
        "pool.ntp.org"
    ]


def test_only_the_ntp_startup_policy_needs_fixing(network: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    net = _ready_network(network).model_copy(update={"ntp_policy": "off"})
    action = next(a for a in _assess(net, storage).plan if a.id == "configure_ntp")
    assert action.title.startswith("Make NTP start with the host") and action.params["policy"] == "on"


def test_a_trunk_with_reject_security_gets_its_policy_fixed(
    network: EsxiNetworkConfig, storage: EsxiStorage
) -> None:
    net = _ready_network(network)
    pgs = [p.model_copy(update={"security": SecurityPolicy()}) if p.is_trunk else p for p in net.portgroups]
    r = _assess(net.model_copy(update={"portgroups": pgs}), storage)
    action = next(a for a in r.plan if a.check == "network.trunk")
    assert action.title.startswith("Set security on port group Holodeck-Trunk")


def test_without_a_fitting_datastore_the_largest_unused_flash_disk_is_proposed(storage: EsxiStorage) -> None:
    small = storage.model_copy(
        update={"datastores": [d for d in storage.datastores if d.name != "localHolodeck"]}
    )
    p = propose_storage(small, required_gb=1175)
    assert p.kind == "format" and p.disk_label == "NVMe Dell Express Flash PM1725b 1.6TB SFF"
    chosen = next(d for d in small.disks if d.name == p.disk)
    assert chosen.partitions == 0 and not chosen.is_boot and not chosen.datastores


def test_formatting_is_destructive_and_needs_a_typed_phrase(
    network: EsxiNetworkConfig, storage: EsxiStorage
) -> None:
    small = storage.model_copy(
        update={"datastores": [d for d in storage.datastores if d.name != "localHolodeck"]}
    )
    action = next(a for a in _assess(network, small).plan if a.id == "create_datastore")
    assert action.destructive and action.confirm_phrase == "format NVMe Dell Express Flash PM1725b 1.6TB SFF"
    assert action.params == {"disk": action.params["disk"], "name": "holodeck"}


def test_disks_with_partitions_unknown_or_in_use_are_never_proposed(storage: EsxiStorage) -> None:
    no_ds = storage.model_copy(update={"datastores": []})
    unknown = no_ds.model_copy(
        update={"disks": [d.model_copy(update={"partitions": None}) for d in no_ds.disks]}
    )
    assert propose_storage(unknown, required_gb=500).kind == "none"
    partitioned = [d for d in storage.disks if d.partitions and not d.datastores and not d.is_boot]
    assert partitioned and propose_storage(no_ds, required_gb=500).disk != partitioned[0].name


def test_nothing_fits_a_dual_site_lab(network: EsxiNetworkConfig, storage: EsxiStorage) -> None:
    r = _assess(network, storage, variant="vcf-9.1-dual")  # 5 TB + Holorouter
    assert r.storage.kind == "none" and _check(r, "storage.datastore") is CheckStatus.FAIL
    assert "smaller variant" in r.storage.reason


@pytest.mark.parametrize(
    ("version", "status"),
    [("8.0.2", CheckStatus.FAIL), ("8.0.3", CheckStatus.PASS), ("9.0.1", CheckStatus.PASS),
     ("9.1.1", CheckStatus.WARN)],
)  # fmt: skip
def test_esx_version_against_the_tested_list(
    network: EsxiNetworkConfig, storage: EsxiStorage, version: str, status: CheckStatus
) -> None:
    assert _check(_assess(network.model_copy(update={"version": version}), storage), "esxi.version") is status
