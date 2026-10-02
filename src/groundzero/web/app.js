// GroundZero web UI: a thin client of the REST API (/api/v1). No build step, no dependencies.
// All server data is rendered with textContent (never innerHTML), so BMC/OS strings cannot inject markup.

const API = "/api/v1";
const app = document.getElementById("app");
const dialog = document.getElementById("dialog");

// ── auth: token arrives once in the URL fragment (never sent to the server), then lives in the session ──
const fromHash = new URLSearchParams(location.hash.slice(1)).get("token");
if (fromHash) {
  sessionStorage.setItem("gz-token", fromHash);
  history.replaceState(null, "", location.pathname + "#/");
}
const token = () => sessionStorage.getItem("gz-token");

class ApiError extends Error {
  constructor(status, problem) {
    super(problem?.detail || problem?.title || `HTTP ${status}`);
    this.status = status;
    this.problem = problem;
  }
}

async function api(method, path, body) {
  const res = await fetch(API + path, {
    method,
    headers: { Authorization: `Bearer ${token()}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { sessionStorage.removeItem("gz-token"); renderLogin(); throw new ApiError(401); }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}
const maybe = (p) => p.catch((e) => { if (e.status === 404) return null; throw e; });

// ── tiny DOM helper ──
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const badge = (status, label) => h("span", { class: `badge ${status}`, "data-status": status }, label ?? status);
const table = (headers, rows) =>
  h("table", {}, h("thead", {}, h("tr", {}, headers.map((x) => h("th", {}, x)))), h("tbody", {}, rows));
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const errorBox = (e) => h("p", { class: "error", role: "alert" }, e.message || String(e));

// ── job progress: reads the per-job server-sent events stream (fetch, so the bearer header is sent) ──
async function followJob(jobId, onEvent) {
  const res = await fetch(`${API}/jobs/${jobId}/events`, { headers: { Authorization: `Bearer ${token()}` } });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let i;
    while ((i = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, i);
      buffer = buffer.slice(i + 2);
      const data = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (data) onEvent(JSON.parse(data.slice(6)));
    }
  }
}

function jobCard(job, { onDone } = {}) {
  const bar = h("div", { style: `width:${Math.round(job.progress * 100)}%` });
  let status = badge(job.status);
  const msg = h("span", { class: "muted", "data-role": "message" }, job.message || "");
  const err = h("div", { class: "error" }, job.error ? job.error.message : "");
  const card = h("div", { class: "job", "data-job": job.id },
    h("div", { class: "row" }, status, h("strong", {}, job.kind), h("span", { class: "mono muted" }, job.id),
      h("span", { class: "spacer" }), h("span", { class: "muted" }, fmtTime(job.created_at))),
    h("div", { class: "progress" }, bar), msg, err);
  if (job.status === "queued" || job.status === "running") {
    followJob(job.id, (ev) => {
      bar.style.width = `${Math.round(ev.progress * 100)}%`;
      status.replaceWith((status = badge(ev.status)));
      msg.textContent = ev.message;
      if (["succeeded", "failed", "cancelled"].includes(ev.status)) {
        api("GET", `/jobs/${job.id}`).then((j) => { err.textContent = j.error ? j.error.message : ""; onDone?.(j); });
      }
    }).catch(() => {});
  }
  return card;
}

// ── views ──
async function viewHosts() {
  const hosts = await api("GET", "/hosts");
  const rows = await Promise.all(hosts.map(async (host) => {
    const [pre, net] = await Promise.all([
      maybe(api("GET", `/hosts/${host.id}/preflight`)),
      maybe(api("GET", `/hosts/${host.id}/os/network`)),
    ]);
    return h("tr", { "data-host": host.name },
      h("td", {}, h("a", { href: `#/hosts/${host.id}` }, host.name)),
      h("td", { class: "mono" }, host.bmc_address),
      h("td", {}, [host.vendor, host.model].filter(Boolean).join(" · ") || "—"),
      h("td", {}, pre ? badge(pre.overall) : badge("none", "not run")),
      h("td", {}, net ? `${net.product}` : "—"));
  }));
  app.replaceChildren(
    h("div", { class: "row" }, h("h1", {}, "Hosts"), h("span", { class: "spacer" }),
      h("button", { class: "primary", onclick: addHostDialog }, "Add host")),
    h("div", { class: "panel" }, hosts.length
      ? table(["Name", "BMC", "Hardware", "Holodeck preflight", "Installed OS"], rows)
      : h("p", { class: "empty" }, "No hosts yet. Add a server by its BMC address.")));
}

