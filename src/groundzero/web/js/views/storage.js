// Storage profiles: RAID volumes, controller mode, drive state and hot spares as rules (not drive ids), so one
// profile fits every server of a kind. Captured from Read storage, edited here, applied by Configure storage.
import { api, badge, card, fmtTime, h, mount, openDialog, pageHeader, showJobDrawer, table, toast } from "../core.js";

const refresh = () => window.dispatchEvent(new Event("gz:refresh"));
const RAIDS = ["RAID0", "RAID1", "RAID5", "RAID6", "RAID10", "RAID50", "RAID60"];
const KINDS = [["boot", "Boot card (BOSS, M.2)"], ["raid", "RAID controller (PERC)"], ["software", "Software RAID"], ["passthrough", "Pass-through"]];

export async function storageProfilesCard() {
  const profiles = await api("GET", "/storage-profiles");
  return card({ "data-panel": "storage-profiles" },
    h("div", { class: "row" }, h("h2", {}, "Storage profiles"), h("span", { class: "spacer" }),
      h("a", { class: "button", href: "#/storage-profiles/new" }, "New storage profile")),
    h("p", { class: "muted small-text" }, "RAID volumes, controller mode, drive state and hot spares, written as rules so one profile fits every server of a kind. Save one from a server's Storage tab, or write one here."),
    profiles.length
      ? table(["Name", "Rules", "Source", "Updated"], profiles.map((p) =>
          h("tr", { "data-storage-profile": p.name },
            h("td", {}, h("a", { href: `#/storage-profiles/${p.id}` }, p.name)),
            h("td", { class: "small-text" }, p.controllers.map(ruleWords).join("; ")),
            h("td", { class: "muted" }, p.source),
            h("td", { class: "muted" }, fmtTime(p.updated_at)))))
      : h("p", { class: "muted" }, "No storage profiles yet."));
}

const ruleWords = (c) => {
  const vols = c.volumes.map((v) => `${v.name} ${v.raid}${v.boot ? " (boot)" : ""}`);
  return `${c.kind}${c.model ? ` ${c.model}` : ""}: ${[...vols, c.mode ? `${c.mode} mode` : null,
    c.hot_spares ? `${c.hot_spares} spare(s)` : null].filter(Boolean).join(", ") || "as is"}`;
};

// ── editor ──
const select = (options, value, attrs = {}) => h("select", attrs, options.map(([v, label]) =>
  h("option", { value: v, selected: v === (value ?? "") }, label)));

