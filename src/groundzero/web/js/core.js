// Shared plumbing for the GroundZero UI: API client, DOM helper, toasts, dialogs and the job drawer.
// All server data is rendered with textContent (never innerHTML), so BMC/OS strings cannot inject markup.

export const API = "/api/v1";

// ── auth: the token arrives once in the URL fragment (never sent to the server), then lives in the session ──
const fromHash = new URLSearchParams(location.hash.slice(1)).get("token");
if (fromHash) {
  sessionStorage.setItem("gz-token", fromHash);
  history.replaceState(null, "", location.pathname + "#/");
}
export const token = () => sessionStorage.getItem("gz-token");
export const signOut = () => sessionStorage.removeItem("gz-token");

export class ApiError extends Error {
  constructor(status, problem) {
    super(problem?.detail || problem?.title || `HTTP ${status}`);
    this.status = status;
    this.problem = problem;
  }
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export async function api(method, path, body) {
  const res = await fetch(API + path, {
    method,
    headers: { Authorization: `Bearer ${token()}`, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { signOut(); onUnauthorized(); throw new ApiError(401); }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}
export const maybe = (p) => p.catch((e) => { if (e.status === 404) return null; throw e; });

// ── tiny DOM helper ──
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

// Replace a container's content; optional sections may be null/false (replaceChildren would print "null").
export const mount = (el, ...nodes) => el.replaceChildren(...nodes.flat().filter((n) => n !== null && n !== undefined && n !== false));
export const badge = (status, label) => h("span", { class: `badge ${status}`, "data-status": status }, label ?? status);
export const table = (headers, rows) =>
  h("div", { class: "table-wrap" },
    h("table", {}, h("thead", {}, h("tr", {}, headers.map((x) => h("th", {}, x)))), h("tbody", {}, rows)));
export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
// "just now", "12 min ago", "3 h ago", "4 days ago": how old a result is matters more than its timestamp.
export const fmtAge = (iso) => {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return `${d} day${d === 1 ? "" : "s"} ago`;
};
// A timestamp shown as its age, with the exact time on hover.
export const age = (iso, attrs = {}) => h("time", { datetime: iso, title: fmtTime(iso), ...attrs }, fmtAge(iso));
const fmtDuration = (job) => {
  if (!job.started_at || !job.finished_at) return "";
  const s = Math.round((new Date(job.finished_at) - new Date(job.started_at)) / 1000);
  return s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min` : s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`;
};
export const fmtBytes = (n) => {
  if (n == null) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
};
export const errorBox = (e) => h("p", { class: "error", role: "alert" }, e.message || String(e));
export const empty = (text, ...actions) => h("div", { class: "empty" }, h("p", {}, text), actions.length ? h("div", { class: "row center" }, actions) : null);
export const pageHeader = (title, subtitle, ...actions) =>
  h("div", { class: "page-header" },
    h("div", {}, h("h1", {}, title), subtitle ? h("p", { class: "muted subtitle" }, subtitle) : null),
    h("div", { class: "row" }, actions));
export const card = (attrs, ...children) => h("section", { class: "panel", ...attrs }, children);

// ── toasts ──
export function toast(message, kind = "info") {
  const region = document.getElementById("toasts");
  const el = h("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  region.append(el);
  setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 300); }, kind === "error" ? 8000 : 4000);
}

// ── modal dialogs: build a form, resolve on submit, map API errors back onto the form ──
const dialog = () => document.getElementById("dialog");

export function openDialog(title, body, { submitLabel = "Save", submitClass = "primary", onSubmit, wide = false } = {}) {
  const err = h("div");
  const submit = h("button", { class: submitClass, value: "ok" }, submitLabel);
  const form = h("form", { method: "dialog", novalidate: false },
    h("h2", {}, title), body, err,
    h("div", { class: "actions" }, h("button", { value: "cancel", formnovalidate: true }, "Cancel"), submit));
  form.addEventListener("submit", async (ev) => {
    if (ev.submitter?.value !== "ok") return;
    ev.preventDefault();
    submit.disabled = true;
    try {
      await onSubmit(new FormData(form), form);
      dialog().close();
    } catch (e) {
      err.replaceChildren(errorBox(e));
    } finally {
      submit.disabled = false;
    }
  });
  const d = dialog();
  d.classList.toggle("wide", wide);
  d.replaceChildren(form);
  d.showModal();
  return { form, submit };
}

// ── job progress: reads the per-job server-sent events stream (fetch, so the bearer header is sent) ──
export async function followJob(jobId, onEvent, signal) {
  const res = await fetch(`${API}/jobs/${jobId}/events`, { headers: { Authorization: `Bearer ${token()}` }, signal });
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

// Task titles come from the catalog (GET /tasks), loaded once after sign-in.
const taskTitles = new Map();
export async function loadTasks() {
  try {
    for (const t of await api("GET", "/tasks")) taskTitles.set(t.id, t.title);
  } catch { /* signed out: retried on the next sign-in */ }
}
export const jobLabel = (job) => taskTitles.get(job.task) || job.task;

const STEP_ICON = { pending: "○", running: "◐", succeeded: "✓", failed: "✕", skipped: "–", cancelled: "✕" };
function stepDuration(step) {
  if (!step.started_at) return "";
  const end = step.finished_at ? new Date(step.finished_at) : new Date();
  const s = Math.max(0, Math.round((end - new Date(step.started_at)) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}
export function stepsList(steps) {
  if (!steps?.length) return null;
  return h("ol", { class: "steps", "aria-label": "Steps" }, steps.map((s) =>
    h("li", { class: `step ${s.status}`, "data-step": s.key, "data-status": s.status },
      h("span", { class: "step-icon", "aria-hidden": "true" }, STEP_ICON[s.status] || "○"),
      h("span", { class: "step-title" }, s.title, h("span", { class: "visually-hidden" }, `: ${s.status}`)),
      h("span", { class: "muted small-text" }, stepDuration(s)),
      s.message ? h("div", { class: "step-msg small-text" }, s.message) : null)));
}

// Download an API resource as a file (the bearer token rides in the header, so a plain link won't do).
export async function download(path, filename) {
  const res = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token()}` } });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  const url = URL.createObjectURL(await res.blob());
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function downloadDiagnostics(jobId) {
  const res = await fetch(`${API}/jobs/${jobId}/diagnostics`, { headers: { Authorization: `Bearer ${token()}` } });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  const url = URL.createObjectURL(await res.blob());
  const a = h("a", { href: url, download: `groundzero-job-${jobId}-diagnostics.json` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const FINAL = ["succeeded", "failed", "cancelled"];
export const isActive = (job) => job.status === "queued" || job.status === "running";

// A job as a row. In lists, finished jobs are one compact line (status, task, host, age, duration, error) and
// "Details" opens the drawer; the progress bar and live message only show while the job is active.
export function jobCard(job, { onDone, hostName, detailed = false } = {}) {
  const active = isActive(job);
  const bar = h("div", { style: `width:${Math.round((job.progress || 0) * 100)}%` });
  const progress = active || detailed ? h("div", { class: "progress" }, bar) : null;
  let status = badge(job.status);
  // A finished job's generic message ("Completed", "Failed") only repeats its badge.
  const showMsg = active || detailed || (job.message && !["Completed", "Failed", "Cancelled"].includes(job.message));
  const msg = h("span", { class: "muted", "data-role": "message", hidden: !showMsg }, job.message || "");
  const err = h("div", { class: "error", "data-role": "error" }, job.error ? job.error.message : "");
  const cancel = active
    ? h("button", { class: "small", onclick: async () => {
        try { await api("POST", `/jobs/${job.id}/cancel`); toast("Cancel requested"); } catch (e) { toast(e.message, "error"); }
      } }, "Cancel")
    : null;
  const details = detailed ? null
    : h("button", { class: "small", onclick: () => showJobDrawer(job, { onDone }) }, "Details");
  const stepsSlot = h("div", {}, detailed ? stepsList(job.steps) : null);
  const diag = detailed
    ? h("button", { class: "small", onclick: () => downloadDiagnostics(job.id).catch((e) => toast(e.message, "error")) },
        "Download diagnostics")
    : null;
  const duration = fmtDuration(job);
  const el = h("div", { class: `job${active ? " active" : ""}`, "data-job": job.id, "data-status": job.status },
    h("div", { class: "row" }, status, h("strong", {}, jobLabel(job)),
      hostName ? h("span", {}, hostName) : null,
      h("span", { class: "mono muted small-text" }, job.id), h("span", { class: "spacer" }),
      duration ? h("span", { class: "muted small-text" }, duration) : null,
      h("span", { class: "muted small-text" }, age(job.created_at)), cancel, details),
    progress, msg, err, stepsSlot, diag ? h("div", { class: "row" }, diag) : null);
  if (active) {
    followJob(job.id, (ev) => {
      bar.style.width = `${Math.round(ev.progress * 100)}%`;
      status.replaceWith((status = badge(ev.status)));
      el.dataset.status = ev.status;
      msg.textContent = ev.message;
      if (detailed && ev.steps?.length) stepsSlot.replaceChildren(stepsList(ev.steps));
      if (FINAL.includes(ev.status)) {
        cancel?.remove();
        api("GET", `/jobs/${job.id}`).then((j) => {
          err.textContent = j.error ? j.error.message : "";
          if (detailed) stepsSlot.replaceChildren(stepsList(j.steps) || "");
          onDone?.(j);
        });
      }
    }).catch(() => {});
  }
  return el;
}

// ── job drawer: a slide-over showing one job's live progress; stays open across page changes ──
export function showJobDrawer(job, { onDone, title } = {}) {
  const drawer = document.getElementById("drawer");
  const close = h("button", { class: "icon", "aria-label": "Close", onclick: () => { drawer.hidden = true; } }, "✕");
  drawer.replaceChildren(
    h("div", { class: "drawer-head" }, h("h2", {}, title || jobLabel(job)), close),
    jobCard(job, {
      detailed: true,
      onDone: (j) => {
        const ok = j.status === "succeeded";
        toast(`${jobLabel(j)} ${j.status}`, ok ? "success" : "error");
        // Success: get out of the way (the toast confirms it). Failure: stay open so the error can be read.
        if (ok) setTimeout(() => { if (drawer.dataset.job === j.id) drawer.hidden = true; }, 2500);
        onDone?.(j);
      },
    }),
    h("p", { class: "muted small-text" }, "You can close this panel; the job keeps running. ", h("a", { href: "#/jobs" }, "All jobs")));
  drawer.dataset.job = job.id;
  drawer.hidden = false;
}

// Start a job through the API and follow it in the drawer.
export async function startJob(method, path, body, opts = {}) {
  try {
    const job = await api(method, path, body);
    showJobDrawer(job, opts);
    return job;
  } catch (e) {
    toast(e.message, "error");
    return null;
  }
}

// Show one stored output (what a later task will read) as formatted JSON.
export async function showOutput(hostId, kind, title) {
  try {
    const data = await api("GET", `/hosts/${hostId}/outputs/${kind}`);
    const text = JSON.stringify(data, null, 2);
    openDialog(title || kind, [
      h("p", { class: "muted small-text" }, `Output kind "${kind}": later tasks read this as their input.`),
      h("pre", { class: "code-block output-json", "data-role": "output-json" }, text),
    ], { submitLabel: "Close", wide: true, onSubmit: async () => {} });
  } catch (e) {
    toast(e.status === 404 ? `No ${title || kind} yet` : e.message, "error");
  }
}
