// Jobs, Info (operator notes) and the API reference embedded in the shell.
import { api, card, empty, h, isActive, jobCard, mount, pageHeader } from "../core.js";

const JOB_FILTERS = [["", "All statuses"], ["active", "Running"], ["failed", "Failed"], ["succeeded", "Succeeded"],
  ["cancelled", "Cancelled"]];

// Filters live in the URL (#/jobs?host=…&status=…) so a filtered view can be linked and survives refreshes.
export async function viewJobs(app, query = new URLSearchParams()) {
  const [jobs, hosts] = await Promise.all([api("GET", "/jobs?limit=200"), api("GET", "/hosts")]);
  const names = Object.fromEntries(hosts.map((x) => [x.id, x.name]));
  const host = query.get("host") || "";
  const status = query.get("status") || "";
  const go = (key, value) => {
    const q = new URLSearchParams(query);
    if (value) q.set(key, value); else q.delete(key);
    location.hash = `#/jobs${q.toString() ? `?${q}` : ""}`;
  };
  const hostSelect = h("select", { id: "jobs-host", onchange: (e) => go("host", e.target.value) },
    h("option", { value: "" }, "All hosts"), hosts.map((x) => h("option", { value: x.id, selected: x.id === host }, x.name)));
  const statusSelect = h("select", { id: "jobs-status", onchange: (e) => go("status", e.target.value) },
    JOB_FILTERS.map(([v, label]) => h("option", { value: v, selected: v === status }, label)));
  const shown = jobs.filter((j) => (!host || j.host_id === host)
    && (!status || (status === "active" ? isActive(j) : j.status === status)));
  mount(app, pageHeader("Jobs", "Everything GroundZero has run, newest first. Running jobs update live."),
    card({},
      h("div", { class: "row filters" },
        h("label", { for: "jobs-host", class: "visually-hidden" }, "Host"), hostSelect,
        h("label", { for: "jobs-status", class: "visually-hidden" }, "Status"), statusSelect,
        h("span", { class: "spacer" }), h("span", { class: "muted small-text" }, `${shown.length} of ${jobs.length}`)),
      shown.length
        ? shown.map((j) => jobCard(j, { hostName: names[j.host_id], onDone: () => window.dispatchEvent(new Event("gz:refresh")) }))
        : empty(jobs.length ? "No jobs match these filters." : "No jobs yet.")));
}

export function viewApi(app) {
  mount(app, 
    pageHeader("API", "GroundZero REST API",
      h("a", { class: "button", href: "/docs", target: "_blank", rel: "noopener" }, "Open in new tab")),
    h("iframe", { class: "api-frame", src: "/docs?embed=1", "aria-label": "API reference" }));
}

// ── info: operator notes (static; mirrors docs/lab-network-notes.md) ──
const IPSEC_RULE = "GroundZero - block GlobalProtect IPsec (UDP 4501)";
const IPSEC_STEPS = {
  macos: {
    title: "macOS (pf firewall)",
    shell: "Terminal (zsh). Run each line on its own: zsh does not accept inline # comments.",
    block: [
      'echo "block drop out quick proto udp from any to any port 4501" | sudo pfctl -a com.apple/250.groundzero -f -',
      "sudo pfctl -E",
      "sudo pfctl -a com.apple/250.groundzero -s rules",
    ],
    blockNote: "pfctl -E prints \"Token : NNNN\". Keep that number: you need it to unblock. The \"flushing of rules\" " +
      "warning is expected; only GroundZero's own anchor is replaced, never macOS's rules.",
    allow: ["sudo pfctl -a com.apple/250.groundzero -F rules", "sudo pfctl -X NNNN"],
    allowNote: "Replace NNNN with the token from pfctl -E. If it is lost, sudo pfctl -s References lists it.",
    log: "/Library/Logs/PaloAltoNetworks/GlobalProtect/pan_gp_event.log (look for \"SSL tunnel creation finished\")",
  },
  windows: {
    title: "Windows (Defender Firewall)",
    shell: "PowerShell, opened with Run as administrator.",
    block: [
      `New-NetFirewallRule -DisplayName "${IPSEC_RULE}" -Direction Outbound -Protocol UDP -RemotePort 4501 -Action Block`,
      `Get-NetFirewallRule -DisplayName "${IPSEC_RULE}" | Format-Table DisplayName, Enabled, Action`,
    ],
    blockNote: "The rule only applies while Windows Defender Firewall is on for the active network profile.",
    allow: [`Remove-NetFirewallRule -DisplayName "${IPSEC_RULE}"`],
    allowNote: "The rule is persistent: it survives reboots until you remove it.",
    log: "C:\\Program Files\\Palo Alto Networks\\GlobalProtect\\PanGPS.log",
  },
};

