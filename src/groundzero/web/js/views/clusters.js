// Clusters: servers named after their BMC, addresses from a pool, and an optional DNS check before install.
import {
  api, badge, card, empty, fmtTime, h, maybe, mount, openDialog, pageHeader, startJob, table, toast,
} from "../core.js";

const refresh = () => window.dispatchEvent(new Event("gz:refresh"));

export async function viewClusters(app) {
  const [clusters, sets] = await Promise.all([api("GET", "/clusters"), api("GET", "/config-sets")]);
  const setName = Object.fromEntries(sets.map((s) => [s.id, s.name]));
  mount(app,
    pageHeader("Clusters", "Servers named after their BMC, with addresses from a pool. Optionally, DNS is checked before anything is installed.",
      h("a", { class: "button primary", href: "#/clusters/new" }, "New cluster")),
    card({}, clusters.length
      ? table(["Name", "Config set", "Range", "Domain", "Members", "DNS check"], clusters.map((c) =>
          h("tr", { "data-cluster": c.name },
            h("td", {}, h("a", { href: `#/clusters/${c.id}` }, c.name)),
            h("td", {}, setName[c.config_set_id] || c.config_set_id),
            h("td", { class: "mono" }, `${c.ip_first} – ${c.ip_last}`),
            h("td", {}, c.dns_domain),
            h("td", {}, String(c.members.length)),
            h("td", {}, c.require_dns ? badge("warn", "required") : badge("none", "optional")))))
      : empty("No clusters yet.", h("a", { class: "button primary", href: "#/clusters/new" }, "New cluster"))));
}

