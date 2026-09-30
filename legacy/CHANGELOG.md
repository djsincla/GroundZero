# Changelog

## [GroundZero] – 2026-09-30

### Changed
- Forked from VCF Readiness Assessment Tool v9.7.3 and renamed to **GroundZero**.
- Python package `vcf_hci` → `groundzero`; entry points `vcfr_web.py` / `vcfr_collector.py` → `groundzero_web.py` / `groundzero_collector.py`; CLI `vcf-assess` → `groundzero`.
- Logger name, local state dir (`~/.groundzero`), temp/marker prefixes (`gz_`), and env vars (`GZ_*`) renamed accordingly.
- Entries below this one are the upstream history and keep the original names.

## [9.7.3] – 2026-09-28

### Fixed
- **Cisco VIC CNA Unbound Variable Fix**:
  - Hoisted `fc_link` and `pci_info` extraction up to adapter scope in `vcf_hci/collector/collect_network.py` before iterating `port_jsons`.
  - Resolved `UnboundLocalError: cannot access local variable 'fc_link'` on Cisco UCS VIC CNA multi-function adapters where Fibre Channel storage functions are registered via `NetworkDeviceFunctions` rather than standard port objects.
  - Verified against crawled replay samples (`samples/cisco-c220-m5`).
- **Clean Decoupling of Session Creation and Session Pool Auditing**:
  - Removed `audit_active_sessions()` from inside `create_session()` in `BaseRedfishCollector`, retaining it in `collect()` immediately following session creation.
  - Eliminates extraneous HTTP GET requests during token acquisition and ensures accurate redirect handling and request pooling.

### Added
- **Multi-Lab Fleet Expansion & Address Space Discovery**:
  - Expanded enterprise lab inventory to **556 physical server BMCs** across three distinct environments reachable via a remote jump host:
    - **Normal Lab** (`198.18.1.0/24`): 212 hosts (Dell 14G/15G/16G, Intel Cascade Lake/Skylake, AMD Rome/Milan).
    - **vSAN-PE Lab** (`198.18.2.0/24`): 154 hosts (Dell 16G/17G, AMD Turin, Intel Xeon 6, high-density NVMe).
    - **IOV Lab** (`198.18.3.0/24`): 190 hosts (Multi-OEM: Dell, HPE ProLiant Gen9/10/11, Lenovo ThinkSystem, Cisco UCS C240 M5/M6).
  - Enrolled 64 newly discovered active BMC targets in the IOV subnet that were previously classified as address space gaps.
  - Synchronized consolidated staging inventory to `/etc/vcf-lab/inventory.json` on jump host `installation-04`.
- **Enterprise Multi-OEM BIOS Golden Baseline Engines**:
  - Built and integrated canonical Golden Baseline drift scoring engines for Dell PowerEdge, Cisco UCS, HPE ProLiant, and Lenovo ThinkSystem based on VMware vSphere 9.0 Performance Best Practices.
  - Scores compliance percentages across System Performance Profile, Sub-NUMA Clustering (SNC), PCIe ASPM, Virtualization, Hyper-Threading, UEFI Boot Mode, C-States, Turbo Boost, and SR-IOV.
- **Fleet-Wide Remote Scan & Telemetry Validation**:
  - Executed 32-concurrency remote fleet scan across 536 active physical targets yielding 529 fully analyzed host reports (98.7% success rate, 0 failures in vSAN-PE lab).
  - Automated generation and synchronization of consolidated HTML reports, 5.3MB multi-tab Excel inventory matrix, standardized CSV exports (fleet, drives, NICs, GPUs), and sanitized obfuscated customer packages.
  - Cataloged fleet hardware anomalies and operational readiness blockers:
    - 40 Dell hosts flagged with active uncorrectable memory ECC faults (`MEM0001` / `MEM0701`).
    - 12 Dell hosts flagged with PCIe fatal bus errors (`PCI0001`).
    - 26 multi-OEM hosts blocked for vSAN ESA due to NVMe behind Tri-Mode RAID controllers.
    - 2 hosts blocked for native NVMe pass-through due to active Intel VMD in BIOS.
    - 9 legacy Intel Haswell/Broadwell v3/v4 servers confirmed unsupported for VCF 9.x.
    - 48 Intel Skylake-SP servers validated as supported with required installation override.

## [9.7.2] – 2026-09-27

### Added
- **Dell iDRAC Lifecycle Controller (LC) Job Queue Pre-Flight Audit**:
  - Implemented `oem_job_queue()` hook in `BaseRedfishCollector` and `DellCollector` querying `/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/Jobs` with fallback to `/redfish/v1/JobService/Jobs` and `/redfish/v1/TaskService/Tasks`.
  - Audits queue state for failed tasks (`FAILED`, `EXCEPTION`, `KILLED`), pending reboot jobs (`REBOOTPENDING`, `WAITINGFORREBOOT`), and stale active jobs running/scheduled for > 24 hours.
  - Added pre-flight readiness finding in post-collection enrichment (`Step 12`), raising proactive warnings when stalled or failed LC tasks are detected which could block automated VCF host imaging, BIOS configuration, or reboots.
  - Rendered dedicated job queue health cards, status badges, and itemized collapsible job drawers in HTML Host Reports with RACADM remediation guidance (`jobqueue delete`).
- **PCIe Slot & Link Negotiation Degradation Detector**:
  - Implemented clean-room detection of negotiated PCIe link width and generation speed degradations (e.g. 25GbE NIC running at Gen3 x4 instead of Gen4 x8) that bottleneck vSAN ESA and VCF 9.1 networking.
  - Added robust normalization routines (`normalize_pcie_gen`, `normalize_pcie_type`, `normalize_pcie_width`) supporting DMTF standards, Dell OEM bus formats (`16XOrX16`, `PCIExpressGen3X16`), and integer types across `vcf_hci/collector/pci_utils.py`.
  - Added `oem_pcie_link_status` hook in `BaseRedfishCollector` and overridden in `DellCollector` for deep extraction across `NetworkAdapters`, `Controllers`, and `PCIeDevices`.
  - Built `evaluate_pcie_link_health` compatibility evaluation engine in `vcf_hci/compat/pci.py` and exposed via `VCF9CompatibilityEngine`.
  - Enforced slot capability ceiling checks to avoid false positives when high-lane cards (x16) are seated in lower-lane mechanical slots (x8).
  - Integrated into post-collection enrichment pipeline (`enrich_host_result`), attaching findings and remediation to host warnings (`host_data["pcie_link_warnings"]` and `host_data["warnings"]`).
  - Added visual degradation warning badges and negotiated PCIe link metrics across HTML host reports (`_render_nic_row`, FC HBAs, PCIe slots, and GPU accelerator cards).
- **Optical Transceiver DDM Telemetry & Signal Health Diagnostics**:
  - Implemented Digital Diagnostics Monitoring (DDM) extraction for enterprise optical transceivers (`DellNetworkTransceiver` and `DellNetworkTransceiverPortMetrics`), supporting direct dBm metrics as well as automatic mW-to-dBm conversion via 10 · log10(P).
  - Captures RX Input Power (dBm), TX Output Power (dBm), transceiver temperature (°C), laser bias current (mA), and supply voltage (V).
  - Added optical link health analysis in post-collection enrichment (`evaluate_optical_link_health`), raising proactive warnings for marginal (< -10.0 dBm) and critical (< -13.0 dBm) receive power on Short Range (850nm) fiber optics to detect dirty endfaces and bend radius issues prior to link failure.
  - Rendered DDM metrics, optical signal health badges, and an advisory banner in the Network report section, overview rollup bar, and fleet inventory hover tooltips.
- **BMC Active Session Capacity Auditing & Pre-1.6 Redfish Fallback**:
  - Added defensive session auditing (`audit_active_sessions`) querying BMC session count against the standard 16-session limit, emitting actionable warnings when active sessions exceed 12 (>75% capacity) to prevent HTTP 503 lockouts.
  - Added fallback in Redfish session creation to probe legacy pre-1.6 `POST /redfish/v1/Sessions` on HTTP 404 responses.
  - Hardened `RedfishSessionManager` and `create_session` with relative URI normalization, ensuring session deletion and redirects safely resolve against the target BMC host.
  - Rendered BMC active session health indicators and capacity warning callouts in the report Health section and overview summary rollup.
- **Global Dell OData `$expand=*($levels=1)` Fast-Path Optimization**:
  - Implemented `oem_expandable_collections()` OEM hook in `BaseRedfishCollector` and `DellCollector` returning collection paths supporting first-level member expansion (`FirmwareInventory`, `EthernetInterfaces`, `ThermalSubsystem/Fans`, `Memory`).
  - Added clean-room, zero-dependency `_fetch_expanded_collection(endpoint, levels=1)` in `BaseRedfishCollector` with defensive automatic fallback to unexpanded GET and per-endpoint rejection recording (`_unsupported_expand_endpoints`).
  - Integrated fast-path expand into `collect_firmware_inventory()` with local deduplication of `Installed-*` vs `Current-*` firmware components, eliminating dozens of individual firmware GET round trips.
  - Integrated early probing and pre-expanded cache population for `EthernetInterfaces` across NIC and LLDP neighbor collections.
  - Optimized memory DIMM collection in `collect_memory_details()` to consume pre-expanded DIMM objects directly from cache, bypassing threadpool executor overhead and individual DIMM requests.
  - Slashed overall Redfish HTTP round trips by **60.6% to 76.2%** across Dell PowerEdge 14G, 15G, 16G, and 17G server models with 100% data parity and zero inventory loss.

## [9.7.1] – 2026-09-26

### Added
- **Dell NVMe SMART Telemetry & Health Monitoring**:
  - Integrated `DellNVMeSMARTAttributes` and `DellDriveSMARTAttributes` telemetry parsing into `vcf_hci/collector/oem/dell.py` and `vcf_hci/collector/collect_storage_drive.py`.
  - Collects Total Bytes Written (TBW in TB), Total Bytes Read (TBR in TB), Power-On Hours (POH), composite temperature in Celsius, unsafe shutdowns, available spare percentage, and media/integrity error counters.
  - Added dynamic endurance fallback: automatically calculates endurance as `100.0 - LifeUsedPercent` when `RemainingRatedWriteEndurancePercent` is missing from `DellPhysicalDisk`.
  - Added capacity regex fallback parsing from drive Model and Description strings when Redfish reports `CapacityBytes = 0`.
  - Implemented proactive drive aging alerts in reports and inventory tables when POH is ≥ 30,000 hours or unsafe shutdowns are ≥ 50.
- **Network Transceiver Telemetry & Port Optics Classification**:
  - Added `oem_port_transceiver` hook in `BaseRedfishCollector` with implementations for Dell (`DellNetworkTransceiver`) and Cisco IMC VIC (`VicPort`).
  - Identifies transceiver type (SFP28, QSFP28, SFP+, DirectAttachCopper / DAC), interface type, optical vendor name, part number, and serial number.
  - Embedded optical transceiver badges (`🔌 SFP28 DirectAttachCopper | DELL | PN: 0Y3K24`) in port link status cells across HTML host reports.
  - Added transceiver metadata columns to `generate_nics_csv` and Excel inventory sheets.
  - Added dual-rate combo NDC port speed resolution (e.g. Dell 2P X550 / 2P I350 where ports 1-2 are 10 GbE and ports 3-4 are 1 GbE).
- **GPU Hardware Sensor & Thermal Telemetry**:
  - Added `oem_gpu_sensors` hook querying `DellGPUSensors`.
  - Collects GPU primary temperature, maximum operating temperature, slowdown threshold, shutdown temperature, and power brake status (Released vs Engaged).
  - Displays real-time thermal telemetry and power brake indicators in PCIe and GPU accelerator cards in HTML reports.
  - Strictly excluded Mellanox and NVIDIA ConnectX DPUs/NICs from GPU compute tables.
- **Persistent Boot Configuration & One-Time Override Telemetry**:
  - Discovers persistent UEFI boot targets and active one-time boot override status (`boot_override`).
  - Implemented fallback resolution to persistent `BootOptions` when `BootSourceOverrideTarget` is `None` or empty.
  - Added interactive `Boot Configuration & Device Order` accordion table in BIOS section of host report, displaying boot option IDs, device names, UEFI device paths, and active override state.
- **Advanced AMD EPYC BIOS & RAS Tuning Telemetry**:
  - Added AMD Zen 5 AVX-512 full-width 512-bit vector pipeline rules (`amdcpuavx512`).
  - Added AMD NUMA Nodes per Socket (`numanodespersocket`: NPS4, NPS2, NPS1) with workload tuning guidance.
  - Added AMD Infinity Fabric (xGMI) link speed detection (`amdmaxxgmispeed`: 32 GT/s vs 28 GT/s).
  - Added Enhanced REP MOVSB/STOSB primitives (`cpufeatureerms`).
  - Added CXL memory interleave modes (`currentcxlmemoryinterleavemode`).
  - Added AMD SEV-SNP confidential computing ASID reservation (`cpuminsevasid`).
  - Added BIOS Security Freeze Lock POST protection (`securityfreezelock`).
  - Added modern NVMe-oF over TCP boot support (`nvmeofendis`).
  - Added dedicated AMD EPYC & High-Core NUMA Optimization callout card in CPU architecture tab.
- **Credential Vault & Remote Jump Host Management Enhancements**:
  - Added CLI commands to edit jump hosts in-place without wiping stored secrets: `edit`, `set-subnets`, `add-subnet`, and `remove-subnet`.
  - Added Web UI Jump Host Subnets Modal: inspect, remove, and add CIDR routing subnets directly from table rows with immediate vault persistence.
  - Added Web UI Jump Host in-place configuration editing with secrets preservation banner.
  - Added multi-subnet support with comma, space, and semicolon parsing.
- **Hardware Archetype-Based Sample Ingestion**:
  - Added `--archetypes` flag in `tools/anonymize_captured_mockups.py` grouping fleet scans by model + CPU family + drive topology + GPU count and ingesting the single richest capture per archetype.
  - Added `--output-base` support for targeting custom sample directories.
- **Test Suite Expansion**:
  - Added `tests/test_oem_telemetry_enrichment.py` covering transceiver parsing, SMART attribute extraction, GPU sensor telemetry, persistent boot resolution, and advanced BIOS knobs.

### Changed
- **Export Robustness & Encoding Hardening**:
  - Hardened `csv_export.py` and `excel_export.py` with `errors="replace"` and safe type coercions (`_safe_int`, `_safe_float`).
  - Added NVMe SMART telemetry columns (`TBW Written (TB)`, `Power-On Hours`, `Temperature (°C)`, `Unsafe Shutdowns`) to Drives CSV export.

### Fixed
- **NVMe SMART Health Table Assertion Alignment**:
  - Aligned unit test assertions in `tests/test_host_report.py` with formatted TBW display strings (`W: 45.2 TB`).
- **Mellanox/NVIDIA GPU Accelerator Classification**:
  - Hardened GPU classification filter to ignore Mellanox NICs and SmartNIC DPUs.

## [9.7.0] – 2026-09-24

### Added
- **Ephemeral Remote Scans via Linux Jump Hosts (Experimental)**:
  - Added zero-dependency `.pyz` zipapp bundling (`vcf_hci/zipapp_builder.py`) and memory-only credential ingestion via stdin (`--creds-stdin`) without writing secrets to disk or exposing them in CLI process tables.
  - Implemented secure ephemeral remote execution engine (`vcf_hci/remote/executor.py`, `vcf_hci/remote/guardrails.py`, `vcf_hci/remote/orchestrator.py`) with strict sandbox path validation (`^(/private)?/tmp/vcfr_remote_[a-f0-9]{8,16}$`), cryptographic markers (`.vcfr_marker`), PID locking, POSIX signal traps (`trap 'cleanup' EXIT INT TERM HUP`), and streaming tar artifact retrieval.
  - Extended Encrypted Credential Vault (`vcf_hci/vault/store.py`, `vcf_hci/vault/jump_hosts.py`, `vcf_hci/vault/jump_cli.py`) with encrypted jump host connection profiles (host, port, user, SSH keys, passwords, CIDR subnet routing tables, and operator notes).
  - Added Web UI remote execution support (`vcf_hci/web/jump_api.py`, `vcf_hci/web/remote_scan.py`, `vcf_hci/web/js/jump_ui.py`) with Execution Target toggle ("Local Workstation" vs "Remote Jump Host (Experimental)") and live SSE progress streaming to browser.
  - Added standalone remote scanner runner CLI (`tools/run_remote.py`) and target network prober (`tools/probe_jump_targets.py`).
  - Added comprehensive user documentation in `docs/REMOTE_JUMP_HOST_GUIDE.md`.