function addHostDialog() {
  const err = h("div");
  const form = h("form", { method: "dialog" },
    h("h2", {}, "Add host"),
    h("label", { for: "f-bmc" }, "BMC address"), h("input", { id: "f-bmc", name: "bmc", required: true, placeholder: "10.0.0.50" }),
    h("label", { for: "f-name" }, "Name"), h("input", { id: "f-name", name: "name", placeholder: "esxi1" }),
    h("label", { for: "f-user" }, "BMC username"), h("input", { id: "f-user", name: "user", value: "root", required: true }),
    h("label", { for: "f-pass" }, "BMC password"), h("input", { id: "f-pass", name: "pass", type: "password", required: true }),
    err,
    h("div", { class: "actions" }, h("button", { value: "cancel", formnovalidate: true }, "Cancel"),
      h("button", { class: "primary", value: "ok" }, "Add")));
  form.addEventListener("submit", async (ev) => {
    if (ev.submitter?.value !== "ok") return;
    ev.preventDefault();
    const f = new FormData(form);
    try {
      await api("POST", "/hosts", { bmc_address: f.get("bmc"), name: f.get("name") || null,
        username: f.get("user"), password: f.get("pass") });
      dialog.close();
      route();
    } catch (e) { err.replaceChildren(errorBox(e)); }
  });
  dialog.replaceChildren(form);
  dialog.showModal();
}

async function viewHost(id) {
  const host = await api("GET", `/hosts/${id}`);
  const [pre, osAccess, net, install, jobs] = await Promise.all([
    maybe(api("GET", `/hosts/${id}/preflight`)),
    maybe(api("GET", `/hosts/${id}/os`)),
    maybe(api("GET", `/hosts/${id}/os/network`)),
    maybe(api("GET", `/hosts/${id}/install`)),
    api("GET", `/jobs?host_id=${id}&limit=10`),
  ]);
  const active = jobs.find((j) => j.status === "queued" || j.status === "running");
  const start = (path, body) => async () => {
    try { await api("POST", `/hosts/${id}${path}`, body); route(); } catch (e) { alertBox.replaceChildren(errorBox(e)); }
  };
  const alertBox = h("div");

  app.replaceChildren(
    h("div", { class: "row" }, h("h1", {}, host.name), h("span", { class: "muted" }, [host.vendor, host.model].filter(Boolean).join(" · "))),
    alertBox,
    h("div", { class: "panel" },
      h("dl", { class: "kv" },
        h("dt", {}, "BMC"), h("dd", { class: "mono" }, host.bmc_address),
        h("dt", {}, "Installed OS"), h("dd", {}, osAccess ? `${net ? net.product : "not read yet"} at ${osAccess.address}` : "not configured"),
        h("dt", {}, "Added"), h("dd", {}, fmtTime(host.created_at)))),
    active ? h("div", { class: "panel" }, h("h2", {}, "Running"), jobCard(active, { onDone: route })) : null,
    preflightPanel(pre, start("/preflight", { profile: "holodeck-9" }), !!active),
    networkPanel(id, osAccess, net, start("/os/network"), !!active),
    installPanel(host, osAccess, install, !!active, jobs.find((j) => j.kind === "install")),
    h("div", { class: "panel" }, h("h2", {}, "Recent jobs"),
      jobs.length ? jobs.map((j) => jobCard(j)) : h("p", { class: "muted" }, "No jobs yet.")));
}

function preflightPanel(pre, run, busy) {
  const header = h("div", { class: "row" }, h("h2", {}, "Holodeck preflight"),
    pre ? badge(pre.overall) : null, h("span", { class: "spacer" }),
    h("button", { onclick: run, disabled: busy }, pre ? "Run again" : "Run preflight"));
  if (!pre) return h("div", { class: "panel" }, header, h("p", { class: "muted" }, "Not run yet. Preflight is read-only."));
  const s = pre.summary;
  return h("div", { class: "panel", "data-panel": "preflight" }, header,
    h("p", { class: "muted" }, `${pre.variant_title} · ${s.passed} passed, ${s.warnings} warnings, ${s.failed} failed, ${s.unknown} unknown`),
    table(["", "Check", "Observed", "Required", "What to do"], pre.checks.map((c) =>
      h("tr", { "data-check": c.id }, h("td", {}, badge(c.status)), h("td", {}, c.title), h("td", {}, c.observed),
        h("td", { class: "muted" }, c.required), h("td", {}, c.remediation || "")))));
}

