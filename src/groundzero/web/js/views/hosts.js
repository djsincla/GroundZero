// Hosts list and the tabbed host page (Pipeline · Readiness · Overview · Networking · Install · Jobs).
import { schemaForm } from "../forms.js";
import {
  age, api, badge, card, empty, fmtBytes, fmtTime, h, isActive, jobCard, jobLabel, maybe, mount, openDialog, pageHeader,
  showJobDrawer, showOutput, startJob, table, toast,
} from "../core.js";

const refresh = () => window.dispatchEvent(new Event("gz:refresh"));
const hardware = (host) => [host.vendor, host.model].filter(Boolean).join(" · ");

// ── hosts list ──
export async function viewHosts(app) {
  const [hosts, jobs] = await Promise.all([api("GET", "/hosts"), api("GET", "/jobs?limit=50")]);
  const running = new Map(jobs.filter(isActive).map((j) => [j.host_id, j]));
  const rows = await Promise.all(hosts.map(async (host) => {
    const [pre, net] = await Promise.all([
      maybe(api("GET", `/hosts/${host.id}/outputs/preflight`)),
      maybe(api("GET", `/hosts/${host.id}/outputs/os_network`)),
    ]);
    const job = running.get(host.id);
    return h("tr", { "data-host": host.name },
      h("td", {}, h("a", { href: `#/hosts/${host.id}` }, host.name)),
      h("td", { class: "mono" }, host.bmc_address),
      h("td", {}, hardware(host) || "—"),
      h("td", {}, pre ? badge(pre.overall) : badge("none", "not run")),
      h("td", {}, net ? net.product : "—"),
      h("td", {}, job ? badge("running", `${jobLabel(job)} ${Math.round(job.progress * 100)}%`) : h("span", { class: "muted" }, "idle")));
  }));
  mount(app, 
    pageHeader("Hosts", "Servers GroundZero manages through their BMC.",
      h("button", { class: "primary", onclick: addHostDialog }, "Add host")),
    card({}, hosts.length
      ? table(["Name", "BMC", "Hardware", "Holodeck preflight", "Installed OS", "Activity"], rows)
      : empty("No hosts yet. Add a server by its BMC address.")));
}

function addHostDialog() {
  openDialog("Add host", [
    h("label", { for: "f-bmc" }, "BMC address"), h("input", { id: "f-bmc", name: "bmc", required: true, placeholder: "10.0.0.50" }),
    h("label", { for: "f-name" }, "Name"), h("input", { id: "f-name", name: "name", placeholder: "esxi1" }),
    h("label", { for: "f-user" }, "BMC username"), h("input", { id: "f-user", name: "user", value: "root", required: true }),
    h("label", { for: "f-pass" }, "BMC password"), h("input", { id: "f-pass", name: "pass", type: "password", required: true }),
    h("p", { class: "help" }, "The password is encrypted at rest and never shown again. The BMC's TLS certificate is pinned on first contact."),
  ], {
    submitLabel: "Add",
    onSubmit: async (f) => {
      const host = await api("POST", "/hosts", { bmc_address: f.get("bmc"), name: f.get("name") || null,
        username: f.get("user"), password: f.get("pass") });
      toast(`Added ${host.name}`, "success");
      refresh();
    },
  });
}

// ── host page ──
const TABS = [["pipeline", "Pipeline"], ["readiness", "Readiness"], ["overview", "Overview"], ["network", "Networking"],
  ["install", "Install"], ["jobs", "Jobs"]];
const TAB_ALIASES = { preflight: "readiness" };  // Preflight is part of Readiness now; old links still land

export async function viewHost(app, id, tab = "pipeline") {
  tab = TAB_ALIASES[tab] || tab;
  const host = await api("GET", `/hosts/${id}`);
  const [pre, osAccess, net, install, jobs, certs] = await Promise.all([
    maybe(api("GET", `/hosts/${id}/outputs/preflight`)),
    maybe(api("GET", `/hosts/${id}/os`)),
    maybe(api("GET", `/hosts/${id}/outputs/os_network`)),
    maybe(api("GET", `/hosts/${id}/outputs/install`)),
    api("GET", `/jobs?host_id=${id}&limit=20`),
    api("GET", `/hosts/${id}/certificates`),
  ]);
  const pipeline = await api("GET", `/hosts/${id}/pipeline`);
  const readiness = tab === "readiness" ? await maybe(api("GET", `/hosts/${id}/outputs/readiness`)) : null;
  const active = jobs.find(isActive);
  const busy = Boolean(active);
  const ctx = { host, id, pre, osAccess, net, install, jobs, certs, active, busy, pipeline, readiness,
    lastInstallJob: jobs.find((j) => j.task === "os.custom" || j.task === "os.reimage") };

  const tabs = h("nav", { class: "tabs", "aria-label": "Host sections" }, TABS.map(([key, label]) =>
    h("a", { href: `#/hosts/${id}/${key}`, class: key === tab ? "active" : null, "aria-current": key === tab ? "page" : null }, label)));

  const body = {
    pipeline: pipelineTab, readiness: readinessTab, overview: overviewTab, network: networkTab, install: installTab,
    jobs: jobsTab,
  }[tab] || pipelineTab;

  // The header offers the recommended next step (the Pipeline tab shows it as a card instead). Reinstalling the OS
  // lives on the Install tab: the page's most prominent button should never be its most destructive one.
  const nextTask = pipeline.next.task && pipelineTasks(pipeline)[pipeline.next.task];
  const headerAction = tab !== "pipeline" && !busy && nextTask
    ? taskButton(ctx, nextTask, { primary: true, label: `Next: ${pipeline.next.title}` }) : null;

  mount(app, 
    pageHeader(host.name, [hardware(host), host.bmc_address].filter(Boolean).join(" · "), headerAction),
    tabs,
    active ? card({ class: "panel running" }, h("h2", {}, "Running"), jobCard(active, { onDone: refresh })) : null,
    body(ctx));
}

