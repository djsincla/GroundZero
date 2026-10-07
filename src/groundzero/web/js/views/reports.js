// Reports: a server's full hardware and configuration on one printable page, and a cluster's members side by
// side with what differs flagged. Built from what GroundZero recorded; nothing is read from the servers.
import { age, api, badge, card, download, fmtTime, h, mount, pageHeader, table, toast } from "../core.js";

const gib = (mib) => `${Math.round(mib / 1024)} GiB`;
const gb = (bytes) => (bytes >= 1e12 ? `${(bytes / 1e12).toFixed(1)} TB` : `${Math.round(bytes / 1e9)} GB`);
const health = (v) => (v ? badge(v === "OK" ? "pass" : v === "Warning" ? "warn" : "fail", v) : "—");
const STATE = { done: "pass", not_needed: "pass", failed: "fail", stale: "warn", running: "running" };

function actions(json, csv, name, extra = []) {
  const get = (path, file) => () => download(path, file).catch((e) => toast(e.message, "error"));
  return [
    h("button", { class: "no-print", onclick: () => window.print() }, "Print"),
    h("button", { class: "no-print", onclick: get(csv, `${name}.csv`) }, "Download CSV"),
    ...extra.map(([label, path, file]) => h("button", { class: "no-print", onclick: get(path, file) }, label)),
    h("button", { class: "no-print", onclick: get(json, `${name}.json`) }, "Download JSON"),
  ];
}

// The hardware sections of a report (also what the Overview tab shows).
export function hardwareSections(inv) {
  if (!inv) return [card({}, h("p", { class: "muted" }, "Hardware not read yet: run Discover hardware."))];
  const kv = (rows) => h("dl", { class: "kv" }, rows.filter(([, v]) => v).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
  const section = (title, key, headers, rows) => (rows.length
    ? card({ "data-section": key }, h("h2", {}, title), table(headers, rows)) : null);
  const firmware = [...inv.firmware].sort((a, b) => a.name.localeCompare(b.name));
  return [
    card({ "data-section": "system" }, h("h2", {}, "System"), kv([
      ["Model", `${inv.system.manufacturer} ${inv.system.model}`], ["Service tag", inv.system.service_tag],
      ["Asset tag", inv.system.asset_tag], ["BIOS", inv.system.bios_version], ["Boot mode", inv.bios.boot_mode],
      ["BMC", [inv.bmc.vendor, inv.bmc.firmware_version, inv.bmc.hostname].filter(Boolean).join(" · ")],
      ["Power", inv.system.power_state], ["Health", inv.system.health], ["Read", fmtTime(inv.collected_at)],
    ])),
    section("Processors", "processors", ["Socket", "Model", "Cores", "Threads", "Max speed"], inv.processors.map((p) =>
      h("tr", {}, h("td", {}, p.socket || "—"), h("td", {}, p.model), h("td", {}, String(p.cores)), h("td", {}, String(p.threads)),
        h("td", {}, p.max_speed_mhz ? `${p.max_speed_mhz} MHz` : "—")))),
    section(`Memory · ${inv.memory.total_gib} GiB in ${inv.memory.dimm_count} DIMMs`, "memory", ["Slot", "Size", "Type", "Speed", "Maker", "Part", "Health"],
      inv.memory.modules.map((m) => h("tr", {}, h("td", {}, m.slot || m.id), h("td", {}, gib(m.capacity_mib)), h("td", {}, m.type || "—"),
        h("td", {}, m.speed_mhz ? `${m.speed_mhz} MHz` : "—"), h("td", {}, m.manufacturer || "—"), h("td", { class: "mono small-text" }, m.part_number || "—"), h("td", {}, health(m.health))))),
    section("Drives", "drives", ["Drive", "Model", "Size", "Type", "Firmware", "Controller"], inv.drives.map((d) =>
      h("tr", {}, h("td", { class: "mono small-text" }, d.id.split(":")[0]), h("td", {}, d.model || "—"), h("td", {}, gb(d.capacity_bytes)),
        h("td", {}, [d.media_type, d.protocol].filter(Boolean).join(" ") || "—"), h("td", { class: "mono" }, d.firmware_version || "—"),
        h("td", { class: "small-text" }, d.controller || "—")))),
    section("Network adapters", "adapters", ["Adapter", "Maker", "Ports", "Firmware", "Health"], inv.network_adapters.map((a) =>
      h("tr", {}, h("td", {}, a.model || a.name || a.id), h("td", {}, a.manufacturer || "—"), h("td", {}, String(a.ports)),
        h("td", { class: "mono" }, a.firmware_version || "—"), h("td", {}, health(a.health))))),
    section("Network ports", "ports", ["Port", "Link", "Speed"], inv.network_ports.map((n) =>
      h("tr", {}, h("td", { class: "mono small-text" }, n.id), h("td", {}, n.link_status || "—"), h("td", {}, n.speed_mbps ? `${n.speed_mbps / 1000} Gb/s` : "—")))),
    section("PCIe devices: storage controllers, HBAs, NICs and more", "pcie", ["Device", "Kind", "Maker", "Firmware", "Health"],
      [...inv.pcie_devices].sort((a, b) => (a.device_class || "").localeCompare(b.device_class || "")).map((x) =>
        h("tr", { "data-class": x.device_class }, h("td", {}, x.name || x.id), h("td", {}, x.device_class || "—"), h("td", { class: "small-text" }, x.manufacturer || "—"),
          h("td", { class: "mono" }, x.firmware_version || "—"), h("td", {}, health(x.health))))),
    section("Power supplies", "psu", ["Supply", "Model", "Capacity", "Firmware", "Health"], inv.power_supplies.map((s) =>
      h("tr", {}, h("td", {}, s.name), h("td", {}, s.model || "—"), h("td", {}, s.capacity_watts ? `${s.capacity_watts} W` : "—"),
        h("td", { class: "mono" }, s.firmware_version || "—"), h("td", {}, health(s.health))))),
    section(`Firmware · ${firmware.length} components`, "firmware", ["Component", "Version", "Updateable"], firmware.map((f) =>
      h("tr", {}, h("td", {}, f.name), h("td", { class: "mono" }, f.version || "—"), h("td", {}, f.updateable ? "yes" : "—")))),
  ];
}

function configurationSection(c) {
  const kv = [["Spec", c.spec], ["Last run", c.last_run], ["Installed OS", c.os], ["Hostname", c.hostname],
    ["Management IP", c.management_ip], ["Boot volume", c.boot_volume], ["Holodeck readiness", c.readiness]].filter(([, v]) => v);
  const ran = c.tasks.filter((t) => !["ready", "blocked", "planned"].includes(t.state));
  const notRun = c.tasks.length - ran.length;
  return card({ "data-section": "configuration" }, h("h2", {}, "Configuration"),
    kv.length ? h("dl", { class: "kv" }, kv.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])) : null,
    notRun ? h("p", { class: "muted small-text" }, `${notRun} other task${notRun === 1 ? "" : "s"} not run yet.`) : null,
    table(["Task", "State", "Result"], ran.map((t) => h("tr", { "data-report-task": t.task },
      h("td", {}, t.title), h("td", {}, badge(STATE[t.state] || "none", t.state.replace("_", " "))),
      h("td", { class: "small-text" }, t.summary || "—", t.at ? [" · ", age(t.at)] : null)))));
}

