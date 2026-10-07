// Config sets (list, create, edit, duplicate, delete) and the ISO repository.
import {
  api, badge, card, empty, errorBox, fmtBytes, fmtTime, h, maybe, mount, openDialog, pageHeader, showJobDrawer, table, toast,
} from "../core.js";
import { biosProfilesCard } from "./bios.js";
import { storageProfilesCard } from "./storage.js";
import { schemaForm } from "../forms.js";

const SECRET_LABELS = {
  root_password: "Root password", holorouter_password: "Holorouter password",
  download_token: "Broadcom download token", offline_depot_password: "Offline depot password",
};
const SECRET_HELP = {
  root_password: "Set on the installed OS. Encrypted at rest and never shown again.",
  download_token: "Needed for the Online depot. Encrypted at rest and never shown again.",
};

// ── config sets ──
export async function viewConfigSets(app) {
  const [sets, families, profiles] = await Promise.all([api("GET", "/config-sets"), api("GET", "/os-families"),
    api("GET", "/appliance-profiles")]);
  const title = Object.fromEntries(families.map((f) => [f.family, f.title]));
  mount(app, 
    pageHeader("Config sets", "Reusable OS settings. Choose one per server at deploy time; hostname and IP stay per server.",
      h("button", { onclick: captureFromServerDialog }, "From a running server…"),
      h("a", { class: "button primary", href: "#/config-sets/new" }, "New config set")),
    card({}, sets.length
      ? table(["Name", "Family", "Source", "Secrets", "Updated"], sets.map((s) =>
          h("tr", { "data-config-set": s.name },
            h("td", {}, h("a", { href: `#/config-sets/${s.id}` }, s.name)),
            h("td", {}, title[s.os_family] || s.os_family),
            h("td", { class: "muted" }, s.source),
            h("td", {}, (s.secrets_set || []).length
              ? badge("pass", `${s.secrets_set.length} stored`) : badge("none", "not set")),
            h("td", { class: "muted" }, fmtTime(s.updated_at)))))
      : empty("No config sets yet. Build one from a running server, or create one from scratch.",
          h("button", { onclick: captureFromServerDialog }, "From a running server…"),
          h("a", { class: "button primary", href: "#/config-sets/new" }, "New config set"))),
    card({ "data-panel": "appliance-profiles" },
      h("div", { class: "row" }, h("h2", {}, "Appliance profiles"), h("span", { class: "spacer" }),
        h("a", { class: "button", href: "#/appliance-profiles/new" }, "New appliance profile")),
      h("p", { class: "muted small-text" }, "Saved values for an OVA: its properties, which port group each of its networks uses, and its passwords. The form comes from the OVA itself."),
      profiles.length
        ? table(["Name", "Appliance", "Source", "Passwords", "Updated"], profiles.map((p) =>
            h("tr", { "data-profile": p.name },
              h("td", {}, h("a", { href: `#/appliance-profiles/${p.id}` }, p.name)),
              h("td", {}, p.product),
              h("td", { class: "muted" }, p.source),
              h("td", {}, p.secrets_set.length ? badge("pass", `${p.secrets_set.length} stored`) : badge("none", "none")),
              h("td", { class: "muted" }, fmtTime(p.updated_at)))))
        : h("p", { class: "muted" }, "No appliance profiles yet.")),
    await biosProfilesCard(),
    await storageProfilesCard());
}