// ── pipeline: bare metal → OS → readiness → prep → Holodeck; each task's output feeds the next ──
const STATE_BADGE = { done: "pass", running: "running", failed: "fail", stale: "warn", blocked: "unknown",
  ready: "none", planned: "none" };
const STATE_LABEL = { done: "done", running: "running", failed: "failed", stale: "out of date", blocked: "blocked",
  ready: "ready", planned: "coming" };
const stateBadge = (state) => badge(STATE_BADGE[state] || "none", STATE_LABEL[state] || state);

function runTask(ctx, task) {
  const { id, host } = ctx;
  if (task.id === "os.custom") { location.hash = `#/hosts/${id}/deploy`; return; }
  if (task.id === "os.reimage") { location.hash = `#/hosts/${id}/deploy?mode=keep`; return; }
  if (task.id === "os.capture") { captureDialog(host); return; }
  if (task.id === "holodeck.router") { holorouterDialog(ctx); return; }
  if (task.id === "appliance.deploy") { applianceDialog(ctx); return; }
  startJob("POST", `/hosts/${id}/tasks/${task.id}`, {}, { onDone: refresh });
}

function taskButton(ctx, task, { primary = false, label = null } = {}) {
  if (!task.available || task.state === "running") return null;
  const blocked = task.state === "blocked";
  const text = label || { done: "Run again", stale: "Run again", failed: "Retry" }[task.state] || "Run";
  return h("button", {
    class: [primary ? "primary" : "small", task.destructive && !primary ? "danger-outline" : ""].join(" ").trim(),
    disabled: ctx.busy || blocked, title: blocked ? task.blocked_by.join("; ") : null,
    "data-run": task.id, onclick: () => runTask(ctx, task),
  }, text);
}

async function openJob(jobId) {
  try { showJobDrawer(await api("GET", `/jobs/${jobId}`), { onDone: refresh }); } catch (e) { toast(e.message, "error"); }
}

const pipelineTasks = (pipeline) => Object.fromEntries(pipeline.stages.flatMap((s) => s.tasks).map((t) => [t.id, t]));

function lastRun(ctx, last) {
  const open = (e) => { e.preventDefault(); openJob(last.id); };
  const link = h("a", { href: `#/hosts/${ctx.id}/pipeline`, onclick: open }, last.status);
  const when = last.finished_at ? [" · ", age(last.finished_at)]
    : ctx.active?.id === last.id && ctx.active.started_at ? [" · started ", age(ctx.active.started_at)] : null;
  return h("p", { class: "small-text muted" }, "Last run: ", link, when);
}

// Tasks whose parameters have their own screens (the install wizard, capture, prep, Holorouter dialogs).
const CUSTOM_RUN = new Set(["os.custom", "os.reimage", "os.capture", "host.prep", "holodeck.router", "appliance.deploy"]);

function optionsButton(ctx, task) {
  const props = Object.keys(task.params_schema?.properties || {});
  if (!task.available || CUSTOM_RUN.has(task.id) || !props.length) return null;
  return h("button", { class: "small", disabled: ctx.busy || task.state === "blocked" || task.state === "running",
    "data-options": task.id, onclick: () => optionsDialog(ctx, task) }, "Options…");
}

// Run a task with chosen parameters: the form is generated from the task's JSON Schema.
function optionsDialog(ctx, task) {
  const form = schemaForm(task.params_schema, {}, { idPrefix: `opt-${task.id.replace(/\W/g, "-")}`, where: "params" });
  openDialog(`${task.title}: options`, [h("p", { class: "muted" }, task.description), form.el], {
    submitLabel: "Run", wide: true,
    onSubmit: async () => {
      form.clearErrors();
      try {
        const job = await api("POST", `/hosts/${ctx.id}/tasks/${task.id}`, { params: form.value() });
        showJobDrawer(job, { onDone: refresh });
      } catch (e) {
        if (e.problem?.errors && form.setErrors(e.problem.errors)) throw new Error("Fix the highlighted values.");
        throw e;
      }
    },
  });
}

// Outputs of one step are inputs of the next: show both directions on every task.
function flowRow(ctx, task) {
  const uses = task.inputs.map((i) => {
    const label = i.from_title && i.status !== "missing" ? `${i.title} · ${i.from_title}` : i.title;
    const attrs = { class: `flow-chip ${i.status}${i.required ? "" : " optional"}`, "data-input": i.kind, "data-status": i.status,
      title: i.status === "missing" ? `Missing: run “${i.from_title || "set OS access"}” first`
        : i.status === "stale" ? "Out of date: the OS was reinstalled since" : `From ${i.from_title || "this host"}` };
    if (i.status === "missing" || !i.from_task) return h("span", attrs, label);
    return h("button", { ...attrs, type: "button", onclick: () => showOutput(ctx.id, i.kind, `${i.title} (from ${i.from_title})`) },
      label, i.produced_at ? [" · ", age(i.produced_at)] : null);
  });
  const seen = new Set();
  const feeds = task.feeds.filter((f) => !seen.has(f.task) && seen.add(f.task)).map((f) =>
    h("button", { type: "button", class: "flow-chip feed", "data-feeds": f.task, onclick: () => {
      const row = document.querySelector(`[data-task="${f.task}"]`);
      row?.scrollIntoView({ behavior: "smooth", block: "center" });
      row?.classList.add("flash");
      setTimeout(() => row?.classList.remove("flash"), 1200);
    } }, f.title));
  if (!uses.length && !feeds.length) return null;
  return h("div", { class: "flow small-text", "data-role": "flow" },
    uses.length ? h("span", { class: "flow-group" }, h("span", { class: "muted" }, "Uses "), uses) : null,
    feeds.length ? h("span", { class: "flow-group" }, h("span", { class: "muted" }, "Feeds → "), feeds) : null);
}

