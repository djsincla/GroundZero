# Installing GroundZero for your lab

This guide takes you from nothing to a server running ESXi and the Holodeck Holorouter, using your own
hardware. Allow about 15 minutes for setup. The ESXi install then takes 20–40 minutes on a local
network, longer over a VPN.

> Addresses in this guide use the documentation ranges (`192.0.2.x` for the ESXi management network,
> `198.51.100.x` for BMCs). Replace them with your own.

## 1. What you need

| | Requirement |
|---|---|
| **Server** | A server with a Redfish BMC and virtual media. Tested: Dell PowerEdge R740xd (iDRAC9, Enterprise or Datacenter license for virtual media). Other Redfish BMCs (HPE iLO, Lenovo XCC, Supermicro) use the generic Redfish path and are not yet tested. |
| **Management machine** | macOS or Linux with Python 3.12+ and [uv](https://docs.astral.sh/uv/), **or** any machine with Podman or Docker for the container. |
| **Network** | The management machine reaches the BMC on HTTPS (443) and the ESXi management address on 443 and 22. **The BMC must reach the management machine on TCP 443**: it fetches the install ISO from GroundZero's media server. |
| **Installers** | A stock ESXi 9.x installer ISO and, for Holodeck, the Holorouter OVA, both downloaded from Broadcom (your entitlement). GroundZero never downloads them for you. |
| **Addresses** | A static management IP, gateway, DNS and VLAN for ESXi, plus one free IP on that network for the Holorouter. |

The install **reinstalls ESXi on the boot disk**. The VMFS datastore on the install disk is kept unless you
explicitly ask to overwrite it, and other disks are not touched.

## 2. Install GroundZero

### Option A: native (uv)

```bash
git clone https://github.com/djsincla/GroundZero.git
cd GroundZero
uv sync
cp .env.example .env        # optional: lab credentials for the CLI and live tests (git-ignored)
```

Start the server and open the web UI:

```bash
uv run groundzero serve     # API + UI on http://127.0.0.1:7182, install-media server on :443
uv run groundzero ui        # opens the UI in your browser, already signed in
```

- **Port 443:** the media server listens on `0.0.0.0:443`. On Linux, binding below 1024 needs privileges.
  Either run with the capability (`sudo setcap 'cap_net_bind_service=+ep' "$(readlink -f .venv/bin/python)"`)
  or move it with `GROUNDZERO_MEDIA_PORT=8443` and allow that port from the BMC.
- **Long jobs:** keep the server running for the whole install or OVA upload. To run it in the
  background, so it survives closing the terminal, use `uv run groundzero serve --detach`. The log goes
  to `~/.groundzero/serve.log`; stop it with `uv run groundzero stop`.

### Option B: one container

The API, web UI, media server and state ship as a single OCI image ([Podman](https://podman.io) is
free; Docker works with `GZ_ENGINE=docker`).

```bash
git clone https://github.com/djsincla/GroundZero.git && cd GroundZero
scripts/gz-container build
scripts/gz-container up --bmc 198.51.100.11   # works out this machine's address on the route to the BMC
scripts/gz-container ui
```

State (database, API token, encryption key, pinned certificates) lives in the `groundzero-data`
volume; ISOs and OVAs are read from `./images`.

## 3. Add your installers

Copy the stock files into `./images` (or point `GROUNDZERO_ISO_REPOSITORY` at another folder), then
rescan from the **Images** page or with:

```bash
uv run groundzero images list   # `images show <file>` lists an OVA's inputs
```

GroundZero recognizes ESXi installer ISOs and appliance OVAs (Holorouter, VCF Installer) by their
contents. It never modifies them: each install builds a temporary copy with the kickstart and deletes
it afterwards.

## 4. Register and check the server

In the web UI: **Hosts → Add host** (BMC address, username, password). Or with the CLI:

```bash
uv run groundzero hosts add --bmc 198.51.100.11 --name esxi1     # the password is prompted
uv run groundzero preflight esxi1                                 # read-only hardware check
```

- **Credentials:** encrypted at rest and never shown again.
- **Certificates:** the BMC's TLS certificate is pinned on first contact.
- **Preflight:** checks CPU support, memory, disks, NICs, boot mode and the BMC against the Holodeck 9
  requirements. It makes no changes.

If preflight finds processor virtualization, the IOMMU or UEFI boot mode turned off, run **Configure BIOS**
from the Pipeline. It writes the settings to the BIOS as pending changes, restarts the server once and waits
until the BIOS reports them, which on an R740xd takes several minutes because the BIOS configuration job runs
during POST. Be aware that the server really does reboot: anything running on it goes down with it.

## 5. Describe the ESXi you want

A **config set** holds the shared settings: VLAN, uplinks, gateway, DNS, NTP, install-disk rule, CPU
override and root password. The server's own **hostname and IP** stay per host. Two ways to make one:

- **From a running ESXi** (handy for reinstalling a host as it is):
  ```bash
  uv run groundzero os set esxi1 --address 192.0.2.101            # how to reach the current ESXi
  uv run groundzero config capture esxi1 --name lab-esxi
  ```
- **From scratch:** in the web UI, open **Config sets → New config set**.

### Several servers: a cluster

If you are building more than one host, create a cluster (**Clusters → New cluster**) with the ESXi config
set, an IP range and the DNS domain, and add the servers to it. Each one is named after its BMC, with the
prefix or suffix you give stripped off, so `idrac-esx01` becomes `esx01`, and gets the next free address in
the range. Those become the server's own values, so the install picks them up without any typing.

**Verify DNS** asks the cluster's DNS servers for the forward and reverse records and tells you what does not
match. It is an option: tick *Require a passing DNS check before install* on the cluster if you would rather
not find out about a missing PTR record after vCenter has.

## 6. Install ESXi

The web UI's **Install → Deploy OS…** wizard runs four steps:
1. Pick the ISO and the config set.
2. Check this server's values.
3. **Preview the kickstart** (passwords hidden).
4. Type `install <host name>` to confirm.

Or with the CLI:

```bash
uv run groundzero install esxi1 --iso VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso \
    --config lab-esxi --hostname esxi1 --ip 192.0.2.101
```

GroundZero then:
1. Builds a custom ISO.
2. Serves it to the BMC as virtual media.
3. Boots the server once from it and waits for the unattended install.
4. Validates the result: build, IP, VLAN, uplinks, NTP and datastores.

Older CPUs that ESXi 9 no longer lists, such as Skylake-SP, are installed with `allowLegacyCPU=true`
when preflight flags them.

## 7. Prepare the host for Holodeck

Open the host's **Pipeline** tab and follow **Next step**:

1. **Assess Holodeck readiness:** reads the installed ESXi and plans what Holodeck still needs.
2. **Prepare host:** applies the fixes you select (MTU 9000, trunk and external port groups, NTP,
   Holodeck datastore). Erasing a disk always needs a typed phrase.
3. **Verify jumbo frames:** sends 9000-byte frames out of one uplink and back in the other through
   your physical switch, then restores the configuration.

## 8. Deploy the Holorouter

1. Create a HoloRouter appliance profile: **Config sets → New appliance profile**, choose the Holorouter
   OVA, and fill in the gateway, DNS, NTP and password. The form comes from the OVA itself, so it shows
   exactly the properties the Holorouter reads.
2. On the Pipeline, run **Deploy Holorouter**, pick the profile and enter this host's Holorouter IP.

GroundZero then uploads the OVA to the host's datastore, writes the appliance's properties, powers it on
and waits for SSH.

Be aware that the Holorouter applies its settings on first boot only, and quietly ignores any change after
that. To change a deployed Holorouter, tick **Replace** and type the confirmation: it is deleted and
deployed fresh, so anything you set up inside it by hand goes with it.

The same applies to any other OVA through **Deploy appliance** in the Appliances stage: pick the OVA and
a profile, map its networks to port groups, and override values for that one deployment.

## Appliances you already have

If you deployed something by hand before GroundZero came along, run **Adopt existing VM** in the Appliances
stage. It reads the VM (read-only) and records it, so later steps use it as if GroundZero had deployed it;
pick *the Holorouter* as the role and the Holodeck steps will use yours.

**Capture appliance profile** goes the other way: it reads a running appliance's OVF settings out of its
`.vmx` and saves them as a profile for the next deployment. Passwords are not copied out of a VM, so set
them on the profile before you deploy from it.

## Just want a hardware report?

You don't need any of the above. Grab `gz-hwreport` for your platform from the
[latest release](https://github.com/djsincla/GroundZero/releases/latest) and point it at a BMC:

```sh
chmod +x gz-hwreport-macos-arm64
GZ_BMC_PASSWORD='...' ./gz-hwreport-macos-arm64 192.0.2.50
```

It reads the server over Redfish (read-only) and writes a folder with one HTML page and one JSON file per
server: firmware versions, CPUs, memory modules, drives and RAID volumes, network adapters, PCIe devices,
power supplies, BIOS and BMC. The page opens anywhere and prints to PDF.

Give it several BMCs, or a file with one per line (`address` or `address username`), and it adds an
`index.html` comparing them, with anything that differs highlighted. Handy for spotting the one host in a
cluster that's a BIOS release behind.

Already have Node.js 20 or newer? Grab `gz-hwreport.mjs` from the same release instead: one file, no
dependencies, the same report. Run it with `node gz-hwreport.mjs 192.0.2.50`. Its
[guide](https://github.com/djsincla/GroundZero/blob/main/node/README.md) covers the options, the output and
what to check when a BMC won't answer, and it ships next to the file in `gz-hwreport-node.zip`.

With GroundZero installed, `groundzero hwreport` is the same tool. Inside GroundZero itself every host
has a **Report** button, and every cluster has one too.

macOS will want you to allow the file the first time (System Settings → Privacy & Security). The file
isn't signed.

## Troubleshooting

| Symptom | What to check |
|---|---|
| The install stalls at "mount" or the BMC never boots the ISO | The BMC can't reach the media server. Allow TCP 443 (or your `GROUNDZERO_MEDIA_PORT`) from the BMC to the management machine, or set `GROUNDZERO_MEDIA_PUBLIC_URL=https://<address the BMC can reach>`. |
| Install media loads extremely slowly over a VPN | Some VPN tunnels throttle uploads (IPsec in particular). See the **Info** page for forcing GlobalProtect into SSL mode, and the upload-speed check. |
| "certificate changed" | A BMC or ESXi was reinstalled or renewed its certificate. After confirming it's legitimate: `uv run groundzero hosts trust esxi1 bmc` (or `os`). |
| A job ends when you close the terminal | `groundzero serve` stopped. Use `groundzero serve --detach` (see section 2). |
| Something failed and you want details | Each job has **Download diagnostics** in the UI (`uv run groundzero jobs diag <job id>`): every BMC and ESXi exchange, with secrets removed. |

## Uninstall

Stop the server and delete `~/.groundzero/` (database, API token, encryption key, pinned certificates).
For the container: `scripts/gz-container down` and remove the `groundzero-data` volume.