// Build a config set by reading a running server (read-only). If GroundZero can't log in to its OS yet,
// the address and credentials are asked for here and saved as the host's OS access first.
async function captureFromServerDialog() {
  const hosts = await api("GET", "/hosts");
  if (!hosts.length) {
    openDialog("Build from a running server", [
      h("p", {}, "Add the server as a host first (Hosts → Add host), then come back here."),
    ], { submitLabel: "Go to Hosts", onSubmit: async () => { location.hash = "#/"; } });
    return;
  }
  const access = Object.fromEntries(await Promise.all(hosts.map(async (x) => [x.id, await maybe(api("GET", `/hosts/${x.id}/os`))])));
  const select = h("select", { id: "cap-host", name: "host" }, hosts.map((x) => h("option", { value: x.id }, x.name)));
  const name = h("input", { id: "cap-name", name: "name", required: true });
  const addr = h("input", { id: "cap-addr", name: "address" });
  const user = h("input", { id: "cap-user", name: "user", value: "root" });
  const pass = h("input", { id: "cap-pass", name: "pass", type: "password", autocomplete: "off" });
  const known = h("p", { class: "help" });
  const creds = h("div", {},
    h("p", { class: "help" }, "GroundZero doesn't know how to log in to this server's OS yet. These are saved as its OS access."),
    h("label", { for: "cap-addr" }, "OS management address"), addr,
    h("label", { for: "cap-user" }, "OS username"), user,
    h("label", { for: "cap-pass" }, "OS password"), pass);
  let nameTouched = false;
  name.addEventListener("input", () => { nameTouched = true; });
  const sync = () => {
    const host = hosts.find((x) => x.id === select.value);
    const a = access[host.id];
    creds.hidden = Boolean(a);
    for (const el of [addr, pass]) el.required = !a;
    known.textContent = a ? `Reads ${a.address} as ${a.username} (read-only).` : "";
    if (!nameTouched) name.value = `${host.name}-captured`;
  };
  select.addEventListener("change", sync);
  openDialog("Build a config set from a running server", [
    h("p", { class: "muted" }, "Reads the running hypervisor's network, DNS, NTP, uplinks and boot disk, and saves them as a reusable config set. ",
      "Nothing on the server changes. Its hostname and IP are kept as that server's own values."),
    h("label", { for: "cap-host" }, "Server"), select, known, creds,
    h("label", { for: "cap-name" }, "Config set name"), name,
  ], {
    submitLabel: "Capture",
    onSubmit: async (f) => {
      const id = f.get("host");
      if (!access[id]) {
        await api("PUT", `/hosts/${id}/os`, { address: f.get("address"), username: f.get("user"), password: f.get("pass") });
      }
      const job = await api("POST", `/hosts/${id}/tasks/os.capture`, { params: { name: f.get("name") } });  // errors stay in the dialog
      showJobDrawer(job, {
        title: "Capture config set",
        onDone: (j) => { if (j.status === "succeeded") location.hash = `#/config-sets/${j.result.config_set_id}`; },
      });
    },
  });
  sync();
}

