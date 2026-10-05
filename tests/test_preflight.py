from __future__ import annotations

from typing import Any

import pytest
from conftest import make_client

from groundzero.inventory.collect import collect_inventory
from groundzero.inventory.models import HostInventory
from groundzero.preflight.evaluate import CheckStatus, UnknownProfileError, evaluate, load_profile
from groundzero.vcf_readiness.cpu import CpuSupport, classify_cpu


async def _inventory(data: dict[str, Any]) -> HostInventory:
    async with make_client(data) as client:
        return (await collect_inventory(client))[1]


def _status(report: Any, check_id: str) -> CheckStatus:
    return next(c.status for c in report.checks if c.id == check_id)


@pytest.mark.parametrize(
    ("model", "support"),
    [
        ("Intel(R) Xeon(R) Gold 6230 CPU @ 2.10GHz", CpuSupport.SUPPORTED),
        ("Intel(R) Xeon(R) Gold 6130 CPU @ 2.10GHz", CpuSupport.OVERRIDE_REQUIRED),
        ("Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz", CpuSupport.UNSUPPORTED),
        ("AMD EPYC 7543 32-Core Processor", CpuSupport.SUPPORTED),
        ("Intel(R) Xeon(R) Gold 6430", CpuSupport.SUPPORTED),
        ("Mystery CPU", CpuSupport.UNKNOWN),
    ],
)
def test_classify_cpu(model: str, support: CpuSupport) -> None:
    assert classify_cpu(model).support is support


def test_profile_loads_all_variants() -> None:
    profile = load_profile("holodeck-9")
    assert profile.default_variant in profile.variants
    assert profile.variants["vcf-9.0-esa-single"].cores == 32


async def test_r740xd_passes_default_variant(idrac9: dict[str, Any]) -> None:
    report = evaluate(await _inventory(idrac9), "holodeck-9")
    failing = [(c.id, c.status) for c in report.checks if c.status != CheckStatus.PASS]
    assert failing == []
    assert report.overall is CheckStatus.PASS


async def test_too_small_for_vcf_9_1(idrac9: dict[str, Any]) -> None:
    report = evaluate(await _inventory(idrac9), "holodeck-9", "vcf-9.1-single")
    assert _status(report, "memory.total") is CheckStatus.FAIL  # 384 GiB < 650 + 12 GB
    assert report.overall is CheckStatus.FAIL


async def test_threads_only_is_a_warning(idrac9: dict[str, Any]) -> None:
    # vcf-9.1-single needs 48 + 6 cores: 40 physical fall short, 80 threads do not.
    report = evaluate(await _inventory(idrac9), "holodeck-9", "vcf-9.1-single")
    assert _status(report, "cpu.cores") is CheckStatus.WARN


async def test_not_enough_threads_fails(idrac9: dict[str, Any]) -> None:
    report = evaluate(await _inventory(idrac9), "holodeck-9", "vcf-9.1-dual")  # 96 + 6 > 80 threads
    assert _status(report, "cpu.cores") is CheckStatus.FAIL


async def test_legacy_bios_and_disabled_vt_fail(idrac9: dict[str, Any]) -> None:
    idrac9["/redfish/v1/Systems/System.Embedded.1/Bios"]["Attributes"].update(
        {"ProcVirtualization": "Disabled", "BootMode": "Bios"}
    )
    report = evaluate(await _inventory(idrac9), "holodeck-9")
    assert _status(report, "bios.cpu_virtualization") is CheckStatus.FAIL
    assert _status(report, "bios.boot_mode") is CheckStatus.FAIL


async def test_express_license_blocks_virtual_media(idrac9: dict[str, Any]) -> None:
    idrac9["/redfish/v1/LicenseService/Licenses/FD000001"]["Description"] = "iDRAC9 Express License"
    report = evaluate(await _inventory(idrac9), "holodeck-9")
    assert _status(report, "bmc.license") is CheckStatus.FAIL


def test_unknown_variant_rejected() -> None:
    with pytest.raises(UnknownProfileError):
        load_profile("nope")
