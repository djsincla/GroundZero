"""
GroundZero — VCF 9.1 compatibility rules engine (Layer B).

Facade module for backward compatibility. Implementation has been split into
domain-specific modules under the ``groundzero.compat`` package:
  - ``groundzero.compat.npar``: NIC Partitioning (NPAR) evaluation
  - ``groundzero.compat.bios_boot``: UEFI/Legacy boot mode and BIOS baseline / Spectre analysis
  - ``groundzero.compat.firmware``: BMC and drive firmware & HCL recommendation comparisons
  - ``groundzero.compat.chassis``: Modular chassis and OEM certification checks
  - ``groundzero.compat.pci``: PCI device compatibility and PCIe root-complex lane budgeting
  - ``groundzero.compat.cpu``: CPU generation categorization and NUMA/chiplet profiling
  - ``groundzero.compat.vsan``: vSAN ESA and OSA hardware readiness rules
  - ``groundzero.compat.memory``: Memory channel interleaving & topology evaluation
  - ``groundzero.compat.engine``: VCF9CompatibilityEngine orchestrator class
"""
from groundzero.compat.bios_boot import _cve_tier_from_date, evaluate_bios_version, evaluate_boot_mode
from groundzero.compat.chassis import _is_oem_chassis_certified
from groundzero.compat.cpu import evaluate_cpu, get_cpu_deep_profile
from groundzero.compat.dell_eems import (
    DellEemsInfo,
    build_dell_eems_guide_url,
    decode_dell_message_id,
)
from groundzero.compat.engine import VCF9CompatibilityEngine
from groundzero.compat.firmware import (
    KNOWN_DEFECTIVE_DRIVE_FIRMWARE,
    _compare_fw_versions,
    _parse_fw_version_tuple,
    check_defective_drive_firmware,
    evaluate_bmc_fw_version,
    evaluate_drive_fw,
    evaluate_driver_firmware_recommendation,
)
from groundzero.compat.memory import MemoryInterleavingEngine, evaluate_memory_topology
from groundzero.compat.npar import evaluate_npar
from groundzero.compat.pci import (
    _EVAL_PCI_CACHE_MAX,
    _EVAL_PCI_COMPAT_CACHE,
    evaluate_pci_compatibility,
    evaluate_pcie_lane_budget,
    evaluate_pcie_link_health,
)
from groundzero.compat.vsan import evaluate_vsan

__all__ = [
    "_EVAL_PCI_CACHE_MAX",
    "_EVAL_PCI_COMPAT_CACHE",
    "MemoryInterleavingEngine",
    "VCF9CompatibilityEngine",
    "_compare_fw_versions",
    "_cve_tier_from_date",
    "_is_oem_chassis_certified",
    "_parse_fw_version_tuple",
    "check_defective_drive_firmware",
    "decode_dell_message_id",
    "DellEemsInfo",
    "build_dell_eems_guide_url",
    "KNOWN_DEFECTIVE_DRIVE_FIRMWARE",
    "evaluate_bios_version",
    "evaluate_bmc_fw_version",
    "evaluate_boot_mode",
    "evaluate_cpu",
    "evaluate_drive_fw",
    "evaluate_driver_firmware_recommendation",
    "evaluate_memory_topology",
    "evaluate_npar",
    "evaluate_pci_compatibility",
    "evaluate_pcie_lane_budget",
    "evaluate_pcie_link_health",
    "evaluate_vsan",
    "get_cpu_deep_profile",
]