function networkPanel(id, osAccess, net, read, busy) {
  const header = h("div", { class: "row" }, h("h2", {}, "ESXi networking"), h("span", { class: "spacer" }),
    osAccess ? h("button", { onclick: read, disabled: busy }, net ? "Read again" : "Read now") : null,
    h("button", { onclick: () => osAccessDialog(id, osAccess) }, osAccess ? "Change OS access" : "Set OS access"));
  if (!net) return h("div", { class: "panel" }, header, h("p", { class: "muted" },
    osAccess ? "Not read yet." : "Tell GroundZero how to reach the installed hypervisor to read its network."));
  const pgs = Object.fromEntries(net.portgroups.map((p) => [p.name, p]));
  return h("div", { class: "panel", "data-panel": "network" }, header,
    h("p", { class: "muted" }, `${net.product} · gateway ${net.default_gateway || "—"} · DNS ${net.dns_servers.join(", ") || "—"} · NTP ${net.ntp_servers.join(", ") || "none"}`),
    table(["vmk", "IP", "Port group", "VLAN", "Active uplinks", "MTU"], net.vmkernel.map((v) => {
      const pg = pgs[v.portgroup] || {};
      return h("tr", {}, h("td", {}, v.device), h("td", { class: "mono" }, v.dhcp ? "dhcp" : `${v.ip}/${v.netmask}`),
        h("td", {}, v.portgroup || "—"), h("td", {}, String(pg.vlan_id ?? "—")),
        h("td", {}, (pg.active_uplinks || []).join(", ")), h("td", {}, String(v.mtu ?? "—")));
    })),
    h("h2", { style: "margin-top:16px" }, "Physical NICs"),
    table(["vmnic", "Speed", "Switch port", "MAC"], net.physical_nics.map((n) =>
      h("tr", {}, h("td", {}, n.device), h("td", {}, n.speed_mbps ? `${n.speed_mbps / 1000} GbE` : "down"),
        h("td", {}, n.switch ? `${n.switch} ${n.switch_port}` : "—"), h("td", { class: "mono" }, n.mac || "—")))),
    h("h2", { style: "margin-top:16px" }, "Virtual switches"),
    table(["vSwitch", "MTU", "Uplinks", "Port groups"], net.vswitches.map((vs) =>
      h("tr", {}, h("td", {}, vs.name), h("td", {}, String(vs.mtu)), h("td", {}, vs.uplinks.join(", ")),
        h("td", {}, vs.portgroups.join(", "))))));
}

function osAccessDialog(id, current) {
  const err = h("div");
  const form = h("form", { method: "dialog" },
    h("h2", {}, "Installed OS access"),
    h("label", { for: "o-addr" }, "Management address"), h("input", { id: "o-addr", name: "address", required: true, value: current?.address || "" }),
    h("label", { for: "o-user" }, "Username"), h("input", { id: "o-user", name: "user", value: current?.username || "root" }),
    h("label", { for: "o-pass" }, "Password"), h("input", { id: "o-pass", name: "pass", type: "password", required: true }),
    err,
    h("div", { class: "actions" }, h("button", { value: "cancel", formnovalidate: true }, "Cancel"),
      h("button", { class: "primary", value: "ok" }, "Save")));
  form.addEventListener("submit", async (ev) => {
    if (ev.submitter?.value !== "ok") return;
    ev.preventDefault();
    const f = new FormData(form);
    try {
      await api("PUT", `/hosts/${id}/os`, { address: f.get("address"), username: f.get("user"), password: f.get("pass") });
      dialog.close();
      route();
    } catch (e) { err.replaceChildren(errorBox(e)); }
  });
  dialog.replaceChildren(form);
  dialog.showModal();
}

function installPanel(host, osAccess, report, busy, lastInstallJob) {
  const header = h("div", { class: "row" }, h("h2", {}, "ESXi install"), h("span", { class: "spacer" }),
    h("button", { class: "danger", disabled: busy || !osAccess, title: osAccess ? "" : "Set OS access first",
      onclick: () => installDialog(host) }, "Reinstall ESXi…"));
  if (!report) return h("div", { class: "panel" }, header, h("p", { class: "muted" }, "No install has run on this host."));
  const target = `ESXi ${report.iso_version} build ${report.iso_build}`;
  const installed = Boolean(report.installed_build) && report.validation.length > 0;
  const valid = installed && report.validation.every((c) => c.ok);
  const media = `${report.media_fetches.length} ISO requests, ${Math.round(report.media_bytes_served / 2 ** 20)} MiB read`;
  let summary;
  if (valid) {
    summary = h("p", { "data-role": "install-summary" }, badge("pass", "installed"), " ",
      `Installed ${target} (was ${report.previous_build || "?"}) and validated · ${media}`);
  } else if (installed) {
    summary = h("p", { "data-role": "install-summary" }, badge("warn", "check"), " ",
      `Installed ${target}, but some validation checks failed · ${media}`);
  } else {
    // A failed attempt only tells us what was *targeted*; never present it as the installed version.
    summary = h("div", { "data-role": "install-summary" },
      h("p", {}, badge("fail", "failed"), " ", `Install of ${target} did not complete. Nothing was installed; `,
        `the host is still on build ${report.previous_build || "?"}.`),
      lastInstallJob?.error ? h("p", { class: "error" }, lastInstallJob.error.message) : null,
      h("p", { class: "muted" }, `Boot method ${report.boot_method || "—"} · ${media}`));
  }
  return h("div", { class: "panel", "data-panel": "install" }, header, summary,
    report.validation.length ? table(["", "Check", "Expected", "Observed"], report.validation.map((c) =>
      h("tr", {}, h("td", {}, badge(c.ok ? "pass" : "fail", c.ok ? "ok" : "failed")), h("td", {}, c.name),
        h("td", { class: "muted" }, c.expected), h("td", {}, c.observed)))) : null);
}

