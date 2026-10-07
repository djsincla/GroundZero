// Specs: the jobs you pick for a server or a cluster, each with its saved parameters, run as one.
// Also the run pieces the host and cluster pages share: the preview + phrase dialog and the live run panel.
import { schemaForm } from "../forms.js";
import {
  age, api, badge, card, empty, fmtTime, h, maybe, mount, openDialog, pageHeader, stepsList, table, toast,
} from "../core.js";

const refresh = () => window.dispatchEvent(new Event("gz:refresh"));
const STAGES = [["hardware", "Hardware"], ["os", "Operating system"], ["readiness", "Holodeck readiness"],
  ["prep", "Host preparation"], ["appliances", "Appliances"], ["holodeck", "Holodeck"]];
// Parameters a spec never carries: per-server values, secrets and free-form maps come from profiles and
// config sets; the confirmation comes from the run.
const HIDDEN_PARAMS = new Set(["confirm", "iso_path", "host_values", "secrets", "values", "networks"]);

// ── list ──
export async function viewSpecs(app) {
  const [specs, clusters, hosts] = await Promise.all([api("GET", "/specs"), api("GET", "/clusters"), api("GET", "/hosts")]);
  const own = await Promise.all(hosts.map(async (x) => [x, await maybe(api("GET", `/hosts/${x.id}/spec`))]));
  const usedBy = (spec) => [
    ...clusters.filter((c) => c.spec_id === spec.id).map((c) => `cluster ${c.name}`),
    ...own.filter(([, e]) => e?.source === "host" && e.spec.id === spec.id).map(([x]) => x.name),
  ];
  mount(app,
    pageHeader("Specs", "The jobs you pick for a server or a cluster, with the settings each one uses. Run one and it works through them in order.",
      h("a", { class: "button primary", href: "#/specs/new" }, "New spec")),
    card({}, specs.length
      ? table(["Name", "Steps", "Used by", "Updated"], specs.map((s) => {
          const users = usedBy(s);
          return h("tr", { "data-spec": s.name },
            h("td", {}, h("a", { href: `#/specs/${s.id}` }, s.name), s.description ? h("div", { class: "muted small-text" }, s.description) : null),
            h("td", { class: "small-text" }, s.steps.map((x) => x.task).join(" → ")),
            h("td", {}, users.length ? users.join(", ") : h("span", { class: "muted" }, "nothing yet")),
            h("td", {}, age(s.updated_at)));
        }))
      : empty("No specs yet. A spec is the list of jobs a server should go through, from bare metal on.",
          h("a", { class: "button primary", href: "#/specs/new" }, "New spec"))));
}

// ── editor ──
async function referenceChoices() {
  const [images, sets, profiles, biosProfiles] = await Promise.all([
    api("GET", "/images"), api("GET", "/config-sets"), api("GET", "/appliance-profiles"), api("GET", "/bios-profiles")]);
  const choice = (items, label) => ({ enum: items.map((x) => x.id), labels: items.map(label) });
  return {
    iso_id: choice(images.filter((i) => i.kind === "iso"), (i) => i.filename),
    image_id: choice(images.filter((i) => i.kind === "ova"), (i) => i.filename),
    config_set_id: choice(sets, (s) => `${s.name} (${s.os_family})`),
    profile_id: choice(profiles, (p) => p.name),
    bios_profile_id: choice(biosProfiles, (p) => `${p.name}${p.model ? ` (${p.model})` : ""}`),
  };
}

// A task's parameter schema for a spec: hidden keys dropped, ids offered as named choices.
function specSchema(task, choices) {
  const schema = structuredClone(task.params_schema || {});
  const props = {};
  for (const [key, node] of Object.entries(schema.properties || {})) {
    if (HIDDEN_PARAMS.has(key)) continue;
    const pick = task.id === "bios.configure" && key === "profile_id" ? choices.bios_profile_id : choices[key];
    props[key] = pick
      ? { type: "string", title: node.title || key, description: node.description, enum: pick.enum,
          "x-enum-labels": pick.labels, nullable: !(schema.required || []).includes(key) }
      : node;
  }
  schema.properties = props;
  schema.required = (schema.required || []).filter((k) => props[k]);
  return schema;
}

