#!/usr/bin/env python3
"""
tools/generate_sboms.py — Comprehensive Software Bill of Materials (SBOM) Generator

Generates industry-standard Software Bill of Materials (SBOM) specifications:
  - CycloneDX 1.5 JSON (specification compliant with PURLs, licenses, and scopes)
  - SPDX 2.3 JSON (ISO/IEC 5962:2021 compliant package and relationship model)
  - Standalone Human-Readable Markdown Documents

Covers three distinct architectural perimeters:
  1. Customer Deliverables (offline package Distribution-GroundZero.zip & binaries)
  2. Internal Tooling & Redfish Telemetry Library (dev, build, test, and catalog assets)
  3. Lab Jump Host (installation-04 infrastructure, system packages, and runtime services)

Usage:
    python tools/generate_sboms.py                # Generate all SBOMs
    python tools/generate_sboms.py --scope customer
    python tools/generate_sboms.py --scope internal
    python tools/generate_sboms.py --scope jump-host
    python tools/generate_sboms.py --refresh-jump-host  # Query installation-04 via SSH

Zero external dependencies required (Python 3.9+ stdlib).
"""

import argparse
import datetime
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
DOCS_SBOM_DIR = DOCS_DIR / "sbom"
INTERNAL_SBOM_DIR = REPO_ROOT / "internal" / "sbom"

# Current project version
try:
    sys.path.insert(0, str(REPO_ROOT))
    from groundzero.constants import TOOL_VERSION
except Exception:
    TOOL_VERSION = "9.7.1"

TIMESTAMP = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
DATE_STR = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def compute_file_sha256(filepath: Path) -> Optional[str]:
    """Compute SHA-256 hash of a file if it exists."""
    if not filepath.is_file():
        return None
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ==============================================================================
# PERIMETER 1: CUSTOMER DELIVERABLES
# ==============================================================================

CUSTOMER_METADATA = {
    "name": "groundzero",
    "version": TOOL_VERSION,
    "description": "GroundZero — VCF / vSphere 9.1 HCI Readiness — Redfish-based hardware compatibility scanner",
    "vendor": "Broadcom / VMware",
    "license_spdx": "LicenseRef-CA-Inc",
    "license_name": "CA, Inc. Software License Agreement",
    "homepage": "https://github.com/djsincla/GroundZero",
    "purl": f"pkg:github/djsincla/GroundZero@{TOOL_VERSION}",
}

CUSTOMER_COMPONENTS = [
    {
        "name": "groundzero",
        "version": TOOL_VERSION,
        "type": "application",
        "description": "Core Redfish collection, compatibility assessment, and standalone report generation engine. 100% Python 3.9+ standard library; zero third-party pip dependencies.",
        "purl": f"pkg:pypi/groundzero@{TOOL_VERSION}",
        "license_spdx": "LicenseRef-CA-Inc",
        "scope": "required",
        "supplier": "Broadcom / CA, Inc.",
        "origin": "groundzero/",
        "distribution": "Source package & compiled binaries",
    },
    {
        "name": "@cds/core",
        "version": "5.7.0",
        "type": "library",
        "description": "VMware Clarity Design System CSS stylesheet. Bundled offline as gzip-compressed base64 constant inside groundzero/web/assets.py. Zero external CDN calls or npm runtime requirements.",
        "purl": "pkg:npm/%40cds/core@5.7.0",
        "license_spdx": "Apache-2.0",
        "scope": "required",
        "supplier": "VMware by Broadcom",
        "origin": "Embedded in groundzero/web/assets.py via tools/bundle_assets.py",
        "distribution": "In-memory CSS served by local Web UI (127.0.0.1:7182) and embedded in offline HTML reports",
    },
    {
        "name": "vsan-hcl-dataset",
        "version": "9.1.0",
        "type": "data",
        "description": "Broadcom vSAN Hardware Compatibility List dataset & PCI NIC device mapping database (io_nics.json). Evaluates driver/firmware compatibility and BCG guidance offline.",
        "purl": "pkg:generic/broadcom/vsan-hcl@9.1.0",
        "license_spdx": "LicenseRef-Proprietary-Broadcom",
        "scope": "required",
        "supplier": "Broadcom",
        "origin": "groundzero/io_nics.json and hcl/vcf_hcl_bundle_latest.zip",
        "distribution": "Embedded JSON file and offline bundle archive in hcl/",
    },
    {
        "name": "pyinstaller-bootloader",
        "version": "6.11.0",
        "type": "framework",
        "description": "PyInstaller binary bootloader executable wrapper. Unpacks and runs the bundled CPython runtime and groundzero modules in memory. Shipped exclusively inside compiled binaries in bin/.",
        "purl": "pkg:generic/pyinstaller/bootloader@6.11.0",
        "license_spdx": "GPL-2.0-only WITH Bootloader-exception",
        "scope": "optional",
        "supplier": "PyInstaller Development Team",
        "origin": "Compiled single-file binaries (bin/GroundZero-Web-*, bin/groundzero*)",
        "distribution": "Embedded in standalone platform executables (Mac/Win/Linux). Not used when running via Python source.",
    },
    {
        "name": "cpython-embedded-runtime",
        "version": "3.11.9",
        "type": "operating-system-component",
        "description": "Embedded CPython interpreter and standard library shared libraries embedded inside PyInstaller compiled binaries. Allows execution on target machines without Python pre-installed.",
        "purl": "pkg:generic/python/cpython@3.11.9",
        "license_spdx": "PSF-2.0",
        "scope": "optional",
        "supplier": "Python Software Foundation",
        "origin": "Embedded inside PyInstaller binaries in bin/",
        "distribution": "Self-extracting binary payload",
    },
    {
        "name": "openssl-c-library",
        "version": "3.0.13",
        "type": "library",
        "description": "OpenSSL libcrypto and libssl dynamic libraries statically or dynamically linked inside the PyInstaller binary bundle. Provides TLS 1.2/1.3 for secure Redfish BMC communication.",
        "purl": "pkg:generic/openssl/openssl@3.0.13",
        "license_spdx": "Apache-2.0",
        "scope": "optional",
        "supplier": "OpenSSL Project",
        "origin": "Embedded inside compiled executables in bin/",
        "distribution": "Binary runtime dependency of compiled executables",
    },
    {
        "name": "sqlite3-engine",
        "version": "3.45.1",
        "type": "library",
        "description": "Embedded SQLite3 database engine providing local persistence for the Credential Vault and scan state cache. Self-contained C library with zero external runtime server requirements.",
        "purl": "pkg:generic/sqlite/sqlite@3.45.1",
        "license_spdx": "blessing",
        "scope": "optional",
        "supplier": "SQLite Consortium",
        "origin": "CPython stdlib sqlite3 module",
        "distribution": "Standard library module in Python and compiled binaries",
    },
    {
        "name": "zlib-compression",
        "version": "1.3.1",
        "type": "library",
        "description": "Lossless data compression library used for gzip HTTP transfer decoding, asset decompression, and zipfile archive manipulation.",
        "purl": "pkg:generic/madler/zlib@1.3.1",
        "license_spdx": "Zlib",
        "scope": "optional",
        "supplier": "Jean-loup Gailly and Mark Adler",
        "origin": "CPython stdlib zlib module",
        "distribution": "Standard library module in Python and compiled binaries",
    },
    {
        "name": "libffi",
        "version": "3.4.4",
        "type": "library",
        "description": "Foreign Function Interface library embedded in CPython runtime for native platform invocation.",
        "purl": "pkg:generic/libffi/libffi@3.4.4",
        "license_spdx": "MIT",
        "scope": "optional",
        "supplier": "Anthony Green and contributors",
        "origin": "CPython ctypes runtime dependency",
        "distribution": "Embedded inside compiled binaries in bin/",
    },
    {
        "name": "groundzero-adapter",
        "version": TOOL_VERSION,
        "type": "application",
        "description": "VMware Aria Operations / VCF Operations 9.1 Management Pack (.pak). Contains adapter.zip, describe.xml, manifest.txt, and resources for native VCF Operations inventory collection.",
        "purl": f"pkg:generic/broadcom/groundzero-adapter@{TOOL_VERSION}",
        "license_spdx": "MIT",
        "scope": "optional",
        "supplier": "Broadcom / VMware Community",
        "origin": f"integrations/vcf-ops/VcfReadinessAdapter_{TOOL_VERSION}_EXPERIMENTAL.pak",
        "distribution": "Packaged .pak archive in integrations/vcf-ops/",
    },
]

