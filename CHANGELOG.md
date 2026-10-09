# Changelog

All notable changes to GroundZero. The project follows [Semantic Versioning](https://semver.org/):
until 1.0, a minor version (0.x) may change the API, and the release notes say how.

## [Unreleased]

### Added
- **A guide for gz-hwreport (Node.js).** `node/README.md` covers what you need, how to run it, every option,
  the output files, exit codes, and what to check when a BMC won't answer.
  - It ships with the file on each release, in `gz-hwreport-node.zip` and as `gz-hwreport-README.md`.
  - A test makes sure every option the tool accepts is in the guide.

### Fixed
- The Node.js gz-hwreport accepts a BMC on another port (`192.0.2.5:8443`) and IPv6 in brackets, as the
  Python version does.

## [0.11.1] - 2026-10-08

The hardware report as one Node.js file.

### Added
- **gz-hwreport for Node.js:** the hardware report as one dependency-free file (`gz-hwreport.mjs`, Node 20+),
  attached to each release. It's a port of the Python collector, and CI replays the same recorded server
  through both and fails if their reports differ in any field.

## [0.11.0] - 2026-10-07

Configure storage from profiles, a full hardware inventory, reports, and gz-hwreport: a hardware report with nothing to set up.

### Added
- **gz-hwreport:** a standalone hardware report, with nothing to set up. It reads one or more BMCs
  over Redfish (read-only) and writes a self-contained HTML page and a JSON file per server.
  - With several servers it adds a comparison page with differences highlighted.
  - Each release has a single-file executable for Linux (x86_64, arm64), macOS (arm64) and Windows. No
    Python needed.
  - `groundzero hwreport` is the same tool inside GroundZero. See "Just want a hardware report?" in the
    install guide.
- **Full hardware inventory:** Discover hardware now also reads the following, and the Overview tab shows
  all of it:
  - every installed firmware version (BIOS, BMC, controllers, NICs, drives, power supplies, backplanes)
  - each memory module
  - the network adapters with their firmware
  - PCIe devices: storage controllers and HBAs, NICs, accelerators
  - power supplies
  - each drive's firmware, and the service tag
- **Reports:** a server's hardware and configuration on one printable page, and a cluster report that
  puts the members side by side and flags what differs (BIOS, BMC and every firmware version, model,
  memory, drives, adapters, power supplies, OS).
  - Download a report as CSV (one row per component, or one row per compared item for a cluster) or JSON.
  - Built from what GroundZero already recorded: nothing is read from the servers.
- **Configure storage:** apply a storage profile covering RAID volumes, controller mode (RAID, HBA,
  enhanced HBA), drive state (RAID-capable or passed straight through) and global hot spares.
  - Profiles are rules, not drive ids, so one fits every server of a kind: "on the boot card, one RAID1
    of two SSDs, the boot volume"; "on the PERC, a RAID5 of three SAS SSDs and one hot spare".
  - Save a server's layout as a profile from its Storage tab, or write one on the Config sets page.
  - **The plan comes first.** It lists every change in the order it's applied, marks the ones that lose
    data, and says plainly why a profile can't be applied (not enough drives, a mode that can't hold
    volumes, no matching controller).
  - **The boot volume the OS runs from is never deleted** unless you tick the box that allows it.
  - The layout is read again before anything is written, and the run stops if it changed since Read
    storage.
  - Changes that wait for a reset share one restart. The layout is read back until the profile is met,
    and the boot volume recorded afterwards is the one the OS install uses.
  - Specs can pick a profile for their Configure storage step. Once applied, the step goes back to ready
    if the layout drifts from the profile.
  - On the command line: `groundzero storage-profile list|show|save|capture|plan|delete`.
  - Tested against the simulator only (it now models PERC volumes, drive conversion, spares and mode
    changes). On the lab R740xd the BOSS holds the running ESXi and the PERC has no drives.

## [0.10.0] - 2026-10-07

BIOS profiles: capture, edit or import saved BIOS settings, and apply them with Configure BIOS.

