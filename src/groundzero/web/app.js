// GroundZero web UI: a thin client of the REST API (/api/v1). No build step, no dependencies.
// The shell (sidebar, top bar, drawer, toasts) never unloads; only <main> is re-rendered per route.
import { api, errorBox, h, isActive, loadTasks, setUnauthorizedHandler, showJobDrawer, signOut, token } from "./js/core.js";
import { viewConfigSet, viewConfigSets, viewImages } from "./js/views/catalog.js";
import { viewDeploy } from "./js/views/deploy.js";
import { viewHost, viewHosts } from "./js/views/hosts.js";
import { viewApi, viewInfo, viewJobs } from "./js/views/misc.js";

const app = document.getElementById("app");

// ── routes: [pattern, section, title, view, live] (live views re-render when a job finishes) ──
const ROUTES = [
  [/^\/(?:hosts)?$/, "hosts", "Hosts", () => viewHosts(app), true],
  [/^\/hosts\/([\w-]+)\/deploy$/, "hosts", "Deploy", (m, q) => viewDeploy(app, m[1], q), false],
  [/^\/hosts\/([\w-]+)(?:\/(\w+))?$/, "hosts", "Host", (m) => viewHost(app, m[1], m[2]), true],
  [/^\/jobs$/, "jobs", "Jobs", (m, q) => viewJobs(app, q), true],
  [/^\/config-sets$/, "config-sets", "Config sets", () => viewConfigSets(app), true],
  [/^\/config-sets\/([\w-]+)$/, "config-sets", "Config set", (m, q) => viewConfigSet(app, m[1], q), false],
  [/^\/(?:images|isos)$/, "images", "Images", () => viewImages(app), false],
  [/^\/api$/, "api", "API", () => viewApi(app), false],
  [/^\/info$/, "info", "Info", () => viewInfo(app), false],
];
let current = null;
let lastPath = null;

let tasksLoaded = false;
async function route() {
  if (!token()) return renderLogin();
  if (!tasksLoaded) { tasksLoaded = true; await loadTasks(); }
  document.body.classList.remove("signed-out");
  const [path, qs] = (location.hash.replace(/^#/, "") || "/").split("?");
  const query = new URLSearchParams(qs || "");
  let match = null;
  current = ROUTES.find(([re]) => (match = path.match(re))) || ROUTES[0];
  const [, section, title, view] = current;
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const on = a.dataset.nav === section;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  closeMenu();
  try {
    await view(match || [], query);
    // A new page starts at the top; a live refresh of the same page keeps the reader's place.
    if (path !== lastPath) window.scrollTo(0, 0);
    lastPath = path;
    document.title = `${document.querySelector("main h1")?.textContent || title} · GroundZero`;
  } catch (e) {
    if (e.status !== 401) app.replaceChildren(errorBox(e));
  }
}

// Re-render the page when a job finishes, but never under an open dialog or over a form being edited.
// Deferred a tick so a dialog that triggered the refresh has closed by then.
window.addEventListener("gz:refresh", () => setTimeout(() => {
  if (document.getElementById("dialog").open) return;
  if (current && current[4]) route();
}, 0));

function renderLogin() {
  document.body.classList.add("signed-out");
  const input = h("input", { id: "token", type: "password", placeholder: "paste the API token", autocomplete: "off" });
  app.replaceChildren(h("div", { class: "panel login" },
    h("h1", {}, "Sign in"),
    h("p", { class: "muted" }, "Run ", h("code", {}, "groundzero ui"), " to open this page signed in, or paste the token from ",
      h("code", {}, "groundzero token show"), "."),
    h("label", { for: "token" }, "API token"), input,
    h("div", { class: "actions" }, h("button", { class: "primary", onclick: () => {
      sessionStorage.setItem("gz-token", input.value.trim());
      route();
    } }, "Sign in"))));
}
setUnauthorizedHandler(renderLogin);

// ── theme: System / Light / Dark, remembered per browser ──
function applyTheme(choice) {
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  document.querySelectorAll("[data-theme-choice]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.themeChoice === (choice || "system"))));
}
let savedTheme = "system";
try { savedTheme = localStorage.getItem("gz-theme") || "system"; } catch { /* storage blocked */ }
applyTheme(savedTheme);
document.querySelectorAll("[data-theme-choice]").forEach((b) => b.addEventListener("click", () => {
  const choice = b.dataset.themeChoice;
  try { localStorage.setItem("gz-theme", choice); } catch { /* storage blocked */ }
  applyTheme(choice);
}));

// ── small screens: the sidebar slides over the content ──
const sidebar = document.getElementById("sidebar");
const scrim = document.getElementById("scrim");
const toggle = document.getElementById("menu-toggle");
function closeMenu() {
  document.body.classList.remove("nav-open");
  scrim.hidden = true;
  toggle.setAttribute("aria-expanded", "false");
}
toggle.addEventListener("click", () => {
  const open = !document.body.classList.contains("nav-open");
  document.body.classList.toggle("nav-open", open);
  scrim.hidden = !open;
  toggle.setAttribute("aria-expanded", String(open));
  if (open) sidebar.querySelector("a")?.focus();
});
scrim.addEventListener("click", closeMenu);

document.getElementById("sign-out").addEventListener("click", () => { signOut(); renderLogin(); });

// ── running-jobs pill in the top bar ──
const pill = document.getElementById("running");
let runningJobs = [];
async function refreshRunning() {
  if (!token() || document.visibilityState !== "visible") return;
  try {
    runningJobs = (await api("GET", "/jobs?limit=20")).filter(isActive);
    pill.hidden = runningJobs.length === 0;
    pill.replaceChildren(h("span", { class: "pulse", "aria-hidden": "true" }), `${runningJobs.length} running`);
  } catch { /* signed out or server restarting */ }
}
async function pollRunning() {
  await refreshRunning();
  setTimeout(pollRunning, 4000);
}
// Poll at once when the tab comes back: background tabs skip polls, so the count could be stale.
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refreshRunning(); });
pill.addEventListener("click", () => {
  if (runningJobs.length === 1) showJobDrawer(runningJobs[0], { onDone: () => window.dispatchEvent(new Event("gz:refresh")) });
  else location.hash = "#/jobs";
});

fetch("/healthz").then((r) => r.json()).then((hz) => {
  const el = document.getElementById("mode");
  if (hz.mode === "simulated") { el.textContent = "simulation mode"; el.hidden = false; }
  const version = document.getElementById("version");
  version.textContent = `GroundZero v${hz.version}`;
  version.title = "Release notes";
  version.hidden = false;
}).catch(() => {});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { document.getElementById("drawer").hidden = true; closeMenu(); }
});
window.addEventListener("hashchange", route);
route();
pollRunning();