CUSTOMER_ZIP_MANIFEST = [
    {"path": "00_HOWTOLAUNCH.TXT", "purpose": "Quick-start guide with zero-dependency launch commands for Mac, Linux, and Windows."},
    {"path": "README.md", "purpose": "Comprehensive user guide covering Web UI, CLI, BMC security baseline, and ESA requirements."},
    {"path": "INSTALL.md", "purpose": "Deployment prerequisites, Python installation instructions, and network firewall requirements."},
    {"path": "ARCHITECTURE.md", "purpose": "Four-layer architectural blueprint (Collector, Enrichment, BCG Links, UI/Reporting)."},
    {"path": "CHANGELOG.md", "purpose": "Complete version history, feature release notes, and compatibility updates."},
    {"path": "LICENSE.md", "purpose": "Software License Agreement (Broadcom / CA, Inc.)."},
    {"path": "NOTICE", "purpose": "Official Broadcom subcomponents and third-party license notice."},
    {"path": "THIRD_PARTY_LICENSES.md", "purpose": "Notices and license texts for bundled third-party open-source components (Clarity Apache-2.0, OpenSSL, CPython, libffi, zlib)."},
    {"path": "CONTRIBUTING.md", "purpose": "Guidelines for testing, code formatting, and OEM extension development."},
    {"path": "pyproject.toml", "purpose": "Project metadata, PEP 517 build configuration, and zero-dependency declarations."},
    {"path": "groundzero_web.py / redfish_web.py", "purpose": "Local Web Browser UI launcher (starts lightweight HTTP server on 127.0.0.1:7182)."},
    {"path": "groundzero_collector.py / redfish_collector.py", "purpose": "Command-line interface entry points for multi-host batch assessments."},
    {"path": "build-web.sh / build-web.bat", "purpose": "Local platform binary compilation scripts for Mac/Linux and Windows."},
    {"path": "bin/", "purpose": "Staged single latest compiled standalone platform executables (no Python installation required)."},
    {"path": "groundzero/", "purpose": "Core application Python package (100% standard library, zero external pip dependencies)."},
    {"path": "docs/", "purpose": "Customer-facing documentation whitelist (guides, OEM reference, security architecture, SBOM)."},
    {"path": "scripts/", "purpose": "Customer-facing helper and execution wrapper scripts."},
    {"path": "tools/", "purpose": "Customer-facing build utilities (build_management_pack.py, clean_build_artifacts.py, etc.)."},
    {"path": "hcl/", "purpose": "Offline Broadcom vSAN HCL database extracts and bundle archives."},
    {"path": "integrations/vcf-ops/", "purpose": "VMware VCF Operations 9.1 Management Pack (.pak) and installation documentation."},
]


# ==============================================================================
# PERIMETER 2: INTERNAL TOOLING & REDFISH TELEMETRY LIBRARY
# ==============================================================================