function installDialog(host) {
  const phrase = `install ${host.name}`;
  const err = h("div");
  const submit = h("button", { class: "danger", value: "ok", disabled: true }, "Reinstall");
  const confirmInput = h("input", { id: "i-confirm", name: "confirm", autocomplete: "off",
    oninput: (e) => { submit.disabled = e.target.value !== phrase; } });
  const form = h("form", { method: "dialog" },
    h("h2", {}, `Reinstall ESXi on ${host.name}`),
    h("div", { class: "notice" },
      "Keeps: the install disk's VMFS datastore (unless wiped below), every other disk, the management IP, VLAN, uplinks, hostname and root password. ",
      "Resets: VM inventory registrations and all other host configuration."),
    h("label", { for: "i-iso" }, "Stock ESXi ISO (path on the GroundZero host)"),
    h("input", { id: "i-iso", name: "iso", required: true, placeholder: "/path/to/VMware-VMvisor-Installer-….iso" }),
    h("label", { for: "i-ntp" }, "NTP servers (comma separated)"), h("input", { id: "i-ntp", name: "ntp", value: "pool.ntp.org" }),
    h("label", { class: "inline" }, h("input", { type: "checkbox", name: "wipe" }), "Overwrite the VMFS datastore on the install disk"),
    h("label", { for: "i-confirm" }, `Type "${phrase}" to confirm`), confirmInput,
    err,
    h("div", { class: "actions" }, h("button", { value: "cancel", formnovalidate: true }, "Cancel"), submit));
  form.addEventListener("submit", async (ev) => {
    if (ev.submitter?.value !== "ok") return;
    ev.preventDefault();
    const f = new FormData(form);
    try {
      await api("POST", `/hosts/${host.id}/install`, {
        iso_path: f.get("iso"), confirm: f.get("confirm"), wipe_install_disk_vmfs: f.get("wipe") === "on",
        ntp_servers: String(f.get("ntp")).split(",").map((s) => s.trim()).filter(Boolean),
      });
      dialog.close();
      route();
    } catch (e) { err.replaceChildren(errorBox(e)); }
  });
  dialog.replaceChildren(form);
  dialog.showModal();
}

async function viewJobs() {
  const jobs = await api("GET", "/jobs?limit=50");
  app.replaceChildren(h("h1", {}, "Jobs"),
    h("div", { class: "panel" }, jobs.length ? jobs.map((j) => jobCard(j)) : h("p", { class: "empty" }, "No jobs yet.")));
}

function renderLogin() {
  const input = h("input", { id: "token", type: "password", placeholder: "paste the API token" });
  app.replaceChildren(h("div", { class: "panel", style: "max-width:480px;margin:40px auto" },
    h("h1", {}, "Sign in"),
    h("p", { class: "muted" }, "Run ", h("code", {}, "groundzero ui"), " to open this page signed in, or paste the token from ",
      h("code", {}, "groundzero token show"), "."),
    h("label", { for: "token" }, "API token"), input,
    h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => {
      sessionStorage.setItem("gz-token", input.value.trim());
      route();
    } }, "Sign in"))));
}

// ── router ──
async function route() {
  if (!token()) return renderLogin();
  const path = location.hash.replace(/^#/, "") || "/";
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", (a.dataset.nav === "jobs") === path.startsWith("/jobs")));
  try {
    const m = path.match(/^\/hosts\/([\w-]+)$/);
    if (m) await viewHost(m[1]);
    else if (path.startsWith("/jobs")) await viewJobs();
    else await viewHosts();
  } catch (e) {
    if (e.status !== 401) app.replaceChildren(errorBox(e));
  }
}

fetch("/healthz").then((r) => r.json()).then((hz) => {
  const el = document.getElementById("mode");
  if (hz.mode === "simulated") { el.textContent = "simulation mode"; el.hidden = false; }
});
window.addEventListener("hashchange", route);
route();
