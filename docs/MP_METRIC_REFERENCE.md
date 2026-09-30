# VCF Operations Management Pack (Experimental) — Metric & Attribute Reference

> **Adapter Kind:** `VcfReadinessAdapter` | **Status:** Experimental / Tech Preview
> **Notice:** The VCF Operations Management Pack (`VcfReadinessAdapter_9.7.0_EXPERIMENTAL.pak`) is currently an experimental integration. Metrics, properties, and resource kinds are subject to evolution as integration requirements develop.

This document provides the complete specification of all Resource Kinds, identifiers, properties, and time-series metrics emitted by the GroundZero Management Pack into VMware Cloud Foundation Operations / VMware Aria Operations.

---

## Table of Contents

- [PhysicalServer](#physicalserver)
- [Processor](#processor)
- [StorageController](#storagecontroller)
- [PhysicalDrive](#physicaldrive)
- [NetworkAdapter](#networkadapter)
- [PowerSupplyUnit](#powersupplyunit)

---

## PhysicalServer

**Display Name:** Physical Server  
**Description:** Monitored physical bare-metal server chassis

### Identifiers

| Key | Name | Data Type | Key Identifier | Required |
|---|---|---|---|---|
| `bmc_ip` | BMC IP Address | `string` | `Yes` | `Yes` |
| `serial_number` | Serial Number | `string` | `No` | `No` |
| `system_uuid` | System UUID | `string` | `No` | `No` |

### Configuration Properties

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `hardware|vendor` | OEM Vendor | `string` | — | OEM Vendor |
| `hardware|model` | Server Model | `string` | — | Server Model |
| `hardware|sku` | Server SKU | `string` | — | Server SKU |
| `hardware|bios_version` | BIOS Version | `string` | — | BIOS Version |
| `hardware|bios_date` | BIOS Release Date | `string` | — | BIOS Release Date |
| `hardware|bmc_firmware` | BMC Firmware Version | `string` | — | BMC Firmware Version |
| `hardware|total_memory_gb` | Total Memory (GB) | `float` | `GB` | Total Memory (GB) |
| `hardware|dimm_count` | DIMM Count | `integer` | — | DIMM Count |
| `hardware|cpu_socket_count` | CPU Sockets | `integer` | — | CPU Sockets |
| `hardware|total_cores` | Total Physical Cores | `integer` | — | Total Physical Cores |
| `vcf9|overall_verdict` | Overall Readiness Verdict | `string` | — | Overall Readiness Verdict |
| `vcf9|vsan_esa_status` | vSAN ESA Status | `string` | — | vSAN ESA Status |
| `vcf9|cpu_support_tier` | CPU Support Tier | `string` | — | CPU Support Tier |
| `vcf9|boot_mode` | Boot Mode | `string` | — | Boot Mode |
| `vcf9|tpm_status` | TPM 2.0 Status | `string` | — | TPM 2.0 Status |
| `vcf9|vmd_status` | Intel VMD Status | `string` | — | Intel VMD Status |
| `vcf9|secure_boot` | Secure Boot Status | `string` | — | Secure Boot Status |
| `vcf9|bios_baseline_status` | BIOS Baseline Status | `string` | — | BIOS Baseline Status |
| `vcf9|bmc_baseline_status` | BMC Baseline Status | `string` | — | BMC Baseline Status |
| `hardware|health_status` | Chassis Health Status | `string` | — | Chassis Health Status |
| `hardware|chassis_state` | Chassis Power State | `string` | — | Chassis Power State |
| `bcg|server_url` | BCG Server Compatibility URL | `string` | — | BCG Server Compatibility URL |

### Time-Series Metrics

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `vcf9|readiness_score` | Readiness Score | `float` | `%` | Readiness Score |
| `telemetry|power_watts` | Power Draw | `float` | `W` | Power Draw |
| `telemetry|power_peak_watts` | Peak Power Draw | `float` | `W` | Peak Power Draw |
| `telemetry|thermal_max_celsius` | Max System Temperature | `float` | `°C` | Max System Temperature |

---

## Processor

**Display Name:** Processor  
**Description:** Installed CPU processor socket

### Identifiers

| Key | Name | Data Type | Key Identifier | Required |
|---|---|---|---|---|
| `socket_id` | Socket ID | `string` | `Yes` | `Yes` |
| `bmc_ip` | Parent BMC IP | `string` | `No` | `Yes` |

### Configuration Properties

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `hardware|model` | Processor Model | `string` | — | Processor Model |
| `hardware|family` | Microarchitecture | `string` | — | Microarchitecture |
| `hardware|cores` | Cores | `integer` | — | Cores |
| `hardware|threads` | Threads | `integer` | — | Threads |
| `vcf9|support_tier` | VCF 9.1 Support Tier | `string` | — | VCF 9.1 Support Tier |
| `vcf9|is_supported` | Supported for VCF 9.1 | `string` | — | Supported for VCF 9.1 |
| `bcg|cpu_url` | BCG CPU URL | `string` | — | BCG CPU URL |

### Time-Series Metrics

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| — | No time-series metrics | — | — | — |

---

## StorageController

**Display Name:** Storage Controller  
**Description:** Storage HBA / RAID Controller

### Identifiers

| Key | Name | Data Type | Key Identifier | Required |
|---|---|---|---|---|
| `controller_id` | Controller ID | `string` | `Yes` | `Yes` |
| `bmc_ip` | Parent BMC IP | `string` | `No` | `Yes` |

### Configuration Properties

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `hardware|model` | Controller Model | `string` | — | Controller Model |
| `hardware|firmware_version` | Firmware Version | `string` | — | Firmware Version |
| `hardware|mode` | Storage Mode (HBA/RAID) | `string` | — | Storage Mode (HBA/RAID) |
| `hardware|is_hba_passthrough` | Is Pass-Through HBA | `string` | — | Is Pass-Through HBA |
| `vcf9|esa_compatible` | Compatible with vSAN ESA | `string` | — | Compatible with vSAN ESA |

### Time-Series Metrics

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| — | No time-series metrics | — | — | — |

---

## PhysicalDrive

**Display Name:** Physical Drive  
**Description:** Storage Drive

### Identifiers

| Key | Name | Data Type | Key Identifier | Required |
|---|---|---|---|---|
| `drive_id` | Drive ID | `string` | `Yes` | `Yes` |
| `serial_number` | Serial Number | `string` | `No` | `No` |
| `bmc_ip` | Parent BMC IP | `string` | `No` | `Yes` |

### Configuration Properties

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `hardware|model` | Drive Model | `string` | — | Drive Model |
| `hardware|vendor` | Manufacturer | `string` | — | Manufacturer |
| `hardware|protocol` | Protocol (NVMe/SAS/SATA) | `string` | — | Protocol (NVMe/SAS/SATA) |
| `hardware|media_type` | Media Type (SSD/HDD) | `string` | — | Media Type (SSD/HDD) |
| `hardware|capacity_gb` | Capacity | `float` | `GB` | Capacity |
| `hardware|firmware_version` | Firmware Version | `string` | — | Firmware Version |
| `vcf9|esa_tier` | vSAN ESA Tier Compatibility | `string` | — | vSAN ESA Tier Compatibility |
| `bcg|ssd_url` | BCG SSD URL | `string` | — | BCG SSD URL |

### Time-Series Metrics

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `health|wear_remaining_pct` | Remaining Rated Endurance | `float` | `%` | Remaining Rated Endurance |
| `health|temperature_celsius` | Drive Temperature | `float` | `°C` | Drive Temperature |

---

## NetworkAdapter

**Display Name:** Network Adapter  
**Description:** Physical NIC

### Identifiers

| Key | Name | Data Type | Key Identifier | Required |
|---|---|---|---|---|
| `adapter_id` | Adapter ID | `string` | `Yes` | `Yes` |
| `bmc_ip` | Parent BMC IP | `string` | `No` | `Yes` |

### Configuration Properties

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `hardware|model` | NIC Model | `string` | — | NIC Model |
| `hardware|vendor` | Vendor | `string` | — | Vendor |
| `hardware|firmware_version` | Firmware Version | `string` | — | Firmware Version |
| `hardware|mac_address` | MAC Address | `string` | — | MAC Address |
| `hardware|max_speed_gbps` | Max Speed | `float` | `Gbps` | Max Speed |
| `vcf9|meets_esa_25g_requirement` | Meets ESA >=25GbE Requirement | `string` | — | Meets ESA >=25GbE Requirement |
| `bcg|io_url` | BCG IO URL | `string` | — | BCG IO URL |

### Time-Series Metrics

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `telemetry|link_status` | Link Status | `integer` | — | Link Status |

---

## PowerSupplyUnit

**Display Name:** Power Supply Unit  
**Description:** Chassis PSU

### Identifiers

| Key | Name | Data Type | Key Identifier | Required |
|---|---|---|---|---|
| `psu_id` | PSU ID | `string` | `Yes` | `Yes` |
| `bmc_ip` | Parent BMC IP | `string` | `No` | `Yes` |

### Configuration Properties

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `hardware|model` | PSU Model | `string` | — | PSU Model |
| `hardware|capacity_watts` | Rated Capacity | `float` | `W` | Rated Capacity |
| `hardware|status_health` | Health State | `string` | — | Health State |

### Time-Series Metrics

| Key | Name | Data Type | Unit | Description |
|---|---|---|---|---|
| `telemetry|output_watts` | Output Power | `float` | `W` | Output Power |
| `telemetry|input_voltage` | Input Voltage | `float` | `V` | Input Voltage |

---

## Ops collection keys

The following table documents all collection keys introduced by the multi-tier Ops collection engine across tiers T0 (Heartbeat), T1 (Telemetry), T2 (Component Health), and T3 (Deep Inventory).

Instanced PCIe attributes are addressed per slot using the format `pcie_slot:{label}|attr`.

| Kind | Key | Property or Metric | Tier | Description |
|---|---|---|---|---|
| `PhysicalServer` | `hardware|hostname` | Property | T3 | Server hostname reported by BMC / host assessment |
| `PhysicalServer` | `hardware|boot_target` | Property | T3 | Primary boot target device |
| `PhysicalServer` | `hardware|boot_order` | Property | T3 | Comma-joined persistent boot order sequence |
| `PhysicalServer` | `hardware|chassis_label` | Property | T3 | Chassis label or enclosure asset tag |
| `PhysicalServer` | `hardware|bmc_model` | Property | T3 | BMC controller hardware model string |
| `PhysicalServer` | `hardware|bmc_license` | Property | T3 | BMC enterprise license tier name |
| `PhysicalServer` | `vcf9|vmd_pending` | Property | T3 | Intel VMD state change pending system reboot |
| `PhysicalServer` | `vcf9|bios_pending_reboot` | Property | T3 | BIOS attribute configuration changes pending system reboot |
| `PhysicalServer` | `vcf9|esa_profile` | Property | T3 | vSAN ESA target workload profile (ESA-L, ESA-M, ESA-S, ESA-XS, Needs 25G, Blocked) |
| `PhysicalServer` | `vcf9|verdict_stale` | Property | T3 | ESA readiness verdict retained from prior cycle due to partial storage scan |
| `PhysicalServer` | `bios|cpu_power_profile` | Property | T3 | BIOS CPU power management profile (Performance, Balanced, PowerSaving, Unknown) |
| `PhysicalServer` | `bios|memory_ras` | Property | T3 | Memory RAS operating mode (Optimized, Advanced ECC, Mirror, Spare) |
| `PhysicalServer` | `bios|microcode_tier` | Property | T3 | CPU microcode patch tier and side-channel mitigation status |
| `PhysicalServer` | `memory|interleave_pct` | Property | T3 | Memory channel interleaving configuration efficiency score percentage |
| `PhysicalServer` | `memory|interleave_status` | Property | T3 | Memory interleaving balance status badge |
| `PhysicalServer` | `memory|channels_active` | Property | T3 | Count of active populated memory channels |
| `PhysicalServer` | `memory|channels_expected` | Property | T3 | Total memory channels supported by CPU architecture |
| `PhysicalServer` | `memory|failed_dimm_count` | Property | T3 | Count of failed, degraded, or unmapped DIMM modules |
| `PhysicalServer` | `memory|ecc_correctable` | Property | T3 | Fleet sum of correctable ECC memory errors across all DIMMs |
| `PhysicalServer` | `memory|ecc_uncorrectable` | Property | T3 | Fleet sum of uncorrectable ECC memory errors across all DIMMs |
| `PhysicalServer` | `pcie|lane_util_pct` | Property | T3 | PCIe lane budget utilization percentage |
| `PhysicalServer` | `pcie|over_budget` | Property | T3 | Flag indicating allocated PCIe lanes exceed CPU root complex capacity |
| `PhysicalServer` | `pcie|downshift_count` | Property | T3 | Count of PCIe devices operating below maximum rated lane width or speed |
| `PhysicalServer` | `power|redundant` | Property | T3 | Power supply redundancy configuration status |
| `PhysicalServer` | `power|capacity_watts` | Property | T3 | Total installed PSU power capacity in watts |
| `PhysicalServer` | `power|cap_watts` | Property | T3 | Configured chassis power capping limit in watts |
| `PhysicalServer` | `power|cap_enforced` | Property | T3 | Chassis power capping active enforcement status |
| `PhysicalServer` | `power|energy_kwh` | Property | T1 | Cumulative electrical energy consumption in kilowatt-hours (refreshed on T1) |
| `PhysicalServer` | `bmc|ntp_status` | Property | T3 | BMC NTP synchronization state (In sync, no servers, disabled, drift) |
| `PhysicalServer` | `bmc|ntp_servers` | Property | T3 | Configured BMC NTP time servers (joined string) |
| `PhysicalServer` | `bmc|time_drift_sec` | Property | T3 | Measured clock offset between BMC and collection host in seconds |
| `PhysicalServer` | `bmc|dns_status` | Property | T3 | BMC DNS name resolution service operational status |
| `PhysicalServer` | `collection|partial` | Property | T3 | Flag indicating assessment collection was partial due to component timeouts |
| `PhysicalServer` | `collection|partial_sections` | Property | T3 | Comma-separated list of Redfish subsystems that timed out or failed |
| `PhysicalServer` | `collection|last_request_count` | Property | T3 | Total Redfish HTTP requests executed during last assessment scan |
| `PhysicalServer` | `collection|last_duration_sec` | Property | T3 | Total elapsed duration of last assessment scan in seconds |
| `PhysicalServer` | `collection|status` | Property | T0 | Polling reachability and collection health status (ok, unreachable, auth_failed) |
| `PhysicalServer` | `security|failed_control_ids` | Property | T3 | Comma-separated list of failing BMC security audit control identifiers |
| `PhysicalServer` | `host|esxi_build` | Property | T3 | Installed VMware ESXi hypervisor build version |
| `PhysicalServer` | `network|max_speed_gbps` | Property | T3 | Highest link speed supported across installed network adapters |
| `PhysicalServer` | `network|ports_up` | Property | T3 | Count of network ports in physical link up state |
| `PhysicalServer` | `network|ports_down` | Property | T3 | Count of network ports in physical link down state |
| `PhysicalServer` | `network|unique_switches` | Property | T3 | Comma-separated list of distinct LLDP switch chassis identifiers |
| `PhysicalServer` | `network|single_switch` | Property | T3 | True when all LLDP neighbors connect to a single ToR switch chassis |
| `PhysicalServer` | `telemetry|fan_fault_count` | Metric | T1 | Real-time count of failed or degraded chassis cooling fans |
| `PhysicalServer` | `dimm:{instance}|capacity_gb` | Property | T3 | DIMM module capacity in GB (instance is slot label, e.g. A1) |
| `PhysicalServer` | `dimm:{instance}|manufacturer` | Property | T3 | DIMM hardware manufacturer |
| `PhysicalServer` | `dimm:{instance}|part_number` | Property | T3 | DIMM part number string |
| `PhysicalServer` | `dimm:{instance}|serial_number` | Property | T3 | DIMM serial number |
| `PhysicalServer` | `dimm:{instance}|speed_mhz` | Property | T3 | DIMM operating clock frequency in MHz |
| `PhysicalServer` | `dimm:{instance}|max_speed_mhz` | Property | T3 | DIMM rated maximum clock frequency in MHz |
| `PhysicalServer` | `dimm:{instance}|type` | Property | T3 | DIMM memory technology type (DDR4, DDR5, LRDIMM, RDIMM) |
| `PhysicalServer` | `dimm:{instance}|socket` | Property | T3 | CPU socket identifier for DIMM slot |
| `PhysicalServer` | `dimm:{instance}|channel` | Property | T3 | Memory channel identifier for DIMM slot |
| `PhysicalServer` | `dimm:{instance}|health` | Property | T3 | DIMM operational health status (OK, Warning, Critical) |
| `PhysicalServer` | `dimm:{instance}|state` | Property | T3 | DIMM presence and enablement state (Enabled, Absent) |
| `PhysicalServer` | `dimm:{instance}|correctable_ecc` | Property | T3 | DIMM module correctable ECC error counter |
| `PhysicalServer` | `dimm:{instance}|uncorrectable_ecc` | Property | T3 | DIMM module uncorrectable ECC error counter |
| `PhysicalServer` | `pcie_slot:{label}|attr` | Property | T3 | Instanced PCIe slot attributes: lanes, pcie_type, populated, device_name, device_manufacturer, vendor_id, device_id, subsystem_vendor_id, subsystem_id, device_health, hot_pluggable |
| `PhysicalServer` | `pcie_slot:{label}|lanes` | Property | T3 | PCIe slot negotiated lane width |
| `PhysicalServer` | `pcie_slot:{label}|pcie_type` | Property | T3 | PCIe slot generation standard (Gen3, Gen4, Gen5) |
| `PhysicalServer` | `pcie_slot:{label}|populated` | Property | T3 | Boolean flag indicating whether slot contains an adapter card |
| `PhysicalServer` | `pcie_slot:{label}|device_name` | Property | T3 | Description of device installed in PCIe slot |
| `PhysicalServer` | `pcie_slot:{label}|device_manufacturer` | Property | T3 | Manufacturer of installed PCIe device |
| `PhysicalServer` | `pcie_slot:{label}|vendor_id` | Property | T3 | PCI Vendor ID (hex string) |
| `PhysicalServer` | `pcie_slot:{label}|device_id` | Property | T3 | PCI Device ID (hex string) |
| `PhysicalServer` | `pcie_slot:{label}|subsystem_vendor_id` | Property | T3 | PCI Subsystem Vendor ID (hex string) |
| `PhysicalServer` | `pcie_slot:{label}|subsystem_id` | Property | T3 | PCI Subsystem ID (hex string) |
| `PhysicalServer` | `pcie_slot:{label}|device_health` | Property | T3 | Operational health of installed PCIe device |
| `PhysicalServer` | `pcie_slot:{label}|hot_pluggable` | Property | T3 | Boolean flag indicating slot hot-plug support |
| `PhysicalServer` | `fw:{instance}|name` | Property | T3 | Firmware component name (instance is component ID) |
| `PhysicalServer` | `fw:{instance}|version` | Property | T3 | Installed firmware version string |
| `PhysicalServer` | `fw:{instance}|updateable` | Property | T3 | Boolean flag indicating firmware is field-updatable via Redfish |
| `PhysicalServer` | `sec:{instance}|status` | Property | T3 | Compliance status for security control ID (pass, fail, unknown, not_applicable) |
| `PhysicalServer` | `sec:{instance}|severity` | Property | T3 | Severity level of security control finding (low, medium, high, critical) |
| `NetworkAdapter` | `port:{id}|current_speed_gbps` | Property | T2 | Current negotiated port link speed in Gbps (refreshed on T2) |
| `NetworkAdapter` | `port:{id}|link_status` | Property | T2 | Physical link state (Up, Down) (refreshed on T2) |
| `NetworkAdapter` | `port:{id}|mac_address` | Property | T2 | MAC address of physical network port |
| `NetworkAdapter` | `port:{id}|transceiver_vendor` | Property | T2 | Optical transceiver or DAC cable manufacturer |
| `NetworkAdapter` | `port:{id}|transceiver_part_number` | Property | T2 | Optical transceiver or DAC cable part number |
| `NetworkAdapter` | `port:{id}|lldp_switch` | Property | T2 | Discovered top-of-rack switch chassis ID / name via LLDP |
| `NetworkAdapter` | `port:{id}|lldp_port` | Property | T2 | Discovered remote switch port identifier via LLDP |
| `NetworkAdapter` | `port:{id}|lldp_mgmt_ip` | Property | T2 | Discovered switch management IP address via LLDP |
| `NetworkAdapter` | `port:{id}|lldp_vlan` | Property | T2 | Discovered port PVID / VLAN identifier via LLDP |
| `Processor` | `hardware|socket` | Property | T3 | CPU socket location identifier |
| `Processor` | `hardware|max_mhz` | Property | T3 | Maximum rated processor clock frequency in MHz |
| `Processor` | `hardware|microcode` | Property | T3 | Microcode patch revision reported by processor |
| `Processor` | `bios|microcode_revision` | Property | T3 | Microcode revision string reported via BIOS side-channel status |
| `StorageController` | `hardware|tri_mode` | Property | T3 | Tri-mode controller capability (supports NVMe, SAS, SATA) |
| `StorageController` | `hardware|software_raid` | Property | T3 | Software RAID controller flag |
| `StorageController` | `hardware|protocols` | Property | T3 | Supported drive interface protocols list |
| `StorageController` | `hardware|boot_controller` | Property | T3 | Designates controller as primary boot controller |
| `StorageController` | `hardware|bbu_health` | Property | T3 | Battery backup unit (BBU) or write-cache supercap health status |
| `StorageController` | `hardware|pcie_gen` | Property | T3 | Controller host interface PCIe generation standard |
| `StorageController` | `hardware|pcie_lanes` | Property | T3 | Active negotiated PCIe lanes |
| `StorageController` | `hardware|pcie_lanes_max` | Property | T3 | Maximum rated PCIe lane width |
| `StorageController` | `hardware|pci_ids` | Property | T3 | Controller PCI identification quad (vendor:device:svendor:sid) |
| `StorageController` | `hardware|has_virtual_disks` | Property | T3 | Flag indicating configured RAID virtual disks are present |
| `PhysicalDrive` | `vcf9|category` | Property | T3 | Drive readiness classification category |
| `PhysicalDrive` | `vcf9|vsan_eligible` | Property | T3 | Direct vSAN ESA qualification flag |
| `PhysicalDrive` | `hardware|bay` | Property | T3 | Drive bay / slot number |
| `PhysicalDrive` | `hardware|boot_media` | Property | T3 | ESXi boot device flag |
| `PhysicalDrive` | `hardware|form_factor` | Property | T3 | Drive form factor (U.2, U.3, E3.S, M.2, 2.5", 3.5") |
| `PhysicalDrive` | `hardware|connector` | Property | T3 | Drive physical connector interface |
| `PhysicalDrive` | `hardware|behind_tri_mode` | Property | T3 | Drive is attached downstream of a tri-mode storage controller |
| `PhysicalDrive` | `hardware|behind_software_raid` | Property | T3 | Drive is attached downstream of a software RAID controller |
| `PhysicalDrive` | `hardware|pcie_gen` | Property | T3 | Drive bus PCIe generation standard |
| `PhysicalDrive` | `hardware|pcie_lanes` | Property | T3 | Drive active negotiated PCIe lane width |
| `PhysicalDrive` | `hardware|pcie_lanes_max` | Property | T3 | Drive maximum rated PCIe lane width |
| `PhysicalDrive` | `hardware|pcie_downshifted` | Property | T3 | Flag indicating drive negotiated fewer PCIe lanes than rated maximum |
| `PhysicalDrive` | `hardware|single_lane_alert` | Property | T3 | Alert flag indicating NVMe drive downshifted to a single PCIe lane (x1) |
| `PhysicalDrive` | `hardware|pci_ids` | Property | T3 | Drive PCI identification quad (vendor:device:svendor:sid) |
| `PhysicalDrive` | `hardware|usage_role` | Property | T3 | Drive deployment role (Data, Cache, System, Spare) |
| `PhysicalDrive` | `bcg|firmware_status` | Property | T3 | Drive firmware compatibility status against Broadcom Compatibility Guide |
| `PhysicalDrive` | `health|wear_remaining_pct` | Property | T2 | Remaining drive endurance percentage (refreshed on T2/T3) |
| `PhysicalDrive` | `health|failure_predicted` | Property | T2 | SMART / NVMe failure prediction alert (refreshed on T2) |
| `PhysicalDrive` | `health|status` | Property | T2 | Real-time drive operational health status (refreshed on T2) |
| `PhysicalDrive` | `health|error` | Property | T2 | Drive error state description string |
| `PhysicalDrive` | `health|media_errors` | Property | T2 | Cumulative unrecovered media errors count |
| `PhysicalDrive` | `health|uncorrectable_read_errors` | Property | T2 | Cumulative uncorrectable read errors count |
| `PhysicalDrive` | `health|pcie_bus_errors` | Property | T2 | Cumulative PCIe bus interface errors count |
| `PhysicalDrive` | `health|power_on_hours` | Property | T2 | Accumulated drive power-on hours |
| `PhysicalDrive` | `health|tbw_written` | Property | T2 | Lifetime data written in terabytes (TBW) |
| `PhysicalDrive` | `health|unsafe_shutdowns` | Property | T2 | Lifetime count of unsafe or unexpected power-loss events |
| `PhysicalDrive` | `health|available_spare_pct` | Property | T2 | Normalized remaining spare flash blocks percentage |
| `PhysicalDrive` | `health|thermal_throttled` | Property | T2 | Drive active thermal throttling status |
| `PhysicalDrive` | `health|plp_capacitor` | Property | T2 | Power loss protection (PLP) capacitor operational health |
| `NetworkAdapter` | `hardware|part_number` | Property | T3 | Adapter hardware part number |
| `NetworkAdapter` | `hardware|pci_ids` | Property | T3 | Adapter PCI identification quad (vendor:device:svendor:sid) |
| `NetworkAdapter` | `hardware|is_cna` | Property | T3 | Converged Network Adapter (FCoE / iSCSI offload) flag |
| `NetworkAdapter` | `hardware|cna_family` | Property | T3 | CNA product architecture family |
| `NetworkAdapter` | `hardware|is_npar` | Property | T3 | NIC Network Partitioning (NPAR) active flag |
| `NetworkAdapter` | `hardware|downgraded` | Property | T3 | Flag indicating adapter link is degraded below maximum capability |
| `NetworkAdapter` | `hardware|downgrade_reason` | Property | T3 | Reason string for network link speed degradation |
| `PowerSupplyUnit` | `hardware|serial_number` | Property | T3 | PSU serial number |
| `PowerSupplyUnit` | `hardware|firmware_version` | Property | T3 | PSU microcontroller firmware version |
| `PowerSupplyUnit` | `hardware|efficiency_pct` | Property | T3 | Rated 80 PLUS electrical conversion efficiency percentage |
| `PowerSupplyUnit` | `hardware|input_watts` | Property | T3 | Rated input power capacity in watts |
| `PowerSupplyUnit` | `hardware|bay_populated` | Property | T3 | Boolean flag indicating PSU presence in chassis bay |
| `PowerSupplyUnit` | `telemetry|input_watts` | Metric | T1 | Real-time measured PSU electrical input power draw (T1 telemetry) |
| `GpuAccelerator` | `hardware|model` | Property | T3 | GPU accelerator model description |
| `GpuAccelerator` | `hardware|vendor` | Property | T3 | GPU hardware vendor |
| `GpuAccelerator` | `hardware|vram_gb` | Property | T3 | Video RAM (VRAM) capacity in GB |
| `GpuAccelerator` | `hardware|pci_ids` | Property | T3 | GPU PCI identification quad (vendor:device:svendor:sid) |
| `GpuAccelerator` | `hardware|health` | Property | T3 | Operational health status |
| `GpuAccelerator` | `hardware|slot` | Property | T3 | Chassis PCIe slot location |
| `GpuAccelerator` | `hardware|firmware` | Property | T3 | GPU VBIOS / firmware version string |
| `GpuAccelerator` | `telemetry|temperature_celsius` | Metric | T1 | Measured GPU core temperature in °C (T1 telemetry) |
| `FibreChannelHba` | `hardware|model` | Property | T3 | Fibre Channel HBA model description |
| `FibreChannelHba` | `hardware|firmware` | Property | T3 | HBA firmware / boot code version |
| `FibreChannelHba` | `hardware|wwpn` | Property | T3 | World Wide Port Name (WWPN) |
| `FibreChannelHba` | `hardware|wwnn` | Property | T3 | World Wide Node Name (WWNN) |
| `FibreChannelHba` | `hardware|port_speed_gbps` | Property | T3 | Negotiated Fibre Channel link speed in Gbps |
| `FibreChannelHba` | `hardware|link_status` | Property | T3 | Physical Fibre Channel port link state |
| `FibreChannelHba` | `hardware|pci_ids` | Property | T3 | HBA PCI identification quad (vendor:device:svendor:sid) |
| `VcfReadinessAdapter_adapter_instance` | `collection|deferred_hosts` | Property | T0 | Count of targets deferred due to cycle time budget limits |
| `MemoryModule` | `module_id` | Identifier | T3 | Physical DIMM slot identifier (model_detail_objects mode) |
| `NetworkPort` | `port_id` | Identifier | T2 | Physical network port identifier (model_detail_objects mode) |
| `PCIeSlot` | `slot_id` | Identifier | T3 | PCIe slot label or index identifier (model_detail_objects mode) |
| `FirmwareComponent` | `component_id` | Identifier | T3 | Firmware component identifier (model_detail_objects mode) |