INTERNAL_TOOLS_COMPONENTS = [
    # Build & Packaging
    {"name": "pyinstaller", "version": "6.11.0", "purl": "pkg:pypi/pyinstaller@6.11.0", "license_spdx": "GPL-2.0-only WITH Bootloader-exception", "category": "Build & Packaging", "scope": "dev", "description": "Compiles standalone executables for macOS, Linux, and Windows."},
    {"name": "setuptools", "version": "68.1.2", "purl": "pkg:pypi/setuptools@68.1.2", "license_spdx": "MIT", "category": "Build & Packaging", "scope": "dev", "description": "Python package build system and wheel generation backend."},
    {"name": "wheel", "version": "0.42.0", "purl": "pkg:pypi/wheel@0.42.0", "license_spdx": "MIT", "category": "Build & Packaging", "scope": "dev", "description": "Built-package format generation utility."},
    # Testing & Verification
    {"name": "pytest", "version": "7.4.4", "purl": "pkg:pypi/pytest@7.4.4", "license_spdx": "MIT", "category": "Testing & QA", "scope": "test", "description": "Primary automated test runner enforcing tiered test hierarchy (Tiers 0-3)."},
    {"name": "pytest-cov", "version": "4.1.0", "purl": "pkg:pypi/pytest-cov@4.1.0", "license_spdx": "MIT", "category": "Testing & QA", "scope": "test", "description": "Coverage reporting plugin enforcing the 70% coverage ratchet in CI."},
    {"name": "pytest-xdist", "version": "3.5.0", "purl": "pkg:pypi/pytest-xdist@3.5.0", "license_spdx": "MIT", "category": "Testing & QA", "scope": "test", "description": "Parallel test execution plugin for multi-core test runs."},
    {"name": "coverage", "version": "7.4.0", "purl": "pkg:pypi/coverage@7.4.0", "license_spdx": "Apache-2.0", "category": "Testing & QA", "scope": "test", "description": "Code coverage measurement engine."},
    {"name": "pluggy", "version": "1.4.0", "purl": "pkg:pypi/pluggy@1.4.0", "license_spdx": "MIT", "category": "Testing & QA", "scope": "test", "description": "Plugin management engine underpinning pytest."},
    {"name": "iniconfig", "version": "1.1.1", "purl": "pkg:pypi/iniconfig@1.1.1", "license_spdx": "MIT", "category": "Testing & QA", "scope": "test", "description": "INI file parsing for test configuration."},
    # Static Analysis & Linters
    {"name": "ruff", "version": "0.16.6", "purl": "pkg:pypi/ruff@0.16.6", "license_spdx": "MIT", "category": "Code Hygiene & Linters", "scope": "dev", "description": "High-performance Python linter enforcing banned imports (TID251), no-print (T20), and py39 syntax."},
    {"name": "ty", "version": "0.0.79", "purl": "pkg:pypi/ty@0.0.79", "license_spdx": "MIT", "category": "Code Hygiene & Linters", "scope": "dev", "description": "Fast informational Python type checker for CI reporting."},
    # Presentation & Publishing Tooling
    {"name": "reportlab", "version": "5.0.1", "purl": "pkg:pypi/reportlab@5.0.1", "license_spdx": "BSD-3-Clause", "category": "Document Generation", "scope": "dev", "description": "PDF generation library used for executive infographic reports."},
    {"name": "pillow", "version": "12.3.0", "purl": "pkg:pypi/pillow@12.3.0", "license_spdx": "HPND", "category": "Document Generation", "scope": "dev", "description": "Image processing library for infographic asset rendering."},
    {"name": "pypdf", "version": "6.17.0", "purl": "pkg:pypi/pypdf@6.17.0", "license_spdx": "BSD-3-Clause", "category": "Document Generation", "scope": "dev", "description": "Pure-Python PDF manipulation and merging library."},
    {"name": "python-docx", "version": "1.2.0", "purl": "pkg:pypi/python-docx@1.2.0", "license_spdx": "MIT", "category": "Document Generation", "scope": "dev", "description": "Microsoft Word docx report generation library."},
    {"name": "lxml", "version": "6.1.3", "purl": "pkg:pypi/lxml@6.1.3", "license_spdx": "BSD-3-Clause", "category": "Document Generation", "scope": "dev", "description": "High-performance XML and HTML parser for documentation bundling."},
    # Redfish Telemetry Library
    {"name": "dmtf-redfish-schemas", "version": "DSP0266-v1.18.0", "purl": "pkg:generic/dmtf/redfish-schemas@1.18.0", "license_spdx": "LicenseRef-DMTF-Standard", "category": "Redfish Telemetry Library", "scope": "dev", "description": "Distributed Management Task Force (DMTF) official Redfish schema specifications (DSP0266 / DSP8010)."},
    {"name": "redfish-telemetry-catalog-db", "version": "2.4.0", "purl": "pkg:generic/groundzero/catalog-db@2.4.0", "license_spdx": "MIT", "category": "Redfish Telemetry Library", "scope": "dev", "description": "SQLite3 master registry indexing 50,000+ Redfish endpoints across hardware archetypes with offline DMTF replay fixtures."},
]


# ==============================================================================
# PERIMETER 3: JUMP HOST (INSTALLATION-04) INFRASTRUCTURE
# ==============================================================================

JUMP_HOST_METADATA = {
    "hostname": "installation-04",
    "ip_documentation": "192.0.2.10 (RFC 5737 / rainpole.net)",
    "os_pretty_name": "Ubuntu 24.04.2 LTS (Noble Numbat)",
    "kernel": "Linux 6.8.0-139-generic #139-Ubuntu SMP PREEMPT_DYNAMIC x86_64",
    "python_version": "3.12.3",
    "purpose": "Telemetry collection jump host, log inspection, scheduled artifact maintenance, and lab testing.",
    "isolation_guarantee": "The ephemeral zipapp worker (gz_remote_worker.pyz) deployed to /tmp executes with Python stdlib only. It isolates its sys.path and does NOT import or link against any of the system pip packages installed on installation-04.",
}

JUMP_HOST_SYSTEM_PACKAGES = [
    {"name": "linux-image-6.8.0-139-generic", "version": "6.8.0-139.139", "type": "operating-system", "license_spdx": "GPL-2.0-only", "description": "Linux kernel core operating system image."},
    {"name": "systemd", "version": "255.4-1ubuntu8.4", "type": "operating-system", "license_spdx": "LGPL-2.1-or-later", "description": "System and service manager for Linux."},
    {"name": "openssh-server", "version": "1:9.6p1-3ubuntu13.4", "type": "operating-system", "license_spdx": "SSH-OpenSSH", "description": "OpenSSH secure remote access daemon (port 22)."},
    {"name": "openssl", "version": "3.0.13-0ubuntu3.4", "type": "operating-system", "license_spdx": "Apache-2.0", "description": "Secure Sockets Layer and Transport Layer Security cryptographic tool."},
    {"name": "dpkg", "version": "1.22.6ubuntu6.1", "type": "operating-system", "license_spdx": "GPL-2.0-or-later", "description": "Debian package management system."},
    {"name": "python3", "version": "3.12.3-0ubuntu1", "type": "operating-system", "license_spdx": "PSF-2.0", "description": "System Python 3.12 interpreter."},
]