- **Dell 17G PowerEdge Architecture & Advanced BIOS Telemetry**:
  - Added full Dell 17G server family support (including AMD 5th Gen EPYC Turin / PowerEdge R7725 and Intel Xeon 6).
  - Implemented vendor-gated and architecture-gated BIOS rule evaluation in `vcf_hci/bios/power_modes.py` and `vcf_hci/bios/ras_modes.py` to prevent cross-OEM and cross-CPU false positives.
  - Added detection and tuning guidance for AMD Performance Determinism, CCX as NUMA Domain, Data Fabric C-States, Data Fabric P-State Optimizer, Processor x2APIC Mode (>255 cores), PCIe ASPM, Post Package Repair on UCE (PPR), correctable ECC SMI logging, memory boot training, CXL memory mode, and AMD Transparent SME / SME.
  - Added Dell 17G PCIe extender slot mappings and firmware inventory normalization in `vcf_hci/collector/oem/dell.py` and `vcf_hci/security/dell.py`.
- **Multi-Host Fleet Ingestion (`tools/anonymize_captured_mockups.py`)**:
  - Auto-discovers and pairs per-host telemetry across fleet scans (`vcf_summary_<ip>.json`, `endpoints_manifest_<ip>.json`, `actions_manifest_<ip>.json`, and `redfish_mockup_<ip>.zip`).
  - Implemented multi-model grouping and hardware richness scoring (evaluating mockup archives, manifests, GPUs, drive/NIC counts, BIOS recency, and thermal health) to automatically select the richest capture per server model.
  - Added CLI ingestion flags: `--distinct-models` (default), `--all-hosts` (individual directories per host), and `--host-ip` (targeted host filtering).
- **Dell PowerEdge R650 & R7725 Sample Fixtures**:
  - Ingested Dell PowerEdge R650 (dual Intel Xeon Gold 6330, BOSS-S2, Broadcom BCM57504S 25GbE, Intel P5500/P5600 NVMe, NVIDIA Tesla T4 GPU accelerator) and Dell PowerEdge R7725 (dual AMD EPYC 9655 96-core Turin, 1.5TB DDR5-6000, 100GbE / 25GbE dual-port NICs, 10x 3.84TB NVMe SSDs).
  - Registered samples in `tests/test_replay_crawled_samples.py` and added `tests/test_replay_dell_17g.py`.
- **Fleet Power Capping & Health Reporting**:
  - Added fleet-level power capping metrics, thermal headroom evaluation, and BIOS security status cards across host and fleet dashboards.

### Changed
- **VCF Operations Management Pack Artifact Naming & Status**:
  - Labeled the management pack as Experimental / Tech Preview in manifests, localization strings, and user/architecture guides.
  - Updated default builder archive output to `dist/<AdapterKind>_<VERSION>_EXPERIMENTAL.pak` (e.g. `VcfReadinessAdapter_9.7.0_EXPERIMENTAL.pak`) with unversioned alias `VcfReadinessAdapter_EXPERIMENTAL.pak`.
  - Updated offline package staging scripts and artifact cleaners to discover and retain experimental `.pak` archives.

### Fixed
- **ConnectX-7 / Mellanox GPU Misclassification (`vcf_hci/collector/collect_gpu.py`)**:
  - Excluded Mellanox/NVIDIA network controllers, Ethernet adapters, and InfiniBand HCAs (PCI vendor `15b3`, device class `NETWORKCONTROLLER`, and keywords `CONNECTX`, `BLUEFIELD`, `ETHERNET`, `NIC`) from GPU accelerator classification.
  - Added unit test coverage in `tests/test_embedded_pcie.py` ensuring Mellanox NICs are ignored while NVIDIA GPU compute/vGPU cards remain properly classified.
- **BMC Security Test Assertions (`tests/test_bmc_security_fixtures.py`, `tests/test_bmc_security_replay.py`)**:
  - Synchronized expected pass and unknown control counts with canonical 84-control security evaluator.

## [9.6.3] – 2026-09-22

### Added / Changed
- Skylake CPU handling: update Skylake-SP evaluation to Supported (Override Required) with Broadcom KB 428874 guidance across reports, inventory, and management pack.

## [9.6.2] – 2026-09-22

### Added
- **Scan Deliverables Plain-Text Readme Index (`vcf_hci/report/readme.py`, `tests/test_readme_export.py`)**:
  - Implemented dynamic, stdlib-only `README.txt` generation across all scan output folders, fleet drops, and obfuscated archives.
  - Dynamically inspects present files (HTML dashboards, Excel workbooks, CSV inventories, raw JSON, and logs) to provide tailored viewer instructions, privacy policy explanations, and artifact navigation.

### Fixed & Hardened
- **Obfuscated Combined Report Client-Side Scrubbing**:
  - Resolved residual hostname leaks in `#host-picker-select` option labels and inner iframe `srcdoc`/`data-srcdoc` titles within offline-cloned combined fleet reports.
- **Obfuscated Zip Archive Packaging**:
  - Fixed parameter signature and dictionary vs list dispatch handling for `create_obfuscated_scan_zip_archive()`.
  - Honored `--no-excel` / `--no-csv` generation flags during zip packaging to prevent unexpected artifact re-generation.
- **Web API Endpoint Robustness**:
  - Fixed mock patching in HCL refresh unit tests and ensured safe handling in Web API HCL refresh and zip export endpoints.

## [9.6.1] – 2026-09-22

### Added
- **Zero-Dependency IPMI Probe (`vcf_hci/security/ipmi_probe.py`, `tests/test_ipmi_probe.py`)**:
  - Implemented stdlib-only network socket IPMI Get Channel Authentication Capabilities probe to evaluate remote BMC cipher suites, anonymous logins, and protocol exposure without external tools (`ipmitool` or third-party libraries).
  - Integrated directly into the 84-control hardware security audit subsystem, providing non-invasive compliance verification.
- **IO NICs HCL Catalog Synchronization (`vcf_hci/hcl/io_nics.json`, `tools/sync_io_hcl.py`, `tests/test_io_nics_catalog.py`)**:
  - Added centralized JSON catalog of certified IO network adapters cross-referenced with Broadcom Compatibility Guide (BCG) and VMware HCL database.
  - Added `tools/sync_io_hcl.py` utility for automated extraction and validation of PCI vendor/device/subvendor/subdevice tuples.

### Changed & Refactored
- **Modular Report & Web UI Architecture**:
  - **Fleet Inventory Panel Modularization (`vcf_hci/report/fleet/inventory/`)**: Decomposed monolithic `inventory_panel.py` into focused sub-modules (`table_header.py`, `table_pager.py`, `table_rows.py`, `filters.py`, `export.py`, etc.) to eliminate context drag and streamline rendering logic.
  - **Web UI Client Scripts (`vcf_hci/web/js/`)**: Modularized `app_js.py` into structured domain modules (`state.js`, `vault.js`, `fleet.js`, `scan.js`, `ui.js`, `components.js`) with deterministic bundling and fallback compatibility.
- **PCI Device Matching & BCG Link Precision (`vcf_hci/bcg_links.py`, `vcf_hci/collector/pci_utils.py`)**:
  - Enhanced PCI quad matching logic for multi-port converged network adapters and NVMe controllers.
  - Improved BCG link generation robustness when handling partial or legacy Redfish PCIe device schemas.
- **Collector & Telemetry Hardening**:
  - Hardened asynchronous collector helpers (`vcf_hci/collector/async_helpers.py`, `vcf_hci/collector/base.py`) with enhanced error isolation and connection pooling.
  - Dell iDRAC9 telemetry parser adjustments for resilient collection during heavy load (`vcf_hci/collector/oem/dell.py`).
  - Improved system scan throttling, memory reclamation, and worker dispatch safety (`vcf_hci/system_throttle.py`, `vcf_hci/web/scan_worker.py`).
- **Reporting & Export Precision**:
  - Refined Excel inventory export (`vcf_hci/report/excel_export.py`) with support for new PCI device metadata and firmware versions.
  - Updated BIOS security and CPU overview sections in standalone host reports (`vcf_hci/report/sections/bios_security.py`, `vcf_hci/report/sections/cpu.py`).

## [9.6.0] – 2026-09-21

### Added
- **Fleet Hub Scale & Multi-Scan Library Assemble (`vcf_hci/fleet_library.py`, `vcf_hci/report/fleet/combined.py`, `vcf_hci/report/inventory_tables.py`, `vcf_hci/web/fleet_api.py`)**:
  - **No 256-Host Cliff & Adaptive Embed Modes**:
    - Eliminated the hard 256-host ceiling (`COMBINED_HTML_MAX_HOSTS = 4096` soft limit) that previously dropped combined report generation.
    - Fleets &le; 64 hosts: Generates an `inline` standalone HTML file with lazy `data-srcdoc` attributes (hidden host iframes are not parsed at load time, conserving browser memory) and embedded Excel workbook.
    - Fleets &gt; 64 hosts: Automatically transitions to `sidecar` mode. Sibling reports are loaded from `reports/` via dynamic `data-src` iframes with an LRU cache capping concurrent active iframes to 3. Host navigation replaces static tab buttons with a searchable, filterable host picker dropdown. Sibling `.xlsx` file links replace Base64 embedding.
    - Capped statically rendered DOM rows: For fleets &gt; 500 hosts, initial HTML render caps Summary and Detailed Inventory sub-tables to 500 rows, guaranteeing sub-second browser paint, while the full fleet dataset is preserved in the compact `#fleet-inv-data` JSON island.
    - 3,000-host synthetic scale proof: Generates a consolidated 3,000-host Fleet Hub HTML report in ~1.3 seconds at 6.10 MB, well under the 8.0 MB budget.
  - **Compact JSON Island & Table Pagination**:
    - Replaced full Redfish trees in the DOM with `#fleet-inv-data` (`build_compact_fleet_inventory()`), containing minimal decision rows, drives, NICs, and health summaries with full PII masking when `--obfuscate` is active.
    - Client-side pagination (`initFleetTablePager`) with 25 / 50 / 100 / All controls (capped at 500 rows with a visible notice).
  - **Multi-Scan Fleet Library & Universal Drop Ingest (`fleet_library.py`)**:
    - Universal Ingest Layout: Standardized scan output folders and zip archives with `MANIFEST.json` containing execution metadata (`tool_version`, `scanned_at`, `host_count`, `collector_id`, `site`, `scan_profile`, `obfuscated`). Zero credentials or secrets in manifests.
    - Remote Worker Drops: Enables remote workers, jump boxes, or scheduled cron runners to drop timestamped scan folders/zips into a central library path (default `~/Desktop/VCF-Scans`) or push via HTTP without requiring direct central-to-BMC connectivity or per-device proxy daemons.
    - Multi-Scan Assembly & Deduplication (`assemble_fleet()`): Crawls multiple scan directories/zips, deduplicates hosts using a deterministic key hierarchy (Redfish System UUID &rarr; Serial + Model &rarr; BMC IP &rarr; Hostname; newest `scanned_at` wins), and retains provenance metadata (`source_scan`, `site`, `collector_id`, `previous_scan_ids`).
    - CLI Integration: `--from-summary <path>` transparently detects single summary files vs. multi-scan library directories; added `--site <name>` tag and `--assemble-only` flag to assemble fleet artifacts without re-rendering individual host reports.
  - **Web UI Fleet Library & Scale Enhancements (`web/fleet_api.py`, `app_html.py`, `app_js.py`)**:
    - "Open Fleet Library" modal: Allows operators to point to a library folder, inspect discovered scans (with host counts, dates, and sites), select scans to assemble, and apply default site tags.
    - Paginated Fleet Index API: Server-side `/api/fleet/index` supporting offset, limit, search text, site/vendor/verdict filters, and facet aggregations.
    - Lazy Host HTML Rendering: Web server lazily renders single-host reports on first open (`_serve_report`) and caches them to disk; added `/api/fleet/prerender` endpoint and UI button to pre-bake all reports when offline portability is required.
    - Ingest Endpoints: Added `POST /api/fleet/ingest` (and `/api/v1/fleet/ingest` alias) to ingest uploaded scan zip archives into the library folder with optional immediate assembly.
    - Memory Management: In-memory `_state["results"]` is trimmed to empty list for fleets &gt; 500 hosts, holding only the lightweight compact index (`_state["fleet_index"]`, ~3–8 MB for 3,000 hosts) in RAM.
- **Optional Encrypted Local Credential Vault (off by default)**:
  - New stdlib-only `vcf_hci/vault/` package storing per-host (`exact`), per-subnet (`cidr`, longest prefix wins) and `default` BMC credentials in a passphrase-encrypted file at `~/.vcf-readiness/credentials.vault` (`0600`, atomic writes, Windows `icacls` owner-only ACL). Nothing is created, read, or used unless the operator opts in.
  - Cryptography (`vault/crypto.py`, ~120 auditable lines): PBKDF2-HMAC-SHA256 key derivation (600,000 iterations, 16-byte random salt), HMAC-derived sub-keys, HMAC-SHA256 counter-mode keystream, and HMAC-SHA256 Encrypt-then-MAC with the canonical header bound as associated data and constant-time verification. The Python standard library has no AES; a pure-Python AES was deliberately not written and the construction is not described as AES anywhere.
  - Management CLI `python -m vcf_hci.vault` (`init`, `add`, `import-csv`, `list`, `remove`, `resolve`, `change-passphrase`, `template`). Passphrases and passwords are read via `getpass` or a named environment variable — never from `argv`. Listings never print passwords.
  - Collector CLI flags `--vault [PATH]` and `--vault-passphrase-env VAR`: resolves a `Dict[ip -> (user, pass)]` for the target list, prints a coverage summary, treats `--username`/`--password-env`/`REDFISH_PASSWORD` as an optional fallback for unmatched targets, and locks the vault when the scan ends. Without `--vault` the CLI is unchanged.
  - Web UI *Encrypted Credential Vault* card (collapsed by default): create / unlock / lock, entry table, single-entry add, **CSV import by file or paste** (with *skip invalid rows* and *replace all*), template download, and a per-scan *Use encrypted credential vault* checkbox that is disabled until unlocked and never pre-selected. Coverage preview shows exact / CIDR / default matches and unmatched hosts.
  - Web API `/api/vault/{status,create,unlock,lock,entries,remove,import-csv,coverage}` and `use_vault` on `POST /api/scan`: credentials are resolved server-side so the browser never receives them; all endpoints require the same-origin check, return `403` under `--allow-remote`, `423` when locked, `401` (with a 0.5 s brake) on a wrong passphrase; the single in-memory vault (`web/vault_session.py`) auto-locks after 60 minutes idle and on shutdown.
  - Documentation: new [Credential Vault Guide](docs/CREDENTIAL_VAULT.md) (bundled into the Web UI help), Security Architecture whitepaper §3.3 (threat model + exact construction), §7 item 7, §10 checklist row; README, INSTALL, `00_HOWTOLAUNCH.TXT`, ARCHITECTURE, and package READMEs updated.
  - Tests: `test_vault_crypto.py`, `test_vault_store.py`, `test_vault_csv.py`, `test_vault_cli.py`, `test_web_vault_api.py`, plus `TestCLIVault` in `test_cli.py`.

