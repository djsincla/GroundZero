// BIOS profiles: saved BIOS settings, built from the server's own attribute registry (what each setting is
// and the values it takes), captured from a server, or imported from a file. Configure BIOS applies them.
import { api, badge, card, fmtTime, h, mount, openDialog, pageHeader, table, toast } from "../core.js";

export async function biosProfilesCard() {
  const profiles = await api("GET", "/bios-profiles");
  return card({ "data-panel": "bios-profiles" },
    h("div", { class: "row" }, h("h2", {}, "BIOS profiles"), h("span", { class: "spacer" }),
      h("button", { onclick: newBiosProfileDialog }, "New BIOS profile…")),
    h("p", { class: "muted small-text" }, "Saved BIOS settings, checked against what the server's BIOS accepts. Configure BIOS writes only the ones that differ, with one reboot."),
    profiles.length
      ? table(["Name", "Model", "Settings", "Source", "Updated"], profiles.map((p) =>
          h("tr", { "data-bios-profile": p.name },
            h("td", {}, h("a", { href: `#/bios-profiles/${p.id}` }, p.name)),
            h("td", {}, p.model || "—"),
            h("td", {}, String(Object.keys(p.attributes).length)),
            h("td", { class: "muted" }, p.source),
            h("td", { class: "muted" }, fmtTime(p.updated_at)))))
      : h("p", { class: "muted" }, "No BIOS profiles yet."));
}

// Capture from a server, import a file, or start empty: each needs a server, whose registry the profile uses.
async function newBiosProfileDialog() {
  const hosts = await api("GET", "/hosts");
  if (!hosts.length) { toast("Add a server first: a BIOS profile is checked against its BIOS.", "error"); return; }
  const how = (value, label, help, checked = false) => h("label", { class: "inline choice" },
    h("input", { type: "radio", name: "how", value, checked }), h("span", {}, h("strong", {}, label), h("br"), h("span", { class: "muted small-text" }, help)));
  const file = h("input", { id: "bp-file", type: "file", accept: ".json,application/json" });
  const fileField = h("div", { class: "field", hidden: true }, h("label", { for: file.id }, "File"), file,
    h("p", { class: "help" }, "A JSON map of attribute → value, or a Dell Server Configuration Profile export (JSON)."));
  const body = [
    h("label", { for: "bp-name" }, "Name"), h("input", { id: "bp-name", name: "name", required: true, autocomplete: "off" }),
    h("label", { for: "bp-host" }, "Server"), h("select", { id: "bp-host", name: "host" }, hosts.map((x) => h("option", { value: x.id }, x.name))),
    h("p", { class: "help" }, "The profile is checked against this server's BIOS. Its attribute registry is read from the BMC the first time (read-only)."),
    h("fieldset", { class: "group" }, h("legend", {}, "Start from"),
      how("capture", "This server's current settings", "Every setting it reports that's a choice (not per-server text). Untick what you don't want afterwards.", true),
      how("import", "A file", "Settings the BIOS won't take, such as read-only ones and passwords, are left out."),
      how("empty", "Nothing", "Add settings one at a time.")),
    fileField,
  ];
  const { form } = openDialog("New BIOS profile", body, {
    submitLabel: "Create", wide: true,
    onSubmit: async (f) => {
      const host = f.get("host");
      const name = f.get("name").trim();
      const choice = f.get("how");
      if (choice === "capture") {
        const p = await api("POST", `/hosts/${host}/bios-profiles/capture`, { name });
        toast(`Captured ${Object.keys(p.attributes).length} settings`, "success");
        location.hash = `#/bios-profiles/${p.id}`;
        return;
      }
      const registry = await api("GET", `/hosts/${host}/bios-registry`);
      if (choice === "import") {
        if (!file.files.length) throw new Error("Choose a file to import.");
        const p = await api("POST", "/bios-profiles/import", { name, registry: registry.key, content: await file.files[0].text() });
        toast(`Imported ${Object.keys(p.attributes).length} settings`, "success");
        location.hash = `#/bios-profiles/${p.id}`;
        return;
      }
      location.hash = `#/bios-profiles/new?registry=${encodeURIComponent(registry.key)}&name=${encodeURIComponent(name)}`;
    },
  });
  form.addEventListener("change", () => { fileField.hidden = form.elements.how.value !== "import"; });
}

// ── editor: only the settings in the profile, grouped by BIOS menu; anything else can be added ──
function control(attr, value, id) {
  if (attr.type === "Enumeration") {
    return h("select", { id }, attr.values.map((v) => h("option", { value: v.name, selected: v.name === value }, v.display || v.name)));
  }
  if (attr.type === "Integer") return h("input", { id, type: "number", step: 1, min: attr.lower, max: attr.upper, value: value ?? "" });
  if (attr.type === "Boolean") return h("input", { id, type: "checkbox", checked: Boolean(value) });
  return h("input", { id, value: value ?? "", minlength: attr.min_length, maxlength: attr.max_length, autocomplete: "off" });
}
const read = (attr, el) => (attr.type === "Integer" ? Number(el.value) : attr.type === "Boolean" ? el.checked : el.value);
const initial = (attr) => attr.default ?? (attr.type === "Enumeration" ? attr.values[0]?.name : attr.type === "Integer" ? attr.lower ?? 0
  : attr.type === "Boolean" ? false : "");