export async function viewHostReport(app, id) {
  const r = await api("GET", `/hosts/${id}/report`);
  mount(app,
    pageHeader(`${r.name}: report`, [r.model, r.service_tag ? `service tag ${r.service_tag}` : null, `generated ${fmtTime(r.generated_at)}`].filter(Boolean).join(" · "),
      ...actions(`/hosts/${id}/report`, `/hosts/${id}/report.csv`, `${r.name}-report`)),
    h("div", { class: "stack report" }, ...hardwareSections(r.inventory), configurationSection(r.configuration)));
}

export async function viewClusterReport(app, id) {
  const r = await api("GET", `/clusters/${id}/report`);
  const names = r.members.map((m) => m.name);
  const differs = r.comparison.filter((c) => c.differs);
  const same = r.comparison.filter((c) => !c.differs);
  const row = (c) => h("tr", { class: c.differs ? "differs" : null, "data-item": c.item },
    h("td", {}, c.item), ...names.map((n) => h("td", { class: "mono small-text" }, c.values[n] ?? "—")));
  mount(app,
    pageHeader(`${r.name}: cluster report`, `${names.length} servers · ${r.differences} item(s) differ · generated ${fmtTime(r.generated_at)}`,
      ...actions(`/clusters/${id}/report`, `/clusters/${id}/report.csv`, `${r.name}-cluster-report`,
        [["Download all components (CSV)", `/clusters/${id}/report-components.csv`, `${r.name}-components.csv`]])),
    h("div", { class: "stack report" },
      card({ "data-section": "differences" }, h("h2", {}, differs.length ? `Differences · ${differs.length}` : "No differences"),
        differs.length ? table(["Item", ...names], differs.map(row)) : h("p", { class: "muted" }, "Every compared item is the same on every member.")),
      card({ "data-section": "same" }, h("h2", {}, `The same on every member · ${same.length}`), table(["Item", ...names], same.map(row))),
      ...r.members.map((m) => card({ "data-member-report": m.name }, h("h2", {}, h("a", { href: `#/hosts/${m.host_id}/report` }, m.name)),
        h("p", { class: "muted" }, [m.model, m.service_tag ? `service tag ${m.service_tag}` : null, m.configuration.os].filter(Boolean).join(" · ")),
        table(["Task", "State", "Result"], m.configuration.tasks.filter((t) => t.state !== "ready").map((t) => h("tr", {},
          h("td", {}, t.title), h("td", {}, badge(STATE[t.state] || "none", t.state.replace("_", " "))), h("td", { class: "small-text" }, t.summary || "—"))))))));
}