### Changed & Fixed
- `00_HOWTOLAUNCH.TXT` example scan command no longer shows a non-existent `-p` password flag; it now uses `--password-env`.

## [9.5.0] – 2026-09-17

### Added
- **Multi-Vendor Enterprise Server Adapters (Quanta Cloud Technology & Gigabyte Technology)**:
  - Added dedicated `QuantaCollector` and `GigabyteCollector` supporting Quanta / QCT and GIGABYTE enterprise servers with `/Systems/Self`, `/Chassis/Self`, and `/Managers/Self` fastpath root discovery (`oem_fastpath_roots`), SimpleStorage fallback routing, and static honest BMC license badges.
  - Implemented multi-key OEM drive telemetry parsing: `Oem.Quanta_RackScale` (with `Oem.Quanta` / `Oem.QCT` backward-compatibility aliases) and `Oem.GBT` (extracting drive `SlotNumber` alongside `Oem.Gigabyte` aliases).
  - Added generic BMC CPU placeholder normalization (`_normalize_cpu_summary_model`) mapping `"Available for assignment"`, `"Not Specified"`, and similar BMC strings to `"Unknown"` when leaf processor queries are unavailable.
  - Integrated Quanta AST2500 and GIGABYTE AMI MegaRAC BMC firmware baselines, Spectre/Meltdown side-channel security advisories, and official SEL reference guide documentation into `constants.py` and `sel_links.py`.
  - Added public class exports in `vcf_hci/collector/` and `vcf_hci/collector/oem/__init__.py`, with expanded zero-network replay and unit test coverage in `test_replay_quanta.py`, `test_replay_gigabyte.py`, and `test_replay_crawled_samples.py`.
- **Enterprise BMC Hardware Security Audit & Federal Guidelines Alignment**:
  - Aligned the 84-control out-of-band BMC security audit engine with the CISA and NSA Joint Cybersecurity Information Sheet (*Harden Baseboard Management Controllers*).
  - Documented explicit cross-walk mapping for all 8 federal CSI recommendations across credential protection, management VLAN isolation, protocol hardening, firmware integrity, and silicon root of trust verification.
  - Expanded reference links to authoritative vendor security guides (Dell iDRAC9, HPE iLO 5/6, Lenovo XCC, Cisco IMC, Supermicro BMC, and Intel Server Systems).
- **Fleet Decision Matrix & Host Inventory Telemetry Enhancements**:
  - Added Host OS detection and End-of-Life (EOL) timeline reporting to the Detailed Inventory Hosts pane and fleet-wide decision matrices.
  - Added BMC license status and expiration tracking across Dell iDRAC and HPE iLO platforms to highlight expired or evaluation licenses before repurposing.
  - Improved BIOS CPU power governor and memory RAS profile selection for Dell and HPE enterprise server platforms.

### Changed & Fixed
- **Canonical Multi-Generation Dell PowerEdge EEMS & SEL Link Resolution**:
  - Re-architected Dell PowerEdge System Event Log (SEL) and Error and Event Messages (EEMs) reference guide integration to use the canonical multi-generation reference architecture (`poweredge-r740xd/error_event_message_guide_c/`).
  - Enriched `DELL_EEMS_CATEGORY_GUIDS` with verified DITA chapter GUIDs for 20+ hardware categories (`SEC`, `PSU`, `RDU`, `PDR`, `HWC`, `MEM`, `PST`, `BOOT`, `CTL`, `PCI`, `TMP`, `TMPS`, `VLT`, `OSE`, `CUMP`, `FLDC`, `NINT`, `NNOD`, `NVCH`, `SEL`, `SRV`).
  - Added safe fallback routing to the Master Reference Guide Root Index for unindexed or unknown event prefixes, preventing "Data is not available for the Topic" errors on Dell's documentation platform.
  - Resolved raw IPMI hex sensor codes for memory, PCI, and temperature to their verified topic chapters.
- **Broadcom Compatibility Guide (BCG) Deep-Linking Engine**:
  - Expanded deep-link generation across server platforms, processor families, storage controllers, NVMe/SAS drives, and I/O controllers to accelerate VMware Cloud Foundation and vSAN ESA compatibility validation.

## [9.4.0] – 2026-09-16

### Added
- **Redfish Hypermedia Crawler, Write Action Cataloger & OEM Discovery Preset (`vcf_hci/collector/crawler.py`, `vcf_hci/collector/base.py`, `vcf_hci/scan.py`, `vcf_hci/cli.py`, `vcf_hci/web/`, `tools/crawl_oem_host.py`, `tools/anonymize_captured_mockups.py`)**:
  - **Comprehensive Hypermedia Crawler Engine (`crawler.py`)**: Pure Python standard library engine exploring the complete Redfish resource hierarchy via safe read-only GET traversal, cycle detection, depth bounds, request budgeting, and cache pre-seeding. Discovers unmapped and OEM-proprietary URIs without modifying server configuration.
  - **Redfish Write/Action Cataloger (`extract_resource_actions()`, `categorize_action()`)**: Catalogs non-GET action endpoints (HTTP POST targets, allowable parameter values, and staged `@Redfish.Settings` modifications) across 11 functional domains (`SystemPower`, `BIOSConfig`, `StorageConfig`, `FirmwareUpdate`, `LogManagement`, `ConfigurationImportExport`, `Diagnostics`, `SecurityAndAccounts`, `VirtualMedia`, `Telemetry`, `OEM`, `PendingSettings`) without executing them.
  - **Manifest & Mockup Export**: Exports structured `endpoints_manifest.json`, `endpoints_manifest.csv`, `actions_manifest.json`, `actions_manifest.csv`, and DMTF-compliant mockup ZIP archives (`redfish_mockup_<HOST>.zip`) embedding all discovered endpoints and actions.
  - **CLI `--oem` & `--crawl` Presets (`cli.py`, `scan.py`)**: CLI flags activating optimal deep-crawl discovery: hypermedia crawling, complete raw payload retention, full readiness profile, partial scan tolerance, and 15-minute host timeouts.
  - **Web UI OEM Import Mode (`web/server.py`, `web/app_html.py`, `web/api_mixin.py`, `web/scan_worker.py`)**: Dedicated `--oem`/`--crawl` server flag displaying a prominent `[🔬 OEM Import Mode]` header badge, deep crawl toggle with empirical time warnings, and automated session parameter restoration.
  - **Multi-Model Anonymized Mockup Library (`samples/`, `tools/anonymize_captured_mockups.py`, `tests/test_replay_crawled_samples.py`)**: Added `tools/anonymize_captured_mockups.py` converting live fleet crawl artifacts into 100% PII-free sample fixtures conforming to repository data hygiene rules. Added 4 new diverse hardware architectures to `samples/`: Dell PowerEdge R670 (17G Intel Xeon 6), Dell PowerEdge R7525 (AMD EPYC 7002/7003 2-socket), Dell PowerEdge R740xd (14G Intel Cascade Lake 24-drive NVMe storage array), and HPE ProLiant DL360 Gen10 (iLO 5), validated with zero-network replay tests.
- **Redfish Collector Resilience Hardening & Schema Modernization (`vcf_hci/collector/`, `vcf_hci/tls_utils.py`, `vcf_hci/report/`)**:
  - **Storage Subsystem Defensive Parsing & Redfish v1.9+ Controllers (`collect_storage.py`, `fleet/tiles.py`)**: Guarded storage and volume capacity calculations and fleet aggregations against `null` and non-numeric values; added support for inline `Controllers` arrays and sub-collection references alongside legacy `StorageControllers`; handled controller model and firmware extraction with fallback naming when `Name` is omitted.
  - **HTTP Transport, Transient Retries & Session 401 Recovery (`base.py`, `tls_utils.py`)**: Separated connect timeout (5.0s) from socket read timeout (15.0s) in `StdlibHTTPConnectionPool` to eliminate hangs on unreachable BMCs; automated retries for transient HTTP 500, 502, 503, and 504 server errors on GET; transparent recovery on mid-scan HTTP 401 session token expiration with fallback to Basic Auth; immediate bypass of dummy placeholder URIs (`/empty`, `none`, `null`).
  - **OEM Error Resilience, SYS518 & Message Normalization (`discovery.py`, `oem/dell.py`, `oem/hpe.py`, `base.py`)**: Normalized `@Message.ExtendedInfo` across all BMCs (safely handling single dicts and lists without `AttributeError`); automated retry for Dell iDRAC error `SYS518` ("data sources are unavailable"); prevented transient 404s on Dell hardware from permanently blacklisting endpoints; enabled OEM retry hooks on HTTP 400 and 503 error payloads; added fallback to `Links.ManagedBy` when `/Managers` collection is omitted.
  - **Network Topology & LLDP Receive v1.12.0 Enrichment (`collect_network.py`, `switch_topology.py`, `switch_matrix.py`, `components.py`)**: Ingested Redfish Port Schema v1.12.0 LLDP receive fields (`ManagementVlanId`, `ManagementAddressIPv6`, `ManagementAddressMAC`, `SystemCapabilities`); sanitized MAC addresses (filtering empty strings and dummy all-zero addresses); displayed switch VLAN ID and management IPv6 in switch topology cards and fleet switch matrix tables.
  - **PCIeFunction Schema & Multi-Function BDF Mapping (`pci_utils.py`, `collect_gpu.py`, `sections/pcie_gpu.py`)**: Added `extract_pcie_functions` extracting FunctionId, DeviceClass, FunctionType, and BDF address while filtering placeholder `/empty` URIs; exposed multi-function badges and function counts in PCIe inventory tables.
  - **Configurable TLS Minimum Version & Legacy Ciphers (`tls_utils.py`, `base.py`, `scan.py`, `cli.py`)**: Added `--legacy-tls` and `--tls-min-version` CLI arguments allowing older BMCs (Dell 13G iDRAC 8, Supermicro X10) requiring TLS 1.0/1.1 or older ciphers (`DEFAULT:@SECLEVEL=1`) to be assessed without OpenSSL 3 handshake aborts.