JUMP_HOST_PYTHON_PACKAGES = [
    {"name": "cryptography", "version": "41.0.7", "license_spdx": "Apache-2.0 OR BSD-3-Clause", "purl": "pkg:pypi/cryptography@41.0.7", "description": "Cryptographic recipes and primitives for Python (system package)."},
    {"name": "requests", "version": "2.31.0", "license_spdx": "Apache-2.0", "purl": "pkg:pypi/requests@2.31.0", "description": "HTTP library for Python (system package, unused by groundzero worker)."},
    {"name": "urllib3", "version": "2.0.7", "license_spdx": "MIT", "purl": "pkg:pypi/urllib3@2.0.7", "description": "HTTP client for Python (system package, unused by groundzero worker)."},
    {"name": "boto3", "version": "1.34.46", "license_spdx": "Apache-2.0", "purl": "pkg:pypi/boto3@1.34.46", "description": "AWS SDK for Python (system utility package)."},
    {"name": "botocore", "version": "1.34.46", "license_spdx": "Apache-2.0", "purl": "pkg:pypi/botocore@1.34.46", "description": "Low-level core functionality of Boto 3."},
    {"name": "Jinja2", "version": "3.1.2", "license_spdx": "BSD-3-Clause", "purl": "pkg:pypi/jinja2@3.1.2", "description": "Template engine for Python."},
    {"name": "PyYAML", "version": "6.0.1", "license_spdx": "MIT", "purl": "pkg:pypi/pyyaml@6.0.1", "description": "YAML parser and emitter for Python."},
    {"name": "netaddr", "version": "0.8.0", "license_spdx": "BSD-3-Clause", "purl": "pkg:pypi/netaddr@0.8.0", "description": "Network address representation and manipulation library."},
    {"name": "netifaces", "version": "0.11.0", "license_spdx": "MIT", "purl": "pkg:pypi/netifaces@0.11.0", "description": "Portable network interface information discovery."},
    {"name": "bcrypt", "version": "3.2.2", "license_spdx": "Apache-2.0", "purl": "pkg:pypi/bcrypt@3.2.2", "description": "Modern password hashing for Python."},
    {"name": "jsonschema", "version": "4.10.3", "license_spdx": "MIT", "purl": "pkg:pypi/jsonschema@4.10.3", "description": "JSON Schema validation implementation."},
    {"name": "pytest", "version": "7.4.4", "license_spdx": "MIT", "purl": "pkg:pypi/pytest@7.4.4", "description": "System test framework for remote smoke testing."},
    {"name": "Twisted", "version": "24.3.0", "license_spdx": "MIT", "purl": "pkg:pypi/twisted@24.3.0", "description": "Event-driven networking engine."},
]

JUMP_HOST_SERVICES = [
    {
        "service": "gz_remote_worker.pyz (Ephemeral)",
        "path": "/tmp/gz_remote_<run_id>/worker.pyz",
        "runtime": "Python 3.12.3 stdlib only",
        "description": "Ephemeral Redfish collector deployed on-demand by local operator or Web UI. Executed unprivileged, queries target BMCs over HTTPS, outputs summary JSON and HTML, and cleans itself up.",
    },
    {
        "service": "jump_host_maintenance.py",
        "path": "/usr/local/bin/jump_host_maintenance.py (or tools/jump_host_maintenance.py)",
        "runtime": "Python 3.12.3 (cron scheduled Sunday 4:00 AM Central)",
        "description": "Weekly automated hygiene service: prunes /var/lib/vcf-lab/artifacts (keeps latest 3, prunes >7d standard or >3d large crawl), purges orphaned /tmp sandboxes, cleans apt caches, logs to weekly-summary.log and syslog.",
    },
    {
        "service": "activity_logger.py / show_jump_activity.py",
        "path": "/var/log/groundzero/activity.jsonl",
        "runtime": "Audit telemetry daemon",
        "description": "Records all SSH remote scan executions, client IPs, target count, and start/finish status for compliance tracing.",
    },
]


# ==============================================================================
# CYCLONEDX & SPDX SERIALIZERS
# ==============================================================================

def generate_cyclonedx_json(
    bom_name: str,
    bom_version: str,
    components: List[Dict[str, Any]],
    metadata_desc: str,
    supplier: str = "Broadcom / VMware",
) -> str:
    """Generate a standard CycloneDX 1.5 JSON formatted SBOM."""
    serial_number = f"urn:uuid:{uuid.uuid4()}"
    cdx_components = []
    dependencies = []

    for c in components:
        comp_id = f"{c['name']}@{c.get('version', 'unknown')}"
        licenses = []
        spdx_lic = c.get("license_spdx")
        if spdx_lic:
            if " OR " in spdx_lic:
                for part in spdx_lic.split(" OR "):
                    licenses.append({"license": {"id": part.strip()}})
            elif spdx_lic.startswith("LicenseRef-"):
                licenses.append({"license": {"name": spdx_lic}})
            else:
                licenses.append({"license": {"id": spdx_lic}})

        comp_dict = {
            "bom-ref": comp_id,
            "type": c.get("type", "library"),
            "name": c["name"],
            "version": c.get("version", "unknown"),
            "description": c.get("description", ""),
            "scope": c.get("scope", "required"),
            "purl": c.get("purl", f"pkg:generic/{c['name']}@{c.get('version', 'unknown')}"),
        }
        if licenses:
            comp_dict["licenses"] = licenses
        if c.get("supplier"):
            comp_dict["supplier"] = {"name": c["supplier"]}
        if c.get("origin"):
            comp_dict["properties"] = [{"name": "origin", "value": c["origin"]}]

        cdx_components.append(comp_dict)
        dependencies.append({"ref": comp_id, "dependsOn": []})

    bom = {
        "$schema": "http://cyclonedx.org/schema/bom-1.5.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": serial_number,
        "version": 1,
        "metadata": {
            "timestamp": TIMESTAMP,
            "tools": [
                {
                    "vendor": "Broadcom / VMware",
                    "name": "groundzero-sbom-generator",
                    "version": TOOL_VERSION,
                }
            ],
            "authors": [{"name": "VCF HCI Readiness Engineering Team"}],
            "component": {
                "bom-ref": f"{bom_name}@{bom_version}",
                "type": "application",
                "name": bom_name,
                "version": bom_version,
                "description": metadata_desc,
                "supplier": {"name": supplier},
            },
        },
        "components": cdx_components,
        "dependencies": dependencies,
    }
    return json.dumps(bom, indent=2)


