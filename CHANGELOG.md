# Changelog

All notable changes to GroundZero. The project follows [Semantic Versioning](https://semver.org/):
until 1.0, a minor version (0.x) may change the API, and the release notes say how.

## [Unreleased]

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

[Unreleased]: https://github.com/djsincla/GroundZero/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/djsincla/GroundZero/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/djsincla/GroundZero/releases/tag/v0.1.0