function codeBlock(lines) {
  const text = lines.join("\n");
  const copy = h("button", { class: "copy", type: "button", "aria-label": "Copy commands", onclick: async () => {
    try { await navigator.clipboard.writeText(text); copy.textContent = "Copied"; }
    catch { copy.textContent = "Select and copy"; }
    setTimeout(() => { copy.textContent = "Copy"; }, 1500);
  } }, "Copy");
  return h("div", { class: "code" }, copy, h("pre", {}, h("code", {}, text)));
}

export function viewInfo(app) {
  const os = /Win/.test(navigator.platform || navigator.userAgent) ? "windows" : "macos";
  const platformPanel = (key) => {
    const s = IPSEC_STEPS[key];
    return h("section", { class: "panel", "data-platform": key },
      h("h2", {}, s.title, key === os ? h("span", { class: "badge pass", style: "margin-left:8px" }, "this machine") : null),
      h("p", { class: "muted" }, s.shell),
      h("h3", {}, "Block IPsec (force SSL)"), codeBlock(s.block), h("p", { class: "muted" }, s.blockNote),
      h("p", {}, "Then disconnect and reconnect GlobalProtect. Settings → Details should show the protocol as SSL."),
      h("h3", {}, "Allow IPsec again"), codeBlock(s.allow), h("p", { class: "muted" }, s.allowNote),
      h("p", {}, "Reconnect GlobalProtect afterwards. GlobalProtect log: ", h("code", {}, s.log)));
  };
  mount(app, 
    pageHeader("Info", "Operator notes for running GroundZero in the lab."),
    h("section", { class: "panel", id: "ipsec" },
      h("h2", {}, "VPN: block or allow GlobalProtect IPsec"),
      h("p", {}, "GroundZero serves the installer ISO from this machine to the server's BMC. Over the GlobalProtect ",
        h("strong", {}, "IPsec"), " tunnel (ESP in UDP 4501), uploads from this machine were throttled to about 5–17 KB/s, " +
        "which is too slow for the BMC to boot the installer. Forcing GlobalProtect into ", h("strong", {}, "SSL"),
        " mode (TCP 443) measured 720–810 KB/s."),
      h("p", {}, "To force SSL, block outbound UDP 4501 before an install and reconnect the VPN. Allow it again when you " +
        "are not installing. Blocking needs administrator rights and only affects this machine."),
      h("p", { class: "muted" }, "Full findings: docs/lab-network-notes.md in the repository.")),
    ...[os, os === "macos" ? "windows" : "macos"].map(platformPanel),
    h("section", { class: "panel" },
      h("h2", {}, "Check upload speed to the lab"),
      h("p", { class: "muted" }, "Sends 1 MB of junk to the iDRAC, which rejects it with HTTP 401, so nothing changes. " +
        "Replace 198.51.100.11 with your BMC. Expect about 5–17 KB/s over IPsec and about 720–810 KB/s over SSL."),
      h("h3", {}, "macOS"),
      codeBlock([
        "head -c 1048576 /dev/urandom > /tmp/1mb.bin",
        'curl -sk -o /dev/null -X POST --data-binary @/tmp/1mb.bin -w "%{speed_upload} B/s (HTTP %{http_code})\\n" https://198.51.100.11/redfish/v1/GroundZeroUploadProbe',
      ]),
      h("h3", {}, "Windows (PowerShell)"),
      codeBlock([
        '$f = "$env:TEMP\\1mb.bin"; $b = [byte[]]::new(1MB); [Random]::new().NextBytes($b); [IO.File]::WriteAllBytes($f, $b)',
        'curl.exe -sk -o NUL -X POST --data-binary "@$f" -w "%{speed_upload} B/s (HTTP %{http_code})\\n" https://198.51.100.11/redfish/v1/GroundZeroUploadProbe',
      ])));
}