export async function viewSpec(app, id) {
  const isNew = id === "new";
  const [tasks, spec, choices] = await Promise.all([
    api("GET", "/tasks"), isNew ? null : api("GET", `/specs/${id}`), referenceChoices()]);
  const chosen = new Map((spec?.steps || []).map((s) => [s.task, s.params]));
  const name = h("input", { id: "spec-name", value: spec?.name || "", autocomplete: "off", placeholder: "Holodeck host" });
  const description = h("input", { id: "spec-desc", value: spec?.description || "", autocomplete: "off" });
  const status = h("div");
  const rows = new Map();  // task id -> {box, form, row}

  const flow = h("div", { class: "flow small-text", "data-role": "spec-flow" });
  const titleOf = Object.fromEntries(tasks.map((t) => [t.id, t.title]));
  const producers = {};  // output kind -> every task that makes it, in pipeline order
  for (const t of tasks) for (const k of [t.produces, ...(t.also_produces || [])].filter(Boolean)) (producers[k] ??= []).push(t.id);
  producers.os_access = ["os.custom", "os.reimage"];  // an OS deploy leaves GroundZero with access to it
  // Inputs of each ticked task: made by an earlier ticked task, or expected to exist already.
  function updateFlow() {
    for (const [taskId, r] of rows) {
      const task = tasks.find((t) => t.id === taskId);
      const on = r.box.checked;
      r.row.classList.toggle("picked", on);
      r.params.hidden = !on;
      r.needs.replaceChildren(...(on ? task.requires.map((k) => {
        const order = [...rows.keys()];
        const earlier = (producers[k] || []).filter((p) => p !== taskId && order.indexOf(p) < order.indexOf(taskId));
        const from = earlier.find((p) => rows.get(p)?.box.checked);
        const inSpec = Boolean(from);
        const label = inSpec ? titleOf[from] : k === "os_access" ? "OS access" : titleOf[(producers[k] || [])[0]] || k;
        return h("span", { class: `flow-chip ${inSpec ? "ok" : "missing optional"}`, "data-needs": k,
          title: inSpec ? "Made earlier in this spec" : "Not in this spec: it must already be done on the server" },
          inSpec ? `← ${label}` : `needs ${label}`);
      }) : []));
    }
  }

  const stages = STAGES.map(([stageId, stageTitle]) => {
    const inStage = tasks.filter((t) => t.stage === stageId);
    if (!inStage.length) return null;
    return h("fieldset", { class: "group spec-stage", "data-stage": stageId }, h("legend", {}, stageTitle),
      inStage.map((task) => {
        const box = h("input", { type: "checkbox", id: `pick-${task.id}`, checked: chosen.has(task.id), disabled: !task.available,
          onchange: updateFlow });
        const schema = specSchema(task, choices);
        const hasParams = Object.keys(schema.properties || {}).length > 0;
        const form = hasParams ? schemaForm(schema, chosen.get(task.id) || {}, { idPrefix: `sp-${task.id.replace(/\W/g, "-")}`, where: "params" }) : null;
        const params = h("div", { class: "spec-params", hidden: true }, form ? form.el : null,
          form ? h("p", { class: "help" }, "Text may use {host} or {hostname}, filled in per server.") : null);
        const needs = h("span", { class: "flow" });
        const row = h("div", { class: "spec-task", "data-task": task.id },
          h("label", { class: "inline", for: box.id }, box, h("strong", {}, task.title),
            task.destructive ? h("span", { class: "chip danger-chip" }, "changes the server") : null,
            task.available ? null : h("span", { class: "chip" }, "coming")),
          h("p", { class: "muted small-text task-desc" }, task.description), needs, params);
        rows.set(task.id, { box, form, row, params, needs });
        return row;
      }));
  });
  updateFlow();

  async function save() {
    status.replaceChildren();
    for (const r of rows.values()) r.form?.clearErrors();
    const picked = [...rows].filter(([, r]) => r.box.checked);
    const body = { name: name.value.trim(), description: description.value.trim(),
      steps: picked.map(([task, r]) => ({ task, params: r.form ? r.form.value() : {} })) };
    try {
      const saved = await api(isNew ? "POST" : "PUT", isNew ? "/specs" : `/specs/${id}`, body);
      toast(`Saved ${saved.name}`, "success");
      location.hash = `#/specs/${saved.id}`;
    } catch (e) {
      const errors = e.problem?.errors || [];
      const unplaced = [];
      for (const err of errors) {
        const [first, index, part, ...rest] = err.loc || [];
        const task = first === "steps" ? picked[index]?.[0] : null;
        const r = task ? rows.get(task) : null;
        if (r?.form && part === "params") r.form.setErrors([{ ...err, loc: ["params", ...rest] }]);
        else unplaced.push(task ? `${titleOf[task]}: ${err.msg}` : `${(err.loc || []).join(".")}: ${err.msg}`);
      }
      status.replaceChildren(h("p", { class: "error", role: "alert" }, errors.length ? "Fix the highlighted steps." : e.message),
        ...unplaced.map((m) => h("p", { class: "error" }, m)));
    }
  }

  const remove = () => openDialog(`Delete ${spec.name}?`, [
    h("p", {}, "Servers that use it as their own spec go back to their cluster's. Nothing on any server changes."),
  ], { submitLabel: "Delete", submitClass: "danger", onSubmit: async () => {
    await api("DELETE", `/specs/${id}`);
    location.hash = "#/specs";
  } });

  mount(app,
    pageHeader(isNew ? "New spec" : spec.name,
      isNew ? "Tick the jobs this spec runs. They run in pipeline order; each one's settings are saved with it."
        : `${spec.steps.length} steps · updated ${fmtTime(spec.updated_at)}`),
    card({ class: "panel form-card" },
      h("div", { class: "grid two" },
        h("div", { class: "field", "data-field": "name" }, h("label", { for: name.id }, "Name"), name),
        h("div", { class: "field" }, h("label", { for: description.id }, "Description"), description)),
      flow, stages, status,
      h("div", { class: "actions" },
        isNew ? null : h("button", { class: "danger-outline", onclick: remove }, "Delete"),
        h("a", { class: "button", href: "#/specs" }, "Back"),
        h("button", { class: "primary", onclick: save }, isNew ? "Create" : "Save"))));
}