function taskRow(ctx, task) {
  const last = task.last_job;
  return h("li", { class: `task ${task.state}`, "data-task": task.id, "data-state": task.state },
    h("div", { class: "row" },
      h("strong", {}, task.title),
      task.optional ? h("span", { class: "chip" }, "optional") : null,
      task.destructive ? h("span", { class: "chip danger-chip" }, "changes the server") : null,
      stateBadge(task.state), h("span", { class: "spacer" }), optionsButton(ctx, task), taskButton(ctx, task)),
    h("p", { class: "muted small-text task-desc" }, task.description),
    task.state === "failed" && last?.error ? h("p", { class: "error small-text", "data-role": "error" }, last.error) : null,
    task.output ? h("p", { class: "task-output", "data-role": "output" }, "→ ", task.output.summary,
      task.output.fresh ? null : h("span", { class: "warn-text" }, " (from before the OS was reinstalled)"),
      task.id === "host.assess" ? [" · ", h("a", { href: `#/hosts/${ctx.id}/readiness` }, "View report")]
        : [" · ", h("a", { href: `#/hosts/${ctx.id}/pipeline`, "data-view-output": task.produces,
            onclick: (e) => { e.preventDefault(); showOutput(ctx.id, task.output.kind, `${task.title}: output`); } }, "View output")]) : null,
    flowRow(ctx, task),
    task.state === "blocked" && task.blocked_by.length
      ? h("p", { class: "small-text blocked-by" }, "Needs: ", task.blocked_by.join("; ")) : null,
    last ? lastRun(ctx, last) : null);
}

function pipelineTab(ctx) {
  const { pipeline } = ctx;
  const next = pipeline.next;
  const nextTask = next.task ? pipelineTasks(pipeline)[next.task] : null;
  return [
    // While a job runs, the Running card above already says what is happening: no "next step" until it ends.
    ctx.active ? null : card({ class: "panel next-step", "data-role": "next-step" },
      h("div", { class: "row" },
        h("div", { class: "grow" }, h("p", { class: "eyebrow" }, "Next step"), h("h2", {}, next.title),
          h("p", { class: "muted" }, next.reason)),
        nextTask ? taskButton(ctx, nextTask, { primary: true, label: next.title }) : null)),
    card({},
      h("ol", { class: "pipeline" }, pipeline.stages.map((stage) =>
        h("li", { class: `stage ${stage.state}`, "data-stage": stage.id },
          h("div", { class: "stage-head" }, h("span", { class: "stage-dot", "aria-hidden": "true" }),
            h("h3", {}, stage.title), stateBadge(stage.state)),
          h("ul", { class: "stage-tasks" }, stage.tasks.map((t) => taskRow(ctx, t))))))),
  ];
}

