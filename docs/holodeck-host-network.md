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
| 7 | **Gap** | No NTP server is configured |
| | Note | The trunk port groups use only vmnic0. Management uses vmnic0 and vmnic1. |
| | Note | The upstream ports Te1/0/11 and Te1/0/12 must allow MTU 9000 once the vSwitch is raised. Not yet verified. |

A reinstall resets all of this. Post-install configuration must recreate requirements 1, 2, 3, 6 and 7.
