# Holodeck 9: ESXi host networking

What the physical ESXi host must provide before Holodeck 9 is deployed on it, and how the lab R740xd
(`esxi1`) compares. The machine-readable version is in `src/groundzero/preflight/profiles/holodeck-9.toml`,
section `[host_network]`.

Source: [Holodeck 9 documentation](https://vmware.github.io/Holodeck/latest/) (Pre-requisites, Networking),
retrieved 2026-09-30.

## Requirements (standalone host, vSphere Standard Switch)

| # | Requirement | Detail |
|---|---|---|
| 1 | Switch MTU 9000 | The vSwitch carrying Holodeck traffic, plus jumbo frames on the upstream switch ports |
| 2 | Dedicated trunk port group | VLAN 4095 (all VLANs) on the vSS, isolated from production port groups |
| 3 | Trunk security policy | Promiscuous mode, MAC address changes and Forged transmits all set to **Accept** |
| 4 | Nested VLANs | Site A uses 0 and 10–25, Site B uses 40–58 (dual-site only). Change them with `-VLANRangeStart`. |
| 5 | Upstream VLANs | Only needed for multi-host vCenter clusters. On a standalone host the VLANs stay inside the trunk. |
| 6 | Holorouter uplink | A separate management/external port group, and one external IP per Holodeck environment |
| 7 | NTP | The NTP service is enabled and an NTP server is configured |

## Lab host `esxi1` (Dell R740xd), read 2026-09-30

Management: `vmk0` on port group "Management Network", **VLAN 100**, uplinks **vmnic0 + vmnic1** (both
active, 10 GbE). These go to switch `dwayneN4032` ports Te1/0/11 and Te1/0/12. The reinstall must preserve
this layout.

| # | Status | Observed |
|---|---|---|
| 1 | **Gap** | vSwitch0 MTU is 1500 |
| 2 | OK | Trunk port groups exist: HoloDeckSite1, HoloDeckSite2, holoSiteA, holoSiteB (VLAN 4095) |
| 3 | OK | All four trunk port groups accept promiscuous, MAC changes and forged transmits |
| 4/5 | OK | Standalone host, so nothing is needed upstream |
| 6 | OK | VLAN 100 port groups (VM Network, ManagementVM) can carry the Holorouter uplink |
| 7 | **Gap** | No NTP server is configured. Lab decision: use **`pool.ntp.org`** |
| | Note | The trunk port groups use only vmnic0. Management uses vmnic0 and vmnic1. |
| | Note | The upstream ports Te1/0/11 and Te1/0/12 must allow MTU 9000 once the vSwitch is raised. Not yet verified. |

## Reinstall spec for `esxi1` (decided with the lab owner)

- ESXi 9.x with the CPU override (`allowLegacyCPU=true`; Skylake-SP is in Deprecated Mode)
- Keep the existing VMFS datastore (`--preservevmfs`). No wipe unless it is explicitly confirmed.
- Static management IP (same address as today, recorded in the host record and `.env`), VLAN 100.
  Installed on vmnic0; vmnic1 is added as a second active uplink on first boot.
- NTP: `pool.ntp.org`
- After install: vSwitch MTU 9000, the trunk port groups (VLAN 4095, security set to Accept), NTP enabled
- Post-install validation: jumbo-frame loop test vmnic0 ↔ vmnic1 across Te1/0/11 ↔ Te1/0/12.

A reinstall resets all of this. Post-install configuration must recreate requirements 1, 2, 3, 6 and 7.
GroundZero does it with pipeline tasks: **Assess Holodeck readiness** (`host.assess`, read-only),
**Prepare host** (`host.prep`) and **Verify jumbo frames** (`net.verify_jumbo`, which replaces the former
`tools/esxi_mtu_loop_test.py`; the old tool reset the MTU to 1500 when it finished).

## Status after the 9.1.1 reinstall and GroundZero host prep (2026-10-02)

| # | Status | Detail |
|---|---|---|
| 1 | OK | vSwitch0 MTU 9000 (was 1500) |
| 2/3 | OK | `Holodeck-Trunk`, VLAN 4095, Promiscuous / MAC changes / Forged transmits = Accept |
| 6 | OK | `Holodeck-External` on VLAN 100 (the management VLAN) for the Holorouter |
| 7 | OK | NTP `pool.ntp.org`, running, startup policy on (the kickstart left the policy off) |
| | OK | Jumbo frames verified: 9000-byte frames pass vmnic0 ↔ vmnic1 through the switch on VLAN 100; 9001 refused |
| | OK | Holodeck datastore: existing `localHolodeck` (4 TB NVMe, 3.9 TB free) |
