# GroundZero

Take a bare-metal server **from zero to a running VMware Holodeck** through one REST API.

```
BMC (Redfish) ──► preflight ──► ESXi install ──► Holodeck 9 deploy
                   M1 ✅          M2              M3
```

Everything is API-first. The CLI, a future web UI and your automation are all clients of the same
versioned REST API (`/api/v1`, OpenAPI at `/docs`).

## Status

| Milestone | Scope | State |
|---|---|---|
| **M1** | API skeleton, job model, Redfish client, host inventory, Holodeck 9 preflight | done |
| M2 | ESXi install: kickstart ISO served by GroundZero, virtual media, boot-once, reset, wait for ESXi | next |
| M3 | Holodeck 9 deployment on the new ESXi host, tracked as a job | planned |
| M4 | Web UI on the API, more OEM profiles, jump-host transport | planned |

M1 is strictly **read-only** against the BMC: only GETs, plus session login and logout.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run groundzero serve                 # API on http://127.0.0.1:7182, docs at /docs
# in another terminal
uv run groundzero hosts add --bmc 10.0.0.50 --user root --name r740xd   # password is prompted
uv run groundzero preflight r740xd                                      # default: VCF 9.0 ESA single site
uv run groundzero preflight r740xd --variant vvf-9.0-single
uv run groundzero profiles                                              # list profiles/variants
```

To call the API directly, use the bearer token from `uv run groundzero token show`:

```bash
TOKEN=$(uv run groundzero token show)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7182/api/v1/hosts
```

## API (v1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | liveness (no auth) |
| GET | `/api/v1/profiles` | preflight profiles and variants |
| POST/GET | `/api/v1/hosts` | register / list BMC targets |
| GET/DELETE | `/api/v1/hosts/{id}` | host detail / remove |
| POST | `/api/v1/hosts/{id}/inventory` | start inventory job (202 + Job) |
| POST | `/api/v1/hosts/{id}/preflight` | start preflight job (202 + Job), body `{profile, variant}` |
| GET | `/api/v1/hosts/{id}/inventory`, `/preflight` | latest result |
| GET | `/api/v1/jobs`, `/api/v1/jobs/{id}` | job status |
| GET | `/api/v1/jobs/{id}/events` | server-sent events for one job |
| POST | `/api/v1/jobs/{id}/cancel` | cancel a job |

- **Errors:** every error is RFC 9457 `application/problem+json`.
- **Jobs:** each host can run only one job at a time.
- **Local state:** stored in `~/.groundzero/`. That covers the SQLite database, the API token, and the key that encrypts stored BMC credentials. Override the location with `GROUNDZERO_HOME`.

## Layout

```
src/groundzero/
  api/         FastAPI app, auth, problem+json errors, routers
  core/        settings, models, SQLite store, job runner, services
  redfish/     async client, vendor detection, capabilities, OEM profiles, capture/replay
  inventory/   typed HostInventory + collector
  preflight/   CPU support table, requirement profiles (TOML), evaluator
  cli/         Typer CLI (thin API client) + dev tools
tests/         pytest; fixtures replay recorded Redfish responses
legacy/        the original VCF Readiness v9.7.3 code, kept for reference only
```

## Development

```bash
uv run ruff check . && uv run mypy && uv run pytest
```

Record fixtures from a real BMC. This is read-only, and serials, MACs and IPs are redacted:

```bash
uv run groundzero dev capture --bmc 10.0.0.50 --out tests/fixtures/dell-r740xd
```

## Origin & license

Forked from the VCF Readiness Assessment Tool v9.7.3 (see `legacy/`). Licensed under the CA, Inc. Software License
Agreement in `LICENSE.md`, which permits use in connection with CA, Inc. (Broadcom) products.
