# VCF 9.1 HCI Readiness Assessment Tool — Presentation & Infographic Kit

> **Release:** v9.7.3 • **Target Platform:** VMware Cloud Foundation 9.1 / vSphere 9.1 / vSAN ESA
> **Interactive Standalone HTML Version:** [`docs/infographic.html`](./infographic.html) (100% self-contained offline single-file app)

---

## Executive Summary & Soundbite

> *"The VCF HCI Readiness Assessment Tool bridges the gap between raw bare-metal server infrastructure and VMware Cloud Foundation 9.1 planning — automating days of manual HCL validation into a 30-second Redfish scan that preserves existing server CapEx."*

```
┌────────────────────────────────────────────────────────────────────────┐
│               VCF 9.1 HCI READINESS ASSESSMENT TOOL v9.7.3             │
├───────────────────┬───────────────────┬────────────────────────────────┤
│ 30 Sec / Host     │ 0 Footprint       │ 8 Server OEMs                  │
│ Automated Scan    │ Agentless Stdlib  │ Dell, HPE, Lenovo, Cisco, etc. │
├───────────────────┼───────────────────┼────────────────────────────────┤
│ 1-Click BCG       │ 100% Air-Gapped   │ 1,425 Test Cases               │
│ Dynamic Deep-Link │ Dark-Site Safe    │ 1.0M+ Lines Anonymized Mockups │
├───────────────────┼───────────────────┼────────────────────────────────┤
│ 84 Security Checks│ SE Decision Matrix│ Canonical SEL / EEMS Links     │
│ CISA / NSA Aligned│ Tab 1 Fast Triage │ Dell, HPE, Cisco, Lenovo, QCT  │
└───────────────────┴───────────────────┴────────────────────────────────┘
```

---

## Tailored Presentation Slide Deck (6 Core Slides)

### Slide 1: Accelerating VCF 9.1 Modernization with Existing Hardware
* **Executive Headline:** *"Maximize Existing CapEx: Instantly Qualify Server Fleets for VMware Cloud Foundation 9.1"*
* **Architect Headline:** *"Deterministic Architecture Alignment: Validating Fleet Repurposing for VCF 9.1"*
* **SecOps Headline:** *"Zero-Risk Operational Discovery: Assessing Fleets with Zero Production Impact"*

#### Key Takeaways
1. **Avoid Premature Hardware Refresh:** 70–85% of existing 14th/15th/16th Gen servers can be repurposed for VCF 9.1 without full rack replacements.
2. **Eliminate Audit Friction:** Replace weeks of manual spreadsheets and physical inspections with a 30-second automated scan.
3. **Deterministic Decision Roadmaps:** Categorize every node into *Ready for VCF 9.1*, *Upgrade Required* (e.g. 25GbE NICs/NVMe), or *Refresh Candidate*.

#### ROI & Labor Savings Model
* **Manual Audit Time:** 3.5 hours per host (BIOS, firmware, drive HCL, and network validation).
* **Automated Audit Time:** 30 seconds per host.
* **32-Node Cluster Savings:** **110+ engineering hours** saved (~$19,250 in avoided labor cost @ $175/hr blended rate).

---

### Slide 2: Enterprise-Grade Safety — Non-Invasive, Zero-Agent Architecture
* **Headline:** *"Enterprise-Grade Safety: Zero Agents, Zero Host Disruption, 100% Out-of-Band"*