export async function viewConfigSet(app, id, query) {
  const families = await api("GET", "/os-families");
  const isNew = id === "new";
  const from = isNew && query.get("from") ? await api("GET", `/config-sets/${query.get("from")}`) : null;
  const existing = isNew ? null : await api("GET", `/config-sets/${id}`);
  const base = existing || from;
  let family = families.find((f) => f.family === (base?.os_family || query.get("family") || "esxi")) || families[0];

  const name = h("input", { id: "cs-name", required: true, value: existing?.name || (from ? `${from.name}-copy` : "") });
  const nameError = h("p", { class: "field-error", role: "alert" });
  const familySelect = h("select", { id: "cs-family", disabled: !isNew },
    families.map((f) => h("option", { value: f.family, selected: f.family === family.family }, f.title)));
  const secretsSlot = h("div");
  let secretInputs = {};
  const renderSecrets = () => {
    secretInputs = {};
    secretsSlot.replaceChildren(...family.secret_fields.map((name) => {
      const stored = (existing?.secrets_set || []).includes(name) && existing.os_family === family.family;
      const input = h("input", { id: `cs-secret-${name}`, type: "password", autocomplete: "new-password",
        placeholder: stored ? "stored: leave blank to keep" : "" });
      secretInputs[name] = input;
      return h("div", { class: "field" }, h("label", { for: input.id }, SECRET_LABELS[name] || name), input,
        h("p", { class: "help" }, SECRET_HELP[name] || "Encrypted at rest and never shown again."));
    }));
  };
  const formSlot = h("div");
  let form;
  const renderForm = () => {
    form = schemaForm(family.settings_schema, base?.os_family === family.family ? base.settings : {},
      { idPrefix: "cs", where: "settings" });
    formSlot.replaceChildren(form.el);
  };
  familySelect.addEventListener("change", () => {
    family = families.find((f) => f.family === familySelect.value);
    renderForm();
    renderSecrets();
  });
  renderForm();
  renderSecrets();

  const status = h("div");
  const save = async () => {
    form.clearErrors();
    nameError.textContent = "";
    status.replaceChildren();
    const secrets = Object.fromEntries(Object.entries(secretInputs).filter(([, i]) => i.value).map(([k, i]) => [k, i.value]));
    const body = { name: name.value.trim(), os_family: family.family, settings: form.value(),
      secrets: Object.keys(secrets).length ? secrets : null };
    try {
      const saved = await api(isNew ? "POST" : "PUT", isNew ? "/config-sets" : `/config-sets/${id}`, body);
      toast(`Saved ${saved.name}`, "success");
      location.hash = "#/config-sets";
    } catch (e) {
      const errors = e.problem?.errors || [];
      for (const err of errors) if (err.loc?.includes("name")) nameError.textContent = err.msg;
      const placed = errors.length && form.setErrors(errors.filter((x) => !x.loc?.includes("name")));
      status.replaceChildren(h("p", { class: "error", role: "alert" },
        placed || errors.length ? "Fix the highlighted fields." : e.message));
    }
  };
  const remove = () => openDialog(`Delete ${existing.name}?`, [
    h("p", {}, "Hosts keep their own per-server values. Installs already done are not affected."),
  ], {
    submitLabel: "Delete", submitClass: "danger",
    onSubmit: async () => {
      await api("DELETE", `/config-sets/${id}`);
      toast(`Deleted ${existing.name}`, "success");
      location.hash = "#/config-sets";
    },
  });

  mount(app, 
    pageHeader(isNew ? "New config set" : existing.name,
      existing ? `${family.title} · ${existing.source} · updated ${fmtTime(existing.updated_at)}` : family.title,
      existing ? h("a", { class: "button", href: `#/config-sets/new?from=${id}` }, "Duplicate") : null,
      existing ? h("button", { class: "danger-outline", onclick: remove }, "Delete…") : null),
    from ? h("p", { class: "notice" }, `Copy of ${from.name}. The root password is not copied; set one below or it falls back to the host's OS access password.`) : null,
    card({ class: "panel form-card" },
      h("div", { class: "grid two" },
        h("div", { class: "field" }, h("label", { for: "cs-name" }, "Name", h("span", { class: "req" }, " *")), name, nameError),
        h("div", { class: "field" }, h("label", { for: "cs-family" }, "OS family"), familySelect)),
      formSlot,
      secretsSlot,
      status,
      h("div", { class: "actions" }, h("a", { class: "button", href: "#/config-sets" }, "Back"),
        h("button", { class: "primary", onclick: save }, isNew ? "Create" : "Save"))));
}