// ── readiness: checks, the datastore proposal and the planned fixes (applied by "Prepare host") ──
function readinessTab(ctx) {
  const { id, readiness: r, busy } = ctx;
  const assess = () => startJob("POST", `/hosts/${id}/tasks/host.assess`, {}, { onDone: refresh });
  const header = h("div", { class: "row" }, h("h2", {}, "Holodeck readiness"), r ? badge(r.ready ? "pass" : "fail", r.ready ? "ready" : "not ready") : null,
    h("span", { class: "spacer" }), h("button", { onclick: assess, disabled: busy }, r ? "Assess again" : "Assess now"));
  if (!r) {
    return [card({ "data-panel": "readiness" }, header, h("p", { class: "muted" },
      "Not assessed yet. The assessment reads the installed OS (read-only) and plans what Holodeck still needs.")),
    preflightPanel(ctx)];
  }
  const s = r.storage;
  const storageText = {
    existing: `Holodeck will use the existing flash datastore ${s.datastore}: ${Math.round(s.free_gb).toLocaleString()} GB free of ${Math.round(s.capacity_gb).toLocaleString()} GB.`,
    format: `Proposed: create datastore “${s.datastore}” on ${s.disk_label} (${Math.round(s.capacity_gb).toLocaleString()} GB). This erases the disk; you'll confirm by typing a phrase.`,
    none: s.reason,
  }[s.kind];
  const prepActions = r.plan.filter((a) => a.task === "host.prep");
  const boxes = new Map();
  const applyBtn = h("button", { class: "primary", disabled: busy || !prepActions.length, onclick: () => applyDialog(ctx, prepActions, boxes) },
    "Apply selected fixes…");
  const actionRow = (a) => {
    const prep = a.task === "host.prep";
    const box = prep ? h("input", { type: "checkbox", checked: a.recommended, disabled: busy, "aria-label": a.title }) : null;
    if (box) boxes.set(a.check, box);
    return h("li", { class: `plan-item${a.destructive ? " destructive" : ""}`, "data-action": a.id, "data-check": a.check },
      h("div", { class: "row" },
        prep ? h("label", { class: "inline" }, box, h("strong", {}, a.title)) : h("strong", {}, a.title),
        a.destructive ? h("span", { class: "chip danger-chip" }, "erases a disk") : null,
        a.recommended ? null : h("span", { class: "chip" }, "optional"),
        h("span", { class: "spacer" }),
        prep ? null : h("button", { class: "small", disabled: busy, "data-run": a.task,
          onclick: () => startJob("POST", `/hosts/${id}/tasks/${a.task}`, {}, { onDone: refresh }) }, "Run test")),
      h("p", { class: "muted small-text" }, a.why));
  };
  const planList = r.plan.length
    ? h("ul", { class: "plan" }, r.plan.map(actionRow))
    : h("p", { class: "muted" }, "Nothing to fix.");
  return [
    card({ "data-panel": "readiness" }, header,
      h("p", { class: "muted" }, `${r.variant_title} · ${r.esxi} · assessed `, age(r.generated_at),
        ` · ${r.summary.passed} passed, ${r.summary.warnings} warnings, ${r.summary.failed} to fix, ${r.summary.unknown} not yet verified`),
      h("div", { class: `storage-proposal ${s.kind}`, "data-role": "storage" }, h("h3", {}, "Holodeck datastore"), h("p", {}, storageText))),
    card({}, h("h2", {}, "Checks"),
      table(["", "Check", "Observed", "Required", "What to do"], r.checks.map((c) =>
        h("tr", { "data-check": c.id }, h("td", {}, badge(c.status)), h("td", {}, c.title), h("td", {}, c.observed),
          h("td", { class: "muted" }, c.required), h("td", {}, c.remediation || ""))))),
    card({ "data-panel": "plan" },
      h("div", { class: "row" }, h("h2", {}, "Planned fixes"), h("span", { class: "spacer" }), prepActions.length ? applyBtn : null),
      h("p", { class: "muted small-text" }, "Each fix changes only what is listed, checks the live state first, and is skipped if already done. GroundZero re-assesses afterwards."),
      planList),
    preflightPanel(ctx),
  ];
}

// A typed confirmation that only appears (and is only required) when "replace" is ticked.
function replaceControl(vmName) {
  const box = h("input", { type: "checkbox", id: "rep-box" });
  const phrase = () => `replace ${vmName()}`;
  const label = h("label", { for: "rep-confirm" });
  const input = h("input", { id: "rep-confirm", autocomplete: "off" });
  const wrap = h("div", { hidden: true, "data-role": "replace-confirm" }, label, input);
  const sync = () => { wrap.hidden = !box.checked; label.textContent = `Type "${phrase()}" to confirm`; };
  box.addEventListener("change", sync);
  return {
    el: h("div", {}, h("label", { class: "inline danger-text", for: "rep-box" }, box,
      "Replace an existing VM of this name (it is deleted and deployed fresh; appliances apply their settings on first boot only)"), wrap),
    checked: () => box.checked,
    confirm: () => (box.checked ? input.value : null),
    sync,
  };
}

// Deploy Holorouter: a HoloRouter appliance profile plus this host's own values (IP, hostname).
async function holorouterDialog(ctx) {
  const { id, host } = ctx;
  const [families, profiles, stored, images] = await Promise.all([
    api("GET", "/os-families"), api("GET", "/appliance-profiles"), maybe(api("GET", `/hosts/${id}/host-values/holodeck`)),
    api("GET", "/images"),
  ]);
  const holodeck = families.find((f) => f.family === "holodeck");
  const choices = profiles.filter((p) => p.product === "HoloRouter");
  const image = images.filter((i) => i.os_family === "holorouter").sort((a, b) => (b.version || "").localeCompare(a.version || ""))[0];
  if (!choices.length || !image) {
    openDialog("Deploy Holorouter", [h("p", {}, !image
      ? "Put the Holorouter OVA in the image repository first (Images page)."
      : "Create a HoloRouter appliance profile first (Config sets → New appliance profile).")],
      { submitLabel: "OK", onSubmit: async () => {} });
    return;
  }
  const select = h("select", { id: "hr-profile" }, choices.map((p) => h("option", { value: p.id }, p.name)));
  const values = schemaForm(holodeck.host_values_schema, stored || {}, { idPrefix: "hr", where: "host_values" });
  const missing = h("p", { class: "notice" });
  const check = () => {
    const p = choices.find((c) => c.id === select.value);
    missing.hidden = p.secrets_set.includes("network.password");
    missing.replaceChildren("This profile has no Holorouter password yet. ",
      h("a", { href: `#/appliance-profiles/${p.id}` }, "Set it in the profile"), ".");
  };
  select.addEventListener("change", check);
  check();
  const vmName = () => `${values.value().instance_id || "holo1"}-holorouter`;
  const replace = replaceControl(vmName);
  values.el.addEventListener("input", replace.sync);
  openDialog(`Deploy the Holorouter on ${host.name}`, [
    h("p", { class: "muted" }, `Image: ${image.filename} (${fmtBytes(image.size)}). It is uploaded from this machine to the host; over a VPN this can take hours (SSL mode is much faster than IPsec, see Info).`),
    h("label", { for: "hr-profile" }, "HoloRouter profile"), select, missing,
    h("h3", {}, "This host"), values.el, replace.el,
  ], {
    submitLabel: "Deploy", wide: true,
    onSubmit: async () => {
      values.clearErrors();
      try {
        await api("PUT", `/hosts/${id}/host-values/holodeck`, values.value());
      } catch (e) {
        if (e.problem?.errors && values.setErrors(e.problem.errors)) throw new Error("Fix the highlighted values.");
        throw e;
      }
      const job = await api("POST", `/hosts/${id}/tasks/holodeck.router`,
        { params: { profile_id: select.value, replace: replace.checked() }, confirm: replace.confirm() });
      showJobDrawer(job, { title: `Deploy the Holorouter on ${host.name}`, onDone: refresh });
    },
  });
  replace.sync();
}

