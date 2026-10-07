# Changelog

All notable changes to GroundZero. The project follows [Semantic Versioning](https://semver.org/):
until 1.0, a minor version (0.x) may change the API, and the release notes say how.

## [Unreleased]

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

[Unreleased]: https://github.com/djsincla/GroundZero/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/djsincla/GroundZero/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/djsincla/GroundZero/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/djsincla/GroundZero/releases/tag/v0.1.0
