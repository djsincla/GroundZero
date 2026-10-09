# gz-hwreport for Node.js

A hardware report straight from a server's BMC, as one JavaScript file with no dependencies. I wanted
something I could drop onto a jump host that already has Node, point at a rack of servers and get back a
page I could print, without installing GroundZero or anything else first. This is that.

It reads each BMC over Redfish and writes an HTML page and a JSON file per server. The page covers:

- firmware versions for every component
- CPUs, memory modules, drives and RAID volumes
- network adapters and ports, and PCIe devices (storage controllers, HBAs, NICs)
- power supplies, the BIOS and the BMC

Give it more than one server and it adds a page comparing them, with anything that differs highlighted.

It only reads. Every request is a GET, apart from logging in to the BMC and logging out again, so it's safe
to run against servers in production.

## What you need

- **Node.js 20 or newer.** Check with `node --version`.
- **HTTPS (TCP 443) from your machine to each BMC.**
- **A BMC account.** Read-only is enough. On a Dell, an iDRAC user with the Read Only role works.

## Get it

Download `gz-hwreport.mjs` from the [latest release](https://github.com/djsincla/GroundZero/releases/latest):

```sh
curl -LO https://github.com/djsincla/GroundZero/releases/latest/download/gz-hwreport.mjs
```

That one file is the whole tool. There's no `npm install`, so you can copy it anywhere Node is.

## Run it

One server:

```sh
GZ_BMC_PASSWORD='your-bmc-password' node gz-hwreport.mjs 192.0.2.50
```

It prints where it wrote the report, a folder named `hwreport-<date>-<time>` in the current directory.
Open the `.html` file in a browser.

Several servers, compared:

```sh
node gz-hwreport.mjs 192.0.2.50 192.0.2.51 192.0.2.52
```

Each server gets its own page, and `index.html` compares them. Up to four BMCs are read at once (change that
with `--parallel`), and one that can't be read doesn't stop the others.

From a file, one BMC per line, with an optional username after the address and `#` for comments:

```text
# rack 1
192.0.2.50
192.0.2.51
192.0.2.52 admin    # this one has its own account
```

```sh
node gz-hwreport.mjs -f bmcs.txt -o rack1
```

On Windows, set the password in PowerShell first:

```powershell
$env:GZ_BMC_PASSWORD = 'your-bmc-password'
node gz-hwreport.mjs 192.0.2.50
```

## Options

| Option | What it does |
|---|---|
| `bmc ...` | BMC addresses: a name or IP, with `:port` if it isn't 443. Put IPv6 in brackets (`[2001:db8::5]`). |
| `-f`, `--file FILE` | Read BMCs from a file, as above. Can be combined with addresses on the command line. |
| `-u`, `--user USER` | The BMC username for addresses without their own. The default is `root`, or `GZ_BMC_USERNAME` if that's set. |
| `-o`, `--out DIR` | Where to write the report. The default is `./hwreport-<date>-<time>`. |
| `--verify-tls` | Check the BMC's TLS certificate. Off by default, see below. |
| `--parallel N` | How many BMCs to read at once. The default is 4. |
| `--version`, `-h` | Show the version, or the help. |

**Password.** It comes from `GZ_BMC_PASSWORD`. If that isn't set, it's asked for once, without echoing,
and used for every BMC. The tool never writes it anywhere.

**Certificates.** BMCs almost always ship self-signed certificates, so by default they aren't checked. If
yours are signed by a CA your machine trusts, add `--verify-tls`.

## What it writes

For each server, named after the BMC's hostname (`idrac-ABC1234`) or its address if it has none:

- **`<name>.html`.** The report. It's self-contained, with no scripts and nothing loaded from the internet,
  so you can email it or print it to PDF.
- **`<name>.json`.** Everything it read, for other tools: `{"bmc", "inventory", "storage"}`.

With more than one server there's also an **`index.html`**. It lists every server, then what differs between
them, then what's the same. Firmware is compared by component name, so a mixed fleet shows a lot of
differences, which is accurate if not very useful.

Be aware that the files contain serial numbers, service tags and MAC addresses. Treat the folder like any
other inventory export, and keep it out of public repositories.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every server was read. |
| 2 | At least one couldn't be read (the others are still written, and each failure is listed on screen and in `index.html`), or the command line was wrong. |
| 1 | Something unexpected broke: please raise an issue with the message. |

## When something goes wrong

| What you see | What to check |
|---|---|
| `ECONNREFUSED`, or a timeout after a minute | The BMC isn't reachable on 443 from where you're running it. Try `curl -k https://<bmc>/redfish/v1` from the same machine. |
| `BMC login refused (401)` | The username or password is wrong, or the account is locked after too many attempts. Some BMCs lock for a few minutes. |
| `certificate` errors | You added `--verify-tls` and the BMC's certificate isn't trusted by this machine. Drop the flag, or trust the CA. |
| A section is missing from a page | That BMC doesn't publish it over Redfish (older firmware often has no firmware inventory or power supply details). The rest of the report is still complete. |
| Odd values on a non-Dell server | It's been run end to end on Dell iDRAC9. Other Redfish BMCs go through the generic path, so expect to find something, and an issue with the JSON file attached is the quickest way to get it fixed. |

## How it relates to GroundZero

It's a port of the Python collector GroundZero uses, so the report is the same as `groundzero hwreport`,
the single-file executables on the release page, and the **Report** button on a host in GroundZero. The
build replays a recorded server through both the Python and the Node.js versions and fails if they
disagree on a single field.