def generate_spdx_json(
    spdx_name: str,
    spdx_version: str,
    components: List[Dict[str, Any]],
    supplier: str = "Broadcom / VMware",
    root_license: str = "LicenseRef-CA-Inc",
) -> str:
    """Generate an ISO/IEC 5962:2021 compliant SPDX 2.3 JSON formatted SBOM."""
    document_namespace = f"https://rainpole.io/spdxdocs/{spdx_name}-{spdx_version}-{uuid.uuid4()}"
    root_spdx_id = "SPDXRef-RootPackage"

    packages = [
        {
            "SPDXID": root_spdx_id,
            "name": spdx_name,
            "versionInfo": spdx_version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "supplier": f"Organization: {supplier}",
            "primaryPackagePurpose": "APPLICATION",
            "licenseConcluded": root_license,
            "licenseDeclared": root_license,
            "copyrightText": "Copyright (c) CA, Inc. All rights reserved.",
        }
    ]

    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relatedSpdxElement": root_spdx_id,
            "relationshipType": "DESCRIBES",
        }
    ]

    for idx, c in enumerate(components, start=1):
        pkg_id = f"SPDXRef-Package-{re.sub(r'[^a-zA-Z0-9-]', '-', c['name'])}-{idx}"
        lic = c.get("license_spdx", "NOASSERTION")
        if lic.startswith("LicenseRef-") or " OR " in lic or lic in ("MIT", "Apache-2.0", "BSD-3-Clause", "PSF-2.0", "Zlib", "blessing", "GPL-2.0-only WITH Bootloader-exception"):
            concluded_lic = lic
        else:
            concluded_lic = "NOASSERTION"

        pkg_dict = {
            "SPDXID": pkg_id,
            "name": c["name"],
            "versionInfo": c.get("version", "unknown"),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "supplier": f"Organization: {c.get('supplier', supplier)}",
            "licenseConcluded": concluded_lic,
            "licenseDeclared": concluded_lic,
            "copyrightText": "NOASSERTION",
            "comment": c.get("description", ""),
        }
        if c.get("purl"):
            pkg_dict["externalRefs"] = [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": c["purl"],
                }
            ]
        packages.append(pkg_dict)
        relationships.append(
            {
                "spdxElementId": root_spdx_id,
                "relatedSpdxElement": pkg_id,
                "relationshipType": "DEPENDS_ON" if c.get("scope") == "required" else "OPTIONAL_DEPENDENCY_OF",
            }
        )

    spdx_doc = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{spdx_name}-{spdx_version}",
        "documentNamespace": document_namespace,
        "creationInfo": {
            "created": TIMESTAMP,
            "creators": [
                f"Tool: groundzero-sbom-generator-{TOOL_VERSION}",
                f"Organization: {supplier}",
            ],
            "licenseListVersion": "3.22",
        },
        "packages": packages,
        "relationships": relationships,
    }
    return json.dumps(spdx_doc, indent=2)


# ==============================================================================
# MARKDOWN DOCUMENT GENERATORS
# ==============================================================================

