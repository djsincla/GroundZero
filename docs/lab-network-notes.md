# Lab network notes: serving installer media over GlobalProtect

Findings from 2026-10-01, from the GroundZero ESXi install runs against `esxi1` (Dell R740xd, iDRAC9 7.00.00.182).

## Setup

- GroundZero runs on a Mac and reaches the lab over **GlobalProtect**. The GP client address is
  `<vpn-client-ip>` and the gateway is your GlobalProtect portal.
- The iDRAC (`198.51.100.11`) mounts the installer ISO from GroundZero's media server at
  `https://<vpn-client-ip>:443/media/...`, using Redfish VirtualMedia (a Remote File Share, RFS).
- A firewall rule allows **TCP 443 from the iDRAC (198.51.100.11) to the GP client (<vpn-client-ip>)**.
  Other ports, such as 80 and 8099, time out.

## Findings

**Symptom:** the iDRAC could not stream the installer ISO from the media server on the Mac.

| Test | Result |
|---|---|
| Mac → lab upload over **IPsec** (ESP in UDP 4501) | **~5–17 KB/s**: a short burst, then capped, with zero TCP retransmissions |
| Lab → Mac download over IPsec | ~300 KB/s and climbing |
| Mac → internet, outside the tunnel (`en0`) | ~1.95 MB/s |
| Mac → GP gateway, plain TCP outside the tunnel | fast (600 KB/s+) |
| Path MTU to the lab | 1400, fine (no MTU black hole) |
| Latency to the lab | ~56 ms round trip, TLS handshake ~0.17 s |
| Palo Alto QoS | default profile only, no bandwidth limits |
| **Mac → lab upload over the SSL tunnel** (TCP 443) | **~720–810 KB/s sustained**, 50–150× faster than IPsec |

**Conclusion:** only uploads inside the **IPsec (UDP 4501)** tunnel are policed, and the Palo Alto is
not doing it. The most likely cause is the **local router or ISP shaping outbound UDP**. Forcing
GlobalProtect into **SSL mode** is a working fix.

**Still slow in SSL mode:** the iDRAC reads the ISO in 128 KB requests at ~1.6 s each, about 80 KB/s
effective, because of per-request overhead. The ESXi 9.1.1 loader needs ~696 MiB of boot modules,
which takes roughly 2–2.5 hours. A single failed read ends the boot with
`Fatal error: 15 (Not found)` (live run 7, after 152 MiB). An ISO source inside the lab would load
in minutes.

## Force GlobalProtect into SSL mode (macOS)

This blocks outbound UDP 4501 in a separate pf anchor under `com.apple/*`, so macOS's own rules
are not replaced. Run each line separately: interactive zsh does not accept inline `#` comments.

**Block** (GlobalProtect falls back to SSL):

```bash
echo "block drop out quick proto udp from any to any port 4501" | sudo pfctl -a com.apple/250.groundzero -f -
sudo pfctl -E
sudo pfctl -a com.apple/250.groundzero -s rules
```

`pfctl -E` prints `Token : NNNN`; keep the number. The warning about "flushing of rules" from `-f`
is expected and does not apply here, because only our anchor is loaded. Then **disconnect and
reconnect GlobalProtect**, and confirm *Settings → Details* shows **SSL**. The GP event log
(`/Library/Logs/PaloAltoNetworks/GlobalProtect/pan_gp_event.log`) records
`SSL tunnel creation finished`.

**Unblock** (back to IPsec):

```bash
sudo pfctl -a com.apple/250.groundzero -F rules
sudo pfctl -X NNNN
```

Then reconnect GlobalProtect. If the token is lost, `sudo pfctl -s References` lists it.

## Quick throughput probe

This measures Mac → lab upload. It sends a 1 MB junk body that the iDRAC rejects with 401, so
nothing changes:

```bash
head -c 1048576 /dev/urandom > /tmp/1mb.bin
curl -sk -o /dev/null -X POST --data-binary @/tmp/1mb.bin \
  -w "%{time_total}s = %{speed_upload} B/s (HTTP %{http_code})\n" \
  https://198.51.100.11/redfish/v1/GroundZeroUploadProbe
```

Reference values: ~5–17 KB/s over IPsec, ~720–810 KB/s over SSL.

## Follow-ups

- Find the UDP shaping on the local router or ISP (look for a UDP, gaming or SQM QoS setting), or
  keep using SSL mode for installs.
- Better long-term: an installer media source inside the lab network, on the same LAN as the iDRAC.
- See also: `docs/holodeck-host-network.md` (ESXi host networking and the reinstall spec).
