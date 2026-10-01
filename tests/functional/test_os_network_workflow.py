"""Reading the installed hypervisor's network through the real CLI and server (simulated ESXi)."""

from __future__ import annotations

import pytest

from .harness import GroundZero

pytestmark = pytest.mark.functional


def test_read_esxi_management_network(simulated_r740xd: GroundZero) -> None:
    gz = simulated_r740xd
    assert gz.cli("hosts", "add", "--bmc", "198.51.100.11", "--name", "r740xd").code == 0

    not_set = gz.cli("os", "network", "r740xd")
    assert not_set.code == 1 and "No OS access configured" in not_set.output

    assert gz.cli("os", "set", "r740xd", "--address", "192.0.2.101").code == 0
    result = gz.cli("os", "network", "r740xd")
    assert result.code == 0, result.output
    out = result.output
    assert "esxi1" in out and "ntp NONE" in out
    mgmt_row = next(line for line in out.splitlines() if "vmk0" in line)
    assert "Management Network" in mgmt_row and "100" in mgmt_row and "vmnic0, vmnic1" in mgmt_row
    assert "Te1/0/11" in out and "Te1/0/12" in out
    assert "vSwitch0: MTU 1500" in out
