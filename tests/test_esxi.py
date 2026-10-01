from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest

from groundzero.esxi.models import EsxiNetworkConfig
from groundzero.esxi.reader import extract_network

ESXI1 = Path(__file__).parent / "fixtures" / "esxi1-network.json"


@pytest.fixture
def esxi1() -> EsxiNetworkConfig:
    return EsxiNetworkConfig.model_validate_json(ESXI1.read_text())


def test_esxi1_management_matches_lab_spec(esxi1: EsxiNetworkConfig) -> None:
    """Lab spec from the user: management vmk on VLAN 100 with vmnic0 + vmnic1."""
    assert esxi1.management is not None and esxi1.management.device == "vmk0"
    assert esxi1.management_vlan() == 100
    assert esxi1.management_uplinks() == ["vmnic0", "vmnic1"]
    assert esxi1.install_nic() == "vmnic0"  # vmk0 carries vmnic0's MAC
    assert esxi1.management.netmask == "255.255.255.0"


def test_esxi1_holodeck_gaps_are_visible(esxi1: EsxiNetworkConfig) -> None:
    assert esxi1.ntp_servers == []
    assert {vs.name: vs.mtu for vs in esxi1.vswitches} == {"vSwitch0": 1500}
    trunks = {p.name for p in esxi1.portgroups if p.vlan_id == 4095}
    assert {"HoloDeckSite1", "HoloDeckSite2"} <= trunks


def _order(active: list[str], standby: list[str]) -> Any:
    return NS(nicTeaming=NS(nicOrder=NS(activeNic=active, standbyNic=standby)))


def test_extract_network_from_vsphere_shapes() -> None:
    about = NS(fullName="VMware ESXi 9.0.1", version="9.0.1", build="1")
    network = NS(
        dnsConfig=NS(hostName="esxi1", domainName="", address=["8.8.8.8"], searchDomain=["lab"], dhcp=False),
        ipRouteConfig=NS(defaultGateway="10.0.0.1"),
        portgroup=[
            NS(
                spec=NS(name="Management Network", vlanId=100, vswitchName="vSwitch0"),
                computedPolicy=_order(["vmnic0", "vmnic1"], []),
            )
        ],
        vswitch=[
            NS(
                name="vSwitch0",
                mtu=1500,
                spec=NS(bridge=NS(nicDevice=["vmnic1", "vmnic0"]), policy=_order(["vmnic0"], ["vmnic1"])),
            )
        ],
        vnic=[
            NS(
                device="vmk0",
                portgroup="Management Network",
                spec=NS(
                    ip=NS(ipAddress="10.0.0.5", subnetMask="255.255.255.0", dhcp=False), mac="aa", mtu=1500
                ),
            )
        ],
        pnic=[
            NS(device="vmnic0", mac="aa", linkSpeed=NS(speedMb=10000), driver="qfle3", pci="0000:19:00.0"),
            NS(device="vmnic1", mac="bb", linkSpeed=None, driver="qfle3", pci="0000:19:00.1"),
        ],
    )
    hints = {"vmnic0": NS(connectedSwitchPort=NS(devId="sw1", portId="Te1/0/11"), lldpInfo=None)}
    cfg = extract_network("10.0.0.5", about, network, ["pool.ntp.org"], {"vmk0": ["management"]}, hints)

    assert cfg.domain is None and cfg.dns_servers == ["8.8.8.8"]
    assert cfg.vswitches[0].active_uplinks == ["vmnic0"] and cfg.vswitches[0].standby_uplinks == ["vmnic1"]
    assert cfg.management_uplinks() == ["vmnic0", "vmnic1"]  # portgroup override wins over vSwitch
    assert cfg.physical_nics[0].switch_port == "Te1/0/11"
    assert cfg.physical_nics[1].speed_mbps is None  # link down
    assert cfg.install_nic() == "vmnic0"


def test_esxi1_trunks_meet_holodeck_security(esxi1: EsxiNetworkConfig) -> None:
    trunks = [p for p in esxi1.portgroups if p.is_trunk]
    assert len(trunks) == 4 and all(p.security.accepts_all for p in trunks)
    mgmt = esxi1.management_portgroup()
    assert mgmt is not None and not mgmt.security.accepts_all  # production port groups stay locked down
