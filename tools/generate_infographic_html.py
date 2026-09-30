#!/usr/bin/env python3
"""
tools/generate_infographic_html.py — VCF 9.1 Readiness Infographic & Presentation Kit Generator

Generates:
1. docs/INFOGRAPHIC.md — Rich GitHub Markdown document viewable natively on GitHub.com.
2. docs/infographic.html — 100% standalone, self-contained, single-file interactive HTML presentation
   with zero external dependencies (no external CSS, JS, fonts, or CDNs). Opens instantly anywhere.

Run automatically during version bumps (scripts/bump_version.sh) and builds (build-web.sh):
    python3 tools/generate_infographic_html.py
"""

import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

from vcf_hci.constants import TOOL_VERSION

HTML_OUT = os.path.join(PROJECT_ROOT, "docs", "infographic.html")
MD_OUT = os.path.join(PROJECT_ROOT, "docs", "INFOGRAPHIC.md")


def generate_markdown() -> str:
    return f"""# VCF 9.1 HCI Readiness Assessment Tool — Presentation & Infographic Kit

> **Release:** v{TOOL_VERSION} • **Target Platform:** VMware Cloud Foundation 9.1 / vSphere 9.1 / vSAN ESA
> **Interactive Standalone HTML Version:** [`docs/infographic.html`](./infographic.html) (100% self-contained offline single-file app)

---

## Executive Summary & Soundbite

> *"The VCF HCI Readiness Assessment Tool bridges the gap between raw bare-metal server infrastructure and VMware Cloud Foundation 9.1 planning — automating days of manual HCL validation into a 30-second Redfish scan that preserves existing server CapEx."*

```
┌────────────────────────────────────────────────────────────────────────┐
│               VCF 9.1 HCI READINESS ASSESSMENT TOOL v{TOOL_VERSION}             │
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
"""