### Added
- **BIOS profiles:** saved BIOS settings, checked against what the server's BIOS accepts. Configure BIOS
  applies them: only the settings that differ are written, with one reboot, and read back afterwards.
  - Three ways to make one:
    - **Capture** from a server's current settings. By default it keeps the choices (lists, numbers,
      on/off) and leaves out per-server text such as asset tags and iSCSI names.
    - **Edit** in GroundZero, from the BIOS's own attribute registry: each setting's name, allowed
      values, bounds and the menu it sits in.
    - **Import** a file: a plain `{attribute: value}` map, or a Dell Server Configuration Profile export.
  - The registry is read from the BMC once (read-only) and cached per model and BIOS version.
  - Values are checked before anything is saved. Read-only settings and BIOS passwords never go in a
    profile.
  - A profile's own value wins over the Holodeck basics (virtualization, IOMMU, UEFI) for any attribute
    both touch.
  - The Configure BIOS dialog shows what a profile would change before you confirm. Specs can pick a
    profile for their Configure BIOS step, which is "not needed" once the server matches it.
  - On the command line: `groundzero bios-profile list|show|capture|import|delete`.

### Changed
- A task that judges itself from its inputs (Configure BIOS) goes back to ready when they move on, for
  example after a BIOS reset or a profile change, instead of staying done.

### Fixed
- Recorded test fixtures no longer redact BIOS settings whose names sound sensitive (`SerialComm`,
  `SubNumaCluster`): values the BIOS registry lists as choices are kept.
- Job diagnostics now redact BIOS password attributes such as `SetupPassword`.
- A BMC that doesn't answer a direct request (for example reading its BIOS registry) is a 502 `bmc_error`
  naming what failed, not a bare 500.

## [0.9.0] - 2026-10-07

Specs: pick the jobs each server or cluster runs, and run them as one.

### Added
- **Specs:** pick the jobs a server or a cluster runs, each with its saved settings (`/specs`).
  - Steps are kept in pipeline order and checked when you save: the task exists, its settings are valid,
    and the images, config sets and profiles they point at exist. Secrets aren't allowed: they stay in
    profiles and config sets.
  - Text settings may use `{host}` or `{hostname}`, filled in per server. A Deploy OS step with no config
    set uses the cluster's.
  - A cluster's spec applies to every member, and a server's own spec overrides it.
  - With a spec, the pipeline's next step follows only the spec's jobs. The rest stay runnable by hand.
- **Runs:** run a server's spec as one, approved once with a typed phrase (`run <spec> on <server>`)
  after a preview.
  - The preview shows which steps run, which are skipped (done already, or not needed) and what the
    destructive ones change.
  - Steps start one after another and the run stops at the first failure. Each step still goes through
    its own checks, and the run's approval stands in for each step's own phrase.
  - **Cluster runs** (`run cluster <name>`) start every member at once; one failing doesn't stop the others.
  - In the web UI: a Specs page with an editor that shows what each picked job needs and which earlier
    job makes it, a spec bar and run panel on the host page, and runs on the cluster page.
  - On the command line: `groundzero spec save|list|show|assign|delete` and `groundzero run-spec`.

## [0.8.0] - 2026-10-06

Read the server's storage, and install to the boot volume it finds.

### Added
- **Read storage:** a new hardware task that reads the controllers, RAID volumes and drives over Redfish
  (read-only) and finds the boot volume the OS installs to. On a Dell with a BOSS card that's the BOSS
  RAID1, and the installer finds it as `DELLBOSS`.
  - A new **Storage** tab on the host page shows what it read: the boot volume, then each controller with
    its volumes and drives.
- **Install to the boot volume:** a config set's install disk can be `boot-volume`, which installs to the
  boot volume Read storage found. It works without a running OS, so a blank server installs to the right
  disk. The OS deploy tasks now list the storage layout as an input.

## [0.7.0] - 2026-10-06

Configure BIOS moves up behind Discover, and steps aside when the BIOS is already right.

### Changed
- **Configure BIOS** now comes straight after Discover hardware, before Preflight, so Preflight passes the
  first time.
  - When the inventory shows the BIOS already right, the task is marked **not needed** (with what was
    checked) and nothing is run or recorded. A later inventory showing a setting off makes it ready again.
  - When a setting is off, Configure BIOS becomes the recommended next step.
- **API:** a new task state `not_needed` with a `not_needed` reason, and a `conditional` flag on tasks that
  are recommended only when needed.

## [0.6.0] - 2026-10-06

Cluster mode: servers named after their BMC, addresses from a pool, and an optional DNS check.