export async function viewCluster(app, id) {
  const isNew = id === "new";
  const [sets, hosts, cluster, clusters] = await Promise.all([
    api("GET", "/config-sets"), api("GET", "/hosts"), isNew ? null : api("GET", `/clusters/${id}`), api("GET", "/clusters"),
  ]);
  const esxiSets = sets.filter((s) => s.os_family === "esxi");
  const field = (key, label, attrs = {}) => {
    const input = h("input", { id: `cl-${key}`, value: cluster?.[key] ?? "", autocomplete: "off", ...attrs });
    return [input, h("div", { class: "field", "data-field": key }, h("label", { for: input.id }, label), input,
      attrs.help ? h("p", { class: "help" }, attrs.help) : null, h("p", { class: "field-error", role: "alert" }))];
  };
  const [name, nameField] = field("name", "Name");
  const setSelect = h("select", { id: "cl-config" }, esxiSets.map((s) =>
    h("option", { value: s.id, selected: s.id === cluster?.config_set_id }, s.name)));
  const [first, firstField] = field("ip_first", "First IP", { placeholder: "192.0.2.101" });
  const [last, lastField] = field("ip_last", "Last IP", { placeholder: "192.0.2.120" });
  const [domain, domainField] = field("dns_domain", "DNS domain", { placeholder: "lab.example" });
  const [prefix, prefixField] = field("strip_prefix", "Strip from the BMC name (prefix)", { placeholder: "idrac-" });
  const [suffix, suffixField] = field("strip_suffix", "Strip from the BMC name (suffix)", { placeholder: "-idrac" });
  const requireDns = h("input", { type: "checkbox", id: "cl-require-dns", checked: cluster?.require_dns || false });
  const status = h("div");

  async function save() {
    status.replaceChildren();
    document.querySelectorAll("[data-field].invalid").forEach((el) => el.classList.remove("invalid"));
    const body = { name: name.value.trim(), config_set_id: setSelect.value, ip_first: first.value.trim(), ip_last: last.value.trim(),
      dns_domain: domain.value.trim(), strip_prefix: prefix.value, strip_suffix: suffix.value, require_dns: requireDns.checked };
    try {
      const saved = await api(isNew ? "POST" : "PUT", isNew ? "/clusters" : `/clusters/${id}`, body);
      toast(`Saved ${saved.name}`, "success");
      location.hash = `#/clusters/${saved.id}`;
    } catch (e) {
      for (const err of e.problem?.errors || []) {
        const el = document.querySelector(`[data-field="${err.loc[err.loc.length - 1]}"]`);
        if (el) { el.classList.add("invalid"); el.querySelector(".field-error").textContent = err.msg; }
      }
      status.replaceChildren(h("p", { class: "error", role: "alert" }, e.message));
    }
  }

  const editor = card({ class: "panel form-card" },
    h("div", { class: "grid two" }, nameField,
      h("div", { class: "field" }, h("label", { for: "cl-config" }, "ESXi config set"), setSelect,
        h("p", { class: "help" }, "VLAN, gateway, DNS servers and NTP for every member"))),
    h("div", { class: "grid two" }, firstField, lastField),
    h("div", { class: "grid two" }, domainField, h("div")),
    h("div", { class: "grid two" }, prefixField, suffixField),
    h("label", { class: "inline", for: "cl-require-dns" }, requireDns, "Require a passing DNS check before install"),
    h("p", { class: "help" }, "Off: run Verify DNS whenever you like. On: members are installed only once their forward and reverse records match."),
    status,
    h("div", { class: "actions" }, h("a", { class: "button", href: "#/clusters" }, "Back"),
      h("button", { class: "primary", onclick: save }, isNew ? "Create" : "Save")));

  if (isNew) {
    mount(app, pageHeader("New cluster", "Names from the BMC, addresses from a pool"), editor);
    return;
  }

  const taken = new Set(clusters.flatMap((c) => c.members.map((m) => m.host_id)));
  const free = hosts.filter((x) => !taken.has(x.id));
  const dnsResults = Object.fromEntries(await Promise.all(cluster.members.map(async (m) =>
    [m.host_id, await maybe(api("GET", `/hosts/${m.host_id}/outputs/dns`))])));
  const dnsCell = (m) => {
    const d = dnsResults[m.host_id];
    const fqdn = `${m.hostname}.${cluster.dns_domain}`;
    if (!d || d.fqdn !== fqdn || d.ip !== m.ip) return badge("none", "not checked");
    return d.ok ? badge("pass", "matches") : h("span", {}, badge("fail", "wrong"), " ", h("span", { class: "small-text error" }, d.problems.join("; ")));
  };
  const addSelect = h("select", { id: "cl-add" }, free.map((x) => h("option", { value: x.id }, `${x.name} (${x.bmc_address})`)));
  const add = async () => {
    try {
      const m = await api("POST", `/clusters/${id}/members`, { host_id: addSelect.value });
      toast(`${m.host_name} is ${m.hostname} (${m.ip})`, "success");
      refresh();
    } catch (e) { toast(e.message, "error"); }
  };
  const remove = (m) => openDialog(`Remove ${m.hostname} from ${cluster.name}?`, [
    h("p", {}, "The server keeps its hostname and IP as its own values; nothing on the server changes."),
  ], { submitLabel: "Remove", submitClass: "danger", onSubmit: async () => {
    await api("DELETE", `/clusters/${id}/members/${m.host_id}`);
    refresh();
  } });

  mount(app,
    pageHeader(cluster.name, `${cluster.ip_first} – ${cluster.ip_last} · ${cluster.dns_domain} · updated ${fmtTime(cluster.updated_at)}`),
    card({ "data-panel": "members" },
      h("div", { class: "row" }, h("h2", {}, "Members"), h("span", { class: "spacer" }),
        free.length ? [h("label", { for: "cl-add", class: "visually-hidden" }, "Server to add"), addSelect,
          h("button", { class: "primary", onclick: add }, "Add server")] : null),
      cluster.members.length
        ? table(["Server", "BMC name", "Hostname", "IP", "DNS", ""], cluster.members.map((m) =>
            h("tr", { "data-member": m.hostname },
              h("td", {}, h("a", { href: `#/hosts/${m.host_id}` }, m.host_name)),
              h("td", { class: "muted" }, m.bmc_hostname || "not reported"),
              h("td", { class: "mono" }, `${m.hostname}.${cluster.dns_domain}`),
              h("td", { class: "mono" }, m.ip),
              h("td", {}, dnsCell(m)),
              h("td", {}, h("div", { class: "row" },
                h("button", { class: "small", onclick: () => startJob("POST", `/hosts/${m.host_id}/tasks/dns.verify`, {}, { onDone: refresh }) }, "Verify DNS"),
                h("button", { class: "small danger-outline", onclick: () => remove(m) }, "Remove"))))))
        : empty("No servers yet. Each one is named after its BMC and given the next free address.")),
    editor);
}