export async function viewBiosProfile(app, id, query) {
  const isNew = id === "new";
  const profile = isNew ? null : await api("GET", `/bios-profiles/${id}`);
  const key = profile?.registry || query.get("registry");
  if (!key) { location.hash = "#/config-sets"; return; }
  const registry = await api("GET", `/bios-registries/${encodeURIComponent(key)}`);
  const attrs = new Map(registry.attributes.map((a) => [a.name, a]));
  const values = new Map(Object.entries(profile?.attributes || {}));
  const name = h("input", { id: "bp-edit-name", value: profile?.name || query.get("name") || "", autocomplete: "off" });
  const description = h("input", { id: "bp-edit-desc", value: profile?.description || "", autocomplete: "off" });
  const list = h("div", { class: "bios-settings" });
  const controls = new Map();
  const status = h("div");
  const count = h("span");

  function render() {
    controls.clear();
    count.replaceChildren(badge("none", `${values.size} setting${values.size === 1 ? "" : "s"}`));
    const menus = new Map();
    for (const a of registry.attributes) {  // registry order is the BIOS setup's own order
      if (!values.has(a.name)) continue;
      if (!menus.has(a.menu)) menus.set(a.menu, []);
      menus.get(a.menu).push(a);
    }
    const unknown = [...values.keys()].filter((n) => !attrs.has(n));
    mount(list,
      values.size ? null : h("p", { class: "muted" }, "No settings yet. Add the ones this profile should set; everything else is left as it is on the server."),
      ...[...menus].map(([menu, items]) => h("fieldset", { class: "group", "data-menu": menu || "Other" }, h("legend", {}, menu || "Other"),
        items.map((a) => {
          const el = control(a, values.get(a.name), `bp-${a.name}`);
          el.addEventListener("change", () => values.set(a.name, read(a, el)));
          controls.set(a.name, el);
          const error = h("p", { class: "field-error", role: "alert" });
          return h("div", { class: "bios-setting", "data-attribute": a.name },
            h("label", { for: el.id }, a.display || a.name, h("span", { class: "mono muted small-text" }, ` ${a.name}`)),
            h("div", { class: "row" }, el, h("button", { class: "small", type: "button", "aria-label": `Remove ${a.display || a.name}`,
              onclick: () => { values.delete(a.name); render(); } }, "Remove")),
            a.help ? h("p", { class: "help" }, a.help.length > 220 ? `${a.help.slice(0, 220)}…` : a.help) : null, error);
        }))),
      unknown.length ? h("p", { class: "warn-text" }, `Not in this BIOS's registry: ${unknown.join(", ")}`) : null);
  }

  const options = h("datalist", { id: "bp-attrs" });
  const refreshOptions = () => options.replaceChildren(...registry.attributes.filter((a) => !values.has(a.name))
    .map((a) => h("option", { value: a.name }, `${a.display || a.name} · ${a.menu || ""}`)));
  const add = h("input", { id: "bp-add", list: "bp-attrs", placeholder: "Search by name, e.g. LogicalProc or Virtualization", autocomplete: "off" });
  const addSetting = () => {
    const wanted = add.value.trim();
    const a = attrs.get(wanted) || registry.attributes.find((x) => (x.display || "").toLowerCase() === wanted.toLowerCase());
    if (!a) { toast(`No setting called ${wanted} in this BIOS`, "error"); return; }
    values.set(a.name, initial(a));
    add.value = "";
    render(); refreshOptions();
    controls.get(a.name)?.focus();
  };
  add.addEventListener("change", addSetting);

  async function save() {
    status.replaceChildren();
    list.querySelectorAll(".bios-setting.invalid").forEach((el) => { el.classList.remove("invalid"); el.querySelector(".field-error").textContent = ""; });
    for (const [n, el] of controls) values.set(n, read(attrs.get(n), el));
    const body = { name: name.value.trim(), description: description.value.trim(), registry: key, attributes: Object.fromEntries(values) };
    try {
      const saved = await api(isNew ? "POST" : "PUT", isNew ? "/bios-profiles" : `/bios-profiles/${id}`, body);
      toast(`Saved ${saved.name}`, "success");
      location.hash = `#/bios-profiles/${saved.id}`;
    } catch (e) {
      for (const err of e.problem?.errors || []) {
        const row = list.querySelector(`[data-attribute="${err.loc?.[err.loc.length - 1]}"]`);
        if (row) { row.classList.add("invalid"); row.querySelector(".field-error").textContent = err.msg; }
      }
      status.replaceChildren(h("p", { class: "error", role: "alert" }, e.message));
    }
  }
  const remove = () => openDialog(`Delete ${profile.name}?`, [h("p", {}, "Nothing on any server changes.")], {
    submitLabel: "Delete", submitClass: "danger", onSubmit: async () => { await api("DELETE", `/bios-profiles/${id}`); location.hash = "#/config-sets"; },
  });

  render(); refreshOptions();
  mount(app,
    pageHeader(isNew ? "New BIOS profile" : profile.name,
      [registry.model, registry.id, profile ? profile.source : null].filter(Boolean).join(" · ")),
    card({ class: "panel form-card" },
      h("div", { class: "grid two" },
        h("div", { class: "field" }, h("label", { for: name.id }, "Name"), name),
        h("div", { class: "field" }, h("label", { for: description.id }, "Description"), description)),
      h("p", { class: "muted" }, count, " Only these are written; every other BIOS setting is left as it is."),
      list,
      h("div", { class: "field" }, h("label", { for: add.id }, "Add a setting"), h("div", { class: "row" }, add, options,
        h("button", { type: "button", onclick: addSetting }, "Add"))),
      status,
      h("div", { class: "actions" },
        isNew ? null : h("button", { class: "danger-outline", onclick: remove }, "Delete"),
        h("a", { class: "button", href: "#/config-sets" }, "Back"),
        h("button", { class: "primary", onclick: save }, isNew ? "Create" : "Save"))));
}