```
┌────────────────────────────────────────────────────────────────────────┐
│                        DISCOVERY ARCHITECTURE                          │
│                                                                        │
│   Admin Workstation (Standard User)             Target Server Estate   │
│  ┌─────────────────────────┐                   ┌─────────────────────┐ │
│  │ Python 3.9+ (Stdlib)    │  HTTPS (Port 443) │ Dell iDRAC 9 / 10   │ │
│  │ • 0 External Packages   ├──────────────────►│ HPE iLO 5 / 6       │ │
│  │ • Read-Only Operator    │   Out-of-Band     │ Lenovo XCC 1 / 2    │ │
│  │ • SHA-256 PII Redaction │   (Zero OS Touch) │ Cisco IMC / UCS     │ │
│  │ • 3-Pass Thread Safe    │                   │ Supermicro DCMS     │ │
│  │ • CISA/NSA BMC Hardened │                   │ Intel Server System │ │
│  │                         │                   │ Quanta / QCT        │ │
│  │                         │                   │ GIGABYTE MegaRAC    │ │
│  └─────────────────────────┘                   └─────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

#### Security Guardrails Matrix
| Dimension | Implementation Standard | Customer Benefit |
| :--- | :--- | :--- |
| **Execution Runtime** | 100% Python Standard Library (No `requests`/`pandas`) | Zero software supply-chain CVE risk |
| **Host Workloads** | 100% Out-of-band via BMC HTTPS | No guest OS reboot or CPU/RAM overhead |
| **Data Privacy** | SHA-256 Salted Serial Masking & RFC 5737 doc IPs | Safe for sharing with external auditors |
| **Privileges** | Standard Read-Only Operator BMC account | Lowest-privilege access model |
| **Traffic Profile** | Adaptive concurrency throttling & 3-pass rescan | Protects low-power BMC controllers |
| **Federal Guidance** | CISA & NSA Joint CSI BMC Hardening Alignment | Verifies 84 out-of-band security controls |

---

### Slide 3: Automated VCF 9.1 Qualification & 84-Control Security Audit
* **Headline:** *"Deterministic Hardware Verdicts: CPU Tiers, vSAN ESA Storage, and Federal Security Baselines"*

#### Rules & Compatibility Matrix
| Component | Broadcom / VCF 9.1 Evaluation Rule | Verdict & Badge |
| :--- | :--- | :--- |
| **CPU Lifecycle** | AMD EPYC 7/8/9xxx, Intel Ice Lake, Sapphire Rapids, Xeon 6 | `🟢 Fully Supported (Tier 1)` |
| **CPU Support Override** | Intel Skylake-SP (Broadcom KB 428874) | `🟡 Supported (Override Required)` |
| **Legacy CPU** | Intel Haswell / Broadwell (v3 / v4) | `🔴 Unsupported for VCF 9.x` |
| **vSAN ESA Storage** | >= 2 Direct-Attached NVMe SSDs + >= 25 GbE NIC | `🟢 vSAN ESA Qualified` |
| **vSAN ESA Storage** | NVMe SSDs behind Hardware RAID Controller | `🔴 Incompatible for ESA` |
| **Security Cryptoprocessor** | TPM 2.0 State | `🟢 EnabledAndActivated` |
| **BIOS Configuration** | Intel Volume Management Device (VMD) | `🟢 Disabled (Native Pass-through)` |
| **BMC Hardening Audit** | CISA / NSA Joint CSI Baseline (84 controls) | `🟢 Baseline Met / 🟡 Action Required` |

---

### Slide 4: Deep Hardware Health, Physical Network Topologies & Multi-Vendor SEL
* **Headline:** *"Beyond Compatibility: Real-Time Drive Wear %, Thermal Metrics, ToR Switch Discovery, and Canonical SEL Links"*

* **OCP 2.6 SMART Telemetry:** Extracts 20+ NVMe health indicators including drive wear %, lifetime power-on hours, remaining spare blocks, and thermal zone history.
* **Physical ToR Switch Mapping:** Harvests LLDP and Cisco CDP neighbor frames from NIC ports to map physical switch hostnames, port IDs, and VLAN trunks.
* **Canonical Dell PowerEdge EEMS & Multi-Vendor SEL Resolution:**
  - Decodes Dell PowerEdge SEL events into canonical multi-generation DITA chapter topics across 20+ hardware categories (`SEC`, `PSU`, `RDU`, `PDR`, `HWC`, `MEM`, `PST`, `BOOT`, `CTL`, `PCI`, `TMP`, `SEL`, etc.) and 76 distinct IPMI hex codes.
  - Generates direct HPE Gen12 IML Troubleshooting Guide links (`class0x...code0x...`).
  - Correlates Cisco UCS IMC faults across 114 `F-code` fault IDs (e.g. `F0409`, `F0510`, `F1008`) and 116 named `flt*` symbols directly into official Cisco Faults Reference Guide chapters.
  - Integrates Lenovo XCC, Supermicro, Quanta AST2500, and Gigabyte AMI MegaRAC SEL references.
* **Private AI Foundation Readiness:** Identifies PCIe accelerator hardware (NVIDIA, AMD GPUs) ready for enterprise GenAI workloads.

---

### Slide 5: Actionable Deliverables, SE Decision Matrix & 1-Click Verification
* **Headline:** *"Enterprise Deliverables: Standalone Interactive Reports, SE Decision Matrix, and 1-Click Broadcom HCL Links"*

1. **Portable Standalone HTML Reports:** Single-file, self-contained interactive reports (0 external CDN or internet calls) that open instantly in any browser.
2. **Tab 1 SE Decision Matrix:** Instant dense fleet triage with compact ESA NVMe disk rollups (`4×3.8TB (15.2TB)`), network port link states with directional arrows (`4×25G↑ 2×10G↓`), memory interleaving efficiency %, TPM/VMD status, and RAID blocking detection.
3. **Unified Multi-Tab Excel Workbook:** 11 domain tabs with client-side Base64 export on `file://` protocol without requiring a server backend.
4. **Obfuscated Excel + Reverse-Mapping Key:** Bundles `inventory_obfuscated.xlsx` with a private `obfuscation_key.json` and security guide for external reviews.
5. **Redfish Hypermedia Crawler & Action Cataloger:** Discovers unmapped and OEM-proprietary URIs, catalogs write/action endpoints across 11 functional domains, and exports DMTF mockup ZIP archives.
6. **Dynamic BCG Deep-Links:** Single-click deep links directly to Broadcom's official Compatibility Guide for server models, CPU microarchitectures, NVMe SSDs, and NICs.
7. **VMware Aria Operations Management Pack:** Ready-to-deploy `.pak` adapter with physical-to-virtual traversal maps and hardware metric dashboards.