### Added
- **Clusters:** an ESXi config set, an IP range, a DNS domain and a naming rule (`/clusters`).
  - Adding a server names it after its BMC (prefix or suffix stripped, e.g. `idrac-esx01` becomes `esx01`)
    and gives it the next free address in the range. Both are written as its per-host values.
  - Inventory now reads the BMC's own hostname.
- **Verify DNS:** asks the cluster's own DNS servers (never the local resolver) for the forward and reverse
  records and names what does not match.
  - It is an option. A cluster with "Require a passing DNS check before install" set blocks its members'
    OS install until it passes; `skip_dns_check` overrides that.
- **UI:** a Clusters page with members, derived names and addresses, DNS status and Verify DNS.
- **Simulator:** a configurable BMC hostname and a static DNS map.

## [0.5.0] - 2026-10-06

Configure BIOS: the settings Holodeck needs, set over Redfish with one reboot.

### Added
- **Configure BIOS:** turns on processor virtualization (VT-x/AMD-V), the IOMMU (VT-d/AMD-Vi) and UEFI
  boot mode where the inventory shows them off.
  - Only what is wrong is changed, keeping the BIOS's own value style.
  - It writes pending settings to `Bios/Settings` with apply-on-reset, restarts once, verifies by reading
    the BIOS back, and re-reads the inventory.
  - It needs the typed phrase `configure bios <host>` whenever something will change.
  - Preflight's BIOS checks now point at it.
- **Simulator:** pending BIOS settings applied on reset, and the faults `bios-wrong` and `bios-not-applied`.

## [0.4.0] - 2026-10-06

Appliances you already have: capture their settings, adopt them, and correct their records.

### Added
- **Reading VMs:** a host's VMs and their layout (NICs and port groups, datastore, size, guest IPs) and the
  OVF settings each was deployed with, read from its `.vmx`, since the vSphere API returns them empty
  (`GET /hosts/{id}/vms`).
- **Capture appliance profile:** save a running appliance's settings and network mapping as a profile,
  matched to its OVA by the property names it uses. Passwords are never copied.
- **Adopt existing VM:** record a VM that is already on the host, as an appliance or as the Holorouter,
  so later steps use it.
- **Outputs record their source** (job, adopted, manual). `PUT /hosts/{id}/outputs/{kind}` corrects a
  record by hand, checked against its schema (`GET /output-kinds`).
- **UI:** an Appliances list on the pipeline with Replace, Capture profile and Edit record, plus Adopt and
  Capture dialogs that list the host's VMs.

## [0.3.0] - 2026-10-06

The modular pipeline, and deploying any appliance (OVA).

### Added
- **Modules:** every pipeline task is a module that declares its inputs, outputs and parameters. Outputs
  are typed, and one task's outputs are the next task's inputs.
- **Data flow in the UI:** each task shows what it uses (and from where, how old) and what it feeds;
  click an input to see exactly what the task reads.
- **Task options:** forms generated from each task's parameter schema. The CLI has
  `run --param KEY=VALUE --confirm …`.
- **Background server:** `groundzero serve --detach` and `groundzero stop`.
- **Any OVA's inputs:** read from its OVF descriptor and shown as a form (`GET /images/{id}/descriptor`,
  `groundzero images show`). Every declared property reaches the guest, with its default when unset.
- **Appliance profiles:** saved values for an OVA (properties, network mapping, encrypted passwords),
  checked against the OVA's descriptor (`/appliance-profiles`, and an editor generated from the OVA).
- **Deploy appliance:** a new Appliances stage deploys any OVA with a profile, per-deployment value
  overrides, network mapping to the host's port groups, a datastore, and an optional wait for a TCP
  port. Each deployment is saved as an `appliance:<vm>` output.
- **Replace:** deletes an existing VM of the same name and deploys it fresh, confirmed with
  `replace <vm>`. Appliances apply their OVF settings on first boot only, so this is the way to change
  one. It replaces `reapply`, which did not work for that reason.

### Changed (API)
- Work starts one way, `POST /hosts/{id}/tasks/{task}` (pipeline-gated). Results are read one way,
  `GET /hosts/{id}/outputs[/{kind}]`.
- **Removed:**
  - The duplicate job routes (`POST /hosts/{id}/inventory|preflight|os/network|os/capture|install`).
  - The per-result getters.
  - `GET /profiles`: the preflight variants are now choices in the task's parameter schema.