// ── image repository: stock ISOs and appliance OVAs ──
export async function viewImages(app) {
  const images = await api("GET", "/images");
  const render = (list) => mount(app,
    pageHeader("Images", "Stock installer ISOs and appliance OVAs. Download them yourself and drop them into the repository folder.",
      h("button", { onclick: rescan, id: "rescan" }, "Rescan folder")),
    card({}, list.length
      ? table(["Image", "Kind", "Product / OS", "Version", "Build", "Size", "SHA-256", ""], list.map((i) =>
          h("tr", { "data-iso": i.filename, "data-image": i.filename },
            h("td", { class: "mono" }, i.filename),
            h("td", {}, i.kind.toUpperCase()),
            h("td", {}, i.product || i.os_family ? badge("pass", i.product || i.os_family) : badge("none", "unrecognised")),
            h("td", {}, i.version || "—"), h("td", {}, i.build || "—"), h("td", {}, fmtBytes(i.size)),
            h("td", { class: "mono small-text", title: i.sha256 }, `${i.sha256.slice(0, 12)}…`),
            h("td", {}, i.kind === "ova" ? h("button", { class: "small", onclick: () => inputsDialog(i) }, "Inputs") : null))))
      : empty("No images found. Put stock ISOs and OVAs in the repository folder (./images by default, or GROUNDZERO_ISO_REPOSITORY), then rescan.")),
    h("p", { class: "help" }, "GroundZero never downloads or changes these files. An ESXi install builds a temporary copy with the kickstart and deletes it afterwards."));
  async function rescan(ev) {
    ev.target.disabled = true;
    ev.target.textContent = "Scanning…";
    try {
      const list = await api("POST", "/images/rescan");
      render(list);
      toast(`Found ${list.length} image${list.length === 1 ? "" : "s"}`, "success");
    } catch (e) {
      toast(e.message, "error");
      ev.target.disabled = false;
      ev.target.textContent = "Rescan folder";
    }
  }
  render(images);
}

// What an OVA takes: read from its descriptor, shown as the form a deployment will use.
async function inputsDialog(image) {
  let info;
  try { info = await api("GET", `/images/${image.id}/descriptor`); } catch (e) { toast(e.message, "error"); return; }
  const d = info.descriptor;
  const size = [d.cpus && `${d.cpus} vCPU`, d.memory_mb && `${d.memory_mb / 1024} GB RAM`, d.disk_gb && `${Math.round(d.disk_gb)} GB disk`]
    .filter(Boolean).join(" · ");
  const hidden = d.properties.filter((p) => !p.user_configurable);
  const form = schemaForm(info.schema, {}, { idPrefix: "ova", secretFields: info.schema["x-secret-fields"] || [] });
  openDialog(`${d.product || image.filename} ${d.version || ""}`, [
    h("p", { class: "muted" }, size || "Size not declared", " · networks: ", d.networks.map((n) => n.name).join(", ") || "none",
      " · settings via ", d.transport.join(", ") || "none"),
    h("h3", {}, `Inputs you set (${Object.keys(info.schema.properties).length})`),
    h("div", { "data-role": "ova-inputs" }, form.el),
    hidden.length ? h("details", {}, h("summary", {}, `${hidden.length} more the appliance sets itself (sent with their defaults)`),
      h("ul", { class: "plain small-text mono" }, hidden.map((p) => h("li", {}, p.qualified_key, p.default ? ` = ${p.default}` : "")))) : null,
  ], { submitLabel: "Close", wide: true, onSubmit: async () => {} });
}