---

### Slide 6: Customer Engagement Journey — 4-Step Readiness Workshop
* **Headline:** *"Your Path Forward: A 4-Step, Zero-Risk Hardware Readiness Workshop"*

| Phase | Timeline | Focus Area | Deliverable |
| :--- | :--- | :--- | :--- |
| **Step 1: Scoping** | 30 Mins | Target subnet definition & read-only BMC credentials | Scoping & Readiness Spec |
| **Step 2: Fleet Scan** | 15–30 Mins | Automated agentless scan across target racks | Raw Telemetry Matrix |
| **Step 3: Qualification** | Automated | VCF 9.1 CPU, vSAN ESA, drive wear & CISA/NSA audit | Enriched Compatibility BOM |
| **Step 4: Roadmap** | 45 Mins | Findings presentation & cluster repurposing plan | Standalone HTML Report & Excel BOM |

---

## Codebase Architecture & Multi-OEM Footprint

```
┌────────────────────────────────────────────────────────────────────────┐
│                   CODEBASE ENGINEERING (189K+ LOC)                     │
├───────────────────────────────┬────────────────────────────────────────┤
│ Automated Test Suite          │ 122,090 LOC (99 modules, 1,425 tests)  │
│ Standalone HTML Reports       │ 15,670 LOC (11 sections, SE Matrix)    │
│ Hardware Collectors (Layer A) │ 12,598 LOC (8 Server OEM Adapters)     │
│ Developer, Build & Crawler    │ 10,661 LOC (Data hygiene, mockups)     │
│ Clarity Web UI & API          │ 8,240 LOC (Clarity Design, SSE stream) │
│ BMC Security Audit Engine     │ 6,751 LOC (84 controls, CISA/NSA)      │
│ Core CLI, Concurrency & Utils │ 6,162 LOC (ThreadPool, 3-Pass Rescan)  │
│ Aria Operations Pack          │ 3,251 LOC (.pak adapter & dashboards)  │
│ VCF 9.1 Compatibility Engine  │ 1,852 LOC (KB 428874, vSAN ESA rules)  │
│ HCL Engine & Datasets         │ 1,820 LOC (19.6 MB bundled HCL matrix) │
│ Real-World Mockup Fixtures    │ 1,008,861 LOC (15+ server architectures)│
└───────────────────────────────┴────────────────────────────────────────┘
```

---

*VCF / vSphere 9.1 HCI Readiness Assessment Tool • Open source VMware SE utility.*