// Deploy any OVA: image → profile → VM name, datastore, networks and value overrides (form from the OVA).
async function applianceDialog(ctx) {
  const { id, host } = ctx;
  const [images, profiles, network, storage] = await Promise.all([
    api("GET", "/images"), api("GET", "/appliance-profiles"),
    maybe(api("GET", `/hosts/${id}/outputs/os_network`)), maybe(api("GET", `/hosts/${id}/outputs/os_storage`)),
  ]);
  const ovas = images.filter((i) => i.kind === "ova");
  if (!ovas.length) {
    openDialog("Deploy appliance", [h("p", {}, "Put an OVA in the image repository first (Images page).")],
      { submitLabel: "OK", onSubmit: async () => {} });
    return;
  }
  const portgroups = (network?.portgroups || []).map((p) => p.name).sort();
  const datastores = (storage?.datastores || []).filter((d) => d.type === "VMFS");
  const imageSelect = h("select", { id: "ad-image" }, ovas.map((i) =>
    h("option", { value: i.id }, `${i.product || i.filename} ${i.version || ""}`)));
  const profileSelect = h("select", { id: "ad-profile" });
  const vm = h("input", { id: "ad-vm", required: true, autocomplete: "off" });
  const ds = datastores.length
    ? h("select", { id: "ad-ds" }, datastores.map((d) => h("option", { value: d.name },
        `${d.name} (${Math.round(d.free_gb || 0).toLocaleString()} GB free)`)))
    : h("input", { id: "ad-ds", placeholder: "datastore name" });
  const netSlot = h("div");
  const formSlot = h("div");
  let form = null;
  let secretKeys = [];
  let netInputs = {};
  const replace = replaceControl(() => vm.value.trim());
  vm.addEventListener("input", replace.sync);

  async function load() {
    const image = ovas.find((i) => i.id === imageSelect.value);
    const mine = profiles.filter((p) => p.product === image.product);
    profileSelect.replaceChildren(h("option", { value: "" }, mine.length ? "No profile: values below only" : "No profiles for this OVA"),
      mine.map((p) => h("option", { value: p.id }, p.name)));
    if (mine.length) profileSelect.value = mine[0].id;
    if (!vm.value) vm.value = (image.product || "appliance").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    await render();
  }
  async function render() {
    const info = await api("GET", `/images/${imageSelect.value}/descriptor`);
    const profile = profiles.find((p) => p.id === profileSelect.value);
    secretKeys = info.schema["x-secret-fields"] || [];
    form = schemaForm(info.schema, profile?.values || {}, { idPrefix: "ad" });
    for (const key of secretKeys) {
      const input = form.el.querySelector(`[data-field="${CSS.escape(key)}"] input`);
      if (input && profile?.secrets_set.includes(key)) input.placeholder = "from the profile: leave blank to keep";
    }
    formSlot.replaceChildren(h("h3", {}, "Values"), h("p", { class: "help" }, "Prefilled from the profile; what you change here applies to this deployment only."), form.el);
    netInputs = {};
    netSlot.replaceChildren(h("h3", {}, "Networks"), ...info.descriptor.networks.map((n) => {
      const current = profile?.networks?.[n.name] || "";
      const input = portgroups.length
        ? h("select", { id: `ad-net-${n.name.replace(/\W/g, "-")}`, "data-network": n.name },
            h("option", { value: "" }, "choose a port group"), portgroups.map((pg) => h("option", { value: pg, selected: pg === current }, pg)))
        : h("input", { id: `ad-net-${n.name.replace(/\W/g, "-")}`, value: current, placeholder: "port group", "data-network": n.name });
      netInputs[n.name] = input;
      return h("div", { class: "field" }, h("label", { for: input.id }, n.name), input);
    }));
  }
  imageSelect.addEventListener("change", load);
  profileSelect.addEventListener("change", render);
  await load();

  openDialog(`Deploy an appliance on ${host.name}`, [
    h("div", { class: "grid two" },
      h("div", { class: "field" }, h("label", { for: "ad-image" }, "OVA"), imageSelect),
      h("div", { class: "field" }, h("label", { for: "ad-profile" }, "Profile"), profileSelect),
      h("div", { class: "field" }, h("label", { for: "ad-vm" }, "VM name"), vm),
      h("div", { class: "field" }, h("label", { for: "ad-ds" }, "Datastore"), ds)),
    netSlot, formSlot, replace.el,
  ], {
    submitLabel: "Deploy", wide: true,
    onSubmit: async () => {
      form.clearErrors();
      const profile = profiles.find((p) => p.id === profileSelect.value);
      const values = {};
      const secrets = {};
      for (const [k, v] of Object.entries(form.value())) {
        if (secretKeys.includes(k)) { if (v) secrets[k] = v; continue; }
        if (v === null || v === undefined || v === "") continue;
        if (profile && JSON.stringify(profile.values[k]) === JSON.stringify(v)) continue;  // unchanged
        values[k] = v;
      }
      const networks = Object.fromEntries(Object.entries(netInputs).map(([k, i]) => [k, i.value]).filter(([, v]) => v));
      const params = { image_id: imageSelect.value, profile_id: profileSelect.value || null, vm_name: vm.value.trim(),
        datastore: ds.value || null, values, secrets, networks, replace: replace.checked() };
      try {
        const job = await api("POST", `/hosts/${id}/tasks/appliance.deploy`, { params, confirm: replace.confirm() });
        showJobDrawer(job, { title: `Deploy ${params.vm_name} on ${host.name}`, onDone: refresh });
      } catch (e) {
        const errors = (e.problem?.errors || []).filter((x) => x.loc[0] === "values")  // checked against the OVA
          .map((x) => ({ ...x, loc: x.loc.slice(1) }));
        if (errors.length) form.setErrors(errors);
        throw e;
      }
    },
  });
  replace.sync();
}