export async function viewStorageProfile(app, id) {
  const isNew = id === "new";
  const profile = isNew ? { name: "", description: "", controllers: [{ kind: "raid", volumes: [], hot_spares: 0, unused_drives: "leave" }] }
    : await api("GET", `/storage-profiles/${id}`);
  const name = h("input", { id: "sp-name", value: profile.name, autocomplete: "off" });
  const description = h("input", { id: "sp-desc", value: profile.description || "", autocomplete: "off" });
  const rules = h("div", { class: "stack" });
  const status = h("div");
  const readers = [];

  function volumeRow(v, list) {
    const cells = {
      name: h("input", { value: v.name || "", "aria-label": "Volume name", maxlength: 15, size: 10 }),
      raid: select(RAIDS.map((r) => [r, r]), v.raid || "RAID1", { "aria-label": "RAID level" }),
      count: h("input", { type: "number", min: 1, value: v.drives?.count ?? "", "aria-label": "Drives", placeholder: "all", style: "width:5em" }),
      media: select([["", "any"], ["SSD", "SSD"], ["HDD", "HDD"]], v.drives?.media, { "aria-label": "Media" }),
      protocol: select([["", "any"], ["SATA", "SATA"], ["SAS", "SAS"], ["NVMe", "NVMe"]], v.drives?.protocol, { "aria-label": "Protocol" }),
      min: h("input", { type: "number", min: 0, value: v.drives?.min_gb ?? "", "aria-label": "Smallest drive (GB)", placeholder: "any", style: "width:6em" }),
      boot: h("input", { type: "radio", name: "boot-volume", checked: Boolean(v.boot), "aria-label": "Boot volume" }),
    };
    const row = h("tr", { "data-volume-rule": v.name || "" },
      ...Object.values(cells).map((c) => h("td", {}, c)),
      h("td", {}, h("button", { class: "small", type: "button", onclick: () => { row.remove(); list.delete(read); } }, "Remove")));
    const num = (el) => (el.value === "" ? null : Number(el.value));
    const read = () => ({ name: cells.name.value.trim(), raid: cells.raid.value, boot: cells.boot.checked,
      drives: { count: num(cells.count), media: cells.media.value || null, protocol: cells.protocol.value || null, min_gb: num(cells.min) } });
    list.add(read);
    return row;
  }

  let ruleCount = 0;
  function ruleCard(c) {
    const volumes = new Set();
    const uid = `rule${ruleCount++}`;
    const kind = select(KINDS, c.kind, { id: `${uid}-kind` });
    const model = h("input", { id: `${uid}-model`, value: c.model || "", placeholder: "any", autocomplete: "off" });
    const mode = select([["", "leave as is"], ["RAID", "RAID"], ["HBA", "HBA"], ["EnhancedHBA", "Enhanced HBA"]], c.mode, { id: `${uid}-mode` });
    const remove = h("input", { id: `${uid}-remove`, type: "checkbox", checked: Boolean(c.remove_other_volumes) });
    const unused = select([["leave", "leave them"], ["non-raid", "pass through (non-RAID)"], ["raid", "make RAID-capable"]], c.unused_drives || "leave", { id: `${uid}-unused` });
    const spares = h("input", { id: `${uid}-spares`, type: "number", min: 0, value: c.hot_spares || 0, style: "width:5em" });
    const body = h("tbody", {}, (c.volumes || []).map((v) => volumeRow(v, volumes)));
    const el = card({ class: "panel rule", "data-rule": c.kind },
      h("div", { class: "row" }, h("h3", {}, "Controller rule"), h("span", { class: "spacer" }),
        h("button", { class: "small", type: "button", onclick: () => { el.remove(); readers.splice(readers.indexOf(read), 1); } }, "Remove rule")),
      h("div", { class: "grid two" },
        h("div", { class: "field" }, h("label", { for: kind.id }, "Controller"), kind),
        h("div", { class: "field" }, h("label", { for: model.id }, "Model contains"), model)),
      h("div", { class: "grid two" },
        h("div", { class: "field" }, h("label", { for: mode.id }, "Mode"), mode),
        h("div", { class: "field" }, h("label", { for: spares.id }, "Global hot spares"), spares)),
      h("div", { class: "grid two" },
        h("div", { class: "field" }, h("label", { for: unused.id }, "Unused drives"), unused),
        h("div", { class: "field" }, h("label", { class: "inline", for: remove.id }, remove, "Delete volumes no rule describes (their data is lost)"))),
      h("table", { class: "table volume-rules" },
        h("thead", {}, h("tr", {}, ["Volume", "RAID", "Drives", "Media", "Protocol", "Min GB", "Boot", ""].map((t) => h("th", {}, t)))), body),
      h("button", { class: "small", type: "button", onclick: () => body.append(volumeRow({ raid: "RAID1", drives: { count: 2 } }, volumes)) }, "Add volume"));
    const read = () => ({ kind: kind.value, model: model.value.trim() || null, mode: mode.value || null,
      remove_other_volumes: remove.checked, unused_drives: unused.value, hot_spares: Number(spares.value || 0),
      volumes: [...volumes].map((fn) => fn()) });
    readers.push(read);
    return el;
  }

  mount(rules, profile.controllers.map(ruleCard));
  async function save() {
    status.replaceChildren();
    const body = { name: name.value.trim(), description: description.value.trim(), controllers: readers.map((fn) => fn()) };
    try {
      const saved = await api(isNew ? "POST" : "PUT", isNew ? "/storage-profiles" : `/storage-profiles/${id}`, body);
      toast(`Saved ${saved.name}`, "success");
      location.hash = `#/storage-profiles/${saved.id}`;
    } catch (e) {
      const errs = (e.problem?.errors || []).map((x) => h("p", { class: "error" }, `${x.loc.filter((p) => p !== "body").join(" › ")}: ${x.msg}`));
      status.replaceChildren(h("p", { class: "error", role: "alert" }, e.message), ...errs);
    }
  }
  const del = () => openDialog(`Delete ${profile.name}?`, [h("p", {}, "Nothing on any server changes.")], {
    submitLabel: "Delete", submitClass: "danger", onSubmit: async () => { await api("DELETE", `/storage-profiles/${id}`); location.hash = "#/config-sets"; },
  });
  mount(app,
    pageHeader(isNew ? "New storage profile" : profile.name, isNew ? "Rules for RAID volumes, controller mode, drive state and hot spares" : profile.source),
    card({ class: "panel form-card" },
      h("div", { class: "grid two" },
        h("div", { class: "field" }, h("label", { for: name.id }, "Name"), name),
        h("div", { class: "field" }, h("label", { for: description.id }, "Description"), description)),
      rules,
      h("button", { type: "button", onclick: () => rules.append(ruleCard({ kind: "raid", volumes: [], hot_spares: 0 })) }, "Add controller rule"),
      status,
      h("div", { class: "actions" },
        isNew ? null : h("button", { class: "danger-outline", onclick: del }, "Delete"),
        h("a", { class: "button", href: "#/config-sets" }, "Back"),
        h("button", { class: "primary", onclick: save }, isNew ? "Create" : "Save"))));
}

