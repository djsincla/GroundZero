"""Reading VMs: the OVF settings an appliance was given, recovered from its .vmx (the API hides them)."""

from __future__ import annotations

from groundzero.esxi import vms

# A Holorouter's .vmx line, as ESXi writes it: the OVF environment with special characters as |XX.
VMX = (
    'displayName = "holo1-holorouter"\n'
    'guestinfo.ovfEnv = "<?xml version=|221.0|22 encoding=|22UTF-8|22?>|0A<Environment '
    "xmlns=|22http://schemas.dmtf.org/ovf/environment/1|22 xmlns:oe=|22http://schemas.dmtf.org/ovf/environment/1|22>"
    "|0A  <PropertySection>|0A    <Property oe:key=|22network.ip|22 oe:value=|22192.0.2.150|22/>"
    "|0A    <Property oe:key=|22network.password|22 oe:value=|22Ex|26amp;ample|22/>"
    "|0A    <Property oe:key=|22extra.ssh_enabled|22 oe:value=|22True|22/>"
    '|0A  </PropertySection>|0A</Environment>|0A"\n'
    'memSize = "12288"\n'
)


def test_ovf_settings_are_read_back_from_the_vmx() -> None:
    env = vms.ovf_env_from_vmx(VMX)
    assert env == {"network.ip": "192.0.2.150", "network.password": "Ex&ample", "extra.ssh_enabled": "True"}


def test_a_vmx_without_ovf_settings_reads_as_empty() -> None:
    assert vms.ovf_env_from_vmx('displayName = "dns"\nmemSize = "4096"\n') == {}
    assert vms.ovf_env_from_vmx('guestinfo.ovfEnv = "not xml"\n') == {}


def test_guest_ips_skip_link_local_and_repeats() -> None:
    """Live finding: Tools reports the primary IP twice, plus the appliance's internal networks."""
    assert vms._ipv4(["192.0.2.150", "169.254.1.1", "fe80::1", "192.0.2.150", "198.51.100.244"]) == [
        "192.0.2.150",
        "198.51.100.244",
    ]
