"""Cluster mode rules: names from the BMC, addresses from the pool, DNS checked both ways."""

from __future__ import annotations

import asyncio

import pytest

from groundzero.clusters import ClusterWrite, derive_hostname, next_free_ip
from groundzero.dnscheck import StaticDns, check


def test_hostnames_come_from_the_bmc_name() -> None:
    assert derive_hostname("idrac-esx01", "idrac-", "") == "esx01"
    assert (
        derive_hostname("ESX02-iDRAC.lab.example", "", "-idrac") == "esx02"
    )  # case-insensitive, FQDN trimmed
    assert derive_hostname("esx03", "idrac-", "") == "esx03"  # nothing to strip
    with pytest.raises(ValueError, match="not a valid hostname"):
        derive_hostname("idrac-", "idrac-", "")


def test_addresses_are_the_next_free_in_the_range() -> None:
    assert next_free_ip("192.0.2.101", "192.0.2.103", set()) == "192.0.2.101"
    assert next_free_ip("192.0.2.101", "192.0.2.103", {"192.0.2.101", "192.0.2.102"}) == "192.0.2.103"
    assert next_free_ip("192.0.2.101", "192.0.2.102", {"192.0.2.101", "192.0.2.102"}) is None


def test_a_cluster_range_and_domain_are_checked() -> None:
    base = {"name": "a", "config_set_id": "x", "dns_domain": "Lab.Example."}
    assert ClusterWrite(**base, ip_first="192.0.2.1", ip_last="192.0.2.9").dns_domain == "lab.example"
    with pytest.raises(ValueError, match="comes before"):
        ClusterWrite(**base, ip_first="192.0.2.9", ip_last="192.0.2.1")
    assert ClusterWrite(**base, ip_first="192.0.2.1", ip_last="192.0.2.9").require_dns is False  # an option


def test_dns_must_agree_in_both_directions() -> None:
    dns = StaticDns({"esx01.lab.example": "192.0.2.101", "other.lab.example": "192.0.2.102"})
    ok = asyncio.run(check(dns, "esx01.lab.example", "192.0.2.101", ["192.0.2.53"]))
    assert ok.ok and ok.problems == []
    wrong = asyncio.run(check(dns, "esx01.lab.example", "192.0.2.102", ["192.0.2.53"]))
    assert not wrong.ok and wrong.problems == [
        "esx01.lab.example resolves to 192.0.2.101, not 192.0.2.102",
        "192.0.2.102 points back to other.lab.example, not esx01.lab.example",
    ]