// Confirm exactly what will change on the server; erasing a disk needs its typed phrase.
function applyDialog(ctx, actions, boxes) {
  const chosen = actions.filter((a) => boxes.get(a.check)?.checked);
  if (!chosen.length) { toast("Select at least one fix", "error"); return; }
  const destructive = chosen.find((a) => a.destructive);
  const phrase = destructive?.confirm_phrase;
  const input = phrase ? h("input", { id: "prep-confirm", autocomplete: "off" }) : null;
  const { submit } = openDialog(`Apply ${chosen.length} fix${chosen.length === 1 ? "" : "es"} on ${ctx.host.name}`, [
    h("p", {}, "GroundZero will make these changes on the host:"),
    h("ul", { class: "change-list" }, chosen.map((a) => h("li", { class: a.destructive ? "danger-text" : null }, a.title))),
    destructive ? h("div", { class: "notice" }, `${destructive.title} erases everything on that disk.`) : null,
    phrase ? [h("label", { for: "prep-confirm" }, `Type "${phrase}" to confirm`), input] : null,
  ], {
    submitLabel: "Apply", submitClass: destructive ? "danger" : "primary", wide: true,
    onSubmit: async () => {
      const job = await api("POST", `/hosts/${ctx.id}/tasks/host.prep`,
        { params: { checks: chosen.map((a) => a.check) }, confirm: input ? input.value : null });
      showJobDrawer(job, { title: `Prepare ${ctx.host.name}`, onDone: refresh });
    },
  });
  if (input) {
    submit.disabled = true;
    input.addEventListener("input", () => { submit.disabled = input.value !== phrase; });
  }
}

function overviewTab(ctx) {
  const { host, id, pre, osAccess, net, install, busy, certs } = ctx;
  const runPreflight = () => startJob("POST", `/hosts/${id}/tasks/preflight`, {}, { onDone: refresh });
  return h("div", { class: "cards" },
    card({ "data-card": "hardware" },
      h("h2", {}, "Hardware"),
      h("dl", { class: "kv" },
        h("dt", {}, "Model"), h("dd", {}, hardware(host) || "unknown until inventory or preflight runs"),
        h("dt", {}, "BMC"), h("dd", { class: "mono" }, host.bmc_address),
        h("dt", {}, "BMC user"), h("dd", {}, host.username),
        h("dt", {}, "Added"), h("dd", {}, fmtTime(host.created_at)))),
    card({ "data-card": "preflight" },
      h("h2", {}, "Holodeck preflight"),
      pre
        ? h("p", {}, badge(pre.overall), " ", `${pre.summary.passed} passed, ${pre.summary.warnings} warnings, ${pre.summary.failed} failed`)
        : h("p", { class: "muted" }, "Not run yet. Preflight only reads from the BMC."),
      h("div", { class: "row" },
        h("button", { onclick: runPreflight, disabled: busy }, pre ? "Run again" : "Run preflight"),
        pre ? h("a", { href: `#/hosts/${id}/readiness` }, "Details") : null)),
    card({ "data-card": "os" },
      h("h2", {}, "Installed OS"),
      osAccess
        ? h("p", {}, net ? net.product : "Not read yet", h("br"), h("span", { class: "mono muted" }, osAccess.address))
        : h("p", { class: "muted" }, "Not configured. Set OS access to read and capture the running hypervisor."),
      installSummary(install, ctx.lastInstallJob, { compact: true }),
      h("div", { class: "row" }, h("a", { href: `#/hosts/${id}/network` }, "Networking"), h("a", { href: `#/hosts/${id}/install` }, "Install history"))),
    certificatesCard(id, certs),
    card({ "data-card": "danger", class: "panel danger-zone" },
      h("h2", {}, "Remove host"),
      h("p", { class: "muted" }, "Forgets the host, its credentials and its history in GroundZero. Nothing on the server changes."),
      h("button", { class: "danger-outline", disabled: busy, onclick: () => removeHostDialog(host) }, "Remove host…")));
}