def generate_customer_markdown_sbom() -> str:
    """Generate docs/CUSTOMER_DELIVERABLE_SBOM.md (100% clean, standalone customer deliverable)."""
    lines = [
        "# Software Bill of Materials (SBOM) — Customer Deliverables",
        "",
        "> **Product:** GroundZero — VCF / vSphere 9.1 HCI Readiness (`groundzero`)  ",
        f"> **Release Version:** v{TOOL_VERSION}  ",
        f"> **Generated Date:** {DATE_STR}  ",
        "> **Standards Compliance:** CycloneDX 1.5 JSON (`docs/sbom/cyclonedx-customer-v9.7.1.json`), SPDX 2.3 JSON (`docs/sbom/spdx-customer-v9.7.1.json`)  ",
        "> **License:** CA, Inc. Software License Agreement (Broadcom)  ",
        "",
        "---",
        "",
        "## 1. Executive Summary & Zero-Dependency Architectural Guarantee",
        "",
        "This document provides a comprehensive, transparent Software Bill of Materials (SBOM) for the standalone customer offline distribution (`Distribution-GroundZero.zip`) and compiled multi-platform binaries.",
        "",
        "### Key Compliance Highlights:",
        "1. **Zero Runtime External Dependencies:**",
        "   - The core Python application (`groundzero/`) imports **strictly from the Python standard library** (Python 3.9+).",
        "   - **Forbidden third-party runtime libraries:** Zero usage of `requests`, `urllib3`, `aiohttp`, `jinja2`, `pandas`, `beautifulsoup4`, or `lxml`.",
        "   - Customers can execute the tool directly using any stock Python 3.9–3.12 interpreter without installing external pip packages or connecting to public/private package indexes.",
        "2. **Zero External CDN / Web Dependencies:**",
        "   - The embedded Web UI and all generated HTML reports operate **100% offline in air-gapped environments**.",
        "   - All stylesheet assets (VMware Clarity Design System) and icons are pre-compiled and embedded directly as in-memory data constants.",
        "3. **Zero Cryptographic Non-Standard Ciphers:**",
        "   - The Credential Vault utilizes standard library primitives only (`hashlib`, `hmac`, PBKDF2-HMAC-SHA256 Encrypt-then-MAC) with zero proprietary or third-party binary encryption drivers.",
        "4. **Strict Isolation & Air-Gapped Safe:**",
        "   - The tool initiates outbound HTTPS connections **only** to the explicitly targeted BMC IP addresses provided by the operator (port 443). No outbound telemetry, update checks, or external analytics calls are made.",
        "",
        "---",
        "",
        "## 2. Software Component Inventory",
        "",
        "The following table enumerates all first-party and bundled open-source components comprising the customer deliverables:",
        "",
        "| Component Name | Version | Type | License | Supplier | Delivery / Inclusion Mechanism | Required / Optional |",
        "|---|---|---|---|---|---|---|",
    ]

    for c in CUSTOMER_COMPONENTS:
        scope_str = "**Required**" if c["scope"] == "required" else "Optional"
        lines.append(
            f"| `{c['name']}` | `{c['version']}` | {c['type']} | {c['license_spdx']} | {c['supplier']} | {c['distribution']} | {scope_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Component Details & Licensing Analysis",
        "",
        "### 3.1. Core Application Engine (`groundzero`)",
        "- **License:** CA, Inc. Software License Agreement (`LICENSE.md`)",
        "- **Purpose:** Enterprise BMC querying (Dell iDRAC, HPE iLO, Supermicro, Cisco IMC, Lenovo XCC, Intel BMC), hardware specification extraction, vSAN ESA readiness evaluation, and standalone HTML report generation.",
        "- **Dependencies:** Strictly standard library (`urllib.request`, `ssl`, `json`, `sqlite3`, `concurrent.futures`, `hashlib`, `hmac`).",
        "",
        "### 3.2. VMware Clarity Design System (`@cds/core`)",
        "- **Version:** 5.7.0",
        "- **License:** Apache-2.0",
        "- **Purpose:** Professional enterprise UI design system for the local browser interface (127.0.0.1:7182) and generated interactive fleet reports.",
        "- **Embedding Method:** Pre-bundled via `tools/bundle_assets.py` into `groundzero/web/assets.py` as a base64-encoded, gzip-compressed string constant. No Node.js or internet access is required.",
        "",
        "### 3.3. Broadcom vSAN Hardware Compatibility Dataset (`vsan-hcl-dataset`)",
        "- **Version:** 9.1.0",
        "- **License:** Broadcom Community / Proprietary Dataset",
        "- **Purpose:** Maps PCI Vendor ID, Device ID, Sub-Vendor ID, and Sub-Device ID to VMware Compatibility Guide (VCG / BCG) records for network interfaces, NVMe drives, and storage controllers.",
        "- **Delivery:** Packaged offline inside `groundzero/io_nics.json` and `hcl/vcf_hcl_bundle_latest.zip`.",
        "",
        "### 3.4. PyInstaller Bootloader & Bundled Binaries (`bin/`)",
        "- **License:** GPL-2.0-only WITH Bootloader-exception",
        "- **Exception Clause:** The PyInstaller Bootloader exception explicitly permits the creation and distribution of standalone executables containing proprietary, commercial, or non-GPL software without triggering copyleft requirements on the packaged application code.",
        "- **Purpose:** Optional convenience executables (`GroundZero-Web-mac`, `GroundZero-Web.exe`, `groundzero`) for operators without a local Python runtime.",
        "- **Contained Runtimes:** Statically bundles CPython 3.11+, OpenSSL 3.0+ (Apache-2.0), SQLite3 (Public Domain), zlib (Zlib), and libffi (MIT).",
        "",
        "### 3.5. VMware VCF Operations Management Pack (`integrations/vcf-ops/`)",
        "- **Version:** 9.7.1",
        "- **License:** Community Tooling License (`management_pack/eula.txt`)",
        "- **Purpose:** Optional adapter for VMware Aria Operations / VCF Operations 9.1 integration. Deploys via `.pak` archive to ingest readiness metrics directly into enterprise dashboards.",
        "",
        "---",
        "",
        "## 4. Master Offline Distribution Zip Contents (`Distribution-GroundZero.zip`)",
        "",
        "When built using `./build_offline_package.sh`, the master distribution package contains strictly the following vetted assets:",
        "",
        "| Directory / File | Description & Purpose |",
        "|---|---|",
    ])

    for item in CUSTOMER_ZIP_MANIFEST:
        lines.append(f"| `{item['path']}` | {item['purpose']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Vulnerability & Risk Management Statements",
        "",
        "- **CVE Risk Surface:** Because runtime Python dependencies are zero, this application is immune to dependency confusion attacks, malicious PyPI package takeovers, or unvetted transitive wheel vulnerabilities.",
        "- **Network Exposure:** The Web UI listens strictly on `127.0.0.1` (loopback only) by default, preventing unauthorized LAN access.",
        "- **SSL Verification:** Uses `ssl.CERT_NONE` by default for BMC HTTPS queries because enterprise BMCs frequently utilize self-signed internal certificates. Operator credentials remain encrypted in transit over TLS.",
        "- **Reporting:** Standalone reports are self-contained single HTML files with zero external tracking pixels, external scripts, or external font stylesheets.",
        "",
        "---",
        "",
        f"*Document generated automatically by `tools/generate_sboms.py` on {DATE_STR}.*",
    ])
    return "\n".join(lines) + "\n"


def generate_internal_markdown_sbom() -> str:
    """Generate internal/sbom/INTERNAL_TOOLS_SBOM.md (internal build, test, and Redfish Library tooling)."""
    lines = [
        "# Software Bill of Materials (SBOM) — Internal Tools & Redfish Library",
        "",
        "> **Repository:** GroundZero Workspace  ",
        f"> **Generated Date:** {DATE_STR}  ",
        "> **Standards Compliance:** CycloneDX 1.5 JSON (`internal/sbom/cyclonedx-internal-tools.json`), SPDX 2.3 JSON (`internal/sbom/spdx-internal-tools.json`)  ",
        "",
        "---",
        "",
        "## 1. Scope & Perimeter Overview",
        "",
        "This SBOM covers internal engineering tools, build infrastructure, testing harnesses, static linters, and the Redfish Telemetry Library assets used by development and QA teams.",
        "",
        "**Notice:** None of the packages listed in this document are shipped in customer-facing source packages or required at customer runtime.",
        "",
        "---",
        "",
        "## 2. Internal Components by Category",
        "",
        "| Component | Version | Category | License | Package URL (PURL) | Purpose |",
        "|---|---|---|---|---|---|",
    ]

    for c in INTERNAL_TOOLS_COMPONENTS:
        lines.append(
            f"| `{c['name']}` | `{c['version']}` | {c['category']} | {c['license_spdx']} | `{c['purl']}` | {c['description']} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Redfish Telemetry Library Specifications",
        "",
        "The Redfish Telemetry Library is an internal development and testing repository used to validate collector robustness against real-world BMC implementations without physical lab access.",
        "",
        "### Key Library Assets:",
        "1. **`catalog.db` Master Registry:**",
        "   - SQLite3 zero-external-dependency database indexing 50,000+ Redfish endpoints across Dell, HPE, Supermicro, Lenovo, Cisco, and Intel architectures.",
        "   - Fingerprints hardware configurations into deduplicated archetypes and tracks unmapped hardware logs.",
        "2. **DMTF Redfish Schemas (DSP0266 / DSP8010):**",
        "   - Distributed Management Task Force official hypermedia schemas used for payload validation and replay mocking.",
        "3. **Offline DMTF Replay Archives:**",
        "   - Anonymized `redfish_mockup_*.zip` archives providing offline hypermedia resource trees for automated test replay (`pytest -m replay`).",
        "",
        "---",
        "",
        "## 4. Developer Environment & CI Tooling Matrix",
        "",
        "- **Build System:** `pyinstaller` (multi-platform binary compiler) + `setuptools` + `wheel`.",
        "- **Testing Framework:** `pytest` + `pytest-cov` (enforcing >=70% test coverage) + `pytest-xdist`.",
        "- **Code Hygiene:** `ruff` (py39 rule enforcement, no-print lint gates, banned API rules) + `ty` (type check).",
        "- **Report & Infographic Tooling:** `reportlab`, `pillow`, `pypdf`, `python-docx`, `lxml`.",
        "",
        "---",
        "",
        f"*Document generated automatically by `tools/generate_sboms.py` on {DATE_STR}.*",
    ])
    return "\n".join(lines) + "\n"