- **Multi-Vendor System Event Log (SEL / IML) Deep-Linking & Offline Mappings (`vcf_hci/report/sel_links.py`, `vcf_hci/report/components.py`, `vcf_hci/report/fleet/inventory_panel.py`)**:
  - **HPE ProLiant IML Direct Deep Linking**: Decoded HPE Redfish IML message convention where event IDs are formatted as `<class_decimal>.<code_decimal>` (e.g. `19.22` for storage predictive failure, `2.35` for fan redundancy, `10.5920` for SMART drive replacement, `51.7` for backplane management, `50.1122` for uncorrectable memory threshold). Implemented `resolve_hpe_event_info` converting decimal and hex class/code entries directly into official HPE Gen12 IML Troubleshooting Guide URLs (`https://support.hpe.com/hpesc/public/docDisplay?docId=ilogen12-msg-en_us&page=class0x{c:04x}code0x{code:04x}-gen12.html`) with enriched display badges.
  - **Cisco UCS IMC Faults 11-Chapter Mapping Table**: Built comprehensive offline catalog `CISCO_FAULT_TO_CHAPTER_MAP` and `CISCO_PREFIX_TO_CHAPTER` mapping all 114 `F\d{4}` fault codes (e.g. `F0409`, `F0462`, `F0510`, `F0744`, `F1008`, `F1744`), 116 named `flt*` symbols (`fltEquipmentFanDegraded`, `fltBiosUnitFD0FailedSecurityVerification`, etc.), and component prefixes directly to their corresponding chapters in the *Cisco UCS Integrated Management Controller Faults Reference Guide*.
  - **Expanded Dell PowerEdge EEMS & IPMI Hex Mapping**: Expanded `DELL_HEX_TO_EEMS_MAP` to cover all 76 distinct raw IPMI hex codes observed across multi-host customer scans (including CPU machine check `07a60140`, memory self-healing `07a3c001`/`07a7c140`, multi-bit ECC `6fa1c001`, PCIe fatal bus errors `6fa91800`–`6fac283c`, BIOS halting `6f0fd0ff`/`fd0ff`, cooling threshold `01520004`, and dynamic drive bay removal `efa00100`–`efa0020e` -> `PDR1016`). Added explicit `TST` test alert category GUID mapping (`guid-c5b145df-c44d-45ee-a532-eba04e646874`) and full 3–4 digit EEMS code recognition (`TST100`).
  - **Multi-Vendor Clickable SEL Rows in Single-Host & Fleet Inventory Panels**: Enabled direct clickable navigation on Message ID cells and alarm descriptions across Dell, HPE, and Cisco in both single-host reports and the Fleet Detailed Inventory Alarms table, alongside internal tab-jumping to host diagnostic views.
  - **Authoritative Vendor SEL Guide Catalog**: Integrated official System Event Log and Fault reference documentation across Dell (PowerEdge EEMS Guide), HPE (IML Messages and Troubleshooting Guide for Gen10/11/12 and Synergy), Cisco (UCS IMC Faults Reference Guide), Lenovo (ThinkSystem XCC Events Guide), and Supermicro (BMC IPMI User's Guide) with right-aligned guide badges in the SEL header.
- **Modular User Guide & Reference Documentation (`docs/user_guide/`, `docs/USER_GUIDE_REFERENCE.md`, `tools/build_user_guide.py`)**: Assembled comprehensive 10-chapter reference guide covering fleet dashboard, health alerts, detailed inventory SE decision matrix, offline Excel export, BMC hardware security audit, SEL/IML deep-links, and Redfish hypermedia crawler.

### Fixed
- **Host Report Tab Navigation & Deep Link Anchor Scrolling (`vcf_hci/report/host_report.py`, `vcf_hci/report/styles.py`, `vcf_hci/report/fleet/combined.py`)**:
  - Implemented programmatic smooth scrolling (`scrollToNav`) for tab changes, URL hash navigation (`#tab-*`), and internal badge jump links, ensuring tab content is immediately brought into view even when inactive panes are initially styled `display: none`.
  - Added CSS `scroll-margin-top` rules to `.tab-nav` (1rem) and `.tab-pane` (4rem) to avoid clipping under sticky headers or top navigation bars.
  - Exposed `window.activateTab` on host reports to allow embedded iframes in the Combined Fleet Report (`00_fleet_combined.html`) to activate tabs and scroll into view seamlessly.

## [9.3.0] – 2026-09-15

### Added
- **Enterprise BMC Hardware Security & Hardening Audit Suite (`vcf_hci/security/`, `vcf_hci/collector/`, `vcf_hci/report/`, `management_pack/`)**:
  - **Neutral Security Contract & Schema (`vcf_hci/security/contract.py`, `vcf_hci/security/metadata.py`)**: Defined a normalized security finding contract with 84 canonical control IDs (`C01`–`C59` configuration, `O01`–`O16` operational, `I01`–`I09` interface), 10 normalized control statuses (`pass`, `fail`, `unknown`, `unknown_write_only`, `not_applicable`, `unsupported`, etc.), standardized reason codes, architectural groupings, confidence ratings, and strict schema validation rejecting HTML tags and distinguishing `None` from `False`/`0`.
  - **Standard Redfish Baseline Evaluator (`vcf_hci/security/evaluation.py`, `vcf_hci/collector/collect_system.py`)**: Pure deterministic evaluator assessing 8 standard Redfish security controls (`C09` TLS min version, `C21` HTTPS protocol, `C23` IPMI-LAN disabled, `C24` Telnet disabled, `C29` SNMPv3-only, `C37` Account lockout threshold, `C43` Session timeout, `C53` UEFI SecureBoot enabled) with zero external network egress or side effects.
  - **Dell iDRAC OEM Security Adapter & 59-Control Evaluator (`vcf_hci/collector/oem/dell.py`, `vcf_hci/security/dell.py`)**: Complete 59-control configuration matrix evaluator with instance-agnostic attribute normalization, user slot grouping, and safe GET-only evidence collection across SysLog, SCEP, Active Directory, OpenLDAP, Web GUI, User Accounts, SEKM, and Lifecycle Controller attributes. Write-only secrets (`C10`, `C26`, `C32`, `C49`) strictly held as `unknown_write_only`, and non-GET or external processes held as `unknown`.
  - **HPE iLO OEM Security Adapter & 59-Control Evaluator (`vcf_hci/collector/oem/hpe.py`, `vcf_hci/security/hpe.py`)**: SecurityService, SecurityDashboard, SecurityParams, CertificateAuthentication, SSO, and ESKM collection and evaluation against peer hypotheses. Dell-specific controls strictly marked as `not_applicable` with zero false passes or blanket assumptions.
  - **Recursive Secret Redaction & PII Hygiene (`vcf_hci/security/redaction.py`, `vcf_hci/obfuscation.py`)**: Recursive sanitizer stripping secret-bearing keys, PEM private keys, URL credentials, and masking literal `"********"` strings while preserving non-secret algorithm metadata and `SecurityKeyNumber`. Customer IPs masked to RFC 5737 and domains to `rainpole.net`.
  - **Integrated Host HTML Security Report Section (`vcf_hci/report/sections/bios_security.py`)**: 7-column security findings table with category headers, status badges, expected vs observed values, and diagnostic hover tooltips, enforcing strict honest posture rollup (`Partially Assessed` for unknowns, `Action Required` for failures, `Baseline Met` only when all checks pass).
  - **Fleet Health Dashboard & Summary Table Rollup (`vcf_hci/report/fleet/tiles.py`, `vcf_hci/report/fleet/summary.py`, `vcf_hci/report/fleet/combined.py`)**: Added Tile 15 ("BMC Security Posture") with aggregated fleet pass/fail/unknown counters and compliance %, plus dedicated sortable "BMC Security" columns in fleet summary tables.
  - **Excel Workbook Security Audit Tab (`vcf_hci/report/excel_export.py`)**: Added Tab 11 `Security_Audit` exporting normalized SCG control findings with full metadata, status formatting, expected vs observed values, and reason codes, marking centralized fleet management appliances as out of scope.
  - **Web UI REST API Endpoints (`vcf_hci/web/api_mixin.py`, `vcf_hci/web/server.py`)**: Added `/api/security/summary`, `/api/security/findings`, and `/api/security/host/<id>`.
  - **VCF Operations Management Pack Integration (`management_pack/`)**: Added 4 aggregate metrics (`security|passed_count`, `security|failed_count`, etc.) and 10 individual SCG control properties to `PhysicalServer` resources with fallback mappings for unassessed hosts.
  - **Deterministic Replay & Test Fixtures (`tests/fixtures/`, `tests/redfish_replay.py`)**: Added sanitized offline replay fixtures for Dell iDRAC9, HPE iLO 5, and generic standard Redfish hosts with zero-network replay verification.
- **Detailed Inventory Security Compaction & Host View Backporting (`vcf_hci/report/fleet/inventory_panel.py`, `vcf_hci/report/sections/bios_security.py`, `vcf_hci/collector/collect_system.py`)**:
  - **Compact Security Sub-Tab Headers & Formatting**: Word-wrapped table headers (`Secure<br>Boot`, `BMC Model<br>&amp; FW`, `CVE Coverage<br>Tier`, `NTP /<br>Time Drift`, `BMC<br>Hardening`) and rebranded `Hyperthreading` to `HT` across fleet reports and reference docs.
  - **Concise NTP Alarm & BMC Hardening Posture Rollup**: Displaying truncated minute-only NTP drift (`{mins}m`) when drift exceeds 1 minute with full skew details preserved in hover tooltips. Dynamic rollup posture badges (`✗ Action Req`, `▲ Review Req`, `✓ Baseline Met`) summarizing granular non-compliant checks with detailed diagnostic tooltips.
  - **Single-Host 11-Point Hardening Baseline Standardization**: Backported full 11-point security hardening checks into single-host views (`bios_security.py`) and Redfish collectors (`collect_system.py`) with explicit "Not Exposed" fallback badges across Account Lockout, Password Policy, Session Timeout, Syslog, HTTP, Telnet, SNMP, and IPMI.
- **Detailed Inventory & SE Decision Matrix Feature Suite (`vcf_hci/report/inventory_tables.py`, `vcf_hci/report/fleet/inventory_panel.py`)**:
  - **SE Decision Matrix (Tab 1 in `fleet_combined.html`)**: Dense HTML decision matrix positioned between Fleet Summary and host iframes, displaying compact rollups for ESA NVMe disks (`summarize_esa_disks()`, e.g. `4×3.8TB (15.2TB)`), network port link states with directional arrows (`summarize_nics()`, e.g. `4×25G↑ 2×10G↓`), CPU tier dots, RAM capacity & DIMM counts, memory interleaving efficiency %, TPM 2.0 / VMD indicators, HW RAID blocking detection, and GPU accelerator counts.
  - **Interactive Facet & Segmented Filtering**: Instant client-side filtering across OEM vendor, CPU support tier, vSAN ESA readiness tier, NIC speed threshold (≥25G vs <25G), link down status, and full-text search, with synchronized drive/NIC subpanes.
  - **Unified 10-Tab Excel Workbook (`vcf_hci/report/excel_export.py`)**: Unified Schema v2.0 domain fields with granular component inventories (`Summary`, `Decision`, `vCPU`, `vMemory`, `vStorage`, `vNetwork`, `vGPU`, `vFirmware`, `vHBA`, `Security`, and optional `Failed_Hosts`).
  - **Offline `file://` Client-Side Excel Export (`vcf_hci/report/fleet/inventory_panel.py`)**: Pre-rendered and embedded Base64 XLSX and Obfuscated ZIP payloads into standalone combined HTML reports, enabling instant offline file downloads on `file://` protocol without requiring the web server backend.
  - **Default Excel Workbook Generation Across All Runners**: Enabled automated Excel export by default in the Web UI, CLI (`--excel` default with `--no-excel` opt-out), scan engine, and remote jump-box scanner (`tools/lab_fleet_smoke.py`), automatically outputting both standard and `00_OBFUSCATED_*.xlsx` workbooks when obfuscation is enabled.
  - **Obfuscation Key & Private Reverse-Mapping Export (`vcf_hci/obfuscation.py`)**: Introduced `ObfuscationKey` and `obfuscate_fleet_with_key()` tracking real-to-token mappings. Built `build_obfuscated_inventory_zip()` bundling `inventory_obfuscated.xlsx` with a private `obfuscation_key.json` and security guidance readme.
  - **Web UI & API Integration**: Added `/api/export-inventory-excel-obfuscated` endpoint and dedicated "Export Obfuscated Excel + Key" UI buttons in both the Web application and report inventory panels.

## [9.2.0] – 2026-09-11

### Added
- **Standardized Multi-Tab Excel Workbook & CSV Fleet Data Exporters (`vcf_hci/report/`)**:
  - **Centralized Schema Registry (`vcf_hci/report/schema_registry.py`)**: Schema v2.0 domain registry defining 40+ standardized, typed export fields spanning 11 architectural domains (Host Identity, Hardware Specs, Compute Architecture, Memory Topology, Storage & vSAN ESA/OSA, Network Topology, Security Baseline, Power & Thermal, Accelerators/GPUs, Host OS/ESXi, and Scan Diagnostics).
  - **Comprehensive Multi-Tab Excel Workbook (`vcf_hci/report/excel_export.py`)**: Upgraded stdlib XML/ZIP workbook generation (`export_to_excel()`) to build 6 complete tabs (`Summary`, `Storage`, `NICs`, `GPUs`, `Security`, and conditional `Failed_Hosts`) with automatic verdict color fills.
  - **Standardized CSV Exporters (`vcf_hci/report/csv_export.py`)**: Built stdlib-only CSV generators for `00_fleet_summary.csv`, `00_drives_inventory.csv`, `00_nics_inventory.csv`, `00_gpus_inventory.csv`, and `00_failed_hosts.csv`.
  - **Automatic Obfuscation Mirroring**: When obfuscation is enabled (`--obfuscate` / `obfuscateChk`), both the CLI and Web scanner automatically generate obfuscated Excel workbooks (`00_OBFUSCATED_vcf_readiness_<timestamp>.xlsx`) and obfuscated CSV tables (`00_OBFUSCATED_fleet_summary.csv`, etc.) alongside standard outputs with deterministic PII masking.
  - **Web UI & API Integration**: Added `/api/export-csv` endpoint supporting `?obfuscated=1`, added "Auto-export CSV & Excel workbook" checkbox in Scan Settings, and added one-click CSV export button in the Web UI Export Data section.
  - **CLI Flags**: Added `--csv-export` flag to `vcf_hci` CLI for standalone and `--from-summary` execution.

## [9.1.3] – 2026-09-10

### Changed
- Release v9.1.3

## [9.1.2] – 2026-09-10

### Changed
- Release v9.1.2

## [9.1.1] – 2026-09-08

### Added
- **Two-Pass Fast Discovery & Longest-Job-First (LJF) Priority Scheduling (`vcf_hci/fleet_discovery.py`)**:
  - Implemented Pass 1 lightweight discovery probe querying `/redfish/v1/Systems/1` and `/Storage` (with a 3-second timeout) to pre-qualify CPU architectures and count storage drive URI links without performing expensive drive leaf GET walks.
  - Implemented Longest-Job-First (LJF) priority queue scheduling: heavy 24-drive storage nodes are dispatched into outer worker pools at $t=0$, sweeping through medium/light compute nodes in parallel and eliminating the straggler long-tail bottleneck.
  - Added historical "Straggler Suspects" duration caching: prior scan results automatically tag known slow hosts (>90s past duration) as Priority 0 for immediate execution.
- **Dynamic System Auto-Stepdown Monitor (`vcf_hci/system_throttle.py`)**:
  - Built stdlib-only system resource monitor inspecting 1-minute CPU load average (`os.getloadavg()`) and available RAM (`/proc/meminfo`).
  - Automatically steps down outer fleet concurrency by 25% if CPU load exceeds $1.5\times$ core capacity or RAM drops below 10%, with automatic step-up recovery once resource metrics normalize.
  - Increased maximum outer concurrency ceiling to 96 threads for high-throughput enterprise scan environments.
- **CLI Options**: Added `--two-pass` and `--no-auto-throttle` arguments to `vcf_hci/cli.py`.

### Changed
- Standardized VCF Operations Management Pack packaging onto canonical `VcfReadinessAdapter_9.1.1.pak` naming according to official VMware Integration SDK conventions.
- Pruned duplicate management pack archive aliases (.zip and unversioned .pak) to streamline distribution deliverables.
- Re-bundled bundled documentation in `vcf_hci/web/docs_data.py`.

## [9.1.0] – 2026-09-07

### Added
- **VCF Operations Plugin Rebranding & Packaging Overhaul (VCF-R / VCF Readiness)**:
  - Removed "HCI" moniker from management pack descriptors, adapter kinds, and manifests; renamed adapter kind to `VcfReadinessAdapter` with display name "VCF Readiness Management Pack (VCF-R)".
  - Updated build artifact names and aliases in `tools/build_management_pack.py` to produce `VcfReadinessAdapter_9.1.1.pak`.
  - Added explicit directory tree entries (`resources/`, `VcfReadinessAdapter/conf/`, etc.) in zip archives to prevent Java `SyncAdapters.extractFiles` `NoSuchFileException` during VCF Operations installation.
  - Designed high-resolution 256x256 RGBA icon badge (`management_pack/icon.png`) conforming to VMware Integration SDK image specifications.
- **Lenovo & Cisco OEM Coverage Remediation & Feature Parity**:
  - **Power Collection Hardening (`vcf_hci/collector/collect_power.py`)**: Added `_safe_num` coercion helper and normalized singular `PowerControl` dict responses to lists (resolving Cisco CIMC non-compliant payloads from gofish #409). Coerced string numeric values (`"152"`, `"11.900"`, `"71"`) and `"N/A"` string sentinels across voltages, thresholds, and fan RPMs.
  - **Replay Harness `@odata.id` Indexing (`tests/redfish_replay.py`)**: Enhanced `load_dump_map()` to index dump files by both normalized filepath and `@odata.id` candidate keys, resolving endpoints with underscored resource identifiers (such as Lenovo `RAID_Slot1`). Added dedicated harness test in `tests/test_redfish_replay.py`.
  - **Raw Replay Sample Dumps (`samples/`)**: Built synthetic, quirk-faithful offline replay dumps for `samples/lenovo-sr630v2/` (from `bmc-toolbox/bmclib` Apache-2.0 fixtures) and `samples/cisco-c220-m5/` (from Cisco UCS C-Series Redfish API and gofish #409 captures), fully sanitized with RFC 5737 test IPs and synthetic serial numbers.
  - **Lenovo XCC OEM Hooks (`vcf_hci/collector/oem/lenovo.py`)**: Implemented `oem_fastpath_roots()` directly resolving `/Systems/1`, `/Chassis/1`, and `/Managers/1`. Implemented `oem_bios_date()` via `/UpdateService/FirmwareInventory` to source UEFI/BIOS release date, activating VCF `_CVE_TIERS` side-channel evaluation. Added Gen-1 Features-on-Demand (`FoD/Keys`) license fallback.
  - **Cisco IMC OEM Hooks (`vcf_hci/collector/oem/cisco.py`)**: Implemented `oem_fastpath_roots()` probing `/Managers/CIMC` and resolving serial-keyed system and chassis paths. Implemented `oem_bios_date()` via `/UpdateService/FirmwareInventory` BIOS entry.
  - **Chassis & Baseline Data Refresh (`vcf_hci/constants.py`)**: Added `LENOVO_MODEL_CHASSIS_DB` covering SR630, SR630 V2, SR650, SR650 V2, and SR650 V3 front bay counts and labels. Refreshed Cisco `BIOS_BASELINES` with per-generation baselines (M5 on 4.3(2.x), M6/M7 on 6.0(2.x)). Updated Cisco and Lenovo `BMC_FW_BASELINES` documentation.
  - **Comprehensive Test Parity (`tests/`)**: Added offline replay test suites `tests/test_replay_lenovo_sr630v2.py` and `tests/test_replay_cisco_c220.py` with zero network egress assertions. Expanded `TestLenovoCollector`, `TestCiscoCollector`, and added `TestPowerCoercion` in `tests/test_collector_oem.py`.

## [9.0.0] – 2026-09-06

### Added
- **VCF Operations Integration SDK Overhaul (`management_pack/`)**:
  - Replaced legacy mock collector calls with real nested `run_assessment()` payloads via `management_pack/payload_map.py`, adding seamless multi-sled / modular chassis discovery support.
  - Implemented thread-safe concurrent BMC collection via `concurrent.futures.ThreadPoolExecutor` with per-cycle deep scan budgeting and persistent JSON caching (`/data/vcf-hci-cache`).
  - Restructured management pack packaging onto the standard VMware Integration SDK layout (`app/adapter.py`, `commands.cfg`, JSON `manifest.txt`, pinned SDK container base).
  - Fixed parent/child topology serialization and vCenter `HostSystem` external resource correlation.
  - Added comprehensive deployment guide (`docs/MANAGEMENT_PACK_GUIDE.md`), automated metric reference generator (`tools/generate_mp_reference.py` -> `docs/MP_METRIC_REFERENCE.md`), and vCommunity drop-in export tool (`tools/export_vcommunity_drop.py`).
- **Fleet Scan Comparison & Consistency Analytics Engine (`tools/compare_scans.py`, `tools/generate_three_run_report.py`)**:
  - Implemented multi-run fleet comparison engine analyzing scan consistency, drift, and throughput metrics across distinct execution environments and concurrency configurations.
  - Computes objective scan depth scores (0–100) and per-host component inventory counts across storage controllers, physical drives, network adapters, ports, PCIe slots, firmware items, and event log entries.
  - Generates standalone, interactive HTML comparison dashboards featuring summary scorecards, component inventory heatmaps, throughput comparisons, and privacy-safe data representation.
- **Post-Collection Enrichment Architecture (`vcf_hci/enrichment.py`)**:
  - Fully decoupled Layer A (OEM Hardware Collection) from Layer B (VCF 9.1 Compatibility Engine) and Layer C (Broadcom BCG Deep-Link Generation).
  - Collectors focus strictly on normalized hardware telemetry extraction, passing payloads through a centralized enrichment pipeline (`enrich_host_result()`) to apply compatibility verdicts, support badges, and BCG URLs.
  - Enables instant offline scan re-evaluation when importing prior scans without requiring BMC re-polling.
- **Code Metadata & Scan Lineage Tracking (`vcf_hci/code_metadata.py`, `tools/inspect_scans.py`)**:
  - Embedded engine version, git commit hash, branch name, and repository state metadata directly into host summary and fleet summary JSON artifacts.
  - Added CLI inspection utility for rapid querying, filtering (by OEM, model, readiness status), and offline Redfish tree inspection.
- **Windows Remote Build Tooling (`scripts/build_win_remote.sh`)**:
  - Added automated remote Windows build execution and artifact retrieval script.
- **Enhanced Fleet Reporting & Topology Matrix (`vcf_hci/report/fleet/`)**:
  - Enhanced Top-of-Rack switch matrix rendering and multi-chassis fabric topology visualization.
  - Refined host summary badges, CNA dual-persona indicators, NPAR consolidation views, and SAN boot target details.
  - Consolidated diagnostic telemetry, partial scan alerts, and connection metrics into unified report banners.

### Changed
- **Web UI & Server Scalability Hardening**:
  - Streamlined scan import pipeline supporting up to 512 MB compressed archives (`.json`, `.gz`, `.zip`) with dynamic rule re-evaluation and fleet summary generation.
  - Improved upload streaming memory efficiency, request handling, and user guidance for large fleet imports.
  - Hardened web server lifecycle stability and input handling across all API endpoints.
- **Multi-Platform Build & CI/CD Pipelines**:
  - Updated GitHub Actions CI/CD workflows for multi-platform compilation across macOS (Intel and Apple Silicon), Linux (x86_64), and Windows (x64).
  - Enhanced PyInstaller bundling specifications and packaging scripts for offline distribution.
- Bumped `TOOL_VERSION` to `9.0.0` across package metadata, pyproject.toml, build specs, documentation, and management pack definitions.
- Release v9.0.0

### Fixed (Management Pack corrective overhaul)
- SDK contract: `app/adapter.py` now translates local results into real `aria.ops` objects and calls
  `send_results()` (test/collect/adapter_definition/endpoint_urls previously failed inside the container).
- Dockerfile: correct Broadcom base-adapter image and drop-relative COPY paths; removed error-masking
  `|| true` pip install.
- `commands.cfg`: `[Commands]` header, standard interpreter paths, added `endpoint_urls`.
- Added missing pack icon (`resources/icon.png`); removed invalid hand-written `conf/describe.xml`.
- payload_map: consume real collector keys (`dimm_list`, `ctrl_model`/`ctrl_firmware`, drive
  `category`-derived `behind_raid`, string thermal `reading`, port-level MAC/link rollup).
- System UUID now collected from Redfish Systems resource, restoring UUID-based vCenter HostSystem
  correlation.
- Added per-cycle deep-scan budget (`max_deep_scans_per_cycle`, default 50) and scan-cache eviction
  for removed targets.
- Export tool now ships an operator `INSTALL.md` (VCF Ops 9.x unsigned-pak toggle, mp-build workflow)
  and produces a distributable ZIP bundle; `build_management_pack.py` archive renamed/flagged as a
  non-installable dev preview.

## [7.2.9] – 2026-09-04

### Added
- **Persistent HTTP/1.1 Keep-Alive Connection Pooling (`StdlibHTTPConnectionPool`)**:
  - Implemented thread-safe connection pool in `vcf_hci/tls_utils.py` managing up to 3 persistent HTTPS connections per BMC, strictly using Python 3.9+ standard library (`http.client.HTTPSConnection`).
  - Eliminates repetitive 150–400ms TLS handshakes per HTTP GET across 40–80 requests per host scan, slashing scan latency by 50–70% over WAN/VPN links.
  - Added connection health validation (`_is_conn_stale`) via non-blocking socket peek and idle timeout eviction.
  - Preserved thumbprint pinning security via `PinnedHTTPSConnection` integration.
- **Latency & Throughput Diagnostics Telemetry**:
  - Instrumented per-host and fleet-wide diagnostic metrics in `BaseRedfishCollector` and `scan.py`, recording `request_count`, `timeout_count`, `throttle_engaged_count`, `phase1_duration_s`, `phase2_duration_s`, `total_scan_duration_s`, `avg_get_latency_ms`, `tls_handshake_avg_ms`, and `tls_reuse_ratio`.
  - Exposed diagnostic telemetry in host summary JSONs, fleet summary JSON, and console/SSE logging streams.
- **Batched Dell TechDirect Warranty Lookups**:
  - Decoupled individual warranty lookups from the critical per-host scan loop, aggregating unique Dell service tags across the entire fleet and querying the TechDirect API in efficient batches.
  - Reused OAuth2 authentication tokens across the entire scan execution.
- **Dell OEM Fast-Path Short-Circuits**:
  - Implemented `oem_fastpath_roots()` in `DellCollector` (`vcf_hci/collector/oem/dell.py`) to directly probe monolithic PowerEdge paths (`System.Embedded.1`, `Chassis.Embedded.1`, `iDRAC.Embedded.1`), bypassing slow OData root traversals with automated fallback for modular/blade chassis.
- **Tiered Scan Depth Profiles (`readiness-full`, `readiness-lean`, `inventory-lite`)**:
  - Added selectable scan depth profiles across CLI (`--profile`) and Clarity UI selector:
    - `readiness-full` (default): Exhaustive audit (Phase 1 + Phase 2 + HCL + PCIe + Telemetry + Interleaving).
    - `readiness-lean`: High-speed VCF 9.1 / vSAN ESA audit (skips historical telemetry logs and secondary member scans).
    - `inventory-lite`: Rapid hardware inventory pre-screening (Systems, Power/Thermal rollup, Storage rollup, NIC summary).
- **LAN Concurrency Policy & Adaptive Latency Throttling**:
  - Tuned outer fleet concurrency model to allow up to 16–24 parallel host workers (max 32) on fast enterprise LANs (<80ms RTT) while keeping inner per-BMC concurrency locked safely at 3 workers.
  - Documented diagnostics interpretation and concurrency guidance in `SCANNING_OPTIMIZATIONS.md`.

## [7.2.8] – 2026-09-04

### Added
- **LLDP & ToR Switch View Context Enrichment**:
  - Correlated LLDP/CDP local interface IDs (e.g., `NIC.Integrated.1-2-1`, `NIC.Slot.2-1`) with resolved NIC model names and negotiated port link speeds.
  - Displayed resolved hardware info directly in both the LLDP neighbor table and Top-of-Rack Switch Topology cards.
- **Dedicated Out-of-Band BMC Management Interface Visualization**:
  - Surfaced the active BMC management port (Dell iDRAC, HPE iLO, Cisco IMC, Lenovo XCC) as a dedicated 1 GbE management entry in host reports, positioned cleanly below host production adapters.

### Fixed
- **NPAR & CNA False Positive Suppression**:
  - Refined `classify_cna_adapter()` to require active, configured FC/FCoE proof (non-zero 16-hex WWPN, active FCoE VLAN, or SAN boot targets) rather than triggering on standard dormant Redfish schema objects.
  - Eliminated false CNA/vHBA detection on standard Ethernet cards including Broadcom NetXtreme-E 57414S, Intel X710/E810, and Mellanox ConnectX.
  - Fixed NPAR grouping logic: distinct physical ports (e.g. `NIC.Integrated.1-1-1` on port 1 and `NIC.Integrated.1-2-1` on port 2) are now recognized as standard 1:1 multi-port NICs, only flagging `is_npar = True` for multiple partitions per physical port, carved non-standard link speeds, or explicit partitioned bandwidth quotas.
- **Report Clean-up**:
  - Moved the switch buffer and silicon research acknowledgment out of the HTML report body and consolidated it in the repository `README.md` references section.

## [7.2.7] – 2026-09-04

### Added
- **Large Scan File Import (512 MB Limit & Error Advice)**:
  - Increased streamed scan upload cap from 64 MB to 512 MB in `vcf_hci/web/server.py` to seamlessly handle large fleet scan archives (> 50-100+ hosts).
  - Added user-friendly error advice and tips in `vcf_hci/web/app_html.py` guiding users to import `data/fleet_summary.json` directly or use CLI `--from-summary` for massive datasets.
  - Added unit test coverage in `tests/test_web_server_hardening.py` for oversized upload handling.

## [7.2.6] – 2026-09-04

### Added
- **Modular Chassis Management & Multi-Sled Discovery**:
  - Implemented automatic detection for Modular Chassis Management Controllers (Dell OpenManage Enterprise Modular / OME-M on MX7000, HPE Synergy Frame Link Module / FLM, Cisco UCS Manager / Intersight, Dell VRTX CMC, Lenovo CMM).
  - Enumerate multi-blade/sled compute topologies (`/redfish/v1/Systems`) with health, model, serial, and power state telemetry.
  - Discover integrated fabric switches / IOMs (Dell MX9116n/MX7116n/MX5108n/MXG610s, HPE Synergy Virtual Connect SE 100Gb/40Gb/FC, Cisco UCS Fabric Interconnects and IOMs) and classify them with ASIC and buffer specifications.
  - Added synthetic chassis summary generation when connecting directly to standalone chassis management endpoints.
- **Converged Network Adapter (CNA) & Cisco VIC Dual-Persona Recognition**:
  - Implemented CNA family classification across Cisco VIC (1200/1300/1400/1500), HPE FlexFabric (580/620/630/650), Marvell FastLinQ (QL41xxx), QLogic 57810S, and Emulex OneConnect (OCe14000).
  - Correlated `NetworkDeviceFunctions` for concurrent Ethernet NIC and Fibre Channel (vHBA) personas.
  - Added dedicated BCG IO deep links for Ethernet drivers (`nenic`, `qfle3`) and Fibre Channel drivers (`fnic`, `qfle3f`, `lpfc`).
  - Added `🟣 CNA: <Family> (vNIC + vHBA)` badges in host and fleet reports.
- **NPAR (NIC Partitioning) Consolidation & VCF 9.1 Advisory**:
  - Consolidated sub-port partitions (e.g., 4Gbps + 2Gbps + 4Gbps) to the parent physical ASIC and flagged `is_npar`.
  - Added `evaluate_npar()` compatibility check and prominent UI advisory highlighting the risks of shared ASIC hardware FIFO queues, buffer exhaustion, and head-of-line blocking under vSAN ESA/OSA and NSX overlay workloads.
- **SAN HBA Boot Target & Storage Array OUI Discovery**:
  - Extracted HBA BIOS-configured SAN Boot Targets, Target WWPNs, Boot LUN IDs, and Priorities from `NetworkDeviceFunctions/FibreChannel/BootTargets`.
  - Integrated IEEE OUI lookup table resolving SAN target WWPNs and remote switch WWPNs to storage array vendors (Dell EMC PowerStore/VNX, Pure Storage FlashArray, NetApp ONTAP, HPE 3PAR/Primera/Alletra, IBM FlashSystem, Hitachi VSP) and SAN fabric switches (Brocade, Cisco MDS).
  - Delineated out-of-band Redfish discovery boundaries in HBA report cards.

### Changed
- Bumped `TOOL_VERSION` to `7.2.6`.
- Release v7.2.6

## [7.2.5] – 2026-09-04

### Added
- **Import Prior Scan & Offline Fleet Report Regeneration**:
  - Added dedicated **`📁 Import Scan`** action button in Web UI next to Run Assessment with support for `.json`, `.gz`, and `.zip` scan archives.
  - Enabled multi-file selection so users can select multiple `vcf_summary_*.json` files or a complete `fleet_summary.json` / scan `.zip` package.
  - Enhanced backend `load_summary()` in `vcf_hci/summary_io.py` to intelligently extract `fleet_summary.json` manifests or host summary files from scan directories and `.zip` archives without duplicating host records.
  - Enhanced `/api/import-summary` and `/api/import-summary-file` in `vcf_hci/web/server.py` to re-evaluate CPU support tiers and compatibility against the latest `VCF9CompatibilityEngine` rules, populate the finished scan summary card, update readiness badges (Supported, Deprecated, Unsupported), generate `00_fleet_summary.html` and `00_fleet_combined.html`, and render imported hosts in the Results Table.
  - Ensured `host_report.py` and `fleet_report.py` dynamically apply updated CPU and drive compatibility rules upon offline scan import.

## [7.2.4] – 2026-09-04

### Added
- **Multi-Vendor LLDP & CDP Redfish Collection**:
  - Fixed Dell iDRAC root-level `DellSwitchConnections` property parsing for `SwitchConnectionID`, `SwitchPortConnectionID`, and interface FQDD tags (`NIC.Slot.*`, `iDRAC.Embedded.1`).
  - Added full support for HPE iLO `Oem.Hpe.LldpData.Receiving` and `/HpeLLDP` sub-resource extraction.
  - Added Cisco IMC `Oem.Cisco.CDP` and `Oem.Cisco.LLDP` extraction with switch platform, interface, and management IP parsing.
  - Added Lenovo XCC `Oem.Lenovo.LLDP` and DMTF standard `LLDP.Receiving` extraction.
- **Switch Intelligence & Packet Buffer Taxonomy**:
  - Integrated switch ASIC catalog and packet buffer depth classification based on **Michael Buraglio's Packet Buffer Reference** (`port-buffers.forwardingplane.net`) and **Jim Warner's UCSC Packet Buffer Research**.
  - Added `🛡️ Ultra-Deep Buffer (VOQ)` badges for Broadcom Jericho/Qumran, Cisco Silicon One, and Juniper Q5 architectures (Arista 7280R/7500R/7800R, Cisco -R/8000 series, Juniper QFX10000).
  - Added `🛡️ Deep Buffer` badges for 100MB+ unified shared buffer switches (Broadcom Trident 4 / Tomahawk 4/5, Cisco CloudScale GX2).
- **Cisco Fabric Extender (FEX / Nexus 2000) Detection**:
  - Implemented automatic FEX detection on remote slot port numbering (`Ethernet100-199/...`) and Nexus 2000/FEX hardware model tokens.
  - Added UI warning banners explaining oversubscribed shared uplinks and latency considerations for VCF 9.1 / vSAN ESA deployments.
- **Modular Chassis vs 1RU Fixed Leaf SVG Graphics**:
  - Created standalone inline SVG illustrations for High Radix Modular Chassis switches (Nexus 7000/7700/9500, Arista 7500/7800) with supervisor cards and line card slots.
  - Created 1RU Fixed Leaf SVG illustrations with status LEDs, port blocks, and QSFP uplinks.
- **Fleet-Wide ToR Leaf Switch Pair Detection & Topology Matrix**:
  - Developed ToR leaf pair correlation algorithm matching co-occurring server connections across switch fabrics.
  - Added **ToR Switch Fabric & Redundancy** dashboard tile and dedicated **Fleet Switch Fabric & Topology Matrix** interactive section with connected host drilldowns and cabling audit alerts.
- **Privacy-Preserving Deterministic PII Obfuscation**:
  - Added deterministic hashing (`SW-XXXXXX`, `02:xx:xx:xx:xx:xx`) for switch hostnames, chassis MACs, and port names in `vcf_hci/obfuscation.py` with in-browser toggle consistency.

### Changed
- Bumped `TOOL_VERSION` to `7.2.4`.
- Release v7.2.4

## [7.2.3] – 2026-08-30

### Added
- **Broadcom IO HCL Alignment & Supplements (`KNOWN_HCL_SUPPLEMENTS`)**:
  - Overlaid authoritative VMware ESXi Hypervisor IO HCL (`program=io`) certifications on top of the vSAN JSON feed (`all.json.gz`).
  - Added full ESXi 9.1 inbox driver (`nmlx5_core 4.25.0.25-1vmw.910`) and firmware (`14.32.2004`) support matrices for Mellanox ConnectX-4 Lx 25GbE adapters (Dell NDC `15b3:1015:15b3:0025`, PCIe `15b3:1015:15b3:0003`, KR Mezz `15b3:1015:15b3:0116`, OCP `15b3:1015:15b3:0009`, etc.).
  - Added `_apply_hcl_supplements()` to bundle manager and runtime loader to guarantee consistency across live, cached, and offline dark-site zip bundles.
- **BCG vSAN RDMA Link Correction & Badging**:
  - Corrected BCG search parameter for network adapters from `program=vsanio` (which is restricted to Storage I/O controllers) to `program=rdmanic` and direct `vcglink` detail URLs.
  - Surfaced `⚡ vSAN RDMA Supported` badges in host reports and component matrices when adapters are certified for vSAN RoCE v2 / RDMA.

### Fixed
- **Normalized Multi-Part Firmware Comparison**:
  - Enhanced `_compare_fw_versions()` in `vcf_hci/compat_engine.py` to normalize 3-part vs 4-part sub-build notations (e.g. `14.32.21.04` vs `14.32.2004`), preventing false "outdated firmware" warnings when newer sub-builds are installed.

### Changed
- Bumped `TOOL_VERSION` to `7.2.3`.
- Release v7.2.3

## [7.2.2] – 2026-08-30

### Added
- **Native OS Folder Browsing (`/api/browse-folder`)**:
  - Integrated native folder picker dialogs across macOS (`osascript` / AppleScript), Windows (PowerShell `FolderBrowserDialog`), and Linux (`zenity` / `kdialog` / `yad`).
  - Added a **📁 Browse…** button beside the Output Folder text field in the Web UI, automatically updating the active target directory and saving it to the user session.
- **Direct Output Folder Reveal Actions (`/api/open-folder`)**:
  - Implemented desktop file manager launcher supporting macOS Finder (`open`), Windows Explorer (`explorer`), and Linux (`xdg-open`).
  - Added **📂 Open Folder** buttons in the post-scan summary card and export actions column for instant access to generated HTML reports and JSON artifacts.

### Removed
- **Output Boundary Sandboxing Checkbox**:
  - Removed confusing `limitDefaultFolderChk` checkbox and restrictive `commonpath` sandboxing error in the Web UI backend.
  - Standard user workflows now default cleanly to `~/Desktop/VCF-Scans` while permitting custom output directories anywhere with write permissions without artificial scan rejection.

### Changed
- Bumped `TOOL_VERSION` to `7.2.2`.
- Release v7.2.2

## [7.2.1] – 2026-08-30

### Added
- **Fleet Scanning Validation & Operations Guidelines**:
  - Detailed architecture, scheduled baseline scans, and VPN latency probing guidelines.
  - Defined subsystem completeness and validation requirements across Dell, HPE, Supermicro, Cisco, and Lenovo platforms.
- **Automated Versioning Standard & Documentation Pipeline**:
  - Established standard policy to iterate patch versions (`X.Y.Z+1`) by default at the completion of substantive implementation plans and update `CHANGELOG.md`.

### Changed
- Bumped `TOOL_VERSION` to `7.2.1` across package metadata, pyproject.toml, build specs, and management pack definitions.
- Release v7.2.1

## [7.2.0] – 2026-08-29

### Added
- **BMC TLS Verification & Enterprise CA Bundle Support**:
  - Implemented `vcf_hci/tls_utils.py` providing `build_ssl_context()` and `format_ssl_error()` to handle both default self-signed BMC workflows (`CERT_NONE`) and strict verified PKI environments (`CERT_REQUIRED`).
  - Added CLI flags `--verify-ssl` and `--ca-bundle <path>`, and corresponding Web UI controls (`ignoreTlsChk`, `tlsModeSystem`, `tlsModeCustom`, `caBundleInput`).
  - Integrated SSL context propagation across `BaseRedfishCollector`, `create_collector`, `detect_management_protocol`, `_redfish_probe`, `_wsman_identify_probe`, and `WsManCollector`.
  - Added explicit SSL error classification and diagnostic formatting (detecting self-signed certs, untrusted CAs, expired certs, and hostname mismatches without crashing).
- **Forward-Confirmed Reverse DNS (FCrDNS) Lookups**:
  - Implemented `resolve_target_fqdn()` in `vcf_hci/logging_utils.py` with thread-safe caching.
  - Performs reverse PTR queries followed by forward A/AAAA record verification before evaluating TLS certificates against BMC Subject Alternative Names (SANs).
  - Added CLI flag `--dns-lookup` and Web UI checkbox `dnsLookupChk`.
- **Target Range & Output Sandboxing Hardening**:
  - Implemented `is_private_or_local_target()` in `vcf_hci/logging_utils.py` to identify RFC 1918, loopback, and link-local ranges.
  - Added `--restrict-private-targets` CLI flag and `restrictPrivateChk` Web UI checkbox to prevent accidental scanning of public WAN/Internet IP ranges.
  - Added optional output folder boundary enforcement (`limit_default_folder`) to confine generated reports within the standard `~/Desktop/VCF-Scans` hierarchy.
- **Web UI & REST API Security Hardening**:
  - Replaced plaintext in-HTML token transmission with secure, unguessable, `HttpOnly`, `SameSite=Strict` session cookies (`vcf_session`).
  - Hardened CORS Origin validation with exact hostname matching in `_is_allowed_origin()`, blocking DNS rebinding and wildcard subdomain bypasses.
  - Injected security headers on HTML and JSON responses (`X-Frame-Options: SAMEORIGIN`, `Content-Security-Policy: default-src 'self' 'unsafe-inline' data:; connect-src 'self';`).
  - Enforced authentication checks across mutating POST/DELETE APIs, SSE event streams, sensitive GET endpoints (`/api/scan/status`, `/api/session`), and static reports.
  - Added mandatory `--allow-remote` flag when binding the web server to `0.0.0.0` or wildcard interfaces with explicit security warning banners.
  - Added `icacls` user-only ACL hardening for Windows DPAPI secret files and surfaced explicit error messages when no secure credential backend is available.
  - Enforced 32 MB payload caps and Zip Slip path traversal defenses on HCL and summary JSON imports.
- **Comprehensive Security Test Suite**:
  - Created `tests/test_security_remediation.py` testing CORS origin validation, session cookie authentication, TLS context generation, FCrDNS resolution, private target filters, and secret store error handling.

### Changed
- Bumped `TOOL_VERSION` to `7.2.0` across package metadata, pyproject.toml, build specs, and management pack definitions.
- Release v7.2.0

## [7.1.0] – 2026-08-29

### Added
- **Multi-Vendor LLDP & Cisco CDP Top-of-Rack Switch Discovery**:
  - Expanded `collect_lldp_neighbors()` in `vcf_hci/collector/collect_network.py` to support standard DMTF Redfish LLDP, Cisco IMC CDP and LLDP (`Oem.Cisco.CDP`, `Oem.CIMC.CDP`, `Oem.Cisco.LLDP`), Dell iDRAC Switch Connections (`DellSwitchConnections` and `Oem.Dell.DellNetworkPort`), Lenovo XCC (`Oem.Lenovo.LLDP`, `NeighborInformation`), and HPE iLO (`LldpData.Receiving`, `/HpeLLDP`).
  - Extended port-level discovery across BMC management interfaces, production `EthernetInterfaces`, `NetworkInterfaces`, and chassis `NetworkPorts`.
  - Added protocol badges (`LLDP` vs `CDP`) and updated ToR switch cards and network assessment tables in HTML host reports and fleet summaries.
- **Progressive Multi-Pass Auto-Retry & Differential Rescan Engine**:
  - Implemented progressive multi-pass auto-retry (up to 3 total passes) in `vcf_hci/web/server.py` to automatically recover slow, degraded, or timeout-prone BMCs.
  - Added adaptive thread clamping (2–4 threads) and extended host timeouts (up to 600s) during auto-retry passes to prevent BMC web server overload.
  - Implemented dynamic phase timeouts scaled proportionally to `host_timeout` (up to 180s for Phase 1 and 300s for Phase 2) in `BaseRedfishCollector`.
  - Added color-coded real-time log indicators (`[🔄]`, `[🔄✓]`, `[🔄⚠️]`, `[⚠️]`) in CLI and Web UI terminal logs.
- **Unit Test Coverage**:
  - Added `TestLLDPNeighborDiscovery` and `TestMultiPassAutoRetry` test suites in `tests/test_rescan_and_throttling.py`.

### Changed
- Bumped `TOOL_VERSION` to `7.1.0` across package metadata, pyproject.toml, build specs, and management pack definitions.
- Release v7.1.0

## [7.0.0] – 2026-08-28

### Added
- **Automated Pre-Scan Network Latency Probing & VPN Adaptive Throttling**:
  - Implemented `probe_fleet_network_latency()` in `vcf_hci/protocol.py` to sample candidate BMC hosts and measure TCP handshake RTT latency across ports 443/80 before scan execution.
  - Automatically detects high-latency WAN/VPN connections (avg RTT > 80ms or max RTT > 150ms) and dynamically scales outer scan concurrency down to a safe profile (8 threads max) to prevent socket buffer exhaustion, packet drops, and BMC timeout cascades.
  - Added `--force-threads` CLI flag and `force_threads: True` API parameter to allow users to bypass latency throttling when unconstrained concurrency is explicitly desired.
- **Complete Targeted Differential Rescan Subsystem Engine**:
  - Expanded `section_dispatch` in `BaseRedfishCollector.rescan_partial_sections()` to support all Phase 1 and Phase 2 subsystems: `pcie_switches`, `bmc_license`, `bmc_security_config`, `bmc_net_proto`, `bmc_firmware`, `secure_boot`, `sw_inv_os`, `pcie_devices`, and `memory_telemetry`.
  - Automatically recalculates PCIe lane budgets and memory topology structures immediately upon resolving relevant subsystems.
  - Successfully clears `partial_scan`, `partial_sections`, `partial_stage`, and `timed_out` flags when all outstanding missing sections are recovered.
- **Remediation Metadata, Badges & Fleet Recovery Indicators**:
  - Recorded standardized `remediation` metadata dictionaries on host scan payloads tracking rescan state, original missing sections, resolved sections, remaining sections, status (`fully_remediated` vs `partially_remediated`), and timestamps.
  - Host HTML Reports: Render prominent `🔄 REMEDIATED VIA TARGETED RESCAN` alert banners with breakdown chips of recovered sections.
  - Fleet HTML Summary & Combined Reports: Added `🔄 Remediated` badge in host tables and an alert banner detailing recovered hosts.
  - Web UI: Added `🔄 Remediated` badges in the real-time results table and surfaced a `X Remediated via Rescan` count badge in the finished scan summary card.

### Fixed
- **Output Directory Normalization on Retries**:
  - Fixed `normalize_output_dir()` and `scan_hosts()` output directory resolution when running additive retries and targeted rescans (`create_subfolder=False`).
  - Eliminated duplicate nested `VCF-Scans/` subdirectories, ensuring rescanned host reports and JSON summaries overwrite and update the existing scan folder cleanly in-place.
- **Web UI Progress Bar & State Synchronization**:
  - Fixed `_state["completed"]` and `_state["total"]` updates in `vcf_hci/web/server.py` upon scan and retry completion.
  - Added explicit progress bar synchronization in `onScanDone()` in `vcf_hci/web/app_html.py` so the progress bar accurately reflects final fleet completion counts.

## [6.15.7] – 2026-08-28

### Added
- **Targeted Subsystem Differential Rescan Engine**:
  - Implemented `rescan_partial_sections()` in `BaseRedfishCollector` and `WsManCollector` to execute fast differential rescans targeting only missing or failed sections (e.g. `pcie_slots`, `firmware_inventory`, `storage_subsystem`, `network_adapters`, `memory_subsystem`, `thermal_telemetry`, etc.) instead of running a full two-phase rescan.
  - Automatically merges resolved sections into existing host payloads, recalculates PCIe lane budgets and memory topologies, and clears partial scan status flags upon completion.
- **Enhanced Web UI Incomplete Host Remediation & Additive Retry**:
  - Added failure category breakdown badges (Unreachable, Partial Data, Timed Out, Auth Failed) in the Web UI remediation panel.
  - Added "Retry Active Issues" and "Retry All Non-Success" action buttons that directly trigger additive scans into the active scan folder without overwriting prior valid findings.
  - Added "Auto-retry incomplete / failed hosts once" option in scan options, enabled by default for fresh assessment runs.
- **Comprehensive Partial Scan Visibility & Reporting**:
  - Surfaced explicit missing subsystem lists across individual host HTML reports, summary JSON files, fleet summary badges, and Web UI active host cards.
  - Added Section 7 to `SCANNING_OPTIMIZATIONS.md` detailing troubleshooting playbooks, BMC reset commands, and fleet concurrency tuning for degraded BMCs.
- **Extended NVMe SMART Telemetry & PCIe Downshift Detection**:
  - Extracted PCIe negotiated and capable link widths, available spare percentage, cryptographic erase capabilities, and hardware error descriptions across Dell iDRAC and HPE iLO OEM drive metrics.
  - Enhanced Storage Mixin and HTML assessment report SMART health table with PCIe link width/downshift badges, crypto erase indicators, and error callout tags.
  - Added unit test coverage for extended SMART metrics extraction and report UI rendering.
- **Multi-Vendor Memory RAS Mode Detection & Documentation Links**:
  - Added primary BIOS memory operating mode key support across HPE (`AdvancedMemProtection`), Dell, Lenovo, Cisco, and Intel/AMD platforms.
  - Suppressed secondary sub-setting warnings (e.g. HPE `MemMirrorMode=Full`) when a non-mirroring primary operating mode is active.
  - Converted non-mirroring protection modes (ADDDC, Online Spare, Rank/Bank Sparing, Partial Mirroring) to info badges accompanied by OEM documentation links.

### Changed
- **Adaptive Throttling & Inner Concurrency Model**:
  - Replaced inner BMC semaphore permit draining with a Condition Variable (`threading.Condition` + `threading.RLock`) pattern.
  - Eliminated permit leakage and starvation across Phase 2 workers during subsystem collection on slow or degraded BMC controllers.
- **Entry Points Modernization to `vcfr_collector.py` and `vcfr_web.py`**:
  - Renamed primary CLI and Web UI entry points to `vcfr_collector.py` and `vcfr_web.py`.
  - Retained `redfish_collector.py` and `redfish_web.py` as full backward-compatibility shims.
  - Updated all build scripts (`build-web.sh`, `build-web.bat`, `build_offline_package.sh`, `build_win_remote.sh`), docstrings, help texts, and documentation.
- **Default Scan Options**:
  - Set "Auto-retry incomplete / failed hosts once" to default enabled across Web UI and server APIs.
- Release v6.15.7

### Fixed
- **AMD EPYC High-Lane PCIe Slot Collection Stalls**:
  - Resolved Phase 2 collection timeouts on 128-to-160 lane AMD platforms (e.g., Dell PowerEdge R7515) by concurrently pre-fetching unique linked `PCIeDevice` endpoints using bounded workers and shallow non-recursive PCI extraction.
  - Reduced slot enumeration duration across 17 physical slots from >120s to ~3.5s.
- **Firmware Inventory Collection Prioritization & Caps**:
  - Prioritized essential hardware controllers (BIOS, BMC, CPLD, NICs, RAID/HBAs, PSUs) and capped collection to the top 25 high-priority items with a 15-second deadline.
- **Web UI Active Host Tracking & Ghost Host Elimination**:
  - Reconciled `_activeHosts` state against active server sets and prevented late stage callbacks from lingering background threads from resurrecting completed host cards.
- **Phase Parallel Timeout Caps & Smart PCIe Priority Sorting**:
  - Enforced a 60-second hard deadline across Phase 1 and Phase 2 host collection execution pools using `wait()` to eliminate 15-minute sequential timeout stacking on slow or unresponsive BMCs.
  - Implemented Smart Priority Sorting and time-bounded chunking in PCIe device enumeration, prioritizing physical Storage, NIC, GPU, and HBA devices over internal CPU bridges.
  - Added a 2-second connection backoff delay on SSL handshake timeouts to allow iDRAC web server connection pools to drain.
- **Scan Timeout, Adaptive Throttling & High-Latency Network Controls**:
  - Increased default per-request socket timeout in `_get()` to 10s and heavy endpoint timeouts to 15s.
  - Refactored adaptive throttling semaphore permit draining to prevent deadlocks in retry loops.
  - Filtered non-hardware software packages early in `collect_firmware_inventory()` and capped sub-worker threadpools.
  - Added round-trip time (RTT) latency measurement in `/api/discover`, displaying a high-latency/VPN warning banner in the Web UI and auto-clamping host concurrency to 6.

## [6.15.6] – 2026-08-20

### Added
- **Configurable Host Scan Timeout**:
  - Added 'Extend host scan timeout' checkbox and custom minute selector (1–45 min) in Web UI options panel.
  - Raised default silent host scan timeout from 120s/240s to 5 minutes (300s) across Web server, CLI, and Redfish/WS-Man collectors.
  - Enforced server-side timeout clamping between 60s and 2700s (45 minutes) and persisted custom timeout settings in session state.

### Changed
- Release v6.15.6

## [6.15.5] – 2026-08-20

### Fixed
- **CLI & Web Entrypoint Resiliency**:
  - Enhanced `redfish_collector.py` and `redfish_web.py` backward-compatibility shims with improved fallback package resolution and version reporting.

### Changed
- Release v6.15.5

## [6.15.4] – 2026-08-20

### Changed
- **Build Script & Packaging Robustness**:
  - Updated PyInstaller standalone Web UI bundle script (`build-web.sh`) with improved error checking and asset validation.
- Release v6.15.4

## [6.15.3] – 2026-08-20

### Changed
- **Version Alignment & Specification Sync**:
  - Synchronized version constants and master framework specs across package files.
- Release v6.15.3

## [6.15.2] – 2026-08-20

### Added
- **Automatic Obfuscated Report & Dashboard Generation**:
  - Generated `OBFUSCATED_Host-N.html`, `00_OBFUSCATED_fleet_summary.html`, and `00_OBFUSCATED_fleet_combined.html` automatically during CLI scans and Web JSON bundle imports.
  - Added direct action links to open obfuscated summary and combined reports in Web UI post-scan UI actions and JSON import handlers.

### Fixed
- **Pre-Obfuscated Report Rendering & Documentation**:
  - Removed redundant interactive "Obfuscate report" controls on pre-obfuscated reports, displaying a static "Obfuscated Report" badge instead.
  - Rendered anonymized host identifiers as plain text on pre-obfuscated reports to prevent double-hashing.
  - Added comprehensive "Data Obfuscation & PII Anonymization" section to `README.md` detailing PII coverage, non-recoverable SHA-256 masking mechanism, and usage.

### Changed
- Release v6.15.2

## [6.15.1] – 2026-08-19

### Added
- **Standardized Output Directory Structure (`VCF-Scans`)**:
  - Enforced `VCF-Scans` container folder for scan outputs across CLI and Web UI (`normalize_output_dir()`).
  - Added `!00_LATEST_vcf_assess_debug.log` alias copy in the container directory for immediate access to the latest debug log.
  - Automatically migrates stray scan folders into the `VCF-Scans` container directory.
- **Mixed ESA & OSA Storage Topology Breakdown**:
  - Detailed drive counts as `X ESA + Y OSA` in the fleet summary table for hosts with mixed storage topologies that fall back to vSAN OSA.
  - Updated compatibility detail messages in host and fleet reports for mixed NVMe/SATA/SAS configurations.
- **Scan Mode Comparison & Reference Documentation**:
  - Added comprehensive comparison reference tables for Quick, Lean, and Full scan modes in `README.md`, `ARCHITECTURE.md`, and in-app Web UI documentation (`vcf_hci/web/docs_data.py`).

### Fixed
- **PCIe Lookup Optimization & Reduced Scan Timeout**:
  - Optimized PCIe device matching with $O(1)$ index lookups and cached expanded PCIeFunctions to eliminate request storms on Dell iDRAC BMCs.
  - Parallelized GPU device collection and reduced default host scan timeout to 2 minutes (`DEFAULT_HOST_TIMEOUT = 120`) with 5-second socket GET timeout.

- Release v6.15.1

## [6.14.0] – 2026-08-19

### Added
- **Live In-Process Hosts Monitor & Skip Capabilities**:
  - Added real-time **In-Process Hosts** card below terminal logs featuring animated spinners, host IP tags, current assessment sub-section/stage badges (`Connecting`, `Phase 1: BIOS & SEL`, `Phase 2: Storage & NICs`, etc.), formatted `MM:SS` live timers, and slow host indicators (`⚠️ Slow (≥5m)`).
  - Added **⏭️ Skip Host** action button allowing users to cancel remaining GET requests for stuck or slow hosts mid-scan without cancelling the entire fleet assessment.
  - Implemented real-time `host_stage` SSE events and `/api/scan/skip_host` endpoint.
  - Added periodic 2.5s frontend status reconciliation polling fallback to guarantee live host progress rendering even across SSE reconnections.

### Fixed
- **Thread-Safe SSE State Snapshots**:
  - Protected `active_hosts` snapshots under `_state_lock` in SSE event broadcasting and `/api/scan/status` endpoints to prevent `RuntimeError: dictionary changed size during iteration`.
  - Fixed host cleanup lifecycle in `scan.py` to invoke `host_done_callback` across all completion and failure paths (unreachable hosts, bad credentials, exceptions).

- Release v6.14.0

## [6.13.2] – 2026-08-19

### Fixed
- **Concurrent Protocol Detection & Fast Failure for Unreachable IPs**:
  - Refactored `detect_management_protocol()` to probe candidate TCP management ports (`443`, `80`, `16993`, `16992`, `624`, `623`) concurrently in parallel threads using `ThreadPoolExecutor`.
  - Reduced detection time for offline, dead, or unreachable target IPs from **18.0 seconds** (6 sequential timeouts) down to **~1.5–2.0 seconds** (single parallel timeout), preventing long hangs at the end of large subnetwork scans.
- Release v6.13.2

## [6.13.1] – 2026-08-19

### Fixed
- **Resilient BMC Collection & Timeout Isolation**:
  - Reduced per-BMC worker thread pool (`_BMC_INNER_WORKERS`) from 6 to 3 and capped drive/DIMM sub-threadpools to 3 to prevent overwhelming BMC embedded HTTP servers.
  - Eliminated global cascading timeout throttle in `_get()`; protected timeout state under lock and automatically reset timeout counter on successful GETs and phase boundaries.
  - Added per-item `try...except` fault isolation in firmware inventory, storage subsystem, and network adapter collection loops so single-item timeouts do not discard whole sections.
- Release v6.13.1

## [6.13.0] – 2026-08-19

### Added
- **Fleet Summary & Combined Report Sorting**:
  - Prefixed main combined tabbed report (`00_fleet_combined.html`) and standalone executive summary (`00_fleet_summary.html`) with `00_` so they sort to the top when sorted alphabetically by name.
  - Re-ordered scan completion workflow so `00_fleet_combined.html` and `00_fleet_summary.html` modification timestamps (`mtime`) are updated last, guaranteeing top placement when sorting by Date Modified.
- **Organized Scan Output Directory Structure**:
  - Reorganized scan output directories with dedicated `reports/` and `data/` subfolders.
  - Per-host HTML assessment reports (`vsphere_vsan_report_<IP>.html`) are saved to `reports/`.
  - Fleet summary manifests (`fleet_summary.json`), per-host summary JSON files (`vcf_summary_<IP>.json`), and debug log files (`vcf_assess_debug.log`) are saved to `data/`.

### Changed
- **Relative Path Navigation & File Serving**:
  - Updated hyperlinks in `00_fleet_summary.html` to point to `reports/vsphere_vsan_report_<IP>.html`.
  - Enhanced web server static file endpoint (`_serve_report`) to fall back across root, `reports/`, and `data/` subfolders for backward-compatible file serving.
- Release v6.13.0

## [6.12.3] – 2026-08-14

### Added
- **Summary Report Performance & Fleet Scaling**:
  - Added `--include-raw` CLI option and web UI checkbox to decouple raw Redfish API capture from structured summary JSON exports (`--save-json`).
  - Added `--no-combined` CLI flag and gated combined tabbed report generation (`fleet_combined.html`) to fleets of <= 64 hosts (matching max single vSphere cluster size).
  - Added `vcf_hci/summary_io.py` helper for version 2 fleet summaries with automatic `.json.gz` compression (>= 1 MiB) and multi-part chunking (> 100 hosts or > 8 MiB).
  - Added `POST /api/import-summary-file` streamed upload endpoint in web UI for importing large or compressed summary files (> 8 MB, `.gz`, `.zip`) directly.
  - Added `--lean` CLI flag and web UI checkbox for Lean Scan mode, skipping telemetry, firmware inventory member GETs, and extra thermal sensor GETs.

### Changed
- Release v6.12.3

## [6.12.2] – 2026-08-14

### Changed
- Release v6.12.2

## [6.12.1] – 2026-08-14

### Changed
- Release v6.12.1

All notable changes to the VCF Readiness Tool are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)  
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [6.12.0] – 2026-08-13

### Added
- **BMC Time Drift & Time Skew Detection**: Added automatic calculation of BMC clock drift relative to scanner time. Triggered time skew warnings in the Security tab and report headers if BMC clock is skewed by >5 minutes.
- **Enhanced OEM NTP Server Extraction**: Improved NTP server discovery from Redfish `NetworkProtocol` across Dell, HPE, Supermicro, Cisco, and Lenovo BMCs.
- **Unit Testing**: Added dedicated `tests/test_ntp_timedrift.py` test suite covering NTP server extraction and time drift parsing.

### Fixed
- **Dark Mode Button Icon Rendering**: Fixed an issue where the theme toggle button rendered ` Dark` with replacement characters (`\uFFFD`) due to UTF-16 surrogate handling in HTML report sanitization. Replaced surrogate escape sequence with native UTF-8 crescent moon icon (`🌙 Dark` / `☀️ Light`).
- **Resilient BMC Communications**: Added socket timeout handling, exponential retry logic, and fallback response decoding (`errors="replace"`) for Redfish HTTP requests and Dell TechDirect API calls.

## [6.11.1] – 2026-08-13

### Fixed
- **CPU & Server Chassis Certification Badges**:
  - Differentiated between fully certified OEM chassis and models requiring vendor qualification confirmation (e.g., Dell 14G Cascade Lake platforms such as PowerEdge R740xd showing "Confirm with Vendor").
  - Added clickable CPU model deep links directly to Broadcom Compatibility Guide (BCG) CPU searches.
  - Suppressed the "Host Operating System" card when no OS data is reported by the BMC.
  - Cleaned CPU architecture summary label by removing redundant "Intel" / "AMD" vendor prefixes.

## [6.11.0] – 2026-08-13

### Added
- **Tier-1 OEM Server + CPU Compatibility Matrix**: Added `BCG_OEM_CERTIFIED_SERVERS` mapping certified Tier-1 server platforms (Dell PowerEdge, HPE ProLiant, Supermicro, Cisco UCS, Lenovo ThinkSystem) to `vcf_hci/constants.py`. Updated `VCF9CompatibilityEngine.evaluate_cpu` across Redfish and WS-Man collectors to upgrade certified Cascade Lake-SP platforms to `🟢 VCF 9.x Supported (Deprecated)`.
- **`get_nested` Null-Safe Dictionary Helper**: Added `get_nested(d, *keys, default=None)` helper function in `vcf_hci/logging_utils.py` to traverse nested dictionaries safely without raising `AttributeError` on intermediate `null`/`None` values.

### Fixed
- **Robust OEM Hook & Collector Dictionary Traversals**: Updated all OEM collector hooks (`dell.py`, `hpe.py`, `lenovo.py`, `supermicro.py`, `cisco.py`) and collector mixins (`collect_system.py`, `collect_network.py`, `collect_storage.py`, `collect_power.py`, `pci_utils.py`, `base.py`, `host_report.py`, `fleet_report.py`, `server.py`, `obfuscation.py`) to prevent `'NoneType' object has no attribute 'get'` exceptions when Redfish BMCs return explicit `null` fields.
- **Unit Test Coverage & Safeguards**: Added unit test coverage for `get_nested` in `tests/test_logging_utils.py` and null OEM attribute structures in `tests/test_collector_oem.py`.

## [6.10.1] – 2026-08-13

### Fixed
- **Null Redfish Attribute Handling**: Protected chained `.get()` dictionary calls across `collect_system.py`, `collect_storage.py`, and `base.py` against explicit `null`/`None` values in Redfish JSON responses (e.g. `"ProcessorSummary": null`, `"Oem": {"Dell": null}`).
- **Drive Health & Status Safeguards**: Updated `drive_health` parsing in `collect_storage.py` to default to `"OK"` when `Status` returns `{"Health": null}`.
- **Defensive Report Rendering**: Safely converted string health and protocol attributes to `str` before calling `.upper()` in `host_report.py` and `components.py`, preventing `AttributeError: 'NoneType' object has no attribute 'upper'`.
- **Null Attribute Unit Test Suite**: Added `TestNullAttributeHandling` in `tests/test_collector_oem.py` and `test_null_drive_health_rendering` in `tests/test_host_report.py`.

## [6.10.0] – 2026-08-13

### Fixed
- **Dell PowerEdge R750 NIC Name Misattribution**: Fixed `_resolve_product_name()` in `vcf_hci/collector/base.py` to handle `None` part numbers cleanly, added `"poweredge rx5xx lom board"` to `GENERIC_NAME_BLOCKLIST`, and implemented fallback inspection of `Oem.Dell.DellNIC.ProductName` via `NetworkDeviceFunctions` links so embedded NICs resolve correctly (e.g. `Broadcom NetXtreme Gigabit Ethernet`) rather than matching SATA controllers.
- **NVMe Drive PCI Quad Extraction & BCG Links**: Expanded `_generic` blocklist in `vcf_hci/bcg_links.py` to filter `"NOT AVAILABLE"` strings. Enhanced `match_pcie_cache()` in `vcf_hci/collector/pci_utils.py` to recursively inspect `PCIeFunctions` collection endpoints (`Links.Drives` / `Oem.Dell.DellPCIeFunction.Id`), resolving exact PCI quads (`144d:a824:144d:a816`) and generating valid PCI ID deep-links on Broadcom's HCL guide.
- **Dell PowerEdge R750 Test Fixture**: Added anonymized `tests/fixtures/dell_r750_summary.json` fixture and `tests/test_r750_fixture.py` unit test suite verifying zero PII leakage, correct NIC name resolution, exact NVMe PCI quad extraction, and HTML report generation.

## [6.9.3] – 2026-08-13

### Fixed
- **HPE SmartStorage Drive Capacity & Firmware Extraction**: Updated `_parse_drive_details` in `collect_storage.py` to evaluate `CapacityGB`, `CapacityMiB`, and `CapacityLogicalBlocks` when standard DMTF `CapacityBytes` is omitted by HPE SmartStorage Redfish endpoints. Fixed drive firmware extraction to read nested `FirmwareVersion.Current.VersionString` (e.g., `HPG2`).
- **HPE Storage Controller Model & Firmware Formatting**: Created `_extract_fw_version` in `collect_storage.py` to parse nested dictionary `FirmwareVersion` objects (`{"Current": {"VersionString": "2.65"}}`) into clean strings. Refined controller model selection to prefer specific `Model` strings (e.g., `HPE Smart Array P408i-a SR Gen10`) when `Name` contains generic placeholder text.
- **Firmware Inventory UI & Backplane Microcontroller Context**: Added `device_context` (`Box=1`) and target `id` tracking to `collect_firmware_inventory` in `collect_system.py` and updated `host_report.py` to distinguish individual UBM backplane microcontroller targets. Clarified "Updateable" column rendering ("Yes (Flashable)" / "No (Fixed)") with explanatory tooltip explaining Redfish UpdateService capability.

## [6.9.2] – 2026-08-13

### Fixed
- **Dell iDRAC Service Tag / SKU Disambiguation**: Resolved issue where Dell iDRAC Redfish populates `System.SKU` with the Service Tag (e.g., `7SBKS13`), causing Service Tags to be mislabeled as "SKU" in HTML reports. Overrode `oem_sku` in `DellCollector` and updated `collect_system.py` to filter out duplicate Service Tags.
- **SKU Obfuscation & Raw Capture Scrubbing**: Updated `vcf_hci/obfuscation.py` to obfuscate distinct order SKUs (e.g., `321-BCQQ` -> `SKU-XXXXXX`) or clear duplicate Service Tag SKUs, and scrubbed `real_sku` from `raw_redfish_capture` payloads.
- **Report Header SKU Rendering**: Updated `vcf_hci/report/host_report.py` to suppress duplicate SKU header sections and wrap distinct SKUs in `class="pii"` spans for the in-browser mask toggle and obfuscated report downloads.

## [6.9.1] – 2026-08-13

### Fixed
- **HPE NVMe OEM Drive & Part Number Population**: Enhanced `_parse_drive_details` in `collect_storage.py` to extract `product_id` and `model` from HPE iLO OEM fields (`SparePartNumber`, `OptionPartNumber`, `AssemblyPartNumber`, `Model`, `Description`, `DriveName`), ensuring accurate part number population for HPE NVMe drives.
- **TLC vs QLC NVMe Badge Disambiguation**: Separated QLC detection (`_is_qlc`) from high-capacity NVMe (>4TB) evaluation in `cross_reference.py`. High-capacity TLC NVMe drives (>4TB) are now accurately labeled with `🔮 Large NVMe (>4TB) — Not vSAN Certified` instead of being mislabeled as QLC.
- **HPE & Vendor NVMe Model Alias HCL Cross-Referencing**: Added `_clean_drive_model` for stripping OEM part number suffixes (e.g., `-000H3`, `-000AU`) and introduced `_MODEL_FAMILY_ALIASES` to map vendor drive family prefixes (Samsung `MZXLR`/`MZWLR`/`MZ3LR` -> `PM1733a`, Kioxia `KCM6`/`KCD6` -> `CM6`/`CD6`, Micron, Solidigm) with capacity-based token scoring against the vSAN HCL CSV database.

## [6.9.0] – 2026-08-13

### Added
- **ECO 1: Strict Hex PCI ID Normalization**: Upgraded `normalize_pci_id()` with full-string boundary regex validation (`r'^(?:pci\\|0x|ven_|dev_|subsys_)*([0-9a-fA-F]{1,4})$'`) and strict range checking (`0 <= val <= 0xFFFF`) to disambiguate concatenated strings and prevent false-positive extraction (e.g. `DEV_14e4` -> `14e4`).
- **ECO 5: Ingestion Schema Guarding (`sanitize_hcl_entry`)**: Added schema sanitizer in Layer D (`vcf_hci/hcl/loader.py`) to enforce safe structural defaults across Broadcom live HCL JSON and dark-site bundles.
- **ECO 3: Isolated Sub-Namespaces for `hcl_index`**: Structured `hcl_index` into isolated sub-dictionaries (`quads`, `pairs`, `models`, `csv_drives`) while maintaining root aliases (`_pci_quads`, `_pci_pairs`) for 100% backward compatibility and zero key collision risk.
- **ECO 2: Emerald Rapids & Intel Xeon 6 CPU Series Mapping**: Broadened BCG CPU deep-link taxonomy generator (`vcf_hci/bcg_links.py`) to support Emerald Rapids (5th Gen Xeon Scalable) and Intel Xeon 6 series (`cpuSeries=%5BIntel%20Xeon%206%20Series%5D`).
- **ECO 4: Formalized Redfish Session Lifecycle & Request Timeout Discipline**: Added `RedfishSessionManager` and automatic session deletion (`DELETE`) on exit in `vcf_hci/collector/base.py`, enforcing a strict 15-second socket timeout on all BMC HTTP requests.

## [6.8.4] – 2026-08-13

### Added
- **NVMe SMART & Storage Health Telemetry Monitoring**: Added support for 20 high-value SMART metrics aligned with OCP Datacenter NVMe SSD Spec v2.6, extracted directly from standard Redfish drive properties, embedded `Metrics` objects, and vendor OEM extensions with zero additional HTTP scan latency.
- **Dedicated Health Tab SMART Card**: Added `💾 NVMe SMART & Drive Health Summary` accordion card in HTML host reports under the Health tab (`tab-health`) featuring high-level alert badges and a detailed per-drive telemetry table (Slot, Model, Protocol, Role, Health, Endurance %, Temp/Throttling, Unsafe Shutdowns, Media Errors, Spare %, WAF, Bad Blocks, PCIe Bus & Width, Workload/POH).
- **Vendor-Specific OEM Telemetry Extensions**: Extracted extended SMART fields across all 5 supported BMC vendors: Dell iDRAC (`Oem.Dell.DellPhysicalDisk`), HPE iLO (`Oem.Hpe` / `/SmartStorage`), Lenovo XCC (`Oem.Lenovo.Drive`), Supermicro (`Oem.Supermicro` / `StorageMetrics`), and Cisco IMC (`Oem.Cisco` / `CIMC`).
- **Fleet Fault Roster Integration**: Integrated drive SMART health alerts (predictive failure flags, low endurance <20%, media errors, unsafe shutdowns) directly into the System Assessment Summary and fleet Hardware Fault Roster.
- **Unit Test Coverage**: Added `test_nvme_smart_health_section_rendering` unit test in `tests/test_host_report.py`.

## [6.8.3] – 2026-08-12

### Added
- Summary JSON export capabilities in both Web UI ("Save summary JSON" checkbox + "Export Summary JSON" button) and CLI (`--save-json` flag) for instant offline report rendering and analysis.
- Maximized raw Redfish capture capability (`raw_redfish_capture`) when either **Enable debug log** or **Save summary JSON** is enabled, collecting complete un-truncated raw BMC HTTP GET response bodies across system, chassis, manager, update service, telemetry, and license endpoints.
- Built-in PII sanitization for `raw_redfish_capture` payload fields (serial numbers, IPs, hostnames, asset tags) when obfuscated mode is enabled.
- New unit test suite in `tests/test_summary_json.py` covering raw Redfish capture, conditional execution, obfuscation, and HTTP summary JSON export API.

### Changed
- Maximized raw Redfish capture is disabled by default during standard scan operations to keep scan payloads and memory lean.

## [6.8.2] – 2026-08-12

### Fixed
- Storage controller deduplication across standard `/Storage` and HPE OEM `/SmartStorage` endpoints by controller serial number, PCI quad, and attached drive serials.
- Fixed drive protocol detection for HPE SAS drive models (e.g. `MM1000GBKAL`, `EG`/`AL` series) and vendor OEM interface/protocol fields.
- Prevented unpopulated and non-NVMe drives from defaulting to PCIe/NVMe and ghost U.2 connectors in report diagrams.
- Added comprehensive unit tests for SAS drive protocol parsing and controller deduplication in `tests/test_collector_oem.py`.

## [6.8.1] – 2026-08-12

### Fixed
- Fixed drive bay SVG diagram header text compression by enforcing a minimum SVG panel width of 380px and centering drive bay grid cells.
- Cleaned up model chassis database entries (`DELL_MODEL_CHASSIS_DB`) and added title string sanitization to eliminate slash-separated form factor confusion (e.g. `/ 4 LFF`).

### Documentation
- Updated `README.md`, `CONTRIBUTING.md`, `docs/OEM_REFERENCE.md`, and `docs/adding-oem-support.md` to invite server OEMs and hardware vendors to contribute chassis maps, front-panel SVG diagrams, order SKU databases, and sanitized Redfish mockups.

## [6.8.0] – 2026-08-12

### Fixed
- Excluded empty storage controllers (such as sSATA AHCI controllers with no populated drives) from chassis bay aggregation and SVG diagram rendering.
- Enforced strict chassis capacity bounds (`0..target_total-1`) in drive bay diagram, eliminating synthetic/phantom empty slot expansion.
- Enhanced Dell Redfish drive location parsing to extract physical slot numbers from Dell drive naming patterns (`PCIe SSD in Slot X` and `Solid State Disk 0:X:0`).
- Improved unified front chassis bay consolidation for shared 2.5" SFF drive backplanes between HBA/PERC controllers and CPU-attached NVMe drives.

## [6.7.0] – 2026-08-12

### Added
- Consolidated physical drive bay chassis visualization across all host storage controllers into a single unified front chassis diagram.
- Added `DELL_SKU_CHASSIS_DB` mapping Dell order SKUs (e.g. `321-BCQQ`) to drive slot counts and chassis descriptions.
- Exact 2x5 grid layout for 10-bay 2.5" SFF chassis (Dell R640 `321-BCQQ`, HPE DL360, etc.) with slot pairing (Slot 0 top-left, Slot 1 bottom-left).
- Dynamic SVG drive slot color coding for NVMe (Emerald), EDSFF (Orange), SATA/SAS (Indigo), HDD (Teal), and Empty Slots (Slate).
- Interactive drive detail cards on hover and click (`showChassisBayInfo`) displaying drive model, part number, capacity, protocol, attached controller, health, endurance, and vSAN status.

---

## [6.6.0] – 2026-08-11

### Added
- Granite Rapids (Intel Xeon 6) CPU die topology, socket parsing, and NUMA profile details (HCC, XCC, UCC, LCC).

### Fixed
- Fixed Redfish test connection auth check to validate credentials against `/redfish/v1/Systems` and `/redfish/v1/Managers` (Issue #4).
- Prevented false positive tri-mode RAID warnings on direct CPU/PCIe-attached NVMe and M.2 drives (Issue #5).
- Added fallbacks for `TotalSystemMemoryKiB`/`TotalSystemMemoryMiB` and DIMM capacity sum when system memory is reported as 0MB (Issue #6).
- Added speed fallback to rated adapter capability / port max speeds when NIC link is down/disconnected (Issue #7).
- Capped memory interleaving recommendations based on physical motherboard slot count (Issue #8).
- Added destination target BMC IP address to top header banner of host HTML reports (Issue #9).
- Expanded syslog configuration detection across DMTF `LogServices`, `SyslogService`, and vendor endpoints (Issue #10).
- Fixed Windows pytest CI failure in `test_root_user.py` for platforms lacking POSIX `os.geteuid`.

---

## [6.5.1] – 2026-08-11

### Fixed
- Accordion unpopulated/empty storage controllers in the host report Drive Bays section.
- Drive bay SVG chassis diagrams light/dark theme adaptability via CSS variables.
- Top navigation tab styling in light mode.
- NUMA & Chiplet architecture diagram box contrast in dark mode.
- Power Health summary tile text contrast in dark mode for fleet report.

---

## [6.5] – 2026-08-07

### Added
- Browser-based UI (`redfish_web.py` + `vcf_hci/web/`) powered by Clarity Design System
  tokens; replaces the Tkinter GUI as the recommended interface.
- Dark mode for all HTML reports: respects OS preference (`prefers-color-scheme`) and
  persists user override to `localStorage`.
- Dark mode toggle for the Tkinter GUI (`redfish_gui.py`), persisted across sessions.
- Server-Sent Events (SSE) for real-time scan progress in the browser UI.
- Combined tabbed HTML report (`fleet_combined.html`) from the browser UI.
- Session and profile persistence in the browser UI (`~/.vcf-readiness-*.json`).
- `tools/bundle_assets.py` dev utility for refreshing the embedded Clarity CSS.

### Fixed
- `UnicodeEncodeError: surrogates not allowed` when scanning Dell iDRAC hosts whose
  firmware returns JSON strings with lone Unicode surrogate characters (e.g. PowerEdge
  R640 14G with certain iDRAC 9 firmware). Reports now write successfully, substituting
  U+FFFD for the unrepresentable characters.

---

## [6.2.0] — 2026-07-xx (Refactor Release)

### Added

- **Modular package structure** — `redfish_collector.py` converted to a `vcf_hci/` Python package.
  The original file is now a thin backward-compatibility shim.
- **OEM ABC pattern** — `BaseRedfishCollector` ABC with pluggable hook methods (`oem_bios_date`,
  `oem_storage_endpoints`, `oem_drive_endurance`, `oem_handle_retry`, etc.).
  New vendors require only a single file in `vcf_hci/collector/oem/`.
- **OEM subclasses**: `DellCollector`, `HPECollector`, `SupermicroCollector`, `CiscoCollector`,
  `LenovoCollector`, `IntelBMCCollector`, `GenericCollector`.
- **`create_collector()` factory** — auto-detects vendor from Redfish Manufacturer field.
- **`vcf-assess` console script** — installable entry point via `pyproject.toml`.
- **`python -m vcf_hci`** — direct package execution via `vcf_hci/__main__.py`.
- **`pyproject.toml`** — modern Python project metadata with zero runtime dependencies.
- **Test suite** (`tests/`) — pytest tests for `compat_engine`, `bcg_links`, `hcl.cross_reference`,
  `obfuscation`, and all OEM hook overrides.
- **`CONTRIBUTING.md`** — step-by-step guide for adding OEM adapters.
- **`docs/adding-oem-support.md`** — full ABC interface reference.
- **GitHub Actions CI** — pytest on every push and PR (`ci.yml`).
- **GitHub Actions release pipeline** — PyInstaller Mac + Windows binaries on version tags (`release.yml`).

### Changed

- `build.sh` and `build.bat` updated to use `--collect-all vcf_hci` for PyInstaller.
- `ARCHITECTURE.md` updated to reflect new package layout and OEM hook API.

### Backward Compatible

- `redfish_collector.py` shim re-exports all names previously imported by `redfish_gui.py`.
- `from redfish_collector import (UniversalRedfishCollector, ...)` continues to work without changes.

---

## [6.0.0] — 2026-06-xx

### Added

- Intel Xeon 6 (Granite Rapids) CPU detection and full VCF 9.1 support classification.
- QLC NVMe drive flagging for `detect_qlc_nvme()` covering Samsung BM1743, Micron 6500/6600 ION,
  Kioxia CD8p/LC9, Solidigm D5-P5430, and SK Hynix PE8010 series.
- Drive firmware baseline evaluation (`evaluate_drive_fw()`) for Samsung PM9A3 and Intel P4510/P4610.
- Memory interleaving topology analysis (`MemoryInterleavingEngine`) for NUMA/UMA detection.
- LLDP neighbor discovery from `/Systems/{id}/EthernetInterfaces` OEM fields.
- Fleet obfuscation mode (`--obfuscate-pii`) with deterministic PII redaction.
- AMD EPYC Siena (8004 series) and Bergamo (9754/9754S) recognition.
- Cisco IMC dynamic system path discovery from serial number.
- Supermicro DCMS license gate detection with user-facing badge.

### Changed

- vSAN HCL cross-reference now auto-selects the newest CSV by filename date.
- HPE SmartStorage array controller scraping uses member pagination.

### Fixed

- Cascade Lake-SP incorrectly showing as "Unsupported" for some ES-series SKUs.
- HPE `ResourceNotReadyRetry` retry logic no longer loops indefinitely.

---

## [5.x] — (Pre-refactor, single-file era)

Previous versions were distributed as a single `redfish_collector.py` file. See git history for per-commit changes.