// ── appliance profile editor: the form is generated from the chosen OVA's descriptor ──
export async function viewApplianceProfile(app, id) {
  const isNew = id === "new";
  const [images, existing] = await Promise.all([api("GET", "/images"), isNew ? null : api("GET", `/appliance-profiles/${id}`)]);
  const ovas = images.filter((i) => i.kind === "ova");
  if (!ovas.length) {
    mount(app, pageHeader("Appliance profile"), card({}, empty("No OVAs in the image repository. Add one, then rescan.",
      h("a", { class: "button", href: "#/images" }, "Open image repository"))));
    return;
  }
  const name = h("input", { id: "ap-name", required: true, value: existing?.name || "" });
  const preferred = existing && (ovas.find((i) => i.id === existing.image_id) || ovas.find((i) => i.product === existing.product));
  const imageSelect = h("select", { id: "ap-image" }, ovas.map((i) =>
    h("option", { value: i.id, selected: preferred ? i.id === preferred.id : false }, `${i.product || i.filename} ${i.version || ""} (${i.filename})`)));
  const formSlot = h("div");
  const networksSlot = h("div");
  const status = h("div");
  let form = null;
  let secretKeys = [];
  let netInputs = {};

  async function load() {
    formSlot.replaceChildren(h("p", { class: "muted" }, "Reading the OVA…"));
    let info;
    try { info = await api("GET", `/images/${imageSelect.value}/descriptor`); } catch (e) { formSlot.replaceChildren(errorBox(e)); return; }
    secretKeys = info.schema["x-secret-fields"] || [];
    form = schemaForm(info.schema, existing?.values || {}, { idPrefix: "ap" });
    for (const key of secretKeys) {  // stored passwords: blank keeps them
      const input = form.el.querySelector(`[data-field="${CSS.escape(key)}"] input`);
      if (input && existing?.secrets_set.includes(key)) input.placeholder = "stored: leave blank to keep";
    }
    formSlot.replaceChildren(h("h3", {}, "Properties"), form.el);
    netInputs = {};
    networksSlot.replaceChildren(h("h3", {}, "Networks"),
      h("p", { class: "help" }, "The port group on the host for each network the OVA declares."),
      ...info.descriptor.networks.map((n) => {
        const input = h("input", { id: `ap-net-${n.name.replace(/\W/g, "-")}`, value: existing?.networks?.[n.name] || "",
          placeholder: "port group, e.g. VM Network", "data-network": n.name });
        netInputs[n.name] = input;
        return h("div", { class: "field" }, h("label", { for: input.id }, n.name), input);
      }));
  }
  imageSelect.addEventListener("change", load);

  async function save() {
    if (!form) return;
    form.clearErrors();
    status.replaceChildren();
    const all = form.value();
    const values = {};
    const secrets = {};
    for (const [k, v] of Object.entries(all)) {
      if (secretKeys.includes(k)) { if (v) secrets[k] = v; } else if (v !== null && v !== undefined && v !== "") values[k] = v;
    }
    const networks = Object.fromEntries(Object.entries(netInputs).map(([k, i]) => [k, i.value.trim()]).filter(([, v]) => v));
    const body = { name: name.value.trim(), image_id: imageSelect.value, values, networks,
      secrets: Object.keys(secrets).length ? secrets : null };
    try {
      const saved = await api(isNew ? "POST" : "PUT", isNew ? "/appliance-profiles" : `/appliance-profiles/${id}`, body);
      toast(`Saved ${saved.name}`, "success");
      location.hash = "#/config-sets";
    } catch (e) {
      const errors = (e.problem?.errors || []).map((x) => ({ ...x, loc: x.loc.slice(1) }));
      const placed = errors.length && form.setErrors(errors);
      status.replaceChildren(h("p", { class: "error", role: "alert" }, placed || errors.length ? "Fix the highlighted values." : e.message));
    }
  }
  const remove = () => openDialog(`Delete ${existing.name}?`, [h("p", {}, "Appliances already deployed with it are not affected.")], {
    submitLabel: "Delete", submitClass: "danger",
    onSubmit: async () => { await api("DELETE", `/appliance-profiles/${id}`); toast(`Deleted ${existing.name}`, "success"); location.hash = "#/config-sets"; },
  });

  mount(app,
    pageHeader(isNew ? "New appliance profile" : existing.name,
      existing ? `${existing.product} · ${existing.source} · updated ${fmtTime(existing.updated_at)}` : "Saved values for an OVA",
      existing ? h("button", { class: "danger-outline", onclick: remove }, "Delete…") : null),
    card({ class: "panel form-card" },
      h("div", { class: "grid two" },
        h("div", { class: "field" }, h("label", { for: "ap-name" }, "Name", h("span", { class: "req" }, " *")), name),
        h("div", { class: "field" }, h("label", { for: "ap-image" }, "OVA"), imageSelect)),
      formSlot, networksSlot, status,
      h("div", { class: "actions" }, h("a", { class: "button", href: "#/config-sets" }, "Back"),
        h("button", { class: "primary", onclick: save }, isNew ? "Create" : "Save"))));
  await load();
}
