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
- **Long jobs:** keep `groundzero serve` running for the whole install or OVA upload. If you start it
  from a shell you'll close, detach it with
  `nohup uv run groundzero serve > ~/.groundzero/serve.log 2>&1 &`.

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
rescan from the **ISOs** page or with:

```bash
uv run groundzero isos list
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

## 5. Describe the ESXi you want

A **config set** holds the shared settings: VLAN, uplinks, gateway, DNS, NTP, install-disk rule, CPU
override and root password. The server's own **hostname and IP** stay per host. Two ways to make one:

- **From a running ESXi** (handy for reinstalling a host as it is):
  ```bash
  uv run groundzero os set esxi1 --address 192.0.2.101            # how to reach the current ESXi
  uv run groundzero config capture esxi1 --name lab-esxi
  ```
- **From scratch:** in the web UI, open **Config sets → New config set**.

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

1. Create a Holodeck config set (**Config sets → New**, family *VMware Holodeck*) with the Holorouter
   gateway, DNS and password.
2. On the Pipeline, run **Deploy Holorouter** and enter the Holorouter's IP.

GroundZero then:
1. Uploads the OVA to the host's datastore.
2. Sets the appliance's network properties.
3. Powers it on and waits for SSH.

The Holorouter applies its settings on **first boot only**. To change them later, redeploy it.

## Troubleshooting

| Symptom | What to check |
|---|---|
| The install stalls at "mount" or the BMC never boots the ISO | The BMC can't reach the media server. Allow TCP 443 (or your `GROUNDZERO_MEDIA_PORT`) from the BMC to the management machine, or set `GROUNDZERO_MEDIA_PUBLIC_URL=https://<address the BMC can reach>`. |
| Install media loads extremely slowly over a VPN | Some VPN tunnels throttle uploads (IPsec in particular). See the **Info** page for forcing GlobalProtect into SSL mode, and the upload-speed check. |
| "certificate changed" | A BMC or ESXi was reinstalled or renewed its certificate. After confirming it's legitimate: `uv run groundzero hosts trust esxi1 bmc` (or `os`). |
| A job ends when you close the terminal | `groundzero serve` stopped. Run it detached (see section 2). |
| Something failed and you want details | Each job has **Download diagnostics** in the UI (`uv run groundzero jobs diag <job id>`): every BMC and ESXi exchange, with secrets removed. |

## Uninstall

Stop the server and delete `~/.groundzero/` (database, API token, encryption key, pinned certificates).
For the container: `scripts/gz-container down` and remove the `groundzero-data` volume.