// ── runs: the preview + phrase dialog, and the live panel ──
const ACTION_BADGE = { run: ["running", "runs"], skip: ["none", "skipped"], blocked: ["fail", "blocked"] };

function previewTable(preview) {
  return table(["Step", "", "Why"], preview.steps.map((s) => {
    const [cls, label] = ACTION_BADGE[s.action];
    return h("tr", { "data-preview-step": s.task, "data-action": s.action },
      h("td", {}, s.title, s.destructive ? [" ", h("span", { class: "chip danger-chip" }, "changes the server")] : null),
      h("td", {}, badge(cls, label)),
      h("td", { class: "small-text muted" }, s.reason || ""));
  }));
}

function phraseField(phrase, submit) {
  const input = h("input", { id: "run-confirm", autocomplete: "off", spellcheck: "false" });
  submit.disabled = true;
  input.addEventListener("input", () => { submit.disabled = input.value !== phrase; });
  return [h("label", { for: input.id }, `Type "${phrase}" to start`), input];
}

export async function runSpecDialog(hostId) {
  const preview = await api("GET", `/hosts/${hostId}/runs/preview`);
  const changes = preview.destructive.length
    ? h("div", { class: "callout warn" }, h("strong", {}, "Approving the run approves these too:"),
        h("ul", {}, preview.destructive.map((d) => h("li", {}, d))))
    : null;
  const body = h("div", {});
  const { submit } = openDialog(`Run ${preview.spec_name} on ${preview.host_name}`, body, {
    submitLabel: "Start run", wide: true,
    onSubmit: async () => {
      await api("POST", `/hosts/${hostId}/runs`, { confirm: document.getElementById("run-confirm").value });
      toast(`Started ${preview.spec_name} on ${preview.host_name}`, "success");
      refresh();
    },
  });
  mount(body, h("p", { class: "muted" }, "Steps run one after another; the run stops at the first failure. Steps already done, or not needed, are skipped."),
    previewTable(preview), changes, ...phraseField(preview.phrase, submit));
}

