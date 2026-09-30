"""
GroundZero — groundzero package root.

This module re-exports every public name that groundzero_web.py, groundzero_collector.py,
and legacy entry points (redfish_collector.py, redfish_web.py) import, providing
full backward compatibility while the codebase is split across sub-modules.

Preferred import paths for new code:
    from groundzero.collector import UniversalRedfishCollector, create_collector
    from groundzero.report import generate_host_html_report, generate_summary_html
    from groundzero.constants import TOOL_VERSION
    from groundzero.logging_utils import configure_logging, sanitize_filename
"""
from groundzero.bcg_links import BCGLinkGenerator
from groundzero.collector import UniversalRedfishCollector, create_collector
from groundzero.collector.pci_utils import normalize_pci_id
from groundzero.compat_engine import (
    MemoryInterleavingEngine,
    VCF9CompatibilityEngine,
    evaluate_bios_version,
    evaluate_bmc_fw_version,
    evaluate_drive_fw,
    evaluate_driver_firmware_recommendation,
    evaluate_pci_compatibility,
)
from groundzero.constants import TOOL_VERSION
from groundzero.enrichment import enrich_host_result
from groundzero.hcl import (
    create_hcl_bundle,
    ensure_auto_hcl_bundle,
    get_hcl_cache_status,
    get_hcl_dir,
    import_hcl_bundle,
    load_optional_vsan_csv,
    load_vsan_hcl_json,
    sanitize_hcl_entry,
)
from groundzero.logging_utils import (
    configure_logging,
    create_obfuscated_scan_zip_archive,
    create_scan_output_dir,
    create_scan_zip_archive,
    generate_scan_dirname,
    get_default_output_dir,
    is_cloud_metadata_target,
    is_private_or_local_target,
    is_root_user,
    normalize_output_dir,
    parse_ip_targets,
    resolve_target_fqdn,
    sanitize_filename,
    update_latest_scan_aliases,
)
from groundzero.obfuscation import obfuscate_host_data
from groundzero.protocol import detect_management_protocol
from groundzero.report import (
    _generate_combined_html,
    build_fleet_tiles_html,
    generate_combined_html,
    generate_combined_tabbed_html,
    generate_host_html_report,
    generate_summary_html,
    normalize_oem_vendor,
)
from groundzero.scan import scan_hosts
from groundzero.servicetag import (
    DellTechDirectClient,
    evaluate_esa_from_components,
    summarise_warranty,
)
from groundzero.tls_utils import build_ssl_context, format_ssl_error
from groundzero.wsman import WsManCollector

__version__ = TOOL_VERSION

__all__ = [
    # Web UI / CLI import these from groundzero_collector / redfish_collector
    "TOOL_VERSION",
    "configure_logging",
    "create_obfuscated_scan_zip_archive",
    "create_scan_output_dir",
    "create_scan_zip_archive",
    "generate_scan_dirname",
    "sanitize_filename",
    "parse_ip_targets",
    "is_private_or_local_target",
    "is_root_user",
    "is_cloud_metadata_target",
    "get_default_output_dir",
    "normalize_output_dir",
    "resolve_target_fqdn",
    "update_latest_scan_aliases",
    "UniversalRedfishCollector",
    "create_collector",
    "obfuscate_host_data",
    "_generate_combined_html",
    "generate_combined_html",
    "generate_combined_tabbed_html",
    "generate_host_html_report",
    "generate_summary_html",
    "normalize_oem_vendor",
    "build_fleet_tiles_html",
    "load_vsan_hcl_json",
    "load_optional_vsan_csv",
    "get_hcl_cache_status",
    "sanitize_hcl_entry",
    "get_hcl_dir",
    "ensure_auto_hcl_bundle",
    "create_hcl_bundle",
    "import_hcl_bundle",
    "detect_management_protocol",
    "WsManCollector",
    "scan_hosts",
    "enrich_host_result",
    "BCGLinkGenerator",
    "VCF9CompatibilityEngine",
    "MemoryInterleavingEngine",
    "evaluate_bios_version",
    "evaluate_bmc_fw_version",
    "evaluate_drive_fw",
    "evaluate_pci_compatibility",
    "evaluate_driver_firmware_recommendation",
    "normalize_pci_id",
    "build_ssl_context",
    "format_ssl_error",
    # Service Tag / TechDirect
    "DellTechDirectClient",
    "evaluate_esa_from_components",
    "summarise_warranty",
]