- `/isos` is now `/images` (ISOs and OVAs); the CLI's `isos list` is now `images list`.
- Jobs carry their task id (`task`); `kind` is gone.
- VCF 9 readiness is optional.
- The Holorouter's settings (gateway, DNS, NTP, password, Webtop, GitOps) moved from the Holodeck config
  set to a HoloRouter appliance profile, and Deploy Holorouter takes `profile_id`. Existing config sets
  are migrated on startup into a `<set>-holorouter` profile, password included.
- The simulated ESXi host rejects OVF properties that the OVA does not declare, as the guest would ignore
  them.

## [0.2.0] - 2026-10-06

The first public release.

### Added
- **Installation guide** (`docs/INSTALL.md`): prerequisites, network requirements, native or container
  install, every step from preflight to the Holorouter, and troubleshooting.
- **Splash page** at https://djsincla.github.io/GroundZero/, with screenshots from simulation mode.
- **Version everywhere:** `groundzero --version`, the web UI sidebar, `/healthz`, and git tags with
  GitHub Releases.

### Changed
- **Pipeline:**
  - Failed tasks show their error inline.
  - Results show their age, and a running task shows when it started.
  - The Next step card hides while a job runs.
- **Host page:** the header offers the next step; Deploy OS moved to the Install tab. Preflight is now
  part of the Readiness tab.
- **Jobs page:** compact rows, host and status filters (kept in the URL), and a Details drawer.
- **Navigation:** pages scroll to the top on navigation, and lists show task titles instead of internal
  job kinds.
- **Credits and licensing:** the VCF Readiness rules are credited to John Nicholson's VCF Readiness
  Assessment Tool (CA, Inc. license). The README's license section matches NOTICE.

### Fixed
- The deploy wizard's step panels were squeezed into a narrow column. A job-progress CSS rule also
  matched them.
- Badge colours leaked onto pipeline stages and tasks: a running stage was painted yellow.
- The Holorouter ignored bare OVF property keys and booted without an IP. Keys are now qualified by their
  `ProductSection` class (`network.ip`).
- A recorded fixture's ESXi version had been redacted as if it were an IP address.

### Security
- Lab IP addresses and VLAN ids were removed from the entire history before publishing. Documentation
  addresses are used throughout.

## [0.1.0] - 2026-10-05

The first working pipeline from bare metal to the Holorouter, run end to end on a Dell PowerEdge
R740xd.

### Added
- **API-first core:** FastAPI with a versioned REST API, RFC 9457 errors, jobs with live progress,
  steps and diagnostics bundles, and a Typer CLI as a thin API client.
- **Preflight:**
  - Redfish inventory and the Holodeck 9 checks, read-only: CPU, memory, disks, NICs, boot mode, BIOS
    VT-x/VT-d and the BMC.
  - The VCF 9 readiness rules from the VCF Readiness tool.
- **Unattended ESXi 9.x install:**
  - A custom ISO built from the stock installer, served over HTTPS as virtual media, booted once.
  - Post-install validation.
  - CPU override, VMFS preservation, and Dell iDRAC9 Remote File Share handling.
- **Config sets and deploy:**
  - Config sets captured from a running ESXi or built in the UI, with per-server values.
  - An ISO repository, and a deploy preview of the exact kickstart.
- **Security:** BMC and ESXi TLS certificate pinning (trust on first use); credentials encrypted at rest.
- **Holodeck pipeline:**
  - Readiness assessment, host preparation (MTU, port groups, NTP, datastore) and jumbo-frame
    verification through the physical switch.
  - Holorouter OVA deployment.
- **Web UI:** a plain HTML/JS app with dark mode, the pipeline, readiness, the deploy wizard, config sets
  and jobs.
- **Testing and packaging:**
  - A stateful simulator of the R740xd BMC and ESXi with fault injection.
  - Functional, browser and live test suites.
  - A single-container bundle.

[Unreleased]: https://github.com/djsincla/GroundZero/compare/v0.11.1...HEAD
[0.11.1]: https://github.com/djsincla/GroundZero/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/djsincla/GroundZero/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/djsincla/GroundZero/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/djsincla/GroundZero/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/djsincla/GroundZero/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/djsincla/GroundZero/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/djsincla/GroundZero/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/djsincla/GroundZero/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/djsincla/GroundZero/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/djsincla/GroundZero/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/djsincla/GroundZero/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/djsincla/GroundZero/releases/tag/v0.1.0
