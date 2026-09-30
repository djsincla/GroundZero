# VCF Operations Management Pack (Experimental) — Deployment, Sizing & Operations Guide

> **Experimental / Tech Preview Notice:**
> The VCF Operations Management Pack (`VcfReadinessAdapter_9.7.0_EXPERIMENTAL.pak`) is currently an experimental tech preview integration. It is provided for evaluation and lab testing to explore day-2 hardware telemetry and readiness scoring inside VMware Cloud Foundation Operations 9.x and VMware Aria Operations 8.10+.

## 1. Supported Platform Versions & Requirements

The **VCF Readiness Management Pack (VCF-R)** (`VcfReadinessAdapter`) is architected for modern containerized VMware Operations deployments:

- **Supported Platforms:**
  - VMware Cloud Foundation Operations (VCF Operations) 9.0, 9.1, and future 9.x releases.
  - VMware Aria Operations 8.10, 8.12, 8.14, 8.16, 8.18 on-premises.
- **Collector Architecture:**
  - Requires deployment onto a **Cloud Proxy** collector node located with Layer 2/3 reachability to the server Out-of-Band (OOB) BMC network.
  - *Legacy Remote Collectors (pre-8.10)* are not supported by design because the Integration SDK executes containerized micro-adapters.
- **Network Requirements:**
  - HTTPS / Port 443 outbound from Cloud Proxy to target BMC IP addresses.
  - TLS 1.2+ support on BMC controllers (Dell iDRAC 8/9, HPE iLO 4/5/6, Supermicro BMC, Cisco IMC, Lenovo XCC).

---

## 2. Installation & PAK Signing Policy

### Unsigned PAK Installation in VCF Operations 9.x
In VCF Operations 9.x, unsigned Management Pack installations are blocked by default as a security baseline. To enable community and custom integration packs:

1. Log into the **VCF Operations Admin UI** as local `admin`:
   ```
   https://<vcf-ops-fqdn>/admin
   ```
2. In the left navigation menu, navigate to **Administrator Settings** &rarr; **Security Settings**.
3. Toggle **Enable Unsigned PAK Installation** to **Enabled**.
4. Save the security settings.
5. In the standard VCF Operations Product UI, navigate to **Data Sources** &rarr; **Integrations** &rarr; **Repository**.
6. Click **Add** and upload `VcfReadinessAdapter_9.7.0_EXPERIMENTAL.pak`.
7. Accept the EULA and check **Ignore Signature Verification** to complete installation.

*(Note: In VMware Aria Operations 8.x, unsigned installation is accepted directly via the installation dialog checkbox without modifying global Admin UI settings).*

### PAK Signing & Container Integrity
- **Broadcom / VMware Signatures:** Cryptographic PAK file signatures are issued through Broadcom's VMware Technology Alliance Partner (TAP) certification program. Community management packs ship unsigned.
- **Container Digest Verification:** The container base image is pinned to the official VMware Integration SDK registry (`projects.packages.broadcom.com/vmware_aria_operations_integration_sdk/base-adapter:python-0.10.3`), guaranteeing runtime container base integrity.

---

## 3. Sizing, Scaling & Fleet Architecture

### Sizing Guidelines

| Fleet Size | Adapter Instances | Cloud Proxies | Concurrency (`max_collection_threads`) | Polling Interval |
|---|---|---|---|---|
| **1 – 100 BMCs** | 1 Adapter Instance | 1 Cloud Proxy | 10 – 25 Threads | 24h Deep / 5m Fast Health |
| **101 – 250 BMCs** | 1 Adapter Instance | 1 Cloud Proxy | 25 – 50 Threads | 24h Deep / 5m Fast Health |
| **251 – 1,000 BMCs** | 2 – 4 Instances (split by rack/subnet) | 2 Cloud Proxies (Collector Group) | 25 – 50 Threads/Instance | 24h Deep / 5m Fast Health |
| **1,000+ BMCs** | N Instances (~250 hosts/instance) | Dedicated Collector Group | 50 Threads/Instance | 24h Deep / 5m Fast Health |

### Architecture Principles

1. **Pinning to Nearest Cloud Proxy:**
   Deploy the adapter instance on the Cloud Proxy residing in the same data center or security zone as the BMC management subnet. Avoid scanning BMCs across high-latency WAN links.
2. **2-Tier Polling Strategy:**
   - **Daily Deep Inventory Scan (24h TTL):** Performs comprehensive multi-mixin Redfish discovery, component inventory, VCF 9.1 / vSAN ESA rule analysis, and BCG link generation. Emits static configuration properties with zero database churn.
   - **Fast Health Ticks (5m default):** On intermediate collection cycles, the adapter executes a single 1-call status query against `/redfish/v1/Chassis`. This detects hardware faults, fan failures, and power supply trips within minutes without overloading embedded BMC microcontrollers.