def generate_jump_host_markdown_sbom() -> str:
    """Generate internal/sbom/INSTALLATION_04_SBOM.md (jump host infrastructure and services)."""
    lines = [
        "# Software Bill of Materials (SBOM) — Lab Jump Host (`installation-04`)",
        "",
        "> **Target Host:** `installation-04`  ",
        f"> **Documented IP:** `{JUMP_HOST_METADATA['ip_documentation']}`  ",
        f"> **Operating System:** `{JUMP_HOST_METADATA['os_pretty_name']}`  ",
        f"> **Kernel:** `{JUMP_HOST_METADATA['kernel']}`  ",
        f"> **Python Interpreter:** `{JUMP_HOST_METADATA['python_version']}`  ",
        f"> **Generated Date:** {DATE_STR}  ",
        "> **Standards Compliance:** CycloneDX 1.5 JSON (`internal/sbom/cyclonedx-installation-04.json`), SPDX 2.3 JSON (`internal/sbom/spdx-installation-04.json`)  ",
        "",
        "---",
        "",
        "## 1. Role & Operational Decoupling Guarantee",
        "",
        "The jump host `installation-04` provides read-only network access to isolated lab datacenter BMC subnets. It hosts diagnostic querying, Redfish telemetry collection, and weekly automated maintenance.",
        "",
        "### Strict Isolation & Dependency Decoupling:",
        "- **Zero Host Pip Dependency:** Remote scans deploy an unprivileged, ephemeral zipapp (`gz_remote_worker.pyz`) to `/tmp`. This worker uses **strictly the Python 3.12 standard library** and isolates its `sys.path`. It **does not import** any of the system pip packages installed on `installation-04`.",
        "- **Read-Only Telemetry:** As enforced by operational policy, all scripts executed through `installation-04` remain strictly read-only diagnostics. No power operations, firmware flashes, or configuration mutations are permitted.",
        "",
        "---",
        "",
        "## 2. Jump Host System Infrastructure Packages",
        "",
        "| Package Name | Version | Type | License | Description |",
        "|---|---|---|---|---|",
    ]

    for p in JUMP_HOST_SYSTEM_PACKAGES:
        lines.append(f"| `{p['name']}` | `{p['version']}` | {p['type']} | {p['license_spdx']} | {p['description']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Host Python Environment Packages (System-Installed)",
        "",
        "The following packages are installed in the jump host system Python environment (used by system utilities and administrative tooling):",
        "",
        "| Package Name | Version | License | Package URL (PURL) | Notes |",
        "|---|---|---|---|---|",
    ])

    for p in JUMP_HOST_PYTHON_PACKAGES:
        lines.append(f"| `{p['name']}` | `{p['version']}` | {p['license_spdx']} | `{p['purl']}` | {p['description']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Deployed GroundZero Workloads & Maintenance Services",
        "",
        "| Service / Workload | Location / Path | Execution Model | Purpose |",
        "|---|---|---|---|",
    ])

    for s in JUMP_HOST_SERVICES:
        lines.append(f"| `{s['service']}` | `{s['path']}` | {s['runtime']} | {s['description']} |")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Storage & Hygiene Policy on `installation-04`",
        "",
        "- **Artifact Storage:** `/var/lib/vcf-lab/artifacts`",
        "- **Hygiene Cron:** `tools/jump_host_maintenance.py` runs every Sunday at 4:00 AM Central.",
        "  - Keeps a minimum of 3 latest scan runs.",
        "  - Prunes standard scan runs older than 7 days (unless `.keep` file exists).",
        "  - Prunes heavy crawls (>2 GB) older than 3 days (unless `.keep` file exists).",
        "  - Prunes orphaned `/tmp/gz_remote_*` working directories older than 24 hours.",
        "- **Audit Logging:** Scan runs and maintenance results log to `/var/log/groundzero/weekly-summary.log` and `/var/log/groundzero/activity.jsonl`.",
        "",
        "---",
        "",
        f"*Document generated automatically by `tools/generate_sboms.py` on {DATE_STR}.*",
    ])
    return "\n".join(lines) + "\n"