def generate_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VCF 9.1 HCI Readiness Assessment — Customer Presentation & Infographic Kit</title>
  <style>
    :root {{
      --bg: #0b1329;
      --bg-card: #132247;
      --bg-card-sub: #0f1b38;
      --border: #233876;
      --border-sub: #1a2c5b;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --blue: #38bdf8;
      --blue-hover: #0284c7;
      --green: #34d399;
      --amber: #fbbf24;
      --red: #f87171;
      --purple: #c084fc;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
    body {{ background: var(--bg); color: var(--text-main); padding: 28px 20px; line-height: 1.5; }}
    .container {{ max-width: 1180px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }}
    /* Header Area */
    .header {{ display: flex; flex-direction: column; gap: 10px; }}
    .top-bar {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }}
    .pills {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .pill {{ background: var(--border-sub); color: #cbd5e1; padding: 5px 12px; border-radius: 9999px; font-size: 12px; font-weight: 600; border: 1px solid var(--border); }}
    .pill.active {{ background: #0369a1; border-color: var(--blue); color: #fff; }}
    .track-selector {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .btn-track {{ background: var(--bg-card); color: #cbd5e1; border: 1px solid var(--border); padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; transition: all 0.15s ease; }}
    .btn-track:hover {{ background: var(--border); color: #fff; }}
    .btn-track.active {{ background: #0284c7; border-color: var(--blue); color: #fff; box-shadow: 0 0 12px rgba(56,189,248,0.35); }}
    h1 {{ font-size: 27px; font-weight: 800; color: #fff; letter-spacing: -0.02em; }}
    h2 {{ font-size: 20px; font-weight: 700; color: #fff; }}
    h3 {{ font-size: 16px; font-weight: 600; color: #fff; }}
    p {{ color: var(--text-muted); font-size: 14px; }}
    /* Card Styles */
    .card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.25); }}
    .card-sub {{ background: var(--bg-card-sub); border: 1px solid var(--border-sub); border-radius: 8px; padding: 16px; }}
    .grid-5 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }}
    .grid-2 {{ display: grid; grid-template-columns: 1.15fr 1fr; gap: 24px; }}
    .grid-3 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
    .grid-4 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
    @media (max-width: 860px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
    /* Stats Box */
    .stat-box {{ background: var(--bg-card-sub); border: 1px solid var(--border-sub); border-radius: 8px; padding: 16px; }}
    .stat-val {{ font-size: 24px; font-weight: 800; color: var(--blue); letter-spacing: -0.02em; }}
    .stat-val.success {{ color: var(--green); }}
    .stat-val.warning {{ color: var(--amber); }}
    .stat-val.purple {{ color: var(--purple); }}
    .stat-lbl {{ font-size: 12px; color: var(--text-muted); margin-top: 4px; font-weight: 500; }}
    /* Navigation Tabs */
    .tab-bar {{ display: flex; gap: 8px; border-bottom: 2px solid var(--border-sub); padding-bottom: 12px; flex-wrap: wrap; }}
    .tab-btn {{ background: transparent; color: var(--text-muted); border: 1px solid transparent; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13.5px; font-weight: 700; transition: all 0.15s ease; }}
    .tab-btn:hover {{ background: var(--bg-card); color: #fff; }}
    .tab-btn.active {{ background: #0369a1; border-color: var(--blue); color: #fff; }}
    /* Table Styles */
    .table-wrap {{ overflow-x: auto; }}
    .table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .table th, .table td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border-sub); }}
    .table th {{ color: #cbd5e1; font-weight: 700; background: #0c1733; text-transform: uppercase; font-size: 11px; letter-spacing: 0.05em; }}
    .table tr:hover {{ background: rgba(56,189,248,0.03); }}
    /* Badges */
    .badge {{ display: inline-block; padding: 3px 9px; border-radius: 4px; font-size: 11px; font-weight: 700; }}
    .badge-success {{ background: rgba(52,211,153,0.15); color: #34d399; border: 1px solid #059669; }}
    .badge-warning {{ background: rgba(251,191,36,0.15); color: #fbbf24; border: 1px solid #d97706; }}
    .badge-info {{ background: rgba(56,189,248,0.15); color: #38bdf8; border: 1px solid #0284c7; }}
    .badge-purple {{ background: rgba(192,132,252,0.15); color: #c084fc; border: 1px solid #9333ea; }}
    .badge-danger {{ background: rgba(248,113,113,0.15); color: #f87171; border: 1px solid #dc2626; }}
    .divider {{ height: 1px; background: var(--border-sub); margin: 16px 0; }}
    code {{ background: #080f21; border: 1px solid var(--border-sub); padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; color: var(--blue); }}
    /* Progress Bars */
    .progress-bar {{ background: #080f21; border: 1px solid var(--border-sub); border-radius: 9999px; height: 10px; overflow: hidden; margin-top: 6px; }}
    .progress-fill {{ height: 100%; border-radius: 9999px; }}
    .progress-fill.green {{ background: linear-gradient(90deg, #10b981, #34d399); }}
    .progress-fill.red {{ background: linear-gradient(90deg, #ef4444, #f87171); }}
    .details-box {{ background: var(--bg-card-sub); border: 1px solid var(--border); border-left: 4px solid var(--blue); border-radius: 8px; padding: 14px; font-size: 13.5px; margin-top: 14px; }}
    /* SVG Chart */
    .chart-bar {{ fill: #38bdf8; transition: fill 0.2s ease; }}
    .chart-bar:hover {{ fill: #0284c7; }}
    .btn-action {{ background: #0284c7; color: #fff; border: 1px solid var(--blue); padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}
    .btn-action:hover {{ background: #0369a1; }}
  </style>
</head>
<body>
  <div class="container">
    <!-- Header Banner -->
    <div class="header">
      <div class="top-bar">
        <div class="pills">
          <span class="pill active">v{TOOL_VERSION} Release</span>
          <span class="pill">VCF / vSphere 9.1 HCI Assessment</span>
          <span class="pill">8 Enterprise Server OEMs</span>
          <span class="pill">CISA / NSA Hardening Audit</span>
          <span class="pill" style="background:#064e3b; border-color:#059669; color:#34d399;">100% Standalone Offline</span>
        </div>
        <div class="track-selector">
          <span style="font-size: 12px; font-weight:600; color: #94a3b8;">Audience Track:</span>
          <button class="btn-track active" id="btn-exec" onclick="setTrack('executive')">Executive (CIO/VP)</button>
          <button class="btn-track" id="btn-arch" onclick="setTrack('architect')">Enterprise Architect</button>
          <button class="btn-track" id="btn-ops" onclick="setTrack('operations')">IT & SecOps</button>
        </div>
      </div>
      <h1>VCF 9.1 HCI Readiness — Customer Presentation Kit & Field Deck</h1>
      <p>Tailored presentation slides, speaker tracks, ROI models, CISA/NSA security audits, and technical proof points for VMware Cloud Foundation 9.1 server repurposing.</p>
    </div>

    <!-- Active Persona Profile Card -->
    <div class="card" id="profile-card">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
        <div>
          <span class="badge badge-info" id="track-badge">CapEx & Strategy Focus</span>
          <h3 id="track-title" style="margin-top: 6px; font-size: 17px;">Executive & Leadership Track (CIO / VP / IT Director)</h3>
          <p id="track-desc" style="font-size: 13.5px; margin-top: 3px;">Focus on CapEx avoidance, rapid time-to-value, deterministic migration roadmaps, and labor cost savings.</p>
        </div>
        <div>
          <button class="btn-action" onclick="copySlidePitch()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect></svg>
            <span id="copy-btn-text">Copy Slide Pitch</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Dynamic Hero KPI Strip -->
    <div class="grid-5" id="stats-grid">
      <!-- Injected via JS -->
    </div>

    <!-- Main Section Tabs -->
    <div class="tab-bar">
      <button class="tab-btn active" id="tab-slides" onclick="switchTab('slides')">Customer Slide Deck (Interactive)</button>
      <button class="tab-btn" id="tab-overview" onclick="switchTab('overview')">Executive Summary & ROI</button>
      <button class="tab-btn" id="tab-features" onclick="switchTab('features')">Technical Capabilities & USPs</button>
      <button class="tab-btn" id="tab-hardware" onclick="switchTab('hardware')">OEM Matrix & Coverage (8 OEMs)</button>
      <button class="tab-btn" id="tab-codebase" onclick="switchTab('codebase')">Architecture & Engineering</button>
    </div>

    <!-- TAB 1: SLIDES -->
    <div id="view-slides" style="display: flex; flex-direction: column; gap: 18px;">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
        <div>
          <h2>Slide Deck Navigator</h2>
          <p id="slide-subtitle">Select a slide to review customer talking points, visuals, and objection handling.</p>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <button class="btn-track" onclick="prevSlide()">◀ Prev</button>
          <select id="slide-select" onchange="setSlide(this.value)" style="background: var(--bg-card); color: #f8fafc; border: 1px solid var(--border); padding: 7px 14px; border-radius: 6px; font-weight: 600; cursor: pointer;">
            <option value="1">Slide 1: Business Opportunity & Repurposing Strategy</option>
            <option value="2">Slide 2: Non-Invasive Agentless Architecture & 8 OEMs</option>
            <option value="3">Slide 3: Automated VCF 9.1 Qualification & Security Audit</option>
            <option value="4">Slide 4: Deep Hardware Health & Canonical SEL Deep-Links</option>
            <option value="5">Slide 5: Enterprise Deliverables, SE Matrix & BCG Links</option>
            <option value="6">Slide 6: Customer Engagement Journey & 4-Step Workshop</option>
          </select>
          <button class="btn-track" onclick="nextSlide()">Next ▶</button>
        </div>
      </div>

      <div class="card">
        <div class="grid-2">
          <div>
            <span class="badge badge-info" id="slide-badge">Slide 1 of 6</span>
            <h3 id="slide-headline" style="margin-top: 10px; font-size: 19px; line-height: 1.35;">Maximize Existing CapEx: Instantly Qualify Server Fleets for VMware Cloud Foundation 9.1</h3>
            <div class="divider"></div>
            <h4 style="font-size: 14px; margin-bottom: 10px; color: #cbd5e1;">Key Presentation Takeaways:</h4>
            <div id="slide-bullets" style="display: flex; flex-direction: column; gap: 10px; font-size: 14px;"></div>
          </div>

          <div id="slide-visual">
            <!-- Dynamic visual card based on slide -->
          </div>
        </div>

        <div class="details-box">
          <p><strong style="color: var(--blue);">Presenter Speaker Track:</strong> <span id="slide-notes"></span></p>
          <div class="divider"></div>
          <p><strong style="color: var(--amber);">Customer Objection / Question:</strong> <span id="slide-objection"></span></p>
          <p style="margin-top: 6px;"><strong style="color: var(--green);">Recommended Answer:</strong> <span id="slide-answer"></span></p>
        </div>
      </div>
    </div>

    <!-- TAB 2: OVERVIEW -->
    <div id="view-overview" style="display: none; flex-direction: column; gap: 20px;">
      <div class="grid-2">
        <div class="card">
          <span class="badge badge-success" style="margin-bottom:8px;">Value Proposition</span>
          <h3>Why Field SEs & Architects Love It</h3>
          <div style="display: flex; flex-direction: column; gap: 12px; margin-top: 12px; font-size: 13.5px;">
            <p><strong style="color: #fff;">Zero-Install Air-Gapped Operation:</strong> Runs on any standard Python 3.9+ runtime without pip install, compiler tools, or root privileges. Zero dependency friction on customer jump boxes.</p>
            <p><strong style="color: #fff;">Instant Repurposing Verdicts:</strong> Assesses legacy hardware against VCF 9.1 CPU rules (KB 428874), vSAN ESA 25GbE + NVMe pass-through, and TPM 2.0.</p>
            <p><strong style="color: #fff;">CISA / NSA Hardening Audit:</strong> Evaluates 84 out-of-band BMC controls aligned with the Joint CSI guide, scoring credential policy, protocol hardening, and firmware integrity.</p>
            <p><strong style="color: #fff;">Single-Click BCG Verification:</strong> Generates exact Broadcom Compatibility Guide deep links for server models, CPUs, drives, and NICs.</p>
          </div>
        </div>
        <div class="card">
          <span class="badge badge-info" style="margin-bottom:8px;">Enterprise Interfaces</span>
          <h3>Delivery Interfaces</h3>
          <div style="display: flex; flex-direction: column; gap: 12px; margin-top: 12px; font-size: 13.5px;">
            <p><strong style="color: #fff;">Interactive Clarity Web Portal:</strong> Real-time multi-host subnet scanning with Server-Sent Events (SSE) streaming, live inventory explorer, and OEM Import Mode.</p>
            <p><strong style="color: #fff;">Standalone HTML Reports:</strong> Single-file interactive reports (zero external CDN or internet calls) featuring the Tab 1 SE Decision Matrix, clickable SEL links, and offline Base64 Excel download.</p>
            <p><strong style="color: #fff;">Unified Multi-Tab Excel Workbook:</strong> 11 domain tabs exportable client-side on <code>file://</code> protocol, plus obfuscated workbooks with private reverse-mapping keys.</p>
            <p><strong style="color: #fff;">VMware Aria Operations Management Pack:</strong> Ready-to-deploy .pak adapter with custom dashboards, physical-to-virtual traversals, and security posture metrics.</p>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>Architectural Footprint by Component (189K+ Total LOC)</h3>
        <p style="margin-bottom: 16px;">Pure Python stdlib engine, automated test fixtures, and standalone report generators.</p>
        <svg viewBox="0 0 850 290" style="width:100%; height:auto; background:var(--bg-card-sub); border-radius:8px; border:1px solid var(--border-sub); padding:10px;">
          <!-- Horizontal Bar Chart -->
          <g transform="translate(180, 20)">
            <!-- Bar 1 -->
            <text x="-10" y="15" fill="#94a3b8" font-size="12" text-anchor="end">Test Suite & Fixtures</text>
            <rect class="chart-bar" x="0" y="2" width="580" height="17" rx="3" fill="#38bdf8"></rect>
            <text x="590" y="15" fill="#f8fafc" font-size="11" font-weight="600">122,090 LOC (1,425 tests)</text>

            <!-- Bar 2 -->
            <text x="-10" y="38" fill="#94a3b8" font-size="12" text-anchor="end">HTML Reports & SE Matrix</text>
            <rect class="chart-bar" x="0" y="25" width="75" height="17" rx="3" fill="#34d399"></rect>
            <text x="85" y="38" fill="#f8fafc" font-size="11" font-weight="600">15,670 LOC (30 files)</text>

            <!-- Bar 3 -->
            <text x="-10" y="61" fill="#94a3b8" font-size="12" text-anchor="end">Hardware Collectors (8 OEMs)</text>
            <rect class="chart-bar" x="0" y="48" width="60" height="17" rx="3" fill="#38bdf8"></rect>
            <text x="70" y="61" fill="#f8fafc" font-size="11" font-weight="600">12,598 LOC (25 files)</text>

            <!-- Bar 4 -->
            <text x="-10" y="84" fill="#94a3b8" font-size="12" text-anchor="end">Dev, Build & Crawler Tools</text>
            <rect class="chart-bar" x="0" y="71" width="51" height="17" rx="3" fill="#0284c7"></rect>
            <text x="61" y="84" fill="#f8fafc" font-size="11" font-weight="600">10,661 LOC (26 files)</text>

            <!-- Bar 5 -->
            <text x="-10" y="107" fill="#94a3b8" font-size="12" text-anchor="end">Clarity Web UI & API</text>
            <rect class="chart-bar" x="0" y="94" width="39" height="17" rx="3" fill="#0284c7"></rect>
            <text x="49" y="107" fill="#f8fafc" font-size="11" font-weight="600">8,240 LOC (11 files)</text>

            <!-- Bar 6 -->
            <text x="-10" y="130" fill="#94a3b8" font-size="12" text-anchor="end">CISA / NSA Security Engine</text>
            <rect class="chart-bar" x="0" y="117" width="32" height="17" rx="3" fill="#34d399"></rect>
            <text x="42" y="130" fill="#f8fafc" font-size="11" font-weight="600">6,751 LOC (84 controls)</text>

            <!-- Bar 7 -->
            <text x="-10" y="153" fill="#94a3b8" font-size="12" text-anchor="end">Core CLI & Concurrency</text>
            <rect class="chart-bar" x="0" y="140" width="29" height="17" rx="3" fill="#38bdf8"></rect>
            <text x="39" y="153" fill="#f8fafc" font-size="11" font-weight="600">6,162 LOC (14 files)</text>

            <!-- Bar 8 -->
            <text x="-10" y="176" fill="#94a3b8" font-size="12" text-anchor="end">vROps Management Pack</text>
            <rect class="chart-bar" x="0" y="163" width="15" height="17" rx="3" fill="#c084fc"></rect>
            <text x="25" y="176" fill="#f8fafc" font-size="11" font-weight="600">3,251 LOC (15 files)</text>

            <!-- Bar 9 -->
            <text x="-10" y="199" fill="#94a3b8" font-size="12" text-anchor="end">VCF 9.1 Compat Engine</text>
            <rect class="chart-bar" x="0" y="186" width="9" height="17" rx="3" fill="#fbbf24"></rect>
            <text x="19" y="199" fill="#f8fafc" font-size="11" font-weight="600">1,852 LOC (11 files)</text>

            <!-- Bar 10 -->
            <text x="-10" y="222" fill="#94a3b8" font-size="12" text-anchor="end">HCL Engine & Datasets</text>
            <rect class="chart-bar" x="0" y="209" width="9" height="17" rx="3" fill="#fbbf24"></rect>
            <text x="19" y="222" fill="#f8fafc" font-size="11" font-weight="600">1,820 LOC (19.6 MB HCL)</text>

            <!-- Bar 11 -->
            <text x="-10" y="245" fill="#94a3b8" font-size="12" text-anchor="end">BCG Deep-Link Generator</text>
            <rect class="chart-bar" x="0" y="232" width="4" height="17" rx="3" fill="#38bdf8"></rect>
            <text x="14" y="245" fill="#f8fafc" font-size="11" font-weight="600">816 LOC (5 domains)</text>
          </g>
        </svg>
      </div>
    </div>

    <!-- TAB 3: FEATURES -->
    <div id="view-features" style="display: none; flex-direction: column; gap: 20px;">
      <div class="card">
        <h3>Feature Battlecard & Technical Capabilities</h3>
        <p style="margin-bottom: 12px;">Everything built into the tool to empower enterprise sales engineers and solution architects.</p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>Capability</th><th>Technical Feature</th><th>Impact & Value Proposition</th></tr>
            </thead>
            <tbody>
              <tr><td><strong>vSAN ESA Qualification</strong></td><td>Direct-attached NVMe + ≥25 GbE NIC</td><td>Verifies unhindered NVMe pass-through; flags RAID controllers blocking ESA.</td></tr>
              <tr><td><strong>CPU Lifecycle Rules</strong></td><td>Broadcom KB 428874 Rules Engine</td><td>Detects unsupported Haswell/Broadwell, Skylake-SP override requirements, and Tier-1 Ice Lake/Xeon 6.</td></tr>
              <tr><td><strong>CISA / NSA BMC Hardening</strong></td><td>84-Control Out-of-Band Security Audit</td><td>Verifies credential policy, protocol hardening, management VLAN isolation, and firmware integrity.</td></tr>
              <tr><td><strong>Canonical Dell & Multi-OEM SEL</strong></td><td>DITA Topics & 76 IPMI Hex Codes</td><td>Clickable links to official Dell EEMS, HPE Gen12 IML, Cisco UCS Faults, Lenovo XCC, and QCT guides.</td></tr>
              <tr><td><strong>SE Decision Matrix (Tab 1)</strong></td><td>Dense Fleet Triage & Interactive Rollups</td><td>Compact ESA NVMe disk capacity (`4×3.8TB`), NIC link arrows (`4×25G↑`), memory efficiency %, and RAID flags.</td></tr>
              <tr><td><strong>Redfish Hypermedia Crawler</strong></td><td>Read-Only Traversal & Action Cataloger</td><td>Discovers complete Redfish tree, catalogs 11 action domains, and exports DMTF mockup ZIPs.</td></tr>
              <tr><td><strong>OCP 2.6 SMART Telemetry</strong></td><td>20+ NVMe Health Indicators</td><td>Extracts drive endurance wear %, lifetime temperature, spare capacity, and error rates.</td></tr>
              <tr><td><strong>ToR Switch Discovery</strong></td><td>LLDP & Cisco CDP Multi-Vendor Neighbor Map</td><td>Discovers physical switch names, port IDs, and VLANs for network cabling audits.</td></tr>
              <tr><td><strong>Private AI / GPU</strong></td><td>PCIe Accelerator GPU Detection</td><td>Identifies hardware capability for Private AI Foundation on VCF workloads.</td></tr>
              <tr><td><strong>Platform Security Baseline</strong></td><td>TPM 2.0 & Intel VMD Audits</td><td>Ensures TPM 2.0 EnabledAndActivated and Intel VMD Disabled for native pass-through.</td></tr>
              <tr><td><strong>Client-Side Base64 Excel</strong></td><td>11-Tab Unified Workbook Export</td><td>Pre-rendered XLSX and obfuscated reverse-key ZIP downloads instantly even on <code>file://</code> protocol.</td></tr>
              <tr><td><strong>Broadcom BCG Links</strong></td><td>Dynamic HCL URL Generation</td><td>Instant single-click BCG lookup for server, CPU, SSD, controller, and NIC hardware.</td></tr>
              <tr><td><strong>Multi-Pass Auto-Retry</strong></td><td>3-Pass Recovery Engine</td><td>Adaptive thread clamping and differential rescan prevents slow BMC lockups.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- TAB 4: HARDWARE -->
    <div id="view-hardware" style="display: none; flex-direction: column; gap: 20px;">
      <div class="grid-4">
        <div class="card">
          <span class="badge badge-info">Dell iDRAC 7/8/9/10</span>
          <h3 style="margin-top: 8px;">Dell PowerEdge</h3>
          <p style="margin-top: 4px;"><strong>679K+ LOC Mockups:</strong> R770, R750, R670 (Xeon 6), R7525 (EPYC), R740xd (24 NVMe). Canonical EEMS DITA topics, BOSS card, wear %, licenses.</p>
        </div>
        <div class="card">
          <span class="badge badge-info">HPE iLO 4/5/6</span>
          <h3 style="margin-top: 8px;">HPE ProLiant</h3>
          <p style="margin-top: 4px;"><strong>376K+ LOC Mockups:</strong> DL380a Gen11, DL360 Gen10, Gen10 Plus. SmartStorage Array parsing, Gen12 IML direct deep links, SystemUsage.</p>
        </div>
        <div class="card">
          <span class="badge badge-info">Lenovo XCC 1/2</span>
          <h3 style="margin-top: 8px;">Lenovo ThinkSystem</h3>
          <p style="margin-top: 4px;"><strong>SR630 & SR650:</strong> SR630 V2 nodes. Drive metrics, LicenseService tiers, LLDP switch port extraction, XCC Events Guide cross-walk.</p>
        </div>
        <div class="card">
          <span class="badge badge-info">Cisco IMC / UCS</span>
          <h3 style="margin-top: 8px;">Cisco UCS</h3>
          <p style="margin-top: 4px;"><strong>C220 & C240 M5/M6:</strong> /Managers/CIMC fastpath, drive telemetry, Cisco CDP neighbor maps, 114 F-code fault guide catalog.</p>
        </div>
        <div class="card">
          <span class="badge badge-info">Supermicro DCMS</span>
          <h3 style="margin-top: 8px;">Supermicro</h3>
          <p style="margin-top: 4px;"><strong>BigTwin & Ultra:</strong> SYS-E200-8D Edge Nodes. SimpleStorage parser, Lighttpd resilient retry, DCMS license detection, IPMI guide.</p>
        </div>
        <div class="card">
          <span class="badge badge-info">Intel BMC</span>
          <h3 style="margin-top: 8px;">Intel Server System</h3>
          <p style="margin-top: 4px;"><strong>Intel Server System:</strong> Dedicated Intel BMC hooks + Generic DMTF Redfish fallback for white-box servers.</p>
        </div>
        <div class="card">
          <span class="badge badge-purple">Quanta / QCT</span>
          <h3 style="margin-top: 8px;">Quanta Cloud Technology</h3>
          <p style="margin-top: 4px;"><strong>QuantaPlex & QuantaGrid:</strong> AST2500 BMC fastpath (`/Systems/Self`), Oem.Quanta_RackScale drive wear, honest license badges.</p>
        </div>
        <div class="card">
          <span class="badge badge-purple">GIGABYTE MegaRAC</span>
          <h3 style="margin-top: 8px;">GIGABYTE Technology</h3>
          <p style="margin-top: 4px;"><strong>Enterprise Servers:</strong> AMI MegaRAC fastpath (`/Systems/Self`), Oem.GBT drive slots, SimpleStorage fallback routing.</p>
        </div>
      </div>

      <div class="card">
        <h3>Test Fixture Data Volume (Real-World Enterprise Redfish Dumps in LOC)</h3>
        <p style="margin-bottom: 16px;">Real-world server dumps recorded from live enterprise BMCs used in zero-network automated pytest replay suites.</p>
        <svg viewBox="0 0 850 250" style="width:100%; height:auto; background:var(--bg-card-sub); border-radius:8px; border:1px solid var(--border-sub); padding:10px;">
          <g transform="translate(190, 20)">
            <text x="-10" y="15" fill="#94a3b8" font-size="12" text-anchor="end">Dell PowerEdge R770</text>
            <rect class="chart-bar" x="0" y="2" width="520" height="17" rx="3" fill="#38bdf8"></rect>
            <text x="530" y="15" fill="#f8fafc" font-size="11" font-weight="600">453,592 lines (1,885 files)</text>

            <text x="-10" y="38" fill="#94a3b8" font-size="12" text-anchor="end">HPE ProLiant DL380a Gen11</text>
            <rect class="chart-bar" x="0" y="25" width="325" height="17" rx="3" fill="#34d399"></rect>
            <text x="335" y="38" fill="#f8fafc" font-size="11" font-weight="600">283,710 lines (1,018 files)</text>

            <text x="-10" y="61" fill="#94a3b8" font-size="12" text-anchor="end">HPE ProLiant DL360 Gen10</text>
            <rect class="chart-bar" x="0" y="48" width="106" height="17" rx="3" fill="#0284c7"></rect>
            <text x="116" y="61" fill="#f8fafc" font-size="11" font-weight="600">92,772 lines (408 files)</text>

            <text x="-10" y="84" fill="#94a3b8" font-size="12" text-anchor="end">Dell PowerEdge R7525 (EPYC)</text>
            <rect class="chart-bar" x="0" y="71" width="84" height="17" rx="3" fill="#38bdf8"></rect>
            <text x="94" y="84" fill="#f8fafc" font-size="11" font-weight="600">73,182 lines (451 files)</text>

            <text x="-10" y="107" fill="#94a3b8" font-size="12" text-anchor="end">Dell PowerEdge R740xd (NVMe)</text>
            <rect class="chart-bar" x="0" y="94" width="76" height="17" rx="3" fill="#0284c7"></rect>
            <text x="86" y="107" fill="#f8fafc" font-size="11" font-weight="600">66,325 lines (425 files)</text>

            <text x="-10" y="130" fill="#94a3b8" font-size="12" text-anchor="end">Dell PowerEdge R670 (Xeon 6)</text>
            <rect class="chart-bar" x="0" y="117" width="68" height="17" rx="3" fill="#38bdf8"></rect>
            <text x="78" y="130" fill="#f8fafc" font-size="11" font-weight="600">59,617 lines (376 files)</text>

            <text x="-10" y="153" fill="#94a3b8" font-size="12" text-anchor="end">GIGABYTE Server (MegaRAC)</text>
            <rect class="chart-bar" x="0" y="140" width="41" height="17" rx="3" fill="#c084fc"></rect>
            <text x="51" y="153" fill="#f8fafc" font-size="11" font-weight="600">36,082 lines (257 files)</text>

            <text x="-10" y="176" fill="#94a3b8" font-size="12" text-anchor="end">Supermicro Enterprise</text>
            <rect class="chart-bar" x="0" y="163" width="10" height="17" rx="3" fill="#fbbf24"></rect>
            <text x="20" y="176" fill="#f8fafc" font-size="11" font-weight="600">8,847 lines (9 files)</text>

            <text x="-10" y="199" fill="#94a3b8" font-size="12" text-anchor="end">Quanta D42A-2U (AST2500)</text>
            <rect class="chart-bar" x="0" y="186" width="5" height="17" rx="3" fill="#c084fc"></rect>
            <text x="15" y="199" fill="#f8fafc" font-size="11" font-weight="600">2,300 lines (32 files)</text>
          </g>
        </svg>
      </div>
    </div>

    <!-- TAB 5: CODEBASE -->
    <div id="view-codebase" style="display: none; flex-direction: column; gap: 20px;">
      <div class="card">
        <h3>Codebase Architecture (189K+ Total LOC)</h3>
        <p style="margin-bottom: 12px;">Strict 4-layer decoupled architecture adhering to 100% Python standard library constraints.</p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>Layer / Component Area</th><th>Description</th><th>Files</th><th>Lines of Code</th><th>Key Technologies</th></tr>
            </thead>
            <tbody>
              <tr><td><strong>Layer A: Redfish Collector</strong></td><td>Hardware discovery mixins & 8 OEM adapters</td><td>25 files</td><td>12,598 LOC</td><td>Dell, HPE, Lenovo, Cisco, Supermicro, Intel, Quanta, Gigabyte</td></tr>
              <tr><td><strong>Layer B: Compat Engine</strong></td><td>VCF 9.1, CPU deprecation, ESA storage rules</td><td>11 files</td><td>1,852 LOC</td><td>KB 428874, vSAN ESA/OSA, TPM 2.0, Intel VMD</td></tr>
              <tr><td><strong>Layer B: Security Engine</strong></td><td>84-control CISA & NSA BMC hardening audit</td><td>8 files</td><td>6,751 LOC</td><td>Neutral contract, 10 statuses, secret redaction, SHA-256</td></tr>
              <tr><td><strong>Layer C: BCG Links</strong></td><td>Dynamic Broadcom HCL deep-links</td><td>1 file</td><td>816 LOC</td><td>Server, CPU, SSD, Controller, GPU URLs</td></tr>
              <tr><td><strong>Layer D: Reports & SE Matrix</strong></td><td>Standalone offline HTML reports & Tab 1 Matrix</td><td>30 files</td><td>15,670 LOC</td><td>11 domain sections, Tab 1 SE Decision Matrix, canonical SEL links</td></tr>
              <tr><td><strong>Layer D: Clarity Web UI</strong></td><td>Browser dashboard, SSE streamer & OEM mode</td><td>11 files</td><td>8,240 LOC</td><td>Clarity Design System, Dark Mode, Async Scanner, OEM Import</td></tr>
              <tr><td><strong>Core CLI, Concurrency & Crawler</strong></td><td>3-pass resilient scanner & hypermedia crawler</td><td>14 files</td><td>6,162 LOC</td><td>ThreadPoolExecutor, crawler engine, action cataloger, obfuscation</td></tr>
              <tr><td><strong>HCL Engine & Loader</strong></td><td>Offline vSAN HCL & CPU series cross-ref</td><td>4 files</td><td>1,820 LOC</td><td>19.6 MB bundled CSV/JSON datasets</td></tr>
              <tr><td><strong>Aria Operations Pack</strong></td><td>vROps integration, dashboards, traversals</td><td>15 files</td><td>3,251 LOC</td><td>.pak package, custom alerts, security metrics, adapter config</td></tr>
              <tr><td><strong>Developer, Build & Data Hygiene</strong></td><td>Data hygiene gates, PyInstaller, bundlers</td><td>26 files</td><td>10,661 LOC</td><td>check_data_hygiene, mock generators, CI test gates</td></tr>
              <tr><td><strong>Automated Test Suite</strong></td><td>99 test modules & real hardware fixtures</td><td>119 files</td><td>122,090 LOC</td><td>1,425 pytest tests, 1.0M+ LOC raw BMC dumps, zero-network replay</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Footer Area -->
    <div class="divider"></div>
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; font-size: 13px; color: var(--text-dim);">
      <span>VCF / vSphere 9.1 HCI Readiness Assessment Tool • Presentation & Infographic Kit v{TOOL_VERSION}</span>
      <span>100% Free-Standing & Offline Capable • Zero External Dependencies</span>
    </div>
  </div>

  <script>
    let currentTrack = 'executive';
    let currentSlide = '1';
    let clusterNodes = 32;

    const trackData = {{
      executive: {{
        title: "Executive & Leadership Track (CIO / VP / IT Director)",
        tag: "CapEx & Strategy Focus",
        desc: "Focus on CapEx avoidance, rapid time-to-value, deterministic migration roadmaps, and labor cost savings.",
        stats: [
          {{ val: "$19,250", lbl: "Labor Cost Avoided (32-Node Cluster)", tone: "success" }},
          {{ val: "30 Sec / Host", lbl: "Automated Velocity (vs 3.5 hrs manual)", tone: "info" }},
          {{ val: "70–85%", lbl: "Typical Existing Fleet Repurposing Rate", tone: "success" }},
          {{ val: "8 OEMs", lbl: "Dell • HPE • Lenovo • Cisco • Supermicro • Intel • QCT • Gigabyte", tone: "purple" }},
          {{ val: "1-Click Sign-off", lbl: "Official Broadcom BCG Verified Reports", tone: "info" }}
        ],
        slides: {{
          '1': {{
            headline: "Maximize Existing CapEx: Instantly Qualify Server Fleets for VMware Cloud Foundation 9.1",
            bullets: [
              "Avoid Unnecessary Hardware Refresh: 70–85% of existing 14th/15th/16th Gen servers can be repurposed for VCF 9.1 without full rack replacements.",
              "Eliminate Audit Friction: Replace weeks of manual spreadsheet audits with an automated 30-second scan per host.",
              "Predictable Migration Timeline: Categorize every cluster node into 'VCF 9.1 Ready', 'Targeted Upgrade Required', or 'Refresh Candidate'."
            ],
            notes: "Emphasize capital expenditure avoidance, fast time-to-value, and risk reduction in migration timelines. Position this assessment as a zero-risk prerequisite before committing budget to new server purchases.",
            objection: "How much budget and staff time does this save us compared to traditional assessment consulting?",
            answer: "On average, a 32-node cluster saves 110+ hours of senior engineering time ($19,250+ in labor), completing in under 30 minutes instead of 2 to 3 weeks."
          }},
          '2': {{
            headline: "Zero-Disruption Enterprise Safety: 100% Out-of-Band & Air-Gapped",
            bullets: [
              "Zero Workload Downtime: Production VMs, databases, and guest operating systems remain completely untouched and unmonitored.",
              "No Software Agents: Runs out-of-band directly against BMC management controllers across 8 Tier-1 OEMs (Dell, HPE, Lenovo, Cisco, Supermicro, Intel, Quanta, GIGABYTE).",
              "Dark-Site & Air-Gapped Compliance: Works completely offline with zero internet connectivity or cloud phone-home."
            ],
            notes: "Reassure executives that scanning creates zero operational downtime and zero compliance exposure.",
            objection: "Does this require installing software on our mission-critical database hosts or guest VMs?",
            answer: "No. The assessment is 100% out-of-band via BMC HTTPS. Nothing is installed, modified, or executed on the host operating system."
          }},
          '3': {{
            headline: "Deterministic Compatibility: CPU Support Tiers & vSAN Express Storage (ESA)",
            bullets: [
              "VCF 9.1 CPU Validation: Automated checks against Broadcom KB 428874 (Intel Ice Lake, Sapphire Rapids, Xeon 6, AMD EPYC; flags Skylake-SP override requirement).",
              "vSAN ESA Storage Qualification: Validates NVMe direct-attached pass-through and >= 25 GbE network fabric.",
              "Clear Remediations: Pinpoints exact minimal upgrade BOMs (e.g., adding OCP 3.0 25GbE NIC) rather than whole-server replacements."
            ],
            notes: "Highlight that every recommendation is backed by strict Broadcom support policies, protecting the organization from uncertified architectures.",
            objection: "What if some of our older servers are not fully supported?",
            answer: "The report gives you an itemized BOM for repurposing: servers that can run VCF 9.1 as-is, servers that need minor NIC/drive upgrades, and older nodes to retire."
          }},
          '4': {{
            headline: "Protecting Data Assets: Deep Drive Health & Multi-Vendor SEL Link Resolution",
            bullets: [
              "Drive Wear & Remaining Life: OCP 2.6 SMART telemetry extracts exact NVMe wear percentage and remaining spare blocks.",
              "System Event Log (SEL) Resolution: Automatically decodes raw error codes into canonical Dell PowerEdge EEMS chapters and HPE Gen12 IML links.",
              "Prevent Post-Deployment Outages: Flags degraded drives and uncorrectable memory errors before provisioning VCF clusters."
            ],
            notes: "Frame drive wear and telemetry as risk avoidance—ensuring repurposed hardware doesn't fail right after deployment.",
            objection: "Can we trust repurposed SSDs for mission-critical enterprise storage?",
            answer: "Yes, because the tool extracts granular endurance wear percentages, spare blocks, and lifetime thermal metrics to guarantee drive health before provisioning."
          }},
          '5': {{
            headline: "Actionable Executive Deliverables: Tab 1 SE Matrix & 1-Click BCG Verification",
            bullets: [
              "Standalone Interactive Reports: Single-file HTML reports easily shared with leadership, finance, and procurement.",
              "Tab 1 SE Decision Matrix: Dense executive rollup of ESA NVMe disk capacity, network port link arrows, memory efficiency, and RAID status.",
              "1-Click Broadcom HCL Links: Pre-computed URLs to official Broadcom Compatibility Guide entries for rapid sign-off.",
              "Aria Operations Integration: Ready-to-import management pack (.pak) for day-2 lifecycle visibility."
            ],
            notes: "Showcase the ease of sharing findings with internal audit and procurement committees.",
            objection: "Who validates that these findings match Broadcom's official support matrix?",
            answer: "Every component in the generated report has a direct 1-click URL linking to its exact entry in Broadcom's official online Compatibility Guide."
          }},
          '6': {{
            headline: "Rapid Engagement Roadmap: 4-Step Zero-Risk Readiness Workshop",
            bullets: [
              "Step 1: Scoping & Read-Only Credentials (30 mins).",
              "Step 2: Automated Fleet Scan (15–30 mins).",
              "Step 3: Qualification & Gap Analysis (Automated).",
              "Step 4: Executive Findings & Migration Roadmap Presentation (45 mins)."
            ],
            notes: "Close with a low-friction call to action for scheduling the rapid readiness assessment.",
            objection: "How much preparation is needed from our internal teams before we start?",
            answer: "Less than 30 minutes to provide read-only BMC IP targets and temporary credentials on a designated management workstation."
          }}
        }}
      }},
      architect: {{
        title: "Enterprise Architect Track (Cloud / Infrastructure / Storage)",
        tag: "VCF 9.1 & vSAN ESA Technical Depth",
        desc: "Focus on VCF 9.1 microarchitectures (KB 428874), vSAN ESA pass-through NVMe storage, 25GbE ToR fabric, Intel VMD/TPM 2.0, and Private AI GPU sizing.",
        stats: [
          {{ val: "8 Server OEMs", lbl: "Dell • HPE • Lenovo • Cisco • Supermicro • Intel • QCT • Gigabyte", tone: "info" }},
          {{ val: "1-Click BCG", lbl: "Dynamic Broadcom HCL URL Generator", tone: "success" }},
          {{ val: "ESA vs OSA", lbl: "Direct-Attached NVMe & 25GbE Validation", tone: "success" }},
          {{ val: "KB 428874", lbl: "CPU Support & Deprecation Rules Engine", tone: "warning" }},
          {{ val: "84 Controls", lbl: "CISA / NSA Joint BMC Hardening Baseline", tone: "purple" }}
        ],
        slides: {{
          '1': {{
            headline: "Deterministic Architecture Alignment: Validating Fleet Repurposing for VCF 9.1",
            bullets: [
              "Architectural Feasibility: Instant qualification of CPU generations, memory interleaving channels, and PCIe lane topologies.",
              "HCL Cross-Referencing: Automatic correlation against 19.6 MB offline Broadcom vSAN HCL datasets and CPU matrices.",
              "Eliminating Architecture Guesswork: Instant classification into vSAN ESA Qualified, OSA Eligible, or Memory Tiering candidates."
            ],
            notes: "Highlight architectural rigour, compliance with VMware Cloud Foundation 9.1 validated designs, and automated HCL correlation.",
            objection: "How does the tool distinguish between Intel Skylake-SP and Cascade Lake-SP under KB 428874?",
            answer: "The engine extracts CPU stepping, model, and family IDs to classify Skylake-SP as Supported (Override Required) and Cascade Lake/Ice Lake/Xeon 6 as Fully Supported Tier 1."
          }},
          '2': {{
            headline: "4-Layer Decoupled Architecture & Multi-OEM Redfish Subsystem",
            bullets: [
              "Standardized DMTF Redfish: Uses /Systems, /Chassis, /Managers, /Storage, and /NetworkAdapters schemas.",
              "8 OEM Extension Adapters: Vendor-specific handlers for Dell iDRAC, HPE iLO, Lenovo XCC, Cisco IMC, Supermicro DCMS, Intel, Quanta, and GIGABYTE.",
              "Adaptive Concurrency: 3-pass resilient thread pool with differential rescan to prevent slow BMC bus lockups."
            ],
            notes: "Explain the clean separation of Layer A (Collector), Layer B (Compat Engine & Security), Layer C (BCG Links), and Layer D (Reports & UI).",
            objection: "How do you handle vendor-specific storage quirks like HPE SmartStorage, Dell BOSS cards, or Quanta/Gigabyte OEM drive bays?",
            answer: "Dedicated OEM hook mixins automatically discover and normalize OEM storage hierarchies into a unified pass-through topology."
          }},
          '3': {{
            headline: "vSAN ESA Rules Engine: NVMe Pass-Through, RAID Incompatibility & 25GbE",
            bullets: [
              "Pass-Through Storage Audit: Verifies NVMe direct attachment to PCIe root complex; flags NVMe behind RAID controllers as ESA-incompatible.",
              "Networking Thresholds: Enforces >= 25 GbE NIC speed requirements for ESA; flags 10 GbE clusters for network remediation.",
              "BIOS & Cryptoprocessor: Verifies TPM 2.0 EnabledAndActivated and Intel VMD Disabled for native pass-through latency."
            ],
            notes: "Walk through the technical conditions for ESA readiness: direct NVMe attachment, 25GbE NICs, and VMD configuration.",
            objection: "Why does the tool flag NVMe drives behind hardware RAID controllers as unsupported for vSAN ESA?",
            answer: "vSAN ESA requires unhindered direct NVMe PCIe pass-through. RAID abstraction introduces latency and prevents native ESA acceleration."
          }},
          '4': {{
            headline: "Fabric Topologies & Hardware Acceleration: ToR LLDP, GPU & Canonical SEL",
            bullets: [
              "Multi-Vendor ToR Neighbor Mapping: Harvests LLDP and Cisco CDP neighbor frames to map physical switch IDs, port numbers, and VLAN trunks.",
              "Canonical SEL Deep-Linking: Canonical Dell PowerEdge EEMS guide DITA topics (20+ chapters), HPE Gen12 IML links, and Cisco 11-chapter fault resolution.",
              "Private AI Foundation Acceleration: Discovers NVIDIA & AMD PCIe accelerator GPUs for enterprise GenAI inference workloads."
            ],
            notes: "Demonstrate how ToR switch discovery verifies cabling symmetry across cluster failure domains.",
            objection: "Can this help us plan VMware Private AI Foundation deployments?",
            answer: "Yes. The collector audits PCIe device IDs and GPU accelerators to confirm host readiness for VMware Private AI Foundation with NVIDIA."
          }},
          '5': {{
            headline: "Technical Artifacts: Tab 1 SE Decision Matrix, Offline Base64 Excel & Aria Pack",
            bullets: [
              "Tab 1 SE Decision Matrix: Instant dense HTML matrix with compact disk rollups, directional NIC link states (↑/↓), and memory efficiency %.",
              "Offline Base64 Excel Workbook: Full 11-tab workbook generated client-side even on file:// protocol without a server backend.",
              "Redfish Hypermedia Crawler: Discovers all endpoints, catalogs 11 action domains, and exports DMTF mockup ZIP archives."
            ],
            notes: "Show the SE Decision Matrix table and how it maps raw inventory directly into VCF design workbooks.",
            objection: "Can we export the raw structured inventory for our configuration management database (CMDB)?",
            answer: "Yes. The tool provides complete JSON manifests, client-side Base64 Excel workbooks, and obfuscated ZIP packages with reverse-mapping keys."
          }},
          '6': {{
            headline: "Architectural Readiness Workshop: Technical Validation Methodology",
            bullets: [
              "Technical Phase 1: Subnet targeting, credential provisioning, and pre-scan latency probing.",
              "Technical Phase 2: Multi-pass Redfish discovery, differential rescan, and raw telemetry aggregation.",
              "Technical Phase 3: Compatibility evaluation, BCG deep-linking, CISA/NSA security audit, and vSAN ESA pass-through scoring.",
              "Technical Phase 4: Delivery of VCF 9.1 cluster BOM, network topology map, and repurposing blueprints."
            ],
            notes: "Structure the engagement as an architecture validation review aligned with VMware Validated Designs.",
            objection: "What outputs do our lead infrastructure architects receive at the end?",
            answer: "Interactive standalone HTML reports with Tab 1 SE Decision Matrix, structured 11-tab Excel spreadsheets, vSAN ESA qualification verdicts, and pre-computed BCG links."
          }}
        }}
      }},
      operations: {{
        title: "IT & SecOps Track (Platform Ops / Infosec / Datacenter)",
        tag: "Zero-Footprint & Security Assurance",
        desc: "Focus on non-invasive agentless discovery, read-only BMC credentials, 100% Python standard library (zero 3rd-party dependencies), 84-control CISA/NSA audit, SHA-256 data sanitization, and air-gapped dark-site operation.",
        stats: [
          {{ val: "0 Footprint", lbl: "Agentless Out-of-Band (100% Python Stdlib)", tone: "success" }},
          {{ val: "84 Controls", lbl: "CISA / NSA Joint BMC Hardening Audit", tone: "success" }},
          {{ val: "Read-Only HTTPS", lbl: "Lowest-Privilege Operator BMC Account", tone: "info" }},
          {{ val: "100% Air-Gapped", lbl: "Zero Cloud Dependencies & Dark-Site Safe", tone: "warning" }},
          {{ val: "SHA-256 Masking", lbl: "Automated PII & Serial Number Sanitization", tone: "info" }}
        ],
        slides: {{
          '1': {{
            headline: "Zero-Risk Operational Discovery: Assessing Fleets with Zero Production Impact",
            bullets: [
              "Zero Host Interruptions: Production OS, hypervisor kernels, and active workloads experience 0% CPU or memory impact.",
              "No Software Deployment: Zero agents installed, zero kernel drivers, and zero system reboots required.",
              "Air-Gapped & Offline: Runs in completely isolated, dark-site datacenters without internet access."
            ],
            notes: "Assure operations teams that running this assessment carries zero operational risk to running workloads.",
            objection: "Will this require scheduling maintenance windows or rebooting cluster nodes?",
            answer: "No. The assessment is conducted out-of-band via standard BMC HTTPS APIs while servers remain 100% operational in production."
          }},
          '2': {{
            headline: "Security Assurance & Architecture: Zero External Runtime Dependencies",
            bullets: [
              "100% Python Standard Library: Built with zero 3rd-party dependencies (no requests, urllib3, pandas, or external binaries).",
              "Read-Only BMC Privileges: Requires only standard read-only Operator BMC accounts on port 443 HTTPS.",
              "Data Sanitization & Privacy: SHA-256 salted serial masking and RFC 5737 documentation IP redaction built-in."
            ],
            notes: "Explain that having 0 external runtime dependencies eliminates software supply-chain vulnerabilities.",
            objection: "Does this introduce third-party library vulnerabilities into our secure management consoles?",
            answer: "No. The tool code strictly uses the Python standard library only, mechanically enforced in CI by Ruff and automated import gates."
          }},
          '3': {{
            headline: "CISA & NSA BMC Hardening Audit: 84 Out-of-Band Security Checks",
            bullets: [
              "Federal Guidance Alignment: Aligned with CISA and NSA Joint Cybersecurity Information Sheet (*Harden Baseboard Management Controllers*).",
              "84 Canonical Controls: Evaluates 59 configuration, 16 operational, and 9 interface controls across credential policy, protocol hardening, and firmware integrity.",
              "Zero Write-Only Secret Leaks: Write-only credentials strictly held as unknown_write_only; recursive secret redaction sanitizes passwords and PEM keys."
            ],
            notes: "Highlight how the tool uncovers BMC security posture gaps, unencrypted services, and credential hygiene issues without invasive probing.",
            objection: "Does the security audit attempt intrusive penetration testing or exploit execution against the BMC?",
            answer: "No. The evaluation uses pure read-only GET inspection of Redfish security schemas, adhering strictly to non-destructive assessment standards."
          }},
          '4': {{
            headline: "Hardware Health & Reliability: NVMe Wear %, Thermals & Canonical SEL Links",
            bullets: [
              "Granular NVMe Wear Telemetry: Extracts OCP 2.6 SMART health, wear %, and lifetime power-on hours.",
              "Canonical Dell PowerEdge EEMS Topics: Direct deep-links to verified DITA chapters across 20+ hardware categories and 76 IPMI hex codes.",
              "Multi-Vendor SEL Coverage: HPE Gen12 IML direct class/code URLs, Cisco UCS 11-chapter fault resolution, Lenovo XCC, and Supermicro IPMI."
            ],
            notes: "Show how SecOps and datacenter engineers can spot failing hardware components before deploying VCF.",
            objection: "Does the scan capture active hardware warnings like fan failures or ECC memory errors?",
            answer: "Yes. The collector extracts SEL and IML logs, highlighting uncorrectable memory errors, thermal alerts, and drive bay removals with clickable vendor reference links."
          }},
          '5': {{
            headline: "Auditable & Portable Artifacts: Zero-Footprint Deliverables & Obfuscated Workbooks",
            bullets: [
              "Zero Web Server Requirement: Standalone HTML reports require no hosting server, database, or external CDN.",
              "Obfuscated Excel + Reverse-Mapping Key: Generates PII-scrubbed workbooks bundled with private decryption keys for external audit.",
              "Aria Operations Integration: Monitor physical hardware health and BMC security posture continuously inside existing vROps workflows."
            ],
            notes: "Emphasize that reports are standalone single files that can be archived into change management tickets.",
            objection: "Can we sanitize the report before sharing it with third-party vendors or consultants?",
            answer: "Yes. The built-in --obfuscate flag scrubs all IP addresses, MAC addresses, serial numbers, and hostnames using SHA-256 hashing while generating an offline reverse-mapping key."
          }},
          '6': {{
            headline: "Streamlined Operations Workflow: 4-Step Zero-Risk Execution",
            bullets: [
              "Step 1: Network Scoping & Read-Only BMC Credential Provisioning (30 mins).",
              "Step 2: Automated Scan Run on Management Host (15–30 mins).",
              "Step 3: Automated Verification, CISA/NSA Security Audit & Health Scrutiny.",
              "Step 4: Report Archival & Remediation Planning."
            ],
            notes: "Emphasize low operational overhead and predictable, bounded execution times.",
            objection: "What network access rules do we need to open in our firewalls?",
            answer: "Only outbound HTTPS (TCP 443) from the designated management console to the BMC management subnet. No agent ports or host OS ports are needed."
          }}
        }}
      }}
    }};

    function setTrack(track) {{
      currentTrack = track;
      document.getElementById('btn-exec').className = track === 'executive' ? 'btn-track active' : 'btn-track';
      document.getElementById('btn-arch').className = track === 'architect' ? 'btn-track active' : 'btn-track';
      document.getElementById('btn-ops').className = track === 'operations' ? 'btn-track active' : 'btn-track';

      const data = trackData[track];
      document.getElementById('track-badge').innerText = data.tag;
      document.getElementById('track-title').innerText = data.title;
      document.getElementById('track-desc').innerText = data.desc;

      // Render stats
      const statsHtml = data.stats.map(s => `
        <div class="stat-box">
          <div class="stat-val ${{s.tone}}">${{s.val}}</div>
          <div class="stat-lbl">${{s.lbl}}</div>
        </div>
      `).join('');
      document.getElementById('stats-grid').innerHTML = statsHtml;

      renderSlide();
    }}

    function setSlide(num) {{
      currentSlide = num;
      document.getElementById('slide-select').value = num;
      renderSlide();
    }}

    function prevSlide() {{
      let num = parseInt(currentSlide, 10) - 1;
      if (num < 1) num = 6;
      setSlide(String(num));
    }}

    function nextSlide() {{
      let num = parseInt(currentSlide, 10) + 1;
      if (num > 6) num = 1;
      setSlide(String(num));
    }}

    function updateNodes(n) {{
      clusterNodes = n;
      const hoursSaved = Math.round(n * 3.5 - (n * 0.5) / 60);
      const costSaved = Math.round(hoursSaved * 175);
      const hrsEl = document.getElementById('roi-hrs');
      const costEl = document.getElementById('roi-cost');
      const lblEl = document.getElementById('roi-nodes-lbl');
      if (hrsEl) hrsEl.innerText = hoursSaved + ' hrs';
      if (costEl) costEl.innerText = '$' + costSaved.toLocaleString();
      if (lblEl) lblEl.innerText = n + ' Nodes';
      ['16', '32', '64', '128'].forEach(btnN => {{
        const el = document.getElementById('btn-node-' + btnN);
        if (el) el.className = btnN == n ? 'btn-track active' : 'btn-track';
      }});
    }}

    function renderSlide() {{
      const slide = trackData[currentTrack].slides[currentSlide];
      document.getElementById('slide-badge').innerText = 'Slide ' + currentSlide + ' of 6';
      document.getElementById('slide-headline').innerText = slide.headline;
      document.getElementById('slide-bullets').innerHTML = slide.bullets.map((b, i) => `
        <div style="display:flex; gap:8px;"><strong style="color: var(--blue); min-width:18px;">${{i + 1}}.</strong> <span>${{b}}</span></div>
      `).join('');
      document.getElementById('slide-notes').innerText = slide.notes;
      document.getElementById('slide-objection').innerText = slide.objection;
      document.getElementById('slide-answer').innerText = slide.answer;

      // Render visual right column
      let visualHtml = '';
      if (currentSlide === '1') {{
        const hoursSaved = Math.round(clusterNodes * 3.5 - (clusterNodes * 0.5) / 60);
        const costSaved = Math.round(hoursSaved * 175);
        visualHtml = `
          <div class="card-sub">
            <h3 style="font-size:15px;">Interactive ROI Model (<span id="roi-nodes-lbl" style="color:var(--blue);">${{clusterNodes}} Nodes</span>)</h3>
            <p style="font-size:12px; margin-top:2px;">Select cluster size to calculate avoided labor:</p>
            <div style="display: flex; gap: 6px; margin: 12px 0;">
              <button id="btn-node-16" class="btn-track ${{clusterNodes == 16 ? 'active' : ''}}" onclick="updateNodes(16)">16</button>
              <button id="btn-node-32" class="btn-track ${{clusterNodes == 32 ? 'active' : ''}}" onclick="updateNodes(32)">32</button>
              <button id="btn-node-64" class="btn-track ${{clusterNodes == 64 ? 'active' : ''}}" onclick="updateNodes(64)">64</button>
              <button id="btn-node-128" class="btn-track ${{clusterNodes == 128 ? 'active' : ''}}" onclick="updateNodes(128)">128</button>
            </div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px;">
              <div class="stat-box"><div class="stat-val success" id="roi-hrs">${{hoursSaved}} hrs</div><div class="stat-lbl">Time Saved</div></div>
              <div class="stat-box"><div class="stat-val info" id="roi-cost">$${{costSaved.toLocaleString()}}</div><div class="stat-lbl">Labor Avoided</div></div>
            </div>
            <p style="font-size:11.5px; color:#64748b; margin-top:8px;">Based on 3.5 hrs/node manual audit @ $175/hr blended architect rate.</p>
          </div>
        `;
      }} else if (currentSlide === '2') {{
        visualHtml = `
          <div class="card-sub">
            <h3 style="font-size:15px; margin-bottom:6px;">Security & Operational Guardrails</h3>
            <div class="table-wrap">
              <table class="table">
                <tr><td><strong>Runtime</strong></td><td>100% Python Standard Library (0 external CVEs)</td></tr>
                <tr><td><strong>Privacy</strong></td><td>SHA-256 Masking & RFC 5737 doc IPs</td></tr>
                <tr><td><strong>Network</strong></td><td>Out-of-band HTTPS Port 443 only</td></tr>
                <tr><td><strong>Privilege</strong></td><td>Read-Only Operator BMC account</td></tr>
                <tr><td><strong>OEM Scope</strong></td><td>8 Enterprise Vendors (Dell, HPE, Lenovo, Cisco, SMC, Intel, QCT, Gigabyte)</td></tr>
              </table>
            </div>
          </div>
        `;
      }} else if (currentSlide === '3') {{
        visualHtml = `
          <div class="card-sub">
            <h3 style="font-size:15px; margin-bottom:6px;">VCF 9.1 & Security Rules Matrix</h3>
            <div class="table-wrap">
              <table class="table">
                <tr><td>CPU Tier 1</td><td><span class="badge badge-success">Supported Tier 1</span></td></tr>
                <tr><td>CPU Support Override</td><td><span class="badge badge-warning">Skylake-SP (Override Req.)</span></td></tr>
                <tr><td>vSAN ESA</td><td><span class="badge badge-success">ESA Qualified</span></td></tr>
                <tr><td>TPM 2.0</td><td><span class="badge badge-success">EnabledAndActivated</span></td></tr>
                <tr><td>CISA / NSA Audit</td><td><span class="badge badge-purple">84-Control Baseline</span></td></tr>
              </table>
            </div>
          </div>
        `;
      }} else if (currentSlide === '4') {{
        visualHtml = `
          <div class="card-sub">
            <h3 style="font-size:15px;">Hardware Health & Canonical SEL Links</h3>
            <div style="margin-top: 10px;">
              <div style="font-size: 12px; display: flex; justify-content: space-between;"><span>Solidigm NVMe SSD Wear</span><span style="color: #34d399; font-weight:600;">14% Used (Healthy)</span></div>
              <div class="progress-bar"><div class="progress-fill green" style="width: 14%;"></div></div>
            </div>
            <div style="margin-top: 12px;">
              <div style="font-size: 12px; display: flex; justify-content: space-between;"><span>Legacy SATA Boot SSD</span><span style="color: #f87171; font-weight:600;">88% Used (Flagged)</span></div>
              <div class="progress-bar"><div class="progress-fill red" style="width: 88%;"></div></div>
            </div>
            <div class="divider"></div>
            <p style="font-size: 12px;"><strong style="color: var(--blue);">ToR Switch:</strong> <code>tor-sw-01a.rack4</code> Port <code>Eth1/14</code> (VLAN 100/200).</p>
            <p style="font-size: 12px; margin-top: 4px;"><strong style="color: var(--purple);">SEL Resolution:</strong> Canonical Dell EEMS chapters (<code>SEC</code>, <code>MEM</code>, <code>PCI</code>) + HPE Gen12 IML links.</p>
          </div>
        `;
      }} else if (currentSlide === '5') {{
        visualHtml = `
          <div class="card-sub">
            <h3 style="font-size:15px;">Enterprise Deliverables Summary</h3>
            <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 10px;">
              <div style="background: rgba(5,150,105,0.15); border:1px solid #059669; padding: 9px; border-radius: 6px; font-size: 12px; color:#34d399;"><strong>✓ Standalone HTML Reports</strong> — Tab 1 SE Decision Matrix, 0 CDN/server calls.</div>
              <div style="background: rgba(2,132,199,0.15); border:1px solid #0284c7; padding: 9px; border-radius: 6px; font-size: 12px; color:#38bdf8;"><strong>✓ 1-Click Broadcom BCG Links</strong> — Server, CPU, SSD, controller, and NIC URLs.</div>
              <div style="background: rgba(251,191,36,0.15); border:1px solid #d97706; padding: 9px; border-radius: 6px; font-size: 12px; color:#fbbf24;"><strong>✓ 11-Tab Excel Workbook</strong> — Client-side Base64 export on file:// protocol.</div>
              <div style="background: rgba(192,132,252,0.15); border:1px solid #9333ea; padding: 9px; border-radius: 6px; font-size: 12px; color:#c084fc;"><strong>✓ Aria Operations Adapter</strong> — .pak bundle for live operational & security telemetry.</div>
            </div>
          </div>
        `;
      }} else {{
        visualHtml = `
          <div class="card-sub">
            <h3 style="font-size:15px;">4-Step Rapid Engagement Schedule</h3>
            <div style="display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; margin-top: 10px;">
              <div style="background:var(--bg-card); padding:8px 10px; border-radius:4px; border-left:3px solid var(--blue);"><strong style="color:var(--blue);">Step 1: Scoping</strong> (30 mins) — Read-only BMC credentials & IP targets.</div>
              <div style="background:var(--bg-card); padding:8px 10px; border-radius:4px; border-left:3px solid var(--blue);"><strong style="color:var(--blue);">Step 2: Fleet Scan</strong> (15-30 mins) — Automated out-of-band scan.</div>
              <div style="background:var(--bg-card); padding:8px 10px; border-radius:4px; border-left:3px solid var(--blue);"><strong style="color:var(--blue);">Step 3: Qualification</strong> (Instant) — VCF 9.1, vSAN ESA & CISA/NSA security audit.</div>
              <div style="background:var(--bg-card); padding:8px 10px; border-radius:4px; border-left:3px solid var(--green);"><strong style="color:var(--green);">Step 4: Presentation</strong> (45 mins) — Deliver findings, HTML reports & Excel BOM.</div>
            </div>
          </div>
        `;
      }}
      document.getElementById('slide-visual').innerHTML = visualHtml;
    }}

    function switchTab(tabId) {{
      ['slides', 'overview', 'features', 'hardware', 'codebase'].forEach(t => {{
        document.getElementById('tab-' + t).className = t === tabId ? 'tab-btn active' : 'tab-btn';
        document.getElementById('view-' + t).style.display = t === tabId ? 'flex' : 'none';
      }});
    }}

    function copySlidePitch() {{
      const slide = trackData[currentTrack].slides[currentSlide];
      const text = `SLIDE ${{currentSlide}} (${{trackData[currentTrack].title}}):\\n${{slide.headline}}\\n\\nTakeaways:\\n${{slide.bullets.map((b, i) => `${{i+1}}. ${{b}}`).join('\\n')}}\\n\\nSpeaker Track:\\n${{slide.notes}}\\n\\nObjection Handling:\\nQ: ${{slide.objection}}\\nA: ${{slide.answer}}`;
      navigator.clipboard.writeText(text).then(() => {{
        const btn = document.getElementById('copy-btn-text');
        if (btn) {{
          btn.innerText = 'Copied to Clipboard!';
          setTimeout(() => {{ btn.innerText = 'Copy Slide Pitch'; }}, 2000);
        }}
      }}).catch(() => {{}});
    }}

    // Initialize
    setTrack('executive');
  </script>
</body>
</html>
"""


def main() -> int:
    os.makedirs(os.path.dirname(HTML_OUT), exist_ok=True)

    print(f"==> Generating VCF 9.1 Readiness Infographic artifacts (v{TOOL_VERSION})...")

    # 1. Write docs/INFOGRAPHIC.md
    md_content = generate_markdown()
    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"  [✓] Written GitHub Markdown: {os.path.relpath(MD_OUT, PROJECT_ROOT)}")

    # 2. Write docs/infographic.html
    html_content = generate_html()
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  [✓] Written Standalone HTML:  {os.path.relpath(HTML_OUT, PROJECT_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