3. **Thread-Safe Bounded Concurrency:**
   The adapter uses Python's standard `concurrent.futures.ThreadPoolExecutor` bounded by the `max_collection_threads` configuration knob (default 25, clamped between 1 and 100).
4. **Persistent JSON Scan Caching:**
   Inventory state is cached in persistent storage (`/data/vcf-readiness-cache/scan_cache.json`) inside the container volume. If a Cloud Proxy container restarts, it loads cached hardware profiles immediately, avoiding thundering-herd rescans across the entire physical fleet.

---

## 4. Configuration Parameter Reference

When adding or editing a **VCF Readiness Adapter** account instance in VCF Operations, the following parameters are available:

| Configuration Key | Label | Type | Default | Description |
|---|---|---|---|---|
| `bmc_targets` | BMC Target Hosts / Subnets | String | *Required* | Comma-separated BMC IP addresses, hostnames, or CIDR ranges (e.g. `192.168.1.50`, `10.10.0.0/24`). |
| `username` | BMC Username | String | *Required* | Administrative or read-only Redfish user (e.g. `root`, `administrator`). |
| `password` | BMC Password | Password | *Required* | BMC account password. |
| `inventory_scan_interval_hours` | Deep Inventory Scan Cadence (Hours) | Integer | `24` | Cadence in hours to run full hardware inventory, VCF 9.1 compatibility evaluation, and BCG link generation. Default is 24 hours. |
| `enable_quick_health_polling` | Enable Intermediate Fast Health Polling | Boolean | `true` | If true, short collection cycles perform a single lightweight 1-call chassis health probe (~200ms) to detect hardware faults between daily scans. |
| `enable_telemetry_metrics` | Collect Real-Time Power & Thermal Metrics | Boolean | `false` | Enable time-series power draw (W) and temperature (°C) metrics. Keep disabled if you only want inventory and readiness tracking to minimize database retention. |
| `timeout_seconds` | BMC HTTP Connection Timeout | Integer | `15` | Timeout in seconds for Redfish HTTPS requests to individual BMCs. |
| `correlate_vcenter_hosts` | Correlate with vCenter HostSystem Objects | Boolean | `true` | Automatically link PhysicalServer objects to corresponding VMware ESXi HostSystem objects using hardware UUIDs and Service Tags. |
| `max_collection_threads` | Max Parallel Collection Threads | Integer | `25` | Maximum number of worker threads to scan multiple BMCs concurrently (bounded between 1 and 100). |
| `max_deep_scans_per_cycle` | Max Deep Scans Per Collection Cycle | Integer | `50` | Upper bound on how many BMCs undergo a full deep inventory scan within a single collection cycle. Hosts over the budget serve cached data and are scanned on subsequent cycles. |

---

## 5. Troubleshooting & Diagnostics

### Viewing Cloud Proxy Collector Logs
Collector execution logs are located on the Cloud Proxy node at:
```bash
/storage/vcops/log/collector/collector.log
/storage/vcops/log/adapters/VcfReadinessAdapter/adapter.log
```

### Common Issues & Remediation

1. **Authentication Failures (HTTP 401 / 403):**
   - *Symptom:* `Authentication failed on BMC <ip>: HTTP 401 Unauthorized.`
   - *Cause:* Invalid BMC credentials or account locked out due to BMC security policy.
   - *Fix:* Verify credentials via standard curl / browser against `https://<bmc-ip>/redfish/v1/`. Ensure the service account has Operator or Administrator privileges on the BMC.
2. **Embedded Web Server 404 HTML Responses:**
   - *Symptom:* JSON decode error parsing Redfish responses on legacy BMC firmware (e.g. Supermicro Lighttpd).
   - *Mitigation:* The adapter wraps all HTTP parsing in defensive `try/except json.JSONDecodeError` blocks and gracefully falls back to available endpoints without aborting collection for the host.
3. **vCenter HostSystem Correlation Not Linking:**
   - *Symptom:* PhysicalServer objects appear without parent relationships to vCenter ESXi hosts.
   - *Cause:* The vCenter Management Pack (VMWARE) has not yet discovered the corresponding ESXi host, or UUID formatting differences.
   - *Fix:* Ensure the vCenter adapter instance is collecting from the vCenter managing these compute nodes. The adapter normalizes both hyphenated and unhyphenated BIOS UUIDs automatically.

---

## 6. vCommunity Hardware Management Pack Roadmap

The **VCF-Operations-Hardware-vCommunity** initiative provides open-source hardware adapters for VMware Cloud Foundation Operations.

- **Phase A (Coexistence):** Side-by-side deployment of `VcfReadinessAdapter` alongside vendor-specific community packs.
- **Phase B (Shared Dashboards):** Unified dashboard templates referencing both multi-vendor `PhysicalServer` resources and vendor-specific metrics.
- **Phase C (Consolidation):** Offering `vcf_hci` as a unified multi-vendor backend collection engine while preserving existing resource kind identifiers for historical continuity.