export async function runClusterDialog(clusterId) {
  const preview = await api("GET", `/clusters/${clusterId}/runs/preview`);
  const body = h("div", {});
  const { submit } = openDialog(`Run every member of ${preview.cluster_name}`, body, {
    submitLabel: "Start runs", wide: true,
    onSubmit: async () => {
      const runs = await api("POST", `/clusters/${clusterId}/runs`, { confirm: document.getElementById("run-confirm").value });
      toast(`Started ${runs.length} runs`, "success");
      refresh();
    },
  });
  const destructive = [...new Set(preview.hosts.flatMap((p) => p.destructive))];
  mount(body,
    h("p", { class: "muted" }, "Every member runs its spec at the same time. One failing doesn't stop the others."),
    ...preview.hosts.map((p) => h("details", { class: "run-preview", "data-preview-host": p.host_name },
      h("summary", {}, `${p.host_name}: ${p.spec_name}`, h("span", { class: "muted small-text" },
        ` · ${p.steps.filter((s) => s.action === "run").length} to run, ${p.steps.filter((s) => s.action === "skip").length} skipped`
        + (p.steps.some((s) => s.action === "blocked") ? ", blocked steps" : ""))),
      previewTable(p))),
    preview.without_spec.length ? h("p", { class: "warn-text" }, `No spec, not run: ${preview.without_spec.join(", ")}`) : null,
    destructive.length ? h("div", { class: "callout warn" }, h("strong", {}, "Approving the runs approves these too:"),
      h("ul", {}, destructive.map((d) => h("li", {}, d)))) : null,
    ...phraseField(preview.phrase, submit));
}

const RUN_BADGE = { running: "running", succeeded: "pass", failed: "fail", cancelled: "warn" };
const asSteps = (run) => run.steps.map((s) => ({ key: s.task, title: s.title, status: s.status, message: s.reason }));

// A run, kept current while it's in progress (polls until it ends, then refreshes the page once).
export function runPanel(run, { compact = false } = {}) {
  const body = h("div", {});
  const panel = card({ class: "panel run-panel", "data-run": run.id }, body);
  let timer = null;
  function render(r) {
    const cancel = r.status === "running"
      ? h("button", { class: "small danger-outline", onclick: async () => {
          try { render(await api("POST", `/runs/${r.id}/cancel`)); } catch (e) { toast(e.message, "error"); }
        } }, "Cancel run") : null;
    mount(body,
      h("div", { class: "row" }, h("h2", {}, compact ? r.host_name : `Run: ${r.spec_name}`),
        badge(RUN_BADGE[r.status] || "none", r.status), h("span", { class: "spacer" }),
        h("span", { class: "muted small-text" }, "started ", age(r.created_at)), cancel),
      stepsList(asSteps(r)),
      r.error ? h("p", { class: "error small-text", "data-role": "run-error" }, r.error) : null);
  }
  render(run);
  if (run.status === "running") {
    timer = setInterval(async () => {
      if (!document.contains(panel)) { clearInterval(timer); return; }
      try {
        const r = await api("GET", `/runs/${run.id}`);
        render(r);
        if (r.status !== "running") { clearInterval(timer); refresh(); }
      } catch { clearInterval(timer); }
    }, 1500);
  }
  return panel;
}
