#!/usr/bin/env node
// gz-hwreport (Node.js): a hardware report straight from a server's BMC. No dependencies, Node 20+.
//
//   node gz-hwreport.mjs 192.0.2.5                     one server: report in ./hwreport-<date>/
//   node gz-hwreport.mjs 192.0.2.5 192.0.2.6           several: a report each, plus a page comparing them
//   node gz-hwreport.mjs -f bmcs.txt -o reports        BMCs from a file: "address" or "address username" per line
//
// It reads the BMC over Redfish (GET requests only, plus the session login and logout): firmware versions,
// processors, memory modules, drives, RAID volumes, network adapters and ports, PCIe devices (storage
// controllers, HBAs, NICs), power supplies, BIOS and BMC. Each server gets one self-contained HTML page and a
// JSON file. The BMC password comes from GZ_BMC_PASSWORD, or is asked for once. BMC certificates are usually
// self-signed, so they aren't checked unless --verify-tls is given.
//
// This is a port of GroundZero's Python collector (groundzero.inventory.collect, groundzero.redfish.storage,
// groundzero.hwreport). Its JSON matches the Python tool's field for field: CI replays the same recorded
// server through both and fails if they disagree.

import { readFileSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { request as httpsRequest } from "node:https";
import { join } from "node:path";
import { createInterface } from "node:readline";

const VERSION = "0.11.1";

// ── Redfish client: a session (or Basic auth), GETs, logout ─────────────────
class Redfish {
  constructor(host, username, password, { verifyTls = false, replay = null } = {}) {
    Object.assign(this, { host, username, password, verifyTls, token: null, session: null, basic: false });
    this.replay = replay ? loadRecording(replay) : null;
  }

  async request(method, path, body) {
    if (this.replay) return this.replayed(method, path);
    const headers = { Accept: "application/json" };
    if (body) headers["Content-Type"] = "application/json";
    if (this.token) headers["X-Auth-Token"] = this.token;
    else if (this.basic) headers.Authorization = `Basic ${Buffer.from(`${this.username}:${this.password}`).toString("base64")}`;
    for (let attempt = 0; ; attempt++) {
      const res = await new Promise((resolve, reject) => {
        const req = httpsRequest({ host: this.host, path, method, headers, rejectUnauthorized: this.verifyTls, timeout: 60_000 }, (r) => {
          const chunks = [];
          r.on("data", (c) => chunks.push(c));
          r.on("end", () => resolve({ status: r.statusCode, headers: r.headers, text: Buffer.concat(chunks).toString("utf8") }));
        });
        req.on("timeout", () => req.destroy(new Error(`${method} ${path} timed out`)));
        req.on("error", reject);
        if (body) req.write(JSON.stringify(body));
        req.end();
      });
      if ((res.status === 429 || res.status === 503) && attempt < 3) {
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      return res;
    }
  }

  replayed(method, path) {
    if (method === "POST") return { status: 201, headers: { "x-auth-token": "replay", location: "/replay" }, text: "{}" };
    if (method === "DELETE") return { status: 204, headers: {}, text: "" };
    const body = this.replay.get(path);
    return body ? { status: 200, headers: {}, text: body } : { status: 404, headers: {}, text: "{}" };
  }

  async login() {
    for (const path of ["/redfish/v1/SessionService/Sessions", "/redfish/v1/Sessions"]) {
      const res = await this.request("POST", path, { UserName: this.username, Password: this.password });
      if (res.status === 401 || res.status === 403) throw new RedfishError(`BMC login refused (${res.status})`, path);
      if (res.status < 300 && res.headers["x-auth-token"]) {
        this.token = res.headers["x-auth-token"];
        this.session = res.headers.location ? new URL(res.headers.location, "https://x").pathname : null;
        return;
      }
    }
    this.basic = true; // sessions unavailable: Basic auth on every request
  }

  async logout() {
    if (this.session && this.token) await this.request("DELETE", this.session).catch(() => {});
  }

  async get(path) {
    const res = await this.request("GET", path);
    if (res.status >= 400) throw new RedfishError(`GET ${path}: ${res.status}`, path);
    return JSON.parse(res.text || "{}");
  }

  async members(path) {
    const collection = await this.get(path);
    return Promise.all((collection.Members || []).filter((m) => m["@odata.id"]).map((m) => this.get(m["@odata.id"])));
  }
}

class RedfishError extends Error {
  constructor(message, path) { super(message); this.path = path; }
}

function loadRecording(dir) {
  const index = JSON.parse(readFileSync(join(dir, "index.json"), "utf8"));
  return new Map(Object.entries(index).map(([path, file]) => [path, readFileSync(join(dir, file), "utf8")]));
}

const link = (resource, key) => (resource && typeof resource[key] === "object" ? resource[key]?.["@odata.id"] ?? null : null);
const absent = (r) => String(r?.Status?.State ?? "").toLowerCase() === "absent";
const health = (r) => r?.Status?.HealthRollup || r?.Status?.Health || null;
const orNull = (v) => (v === undefined || v === "" ? null : v);
async function optional(fn) { try { return await fn(); } catch { return null; } }
const optionalJson = async (c, path) => (path ? (await optional(() => c.get(path))) ?? {} : {});
const optionalMembers = async (c, path) => (path ? (await optional(() => c.members(path))) ?? [] : []);

// ── identity ─────────────────────────────────────────────────────────────
const VENDORS = [["dell", ["DELL"]], ["hpe", ["HPE", "HEWLETT"]], ["lenovo", ["LENOVO"]], ["cisco", ["CISCO"]],
  ["supermicro", ["SUPERMICRO", "SUPER MICRO"]], ["quanta", ["QUANTA", "QCT"]], ["gigabyte", ["GIGABYTE", "GIGA-BYTE"]],
  ["intel", ["INTEL"]]];
const matchVendor = (...fields) => {
  const text = fields.join(" ").toUpperCase();
  return VENDORS.find(([, markers]) => markers.some((m) => text.includes(m)))?.[0] ?? "generic";
};

async function detect(c) {
  const root = await c.get("/redfish/v1");
  const first = async (key) => {
    const l = link(root, key);
    if (!l) return null;
    const members = (await optional(() => c.get(l)))?.Members ?? [];
    return members[0]?.["@odata.id"] ?? null;
  };
  const systemPath = await first("Systems");
  if (!systemPath) throw new RedfishError("BMC exposes no ComputerSystem resource", "/redfish/v1/Systems");
  const system = await c.get(systemPath);
  return {
    vendor: matchVendor(String(root.Vendor ?? ""), String(system.Manufacturer ?? ""), Object.keys(root.Oem ?? {}).join(" "), String(root.Product ?? "")),
    manufacturer: String(system.Manufacturer ?? ""), model: String(system.Model ?? ""), redfishVersion: root.RedfishVersion ?? null,
    systemPath, managerPath: await first("Managers"), chassisPath: await first("Chassis"),
  };
}

// ── BIOS flags (the vendor's attribute names) ──────────────────────────────
const TRUTHY = new Set(["ENABLED", "ENABLE", "ON", "TRUE", "YES", "AUTO"]);
const FALSY = new Set(["DISABLED", "DISABLE", "OFF", "FALSE", "NO"]);
const GENERIC_KEYS = {
  cpu: ["ProcVirtualization", "IntelVirtualizationTechnology", "Processors_IntelVirtualizationTechnology", "IntelVT", "SvmMode", "AmdVirtualization"],
  iommu: ["VtdSupport", "IntelVTD", "IntelVtd", "IntelVTForDirectedIO", "IntelVTforDirectedIOVTd", "Processors_IntelVTforDirectedIOVTd", "IntelProcVtd", "ProcAmdIoVt", "Iommu"],
};
const keysFor = (vendor) => (vendor === "dell" ? { cpu: ["ProcVirtualization"], iommu: ["ProcVirtualization"] } : GENERIC_KEYS);
function biosFlag(attributes, keys) {
  for (const key of keys) {
    if (!(key in attributes)) continue;
    const value = attributes[key];
    if (typeof value === "boolean") return value;
    const text = String(value).trim().toUpperCase();
    if (TRUTHY.has(text)) return true;
    if (FALSY.has(text)) return false;
  }
  return null;
}

// ── inventory (groundzero.inventory.collect) ───────────────────────────────
const BOOT_CONTROLLERS = ["BOSS", "M.2", "SD MODULE", "IDSDM", "NS204"];
const PCIE_CLASSES = [
  ["storage", ["RAID", "SATA", "SAS", "NVME", "SSD", "BOSS", "PERC", "HBA", "STORAGE", "FIBRE", "EXPRESS FLASH"]],
  ["network", ["ETHERNET", "NETWORK", "NIC", "CONNECTX", "QLOGIC", "MELLANOX"]],
  ["accelerator", ["GPU", "NVIDIA", "TESLA", "ACCELERATOR", "FPGA"]],
  ["display", ["GRAPHICS", "VGA", "MATROX"]],
];
const pcieClass = (name) => PCIE_CLASSES.find(([, words]) => words.some((w) => name.toUpperCase().includes(w)))?.[0] ?? "chipset";
const int = (v) => Math.trunc(Number(v) || 0);

async function collectInventory(c, id) {
  const system = await c.get(id.systemPath);
  const manager = id.managerPath ? (await optionalJson(c, id.managerPath)) : {};
  const processors = (await optionalMembers(c, link(system, "Processors")))
    .filter((p) => String(p.ProcessorType ?? "CPU").toUpperCase() === "CPU" && !absent(p))
    .map((p) => ({ socket: orNull(p.Socket), manufacturer: orNull(p.Manufacturer), model: String(p.Model || p.Name || "Unknown"),
      cores: int(p.TotalCores), threads: int(p.TotalThreads), max_speed_mhz: p.MaxSpeedMHz ?? null }));
  const dimmCollection = await optionalJson(c, link(system, "Memory"));
  const modules = (await optionalMembers(c, link(system, "Memory"))).filter((m) => !absent(m)).map((m) => ({
    id: m.Id ?? String(m["@odata.id"] ?? "").split("/").pop(), slot: m.DeviceLocator || m.MemoryLocation?.Slot || null,
    capacity_mib: int(m.CapacityMiB), type: orNull(m.MemoryDeviceType), speed_mhz: m.OperatingSpeedMhz ?? null,
    manufacturer: (m.Manufacturer ?? "").trim() || null, part_number: (m.PartNumber ?? "").trim() || null, health: health(m),
  }));
  const memory = { total_gib: Number(system.MemorySummary?.TotalSystemMemoryGiB || 0),
    dimm_count: int(dimmCollection["Members@odata.count"] || (dimmCollection.Members ?? []).length), modules };

  const drives = [];
  for (const storage of await optionalMembers(c, link(system, "Storage"))) {
    const sc = (storage.StorageControllers ?? [])[0];
    const controller = (sc && (sc.Model || sc.Name)) || storage.Name || storage.Id || null;
    const raws = await Promise.all((storage.Drives ?? []).filter((d) => d["@odata.id"]).map((d) => c.get(d["@odata.id"])));
    for (const raw of raws.filter((r) => !absent(r))) {
      drives.push({ id: String(raw.Id || raw["@odata.id"]), name: orNull(raw.Name), model: orNull(raw.Model), media_type: orNull(raw.MediaType),
        protocol: orNull(raw.Protocol), capacity_bytes: int(raw.CapacityBytes), firmware_version: orNull(raw.Revision), controller,
        is_boot_device: BOOT_CONTROLLERS.some((m) => (controller ?? "").toUpperCase().includes(m)) });
    }
  }
  const network_ports = (await optionalMembers(c, link(system, "EthernetInterfaces"))).map((p) => ({
    id: String(p.Id || p["@odata.id"]), name: orNull(p.Name), mac_address: p.MACAddress || p.PermanentMACAddress || null,
    link_status: orNull(p.LinkStatus), speed_mbps: p.SpeedMbps ?? null }));

  const biosRaw = await optionalJson(c, link(system, "Bios"));
  const attributes = Object.fromEntries(Object.entries(biosRaw.Attributes ?? {}).filter(([, v]) => ["string", "number", "boolean"].includes(typeof v)));
  const keys = keysFor(id.vendor);
  const bootMode = ["BootMode", "BootModeSelect", "BootModeOptimized"].map((k) => attributes[k]).find(Boolean);
  const bios = { boot_mode: bootMode ? String(bootMode) : system.Boot?.BootSourceOverrideMode ?? null, cpu_virtualization: biosFlag(attributes, keys.cpu),
    iommu: biosFlag(attributes, keys.iommu), attributes, registry_id: biosRaw.AttributeRegistry ?? null };

  const bmcNics = id.managerPath ? await optionalMembers(c, link(manager, "EthernetInterfaces")) : [];
  const bmcNic = bmcNics.find((n) => n.HostName) ?? {};

  const chassis = await optionalJson(c, id.chassisPath);
  const service = await optionalJson(c, "/redfish/v1/UpdateService");
  const items = await optionalMembers(c, link(service, "FirmwareInventory"));
  const installed = items.filter((i) => String(i.Id ?? "").startsWith("Installed"));
  const firmware = (installed.length ? installed : items).map((i) => ({ id: i.Id ?? "", name: i.Name || i.Id || "",
    version: orNull(i.Version), updateable: i.Updateable ?? null, health: health(i) }));
  const network_adapters = (await optionalMembers(c, link(chassis, "NetworkAdapters"))).map((a) => {
    const ctl = (a.Controllers ?? [{}])[0] ?? {};
    let ports = ctl.ControllerCapabilities?.NetworkPortCount;
    if (ports === undefined || ports === null) ports = (ctl.Links?.Ports ?? ctl.Links?.NetworkPorts ?? []).length;
    return { id: a.Id ?? "", name: a.Model || a.Name || null, manufacturer: orNull(a.Manufacturer), model: orNull(a.Model),
      part_number: a.PartNumber || null, firmware_version: ctl.FirmwarePackageVersion || null, ports: int(ports), health: health(a) };
  });
  let pcieRaw;
  if (Array.isArray(system.PCIeDevices) && system.PCIeDevices.length) {
    pcieRaw = (await Promise.all(system.PCIeDevices.filter((d) => d["@odata.id"]).map((d) => optional(() => c.get(d["@odata.id"]))))).filter(Boolean);
  } else {
    pcieRaw = await optionalMembers(c, link(chassis, "PCIeDevices") || link(system, "PCIeDevices"));
  }
  const pcie_devices = pcieRaw.filter((d) => !absent(d)).map((d) => ({ id: d.Id ?? "", name: orNull(d.Name), manufacturer: orNull(d.Manufacturer),
    model: d.Model || d.Name || null, device_class: pcieClass(d.Name || d.Model || ""), firmware_version: d.FirmwareVersion || null,
    slot: d.Slot?.Location?.PartLocation?.ServiceLabel || null, health: health(d) }));
  const power = await optionalJson(c, link(chassis, "Power"));
  const power_supplies = (power.PowerSupplies ?? []).filter((p) => !absent(p)).map((p) => ({ name: p.Name || p.MemberId || "Power supply",
    model: orNull(p.Model), manufacturer: orNull(p.Manufacturer), capacity_watts: p.PowerCapacityWatts ?? null,
    firmware_version: p.FirmwareVersion || null, health: health(p) }));

  return {
    collected_at: new Date().toISOString(),
    system: { manufacturer: id.manufacturer, model: id.model, serial_number: orNull(system.SerialNumber), service_tag: system.SKU || null,
      asset_tag: system.AssetTag || null, bios_version: orNull(system.BiosVersion), power_state: orNull(system.PowerState),
      health: system.Status?.HealthRollup || system.Status?.Health || null },
    processors, memory, drives, network_ports, bios,
    bmc: { vendor: id.vendor, hostname: bmcNic.HostName || null, fqdn: bmcNic.FQDN || null, firmware_version: manager.FirmwareVersion ?? null,
      redfish_version: id.redfishVersion },
    firmware, network_adapters, pcie_devices, power_supplies,
  };
}

// ── storage layout (groundzero.redfish.storage) ────────────────────────────
function controllerKind(model, supported, drives) {
  const text = model.toUpperCase();
  if (text.includes("BOSS") || text.includes("M.2")) return "boot";
  if (text.includes("PERC S") || text.includes("SOFTWARE")) return "software";
  if (!supported.length && (text.includes("EXTENDER") || text.includes("NVME") || drives.every((d) => ["NVMe", "PCIe"].includes(d.protocol)))) return "passthrough";
  return supported.length ? "raid" : "other";
}
const round1 = (bytes) => Math.round(((bytes || 0) / 1e9) * 10) / 10;

async function readStorageLayout(c, systemPath, dell) {
  const system = await c.get(systemPath);
  const controllers = [];
  for (const storage of await optionalMembers(c, link(system, "Storage"))) {
    const sc = (storage.StorageControllers ?? [{}])[0] ?? {};
    const model = sc.Model || sc.Name || storage.Name || storage.Id || "";
    const supported = (sc.SupportedRAIDTypes ?? []).map(String);
    const raws = (await Promise.all((storage.Drives ?? []).map((d) => optional(() => c.get(d["@odata.id"]))))).filter(Boolean);
    const drives = raws.map((raw) => {
      const pd = raw.Oem?.Dell?.DellPhysicalDisk ?? {};
      return { id: raw.Id ?? raw["@odata.id"].split("/").pop(), path: raw["@odata.id"], name: orNull(raw.Name), model: (raw.Model ?? "").trim() || null,
        media: orNull(raw.MediaType), protocol: orNull(raw.Protocol), capacity_gb: round1(raw.CapacityBytes), state: pd.RaidStatus ?? null,
        hotspare: raw.HotspareType && raw.HotspareType !== "None" ? raw.HotspareType : null, volumes: [], health: raw.Status?.Health ?? null };
    });
    const volumesPath = link(storage, "Volumes");
    let applyTimes = [];
    let volumes = [];
    if (volumesPath) {
      const collection = await optional(() => c.get(volumesPath));
      if (collection) {
        applyTimes = [...(collection["@Redfish.OperationApplyTimeSupport"]?.SupportedValues ?? [])];
        const vraws = (await Promise.all((collection.Members ?? []).map((m) => optional(() => c.get(m["@odata.id"]))))).filter(Boolean);
        volumes = vraws.map((raw) => {
          const dv = raw.Oem?.Dell?.DellVolume ?? raw.Oem?.Dell?.DellVirtualDisk ?? {};
          const boot = dv.BootVolumeSource ?? dv.BootVolume;
          const type = raw.VolumeType ?? null;
          return { id: raw.Id ?? raw["@odata.id"].split("/").pop(), path: raw["@odata.id"], name: orNull(raw.Name), raid: raw.RAIDType ?? null,
            volume_type: type, capacity_gb: round1(raw.CapacityBytes),
            drives: (raw.Links?.Drives ?? []).filter((d) => d["@odata.id"]).map((d) => d["@odata.id"].split("/").pop()),
            raw: type === "RawDevice" || ((raw.RAIDType ?? null) === null && (type === null || type === "RawDevice")),
            boot: boot === undefined || boot === null ? null : ["true", "yes", "primary"].includes(String(boot).toLowerCase()) };
        });
      }
    }
    for (const v of volumes) for (const d of drives) if (v.drives.includes(d.id)) d.volumes.push(v.id);
    const mode = storage.Oem?.Dell?.DellController?.CurrentControllerMode ?? null;
    controllers.push({ id: storage.Id ?? "", path: storage["@odata.id"], name: orNull(storage.Name), model, kind: controllerKind(model, supported, drives),
      mode, mode_settable: "@Redfish.Settings" in storage && ![null, "NotSupported"].includes(mode), supported_raid: supported,
      volume_apply_times: applyTimes, drives, volumes });
  }
  let raid_service_actions = [];
  if (dell) {
    const service = await optional(() => c.get(`${systemPath}/Oem/Dell/DellRaidService`));
    if (service) raid_service_actions = [...new Set(Object.keys(service.Actions ?? {}).map((a) => a.replace(/^#/, "").split(".").pop()))].sort();
  }
  return { controllers, raid_service_actions };
}

async function readServer(address, username, password, opts) {
  const c = new Redfish(address, username, password, opts);
  const result = { address, name: address, inventory: null, storage: null, error: null };
  try {
    await c.login();
    try {
      const id = await detect(c);
      result.inventory = await collectInventory(c, id);
      result.storage = await readStorageLayout(c, id.systemPath, id.vendor === "dell");
      result.name = result.inventory.bmc.hostname || address;
    } finally {
      await c.logout();
    }
  } catch (e) {
    result.error = `${e.constructor?.name ?? "Error"}: ${e.message}`;
  }
  return result;
}

// ── comparison (groundzero.core.reports.compare) ───────────────────────────
function comparable(r) {
  const inv = r.inventory;
  const out = { Model: inv ? `${inv.system.manufacturer} ${inv.system.model}` : null };
  if (!inv) return { ...out, Hardware: "not read" };
  const sorted = (xs) => [...xs].sort();
  Object.assign(out, {
    BIOS: inv.system.bios_version, "BMC firmware": inv.bmc.firmware_version,
    Processors: `${sorted(new Set(inv.processors.map((p) => p.model))).join(", ")} x ${inv.processors.length}`,
    Memory: `${inv.memory.total_gib} GiB in ${inv.memory.dimm_count} DIMMs`, Drives: String(inv.drives.length),
    "Network adapters": sorted(inv.network_adapters.map((a) => a.model || a.name || a.id)).join(", ") || null,
    "Power supplies": sorted(inv.power_supplies.map((p) => p.model || p.name)).join(", ") || null,
    "Virtualization in BIOS": inv.bios.cpu_virtualization === null ? null : inv.bios.cpu_virtualization ? "on" : "off",
    "Boot mode": inv.bios.boot_mode,
  });
  for (const f of inv.firmware) out[`Firmware: ${f.name}`] = f.version;
  return out;
}
function compare(results) {
  const rows = new Map();
  for (const r of results) for (const [item, value] of Object.entries(comparable(r))) {
    if (!rows.has(item)) rows.set(item, {});
    rows.get(item)[r.name] = value ?? null;
  }
  return [...rows].map(([item, values]) => {
    const full = Object.fromEntries(results.map((r) => [r.name, values[r.name] ?? null]));
    return { item, values: full, differs: new Set(Object.values(full)).size > 1 };
  }).filter((c) => Object.values(c.values).some((v) => v !== null));
}

// ── HTML (the same page as the Python tool) ────────────────────────────────
const CSS = `:root{--line:#dde1e6;--muted:#5d6570;--warn:#fef3c7;--fail:#b42318}*{box-sizing:border-box}
body{font:14px/1.45 -apple-system,"Segoe UI",Roboto,sans-serif;color:#17191c;margin:0;background:#f5f6f8}
main{max-width:1100px;margin:0 auto;padding:28px 20px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:0 0 10px}
.sub{color:var(--muted);margin:0 0 20px}section{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:0 0 14px;break-inside:avoid}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}tr:last-child td{border-bottom:0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 18px;margin:0}
dt{color:var(--muted)}dd{margin:0}tr.differs td{background:var(--warn)}tr.differs td:first-child{font-weight:600}.error{color:var(--fail)}
footer{color:var(--muted);font-size:12px;margin-top:24px}@media print{body{background:#fff}section{border-color:#ccc}}`;
const esc = (v) => (v === null || v === undefined || v === "" ? "—" : String(v)).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" })[ch]);
const table = (headers, rows, mono = []) => (rows.length
  ? `<table><thead><tr>${headers.map((x) => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
      `<tr>${r.map((cell, i) => `<td${mono.includes(i) ? " class=mono" : ""}>${esc(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table>`
  : "");
const section = (title, content, key) => (content ? `<section data-section="${key}"><h2>${esc(title)}</h2>${content}</section>` : "");
const page = (title, sub, body) => `<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width'>`
  + `<title>${esc(title)}</title><style>${CSS}</style></head><body><main><h1>${esc(title)}</h1><p class=sub>${esc(sub)}</p>${body}`
  + `<footer>${esc(`gz-hwreport ${VERSION} (Node.js) · ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`)} · read-only from the BMC over Redfish</footer></main></body></html>`;

function serverHtml(r) {
  const inv = r.inventory;
  if (!inv) return page(r.name, r.address, `<section><p class=error>${esc(r.error)}</p></section>`);
  const s = inv.system;
  const kv = [["Model", `${s.manufacturer} ${s.model}`], ["Service tag", s.service_tag], ["Asset tag", s.asset_tag], ["BIOS", s.bios_version],
    ["Boot mode", inv.bios.boot_mode], ["Virtualization", { true: "on", false: "off" }[inv.bios.cpu_virtualization]],
    ["BMC", [inv.bmc.vendor, inv.bmc.firmware_version, inv.bmc.hostname].filter(Boolean).join(" · ")], ["BMC address", r.address],
    ["Power", s.power_state], ["Health", s.health]].filter(([, v]) => v);
  const storageRows = (r.storage?.controllers ?? []).map((c) => [c.model || c.id, c.kind, c.mode, c.drives.length,
    c.volumes.filter((v) => !v.raw).map((v) => `${v.name || v.id} ${v.raid} ${v.capacity_gb} GB`).join(", ") || "—"]);
  const fw = [...inv.firmware].sort((a, b) => a.name.localeCompare(b.name));
  const body = [
    section("System", `<dl>${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`, "system"),
    section("Processors", table(["Socket", "Model", "Cores", "Threads"], inv.processors.map((p) => [p.socket, p.model, p.cores, p.threads])), "processors"),
    section(`Memory · ${inv.memory.total_gib} GiB in ${inv.memory.dimm_count} DIMMs`, table(["Slot", "Size", "Type", "Speed", "Maker", "Part", "Health"],
      inv.memory.modules.map((m) => [m.slot || m.id, `${Math.floor(m.capacity_mib / 1024)} GiB`, m.type, m.speed_mhz ? `${m.speed_mhz} MHz` : null, m.manufacturer, m.part_number, m.health]), [5]), "memory"),
    section("Storage controllers and RAID volumes", table(["Controller", "Kind", "Mode", "Drives", "RAID volumes"], storageRows), "storage"),
    section("Drives", table(["Drive", "Model", "Size", "Type", "Firmware", "Controller"], inv.drives.map((d) => [d.id.split(":")[0], d.model,
      `${Math.round(d.capacity_bytes / 1e9)} GB`, [d.media_type, d.protocol].filter(Boolean).join(" "), d.firmware_version, d.controller]), [0, 4]), "drives"),
    section("Network adapters", table(["Adapter", "Maker", "Ports", "Firmware", "Health"], inv.network_adapters.map((a) => [a.model || a.name, a.manufacturer, a.ports, a.firmware_version, a.health]), [3]), "adapters"),
    section("Network ports", table(["Port", "Link", "Speed"], inv.network_ports.map((n) => [n.id, n.link_status, n.speed_mbps ? `${n.speed_mbps / 1000} Gb/s` : null]), [0]), "ports"),
    section("PCIe devices", table(["Device", "Kind", "Maker", "Firmware", "Health"], [...inv.pcie_devices].sort((a, b) => (a.device_class ?? "").localeCompare(b.device_class ?? ""))
      .map((x) => [x.name, x.device_class, x.manufacturer, x.firmware_version, x.health]), [3]), "pcie"),
    section("Power supplies", table(["Supply", "Model", "Capacity", "Firmware", "Health"], inv.power_supplies.map((p) => [p.name, p.model, p.capacity_watts ? `${p.capacity_watts} W` : null, p.firmware_version, p.health]), [3]), "psu"),
    section(`Firmware · ${fw.length} components`, table(["Component", "Version"], fw.map((f) => [f.name, f.version]), [1]), "firmware"),
  ].join("");
  return page(`${r.name}: hardware report`, `${s.manufacturer} ${s.model} · read ${inv.collected_at.slice(0, 16).replace("T", " ")} UTC`, body);
}

function comparisonHtml(results, files) {
  const good = results.filter((r) => r.inventory);
  const names = good.map((r) => r.name);
  const rows = good.length ? compare(good) : [];
  const differs = rows.filter((c) => c.differs);
  const cmp = (items) => (items.length ? `<table><thead><tr><th>Item</th>${names.map((n) => `<th>${esc(n)}</th>`).join("")}</tr></thead><tbody>${items.map((c) =>
    `<tr class="${c.differs ? "differs" : ""}"><td>${esc(c.item)}</td>${names.map((n) => `<td class=mono>${esc(c.values[n])}</td>`).join("")}</tr>`).join("")}</tbody></table>` : "");
  const link = (r) => (files[r.address] ? `<a href="${esc(files[r.address])}">${esc(r.name)}</a>` : esc(r.name));
  const servers = `<table><thead><tr><th>Server</th><th>BMC</th><th>Model</th></tr></thead><tbody>${results.map((r) =>
    `<tr><td>${link(r)}</td><td class=mono>${esc(r.address)}</td><td>${esc(r.inventory ? `${r.inventory.system.manufacturer} ${r.inventory.system.model}` : r.error)}</td></tr>`).join("")}</tbody></table>`;
  const failed = results.filter((r) => r.error).map((r) => `<li class=error>${esc(r.address)}: ${esc(r.error)}</li>`).join("");
  const body = section("Servers", servers, "servers") + (failed ? section("Couldn't be read", `<ul>${failed}</ul>`, "failed") : "")
    + section(differs.length ? `Differences · ${differs.length}` : "No differences", cmp(differs) || "<p>Every compared item is the same on every server.</p>", "differences")
    + section(`The same on every server · ${rows.length - differs.length}`, cmp(rows.filter((c) => !c.differs)), "same");
  return page("Hardware comparison", `${good.length} of ${results.length} servers read`, body);
}

// ── command line ────────────────────────────────────────────────────────────
const HELP = `usage: gz-hwreport [-h] [-f FILE] [-u USER] [-o OUT] [--verify-tls] [--parallel N] [bmc ...]

A hardware report straight from a server's BMC (read-only).

  bmc               BMC addresses (iDRAC, iLO, XCC, ...)
  -f, --file FILE   a file of BMCs, one per line: "address" or "address username"
  -u, --user USER   BMC username (default root, or GZ_BMC_USERNAME)
  -o, --out DIR     output folder (default ./hwreport-<date>)
  --verify-tls      check the BMC's TLS certificate
  --parallel N      BMCs read at once (default 4)
  --version         show the version

The BMC password comes from GZ_BMC_PASSWORD, or is asked for once.`;

function parseArgs(argv) {
  const opts = { bmc: [], file: null, user: process.env.GZ_BMC_USERNAME || "root", out: null, verifyTls: false, parallel: 4, replay: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => { if (i + 1 >= argv.length) throw new Error(`${a} needs a value`); return argv[++i]; };
    if (a === "-h" || a === "--help") { process.stdout.write(`${HELP}\n`); process.exit(0); }
    else if (a === "--version") { process.stdout.write(`gz-hwreport ${VERSION}\n`); process.exit(0); }
    else if (a === "-f" || a === "--file") opts.file = next();
    else if (a === "-u" || a === "--user") opts.user = next();
    else if (a === "-o" || a === "--out") opts.out = next();
    else if (a === "--verify-tls") opts.verifyTls = true;
    else if (a === "--parallel") opts.parallel = Math.max(1, Number(next()) || 1);
    else if (a === "--replay") opts.replay = next(); // a recorded BMC, for tests and demos
    else if (a.startsWith("-")) throw new Error(`unknown option ${a}`);
    else opts.bmc.push(a);
  }
  return opts;
}

async function askPassword() {
  if (!process.stdin.isTTY) return "";
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  process.stderr.write("BMC password: ");
  rl._writeToOutput = () => {}; // don't echo
  const answer = await new Promise((resolve) => rl.question("", resolve));
  rl.close();
  process.stderr.write("\n");
  return answer;
}

const slug = (name) => name.replace(/[^A-Za-z0-9._-]/g, "_");

async function main(argv) {
  let opts;
  try { opts = parseArgs(argv); } catch (e) { process.stderr.write(`gz-hwreport: ${e.message}\n${HELP}\n`); return 2; }
  const targets = opts.bmc.map((address) => ({ address, user: opts.user }));
  if (opts.file) {
    for (const line of readFileSync(opts.file, "utf8").split(/\r?\n/)) {
      const words = line.split("#")[0].trim().split(/\s+/).filter(Boolean);
      if (words.length) targets.push({ address: words[0], user: words[1] || opts.user });
    }
  }
  if (!targets.length) { process.stderr.write(`gz-hwreport: give at least one BMC address, or -f FILE\n${HELP}\n`); return 2; }
  const password = process.env.GZ_BMC_PASSWORD || (opts.replay ? "" : await askPassword());

  const results = new Array(targets.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(opts.parallel, targets.length) }, async () => {
    while (next < targets.length) {
      const i = next++;
      process.stderr.write(`Reading ${targets[i].address} …\n`);
      const replay = opts.replay && existsSync(join(opts.replay, "index.json")) ? opts.replay : null;
      results[i] = opts.replay && !replay
        ? { address: targets[i].address, name: targets[i].address, inventory: null, storage: null, error: `FileNotFoundError: ${opts.replay}` }
        : await readServer(targets[i].address, targets[i].user, password, { verifyTls: opts.verifyTls, replay });
    }
  }));
  const counts = {};
  for (const r of results) counts[r.name] = (counts[r.name] ?? 0) + 1;
  for (const r of results) if (counts[r.name] > 1) r.name = `${r.name} (${r.address})`;

  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const out = opts.out || `hwreport-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
  mkdirSync(out, { recursive: true });
  const files = {};
  const used = new Set();
  for (const r of results) {
    if (!r.inventory) { process.stderr.write(`  ${r.address}: ${r.error}\n`); continue; }
    let stem = slug(r.name);
    while (used.has(stem)) stem += "_";
    used.add(stem);
    writeFileSync(join(out, `${stem}.html`), serverHtml(r));
    writeFileSync(join(out, `${stem}.json`), `${JSON.stringify({ bmc: r.address, inventory: r.inventory, storage: r.storage }, null, 2)}\n`);
    files[r.address] = `${stem}.html`;
    process.stdout.write(`  ${r.name}: ${join(out, `${stem}.html`)}\n`);
  }
  if (results.length > 1) {
    writeFileSync(join(out, "index.html"), comparisonHtml(results, files));
    process.stdout.write(`  comparison: ${join(out, "index.html")}\n`);
  }
  const failed = results.filter((r) => !r.inventory).length;
  process.stdout.write(`${results.length - failed} of ${results.length} servers read into ${out}\n`);
  return failed ? 2 : 0;
}

export { readServer, collectInventory, readStorageLayout, compare, serverHtml, comparisonHtml };

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith("gz-hwreport.mjs")) {
  main(process.argv.slice(2)).then((code) => process.exit(code), (e) => { process.stderr.write(`gz-hwreport: ${e.stack || e}\n`); process.exit(1); });
}
