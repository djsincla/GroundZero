// Deploy wizard: installer image → configuration → this server's values → review (kickstart preview) → typed confirm.
// The ISO repository, config sets and per-server values stay separate; they are merged only here.
import {
  api, card, empty, errorBox, fmtBytes, h, isActive, maybe, mount, pageHeader, startJob, toast,
} from "../core.js";
import { schemaForm } from "../forms.js";

const LEGACY = "";  // "keep this host's current settings": captured from the running OS at install time

export async function viewDeploy(app, id) {
  const [host, osAccess, families, isos, sets, stored, jobs] = await Promise.all([
    api("GET", `/hosts/${id}`),
    maybe(api("GET", `/hosts/${id}/os`)),
    api("GET", "/os-families"),
    api("GET", "/isos"),
    api("GET", "/config-sets"),
    maybe(api("GET", `/hosts/${id}/host-values/esxi`)),
    api("GET", `/jobs?host_id=${id}&limit=5`),
  ]);
  const esxi = families.find((f) => f.family === "esxi");
  const images = isos.filter((i) => i.os_family === "esxi");
  const esxiSets = sets.filter((s) => s.os_family === "esxi");
  const busy = jobs.some(isActive);
  const phrase = `install ${host.name}`;

  // ── step 1: installer image ──
  const isoChoices = images.map((img, i) => h("label", { class: "choice", "data-iso": img.filename },
    h("input", { type: "radio", name: "iso", value: img.id, checked: i === 0 }),
    h("span", {}, h("strong", {}, `ESXi ${img.version} build ${img.build}`), h("br"),
      h("span", { class: "mono muted small-text" }, img.filename), " ", h("span", { class: "muted small-text" }, fmtBytes(img.size)))));
  const isoStep = step(1, "Installer image",
    images.length
      ? h("div", { class: "choices" }, isoChoices)
      : empty("No ESXi installer ISOs in the repository.", h("a", { class: "button", href: "#/isos" }, "Open ISO repository")));

  // ── step 2: configuration ──
  const preferred = esxiSets[0]?.id ?? LEGACY;
  const setSelect = h("select", { id: "d-config", name: "config" },
    esxiSets.map((s) => h("option", { value: s.id, selected: s.id === preferred }, s.name)),
    h("option", { value: LEGACY, disabled: !osAccess, selected: preferred === LEGACY },
      osAccess ? "Keep this host's current settings (copied from the running OS)" : "Keep current settings (needs OS access)"));
  const setSummary = h("div", { class: "set-summary" });
  const configStep = step(2, "Configuration",
    h("label", { for: "d-config" }, "Config set"), setSelect, setSummary,
    h("p", { class: "help" }, h("a", { href: "#/config-sets/new" }, "New config set"), " · ", h("a", { href: "#/config-sets" }, "Manage config sets")));

  // ── step 3: this server ──
  const valuesForm = schemaForm(esxi.host_values_schema, stored || { hostname: host.name, ip: osAccess?.address || "" },
    { idPrefix: "hv", where: "host_values" });
  const valuesStep = step(3, "This server", h("p", { class: "help" },
    "Per-server values. Blank overrides inherit from the config set."), valuesForm.el);

  // ── step 4: options ──
  const wipe = h("input", { type: "checkbox", id: "d-wipe", name: "wipe" });
  const ntp = h("input", { id: "d-ntp", name: "ntp", value: "pool.ntp.org" });
  const ntpWrap = h("div", {}, h("label", { for: "d-ntp" }, "NTP servers (comma separated)"), ntp);
  const optionsStep = step(4, "Options",
    h("label", { class: "inline danger-text", for: "d-wipe" }, wipe, "Overwrite the VMFS datastore on the install disk"),
    ntpWrap);

  // ── step 5: review & confirm ──
  const previewOut = h("div", { "data-role": "preview" });
  const previewBtn = h("button", { type: "button", onclick: () => preview() }, "Preview kickstart");
  const confirm = h("input", { id: "d-confirm", autocomplete: "off", oninput: () => sync() });
  const start = h("button", { class: "danger", type: "button", disabled: true, onclick: () => go() }, "Start install");
  const reviewStep = step(5, "Review and confirm",
    h("div", { class: "notice" },
      "Keeps: the install disk's VMFS datastore (unless overwritten above) and every other disk. ",
      "Replaces: the hypervisor, its VM inventory registrations and all host configuration not set here."),
    h("div", { class: "row" }, previewBtn), previewOut,
    h("label", { for: "d-confirm" }, `Type "${phrase}" to confirm`), confirm,
    h("div", { class: "actions" }, h("a", { class: "button", href: `#/hosts/${id}` }, "Cancel"), start));

  let previewed = false;
  const legacy = () => setSelect.value === LEGACY;
  const body = (confirmText) => {
    const iso = isoStep.querySelector("input[name=iso]:checked")?.value;
    const out = { confirm: confirmText, iso_id: iso, wipe_install_disk_vmfs: wipe.checked };
    if (legacy()) {
      out.ntp_servers = ntp.value.split(",").map((s) => s.trim()).filter(Boolean);
    } else {
      out.config_set_id = setSelect.value;
      out.host_values = valuesForm.value();
    }
    return out;
  };
  function sync() {
    const ready = images.length && !busy && (legacy() ? Boolean(osAccess) : previewed);
    start.disabled = !(ready && confirm.value === phrase);
  }
  function invalidate() {
    previewed = false;
    previewOut.replaceChildren();
    sync();
  }
  function renderSetSummary() {
    valuesStep.hidden = legacy();
    ntpWrap.hidden = !legacy();
    previewBtn.hidden = legacy();
    if (legacy()) {
      setSummary.replaceChildren(h("p", { class: "help" },
        "Network, NTP and the boot disk are read from the running host at install time; there is nothing to preview."));
      return;
    }
    const s = esxiSets.find((x) => x.id === setSelect.value);
    const st = s.settings;
    const disk = st.install_disk.mode === "current-boot-disk" ? "current boot disk" : `${st.install_disk.mode}: ${st.install_disk.value}`;
    setSummary.replaceChildren(h("dl", { class: "kv compact" },
      h("dt", {}, "Network"), h("dd", {}, `VLAN ${st.vlan_id || "untagged"} · ${[st.install_nic, ...st.extra_uplinks].join(" + ")} · gw ${st.gateway}`),
      h("dt", {}, "DNS / NTP"), h("dd", {}, `${st.nameservers.join(", ")} / ${st.ntp_servers.join(", ") || "none"}`),
      h("dt", {}, "Disk"), h("dd", {}, disk),
      h("dt", {}, "VMFS"), h("dd", {}, st.preserve_vmfs ? "preserved" : "overwritten"),
      h("dt", {}, "CPU override"), h("dd", {}, st.cpu_override),
      h("dt", {}, "Root password"), h("dd", {}, s.has_root_password ? "stored (hidden)" : "from OS access")),
      h("a", { href: `#/config-sets/${s.id}` }, "Edit this set"));
  }

  async function preview() {
    valuesForm.clearErrors();
    previewBtn.disabled = true;
    try {
      const p = await api("POST", `/hosts/${id}/install/preview`, body("-"));
      previewed = true;
      previewOut.replaceChildren(
        p.notes.length ? h("ul", { class: "notes" }, p.notes.map((n) => h("li", {}, n))) : null,
        h("details", { open: true }, h("summary", {}, "Generated kickstart (password hash hidden)"),
          h("pre", { class: "code-block", "data-role": "kickstart" }, p.kickstart)));
    } catch (e) {
      previewed = false;
      const placed = e.problem?.errors && valuesForm.setErrors(e.problem.errors);
      previewOut.replaceChildren(placed ? h("p", { class: "error" }, "Fix the highlighted values.") : errorBox(e));
    } finally {
      previewBtn.disabled = false;
      sync();
    }
  }

  async function go() {
    start.disabled = true;
    const job = await startJob("POST", `/hosts/${id}/install`, body(confirm.value), {
      title: `Install on ${host.name}`,
      onDone: () => window.dispatchEvent(new Event("gz:refresh")),
    });
    if (job) {
      toast("Install started", "success");
      location.hash = `#/hosts/${id}/install`;
    } else {
      sync();
    }
  }

  for (const el of [isoStep, setSelect, valuesStep, wipe, ntp]) {
    el.addEventListener("input", invalidate);
    el.addEventListener("change", invalidate);
  }
  setSelect.addEventListener("change", renderSetSummary);
  renderSetSummary();
  sync();

  mount(app, 
    pageHeader(`Deploy an OS on ${host.name}`, "Stock ISO + config set + this server's values, merged just in time."),
    busy ? h("p", { class: "notice" }, "A job is running on this host; wait for it to finish.") : null,
    h("div", { class: "wizard" }, isoStep, configStep, valuesStep, optionsStep, reviewStep));
}

function step(n, title, ...children) {
  return card({ class: "panel step", "data-step": String(n) },
    h("h2", {}, h("span", { class: "step-num" }, String(n)), title), children);
}