function certificatesCard(id, certs) {
  const retrust = (role) => openDialog(`Re-trust the ${role.toUpperCase()} certificate`, [
    h("p", {}, "Only do this after a legitimate change, such as a reinstall or a renewed certificate. ",
      "GroundZero will pin whatever certificate the server presents right now."),
  ], {
    submitLabel: "Trust new certificate", submitClass: "danger",
    onSubmit: async () => {
      const c = await api("POST", `/hosts/${id}/certificates/${role}/trust`);
      toast(`Pinned ${c.fingerprint.slice(0, 23)}…`, "success");
      refresh();
    },
  });
  return card({ "data-card": "certificates" },
    h("h2", {}, "Trusted certificates"),
    h("p", { class: "help" }, "Pinned on first contact. Credentials are only ever sent to these certificates."),
    certs.length
      ? h("ul", { class: "plain" }, certs.map((c) => h("li", { "data-cert": c.role },
          h("div", { class: "row" }, h("strong", {}, c.role.toUpperCase()), h("span", { class: "mono muted" }, c.address),
            h("span", { class: "spacer" }), h("button", { class: "small", onclick: () => retrust(c.role) }, "Re-trust…")),
          h("div", { class: "mono small-text fingerprint" }, c.fingerprint))))
      : h("p", { class: "muted" }, "None yet (simulation mode, or not contacted yet)."));
}

function removeHostDialog(host) {
  const submit = { el: null };
  const input = h("input", { id: "rm-confirm", name: "confirm", autocomplete: "off",
    oninput: (e) => { submit.el.disabled = e.target.value !== host.name; } });
  const { submit: btn } = openDialog(`Remove ${host.name}`, [
    h("p", {}, "This removes the host and its job history from GroundZero. The server itself is not touched."),
    h("label", { for: "rm-confirm" }, `Type "${host.name}" to confirm`), input,
  ], {
    submitLabel: "Remove", submitClass: "danger",
    onSubmit: async () => {
      await api("DELETE", `/hosts/${host.id}`);
      toast(`Removed ${host.name}`, "success");
      location.hash = "#/";
    },
  });
  submit.el = btn;
  btn.disabled = true;
}

// Hardware preflight (BMC, read-only): shown under the readiness report, which builds on it.
function preflightPanel({ id, pre, busy }) {
  const run = () => startJob("POST", `/hosts/${id}/tasks/preflight`, {}, { onDone: refresh });
  const header = h("div", { class: "row" }, h("h2", {}, "Hardware preflight"),
    pre ? badge(pre.overall) : null, h("span", { class: "spacer" }),
    h("button", { onclick: run, disabled: busy }, pre ? "Run again" : "Run preflight"));
  if (!pre) return card({ "data-panel": "preflight" }, header, h("p", { class: "muted" }, "Not run yet. Preflight is read-only."));
  const s = pre.summary;
  return card({ "data-panel": "preflight" }, header,
    h("p", { class: "muted" }, `${pre.variant_title} · checked `, age(pre.generated_at),
      ` · ${s.passed} passed, ${s.warnings} warnings, ${s.failed} failed, ${s.unknown} unknown`),
    table(["", "Check", "Observed", "Required", "What to do"], pre.checks.map((c) =>
      h("tr", { "data-check": c.id }, h("td", {}, badge(c.status)), h("td", {}, c.title), h("td", {}, c.observed),
        h("td", { class: "muted" }, c.required), h("td", {}, c.remediation || "")))));
}

function networkTab({ id, host, osAccess, net, busy }) {
  const read = () => startJob("POST", `/hosts/${id}/tasks/os.read`, {}, { onDone: refresh });
  const header = h("div", { class: "row" }, h("h2", {}, "ESXi networking"), h("span", { class: "spacer" }),
    osAccess ? h("button", { onclick: read, disabled: busy }, net ? "Read again" : "Read now") : null,
    osAccess ? h("button", { onclick: () => captureDialog(host), disabled: busy }, "Capture config set…") : null,
    h("button", { onclick: () => osAccessDialog(id, osAccess) }, osAccess ? "Change OS access" : "Set OS access"));
  if (!net) return card({ "data-panel": "network" }, header, h("p", { class: "muted" },
    osAccess ? "Not read yet." : "Tell GroundZero how to reach the installed hypervisor to read its network."));
  const pgs = Object.fromEntries(net.portgroups.map((p) => [p.name, p]));
  return card({ "data-panel": "network" }, header,
    h("p", { class: "muted" }, `${net.product} · gateway ${net.default_gateway || "—"} · DNS ${net.dns_servers.join(", ") || "—"} · NTP ${net.ntp_servers.join(", ") || "none"}`),
    h("h3", {}, "VMkernel interfaces"),
    table(["vmk", "IP", "Port group", "VLAN", "Active uplinks", "MTU"], net.vmkernel.map((v) => {
      const pg = pgs[v.portgroup] || {};
      return h("tr", {}, h("td", {}, v.device), h("td", { class: "mono" }, v.dhcp ? "dhcp" : `${v.ip}/${v.netmask}`),
        h("td", {}, v.portgroup || "—"), h("td", {}, String(pg.vlan_id ?? "—")),
        h("td", {}, (pg.active_uplinks || []).join(", ")), h("td", {}, String(v.mtu ?? "—")));
    })),
    h("h3", {}, "Physical NICs"),
    table(["vmnic", "Speed", "Switch port", "MAC"], net.physical_nics.map((n) =>
      h("tr", {}, h("td", {}, n.device), h("td", {}, n.speed_mbps ? `${n.speed_mbps / 1000} GbE` : "down"),
        h("td", {}, n.switch ? `${n.switch} ${n.switch_port}` : "—"), h("td", { class: "mono" }, n.mac || "—")))),
    h("h3", {}, "Virtual switches"),
    table(["vSwitch", "MTU", "Uplinks", "Port groups"], net.vswitches.map((vs) =>
      h("tr", {}, h("td", {}, vs.name), h("td", {}, String(vs.mtu)), h("td", {}, vs.uplinks.join(", ")),
        h("td", {}, vs.portgroups.join(", "))))));
}