// ── from a host's Storage tab ──
export function captureStorageDialog(ctx) {
  openDialog("Save this layout as a storage profile", [
    h("p", { class: "muted" }, "Rules that describe this server's storage as Read storage last saw it: its RAID volumes, spares and controller modes. Nothing on the server changes."),
    h("label", { for: "sp-cap-name" }, "Name"), h("input", { id: "sp-cap-name", name: "name", required: true, autocomplete: "off" }),
  ], {
    submitLabel: "Save", onSubmit: async (f) => {
      const p = await api("POST", `/hosts/${ctx.id}/storage-profiles/capture`, { name: f.get("name").trim() });
      toast(`Saved ${p.name}`, "success");
      location.hash = `#/storage-profiles/${p.id}`;
    },
  });
}

export async function configureStorageDialog(ctx) {
  const profiles = await api("GET", "/storage-profiles");
  if (!profiles.length) { toast("Make a storage profile first: save one from this server, or write one on the Config sets page.", "error"); return; }
  const phrase = `configure storage ${ctx.host.name}`;
  const pick = select(profiles.map((p) => [p.id, p.name]), profiles[0].id, { id: "st-profile" });
  const allow = h("input", { type: "checkbox", id: "st-allow" });
  const planBox = h("div", { "data-role": "storage-plan" });
  const input = h("input", { id: "st-confirm", autocomplete: "off" });
  let plan = null;
  const { submit } = openDialog(`Configure storage on ${ctx.host.name}`, [
    h("p", { class: "muted" }, "Compares the profile with the layout Read storage last saw, and shows what would change. The layout is read again before anything is written."),
    h("label", { for: pick.id }, "Storage profile"), pick, planBox,
    h("label", { class: "inline", for: allow.id }, allow, "Allow changes to the boot volume the OS runs from (its data is lost)"),
    h("label", { for: input.id }, `Type "${phrase}" to confirm`), input,
  ], {
    submitLabel: "Apply", submitClass: "danger", wide: true,
    onSubmit: async () => {
      const job = await api("POST", `/hosts/${ctx.id}/tasks/storage.configure`,
        { params: { profile_id: pick.value, allow_boot_volume: allow.checked }, confirm: input.value || null });
      showJobDrawer(job, { title: `Configure storage on ${ctx.host.name}`, onDone: refresh });
    },
  });
  const sync = () => { submit.disabled = !plan || plan.problems.length > 0 || (plan.actions.length > 0 && input.value !== phrase); };
  async function show() {
    try {
      plan = await api("GET", `/hosts/${ctx.id}/storage-plan?profile_id=${pick.value}&allow_boot_volume=${allow.checked}`);
      mount(planBox,
        plan.problems.length ? h("div", { class: "callout fail", "data-role": "problems" }, h("strong", {}, "Can't go ahead:"),
          h("ul", {}, plan.problems.map((p) => h("li", {}, p)))) : null,
        plan.actions.length
          ? h("ul", { class: "plan" }, plan.actions.map((a) => h("li", { class: `plan-item${a.destroys_data ? " danger" : ""}`, "data-action": a.kind },
              a.destroys_data ? badge("fail", "data lost") : badge("none", "change"), " ", a.title)))
          : plan.problems.length ? null : h("p", { class: "muted" }, "Already matches: nothing to change."));
    } catch (e) { plan = null; mount(planBox, h("p", { class: "error" }, e.message)); }
    sync();
  }
  pick.addEventListener("change", show);
  allow.addEventListener("change", show);
  input.addEventListener("input", sync);
  await show();
}