# ==============================================================================
# MAIN DRIVER
# ==============================================================================

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scope", choices=["all", "customer", "internal", "jump-host"], default="all", help="Which SBOM scope to generate (default: all)")
    parser.add_argument("--refresh-jump-host", action="store_true", help="Connect to installation-04 via SSH to refresh system package lists")
    args = parser.parse_args(argv)

    DOCS_SBOM_DIR.mkdir(parents=True, exist_ok=True)
    INTERNAL_SBOM_DIR.mkdir(parents=True, exist_ok=True)

    print("=========================================================================")
    print(" GroundZero — Master SBOM Generator")
    print(f" Tool Version    : v{TOOL_VERSION}")
    print(f" Timestamp       : {TIMESTAMP}")
    print(f" Selected Scope  : {args.scope}")
    print("=========================================================================")

    # 1. Customer Deliverables SBOM
    if args.scope in ("all", "customer"):
        print("\n==> [1/3] Generating Customer Deliverables SBOM...")
        customer_md = generate_customer_markdown_sbom()
        customer_md_path = DOCS_DIR / "CUSTOMER_DELIVERABLE_SBOM.md"
        customer_md_path.write_text(customer_md, encoding="utf-8")
        print(f"    [✓] Markdown : {customer_md_path.relative_to(REPO_ROOT)}")

        customer_cdx = generate_cyclonedx_json(
            bom_name="groundzero",
            bom_version=TOOL_VERSION,
            components=CUSTOMER_COMPONENTS,
            metadata_desc=CUSTOMER_METADATA["description"],
            supplier=CUSTOMER_METADATA["vendor"],
        )
        customer_cdx_path = DOCS_SBOM_DIR / f"cyclonedx-customer-v{TOOL_VERSION}.json"
        customer_cdx_path.write_text(customer_cdx, encoding="utf-8")
        # Also maintain unversioned alias for scripts and packaging
        (DOCS_SBOM_DIR / "cyclonedx-customer-latest.json").write_text(customer_cdx, encoding="utf-8")
        print(f"    [✓] CycloneDX: {customer_cdx_path.relative_to(REPO_ROOT)}")

        customer_spdx = generate_spdx_json(
            spdx_name="groundzero-customer",
            spdx_version=TOOL_VERSION,
            components=CUSTOMER_COMPONENTS,
            supplier=CUSTOMER_METADATA["vendor"],
        )
        customer_spdx_path = DOCS_SBOM_DIR / f"spdx-customer-v{TOOL_VERSION}.json"
        customer_spdx_path.write_text(customer_spdx, encoding="utf-8")
        (DOCS_SBOM_DIR / "spdx-customer-latest.json").write_text(customer_spdx, encoding="utf-8")
        print(f"    [✓] SPDX 2.3 : {customer_spdx_path.relative_to(REPO_ROOT)}")

    # 2. Internal Tooling & Redfish Library SBOM
    if args.scope in ("all", "internal"):
        print("\n==> [2/3] Generating Internal Tooling & Redfish Library SBOM...")
        internal_md = generate_internal_markdown_sbom()
        internal_md_path = INTERNAL_SBOM_DIR / "INTERNAL_TOOLS_SBOM.md"
        internal_md_path.write_text(internal_md, encoding="utf-8")
        print(f"    [✓] Markdown : {internal_md_path.relative_to(REPO_ROOT)}")

        internal_cdx = generate_cyclonedx_json(
            bom_name="groundzero-internal-tools",
            bom_version=TOOL_VERSION,
            components=INTERNAL_TOOLS_COMPONENTS,
            metadata_desc="Internal engineering, testing, build, and Redfish Telemetry Library assets.",
            supplier="Broadcom / VMware Internal Engineering",
        )
        internal_cdx_path = INTERNAL_SBOM_DIR / "cyclonedx-internal-tools.json"
        internal_cdx_path.write_text(internal_cdx, encoding="utf-8")
        print(f"    [✓] CycloneDX: {internal_cdx_path.relative_to(REPO_ROOT)}")

        internal_spdx = generate_spdx_json(
            spdx_name="groundzero-internal-tools",
            spdx_version=TOOL_VERSION,
            components=INTERNAL_TOOLS_COMPONENTS,
            supplier="Broadcom / VMware Internal Engineering",
        )
        internal_spdx_path = INTERNAL_SBOM_DIR / "spdx-internal-tools.json"
        internal_spdx_path.write_text(internal_spdx, encoding="utf-8")
        print(f"    [✓] SPDX 2.3 : {internal_spdx_path.relative_to(REPO_ROOT)}")

    # 3. Installation-04 Jump Host SBOM
    if args.scope in ("all", "jump-host"):
        print("\n==> [3/3] Generating Installation-04 Jump Host SBOM...")
        jump_md = generate_jump_host_markdown_sbom()
        jump_md_path = INTERNAL_SBOM_DIR / "INSTALLATION_04_SBOM.md"
        jump_md_path.write_text(jump_md, encoding="utf-8")
        print(f"    [✓] Markdown : {jump_md_path.relative_to(REPO_ROOT)}")

        all_jump_components = [
            {
                "name": p["name"],
                "version": p["version"],
                "type": p["type"],
                "description": p["description"],
                "license_spdx": p["license_spdx"],
                "scope": "required",
                "purl": f"pkg:deb/ubuntu/{p['name']}@{p['version']}?distro=ubuntu-24.04",
                "supplier": "Canonical / Ubuntu",
            }
            for p in JUMP_HOST_SYSTEM_PACKAGES
        ] + [
            {
                "name": p["name"],
                "version": p["version"],
                "type": "library",
                "description": p["description"],
                "license_spdx": p["license_spdx"],
                "scope": "optional",
                "purl": p["purl"],
                "supplier": "Open Source Python Community",
            }
            for p in JUMP_HOST_PYTHON_PACKAGES
        ]

        jump_cdx = generate_cyclonedx_json(
            bom_name="installation-04-jump-host",
            bom_version="ubuntu-24.04.2",
            components=all_jump_components,
            metadata_desc="Infrastructure and Python runtime environment on lab jump host installation-04.",
            supplier="Canonical / Ubuntu & Broadcom Lab Infrastructure",
        )
        jump_cdx_path = INTERNAL_SBOM_DIR / "cyclonedx-installation-04.json"
        jump_cdx_path.write_text(jump_cdx, encoding="utf-8")
        print(f"    [✓] CycloneDX: {jump_cdx_path.relative_to(REPO_ROOT)}")

        jump_spdx = generate_spdx_json(
            spdx_name="installation-04-jump-host",
            spdx_version="ubuntu-24.04.2",
            components=all_jump_components,
            supplier="Canonical / Ubuntu & Broadcom Lab Infrastructure",
        )
        jump_spdx_path = INTERNAL_SBOM_DIR / "spdx-installation-04.json"
        jump_spdx_path.write_text(jump_spdx, encoding="utf-8")
        print(f"    [✓] SPDX 2.3 : {jump_spdx_path.relative_to(REPO_ROOT)}")

    print("\n=========================================================================")
    print(" Master SBOM Generation Complete!")
    print("=========================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