function osAccessDialog(id, current) {
  openDialog("Installed OS access", [
    h("label", { for: "o-addr" }, "Management address"), h("input", { id: "o-addr", name: "address", required: true, value: current?.address || "" }),
    h("label", { for: "o-user" }, "Username"), h("input", { id: "o-user", name: "user", value: current?.username || "root" }),
    h("label", { for: "o-pass" }, "Password"), h("input", { id: "o-pass", name: "pass", type: "password", required: true }),
  ], {
    onSubmit: async (f) => {
      await api("PUT", `/hosts/${id}/os`, { address: f.get("address"), username: f.get("user"), password: f.get("pass") });
      toast("OS access saved", "success");
      refresh();
    },
  });
}

function captureDialog(host) {
  openDialog(`Capture a config set from ${host.name}`, [
    h("p", { class: "muted" }, "Reads the running hypervisor's network, NTP and boot disk (read-only) and saves them as a reusable config set. ",
      "The hostname and IP are saved as this server's own values."),
    h("label", { for: "c-name" }, "Config set name"),
    h("input", { id: "c-name", name: "name", required: true, value: `${host.name}-captured` }),
  ], {
    submitLabel: "Capture",
    onSubmit: async (f) => {
      const job = await api("POST", `/hosts/${host.id}/tasks/os.capture`, { params: { name: f.get("name") } });  // errors stay in the dialog
      showJobDrawer(job, {
        onDone: (j) => { if (j.status === "succeeded") location.hash = `#/config-sets/${j.result.config_set_id}`; },
      });
    },
  });
}

export function installSummary(report, lastInstallJob, { compact = false } = {}) {
  if (!report) return compact ? null : h("p", { class: "muted", "data-role": "install-summary" }, "No install has run on this host.");
  const target = `ESXi ${report.iso_version} build ${report.iso_build}`;
  const installed = Boolean(report.installed_build) && report.validation.length > 0;
  const valid = installed && report.validation.every((c) => c.ok);
  const media = `${report.media_fetches.length} ISO requests, ${Math.round(report.media_bytes_served / 2 ** 20)} MiB read`;
  if (valid) {
    return h("p", { "data-role": "install-summary" }, badge("pass", "installed"), " ",
      `Installed ${target} (was ${report.previous_build || "?"}) and validated`, compact ? "" : ` · ${media}`);
  }
  if (installed) {
    return h("p", { "data-role": "install-summary" }, badge("warn", "check"), " ",
      `Installed ${target}, but some validation checks failed`, compact ? "" : ` · ${media}`);
  }
  // A failed attempt only tells us what was *targeted*; never present it as the installed version.
  return h("div", { "data-role": "install-summary" },
    h("p", {}, badge("fail", "failed"), " ", `Install of ${target} did not complete. Nothing was installed; `,
      `the host is still on build ${report.previous_build || "?"}.`),
    lastInstallJob?.error ? h("p", { class: "error" }, lastInstallJob.error.message) : null,
    compact ? null : h("p", { class: "muted" }, `Boot method ${report.boot_method || "—"} · ${media}`));
}

function installTab({ id, install, busy, lastInstallJob }) {
  const header = h("div", { class: "row" }, h("h2", {}, "OS install"), h("span", { class: "spacer" }),
    h("a", { class: `button danger${busy ? " disabled" : ""}`, href: `#/hosts/${id}/deploy`,
      onclick: (e) => { if (busy) e.preventDefault(); } }, "Deploy OS…"));
  return card({ "data-panel": "install" }, header, installSummary(install, lastInstallJob), installSettings(install),
    install?.validation.length ? table(["", "Check", "Expected", "Observed"], install.validation.map((c) =>
      h("tr", {}, h("td", {}, badge(c.ok ? "pass" : "fail", c.ok ? "ok" : "failed")), h("td", {}, c.name),
        h("td", { class: "muted" }, c.expected), h("td", {}, c.observed)))) : null);
}

// What the generated kickstart put on the custom ISO (password hash excluded by the API).
function installSettings(report) {
  const spec = report?.spec;
  if (!spec?.network) return null;
  const n = spec.network;
  const disk = spec.install_firstdisk ? `first match: ${spec.install_firstdisk}` : spec.install_disk;
  return h("div", { "data-role": "install-settings" },
    h("h3", {}, "Settings in the custom ISO"),
    h("dl", { class: "kv compact" },
      h("dt", {}, "Host"), h("dd", {}, `${n.hostname} · ${n.ip}/${n.netmask} · gateway ${n.gateway}`),
      h("dt", {}, "DNS / NTP"), h("dd", {}, `${(n.nameservers || []).join(", ")} / ${(spec.ntp_servers || []).join(", ") || "none"}`),
      h("dt", {}, "Network"), h("dd", {}, `VLAN ${n.vlan_id || "untagged"} · ${[n.install_nic, ...(n.extra_uplinks || [])].join(" + ")}`),
      h("dt", {}, "Install disk"), h("dd", { class: "mono" }, disk || "—"),
      h("dt", {}, "VMFS"), h("dd", {}, spec.preserve_vmfs ? "kept" : "overwritten"),
      h("dt", {}, "CPU override"), h("dd", {}, spec.allow_legacy_cpu ? "on (allowLegacyCPU)" : "off")));
}

function jobsTab({ jobs }) {
  return card({}, h("h2", {}, "Recent jobs"),
    jobs.length ? jobs.map((j) => jobCard(j, { onDone: refresh })) : h("p", { class: "muted" }, "No jobs yet."));
}

