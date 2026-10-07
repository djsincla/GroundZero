// Schema-driven forms: render an OS family's JSON Schema (from GET /os-families) as form fields, read the
// values back as JSON, and map API 422 errors (loc = [where, ...path]) onto the matching fields.
// Supports what the OS plugins use: objects/$ref, string, integer, boolean, enum (labels in x-enum-labels),
// string arrays, nullable.
import { h } from "./core.js";

function resolve(node, defs) {
  let n = node;
  if (n.$ref) {
    const target = defs[n.$ref.split("/").pop()] || {};
    n = { ...target, ...n, title: n.title ?? target.title, description: n.description ?? target.description };
    delete n.$ref;
  }
  if (n.anyOf) {
    const real = n.anyOf.filter((x) => x.type !== "null");
    if (real.length === 1) {
      const inner = resolve(real[0], defs);
      n = { ...inner, title: n.title ?? inner.title, description: n.description ?? inner.description,
        default: n.default, nullable: n.anyOf.length > real.length };
    }
  }
  return n;
}

export function schemaForm(schema, initial = {}, { idPrefix = "f", secretFields = [], where = null } = {}) {
  const defs = schema.$defs || {};
  const fields = new Map(); // "a.b" -> {wrap, error}
  const readers = [];
  const formError = h("div", { class: "form-error" });

  function fieldWrap(path, title, required, help, control, { inline = false } = {}) {
    const error = h("p", { class: "field-error", role: "alert" });
    const id = control.id;
    const label = inline
      ? h("label", { class: "inline", for: id }, control, title)
      : h("label", { for: id }, title, required ? h("span", { class: "req", "aria-hidden": "true" }, " *") : null);
    const wrap = h("div", { class: "field", "data-field": path.join(".") },
      label, inline ? null : control, help ? h("p", { class: "help" }, help) : null, error);
    fields.set(path.join("."), { wrap, error });
    return wrap;
  }

  function build(node, path, value, required, readInto) {
    const n = resolve(node, defs);
    const key = path[path.length - 1];
    const title = n.title || key;
    const id = `${idPrefix}-${path.join("-")}`;
    const current = value !== undefined ? value : n.default;

    if (n.type === "object" && n.properties) {
      const req = new Set(n.required || []);
      const childReaders = [];
      const children = Object.entries(n.properties).map(([k, child]) =>
        build(child, [...path, k], current?.[k], req.has(k), (fn) => childReaders.push([k, fn])));
      readInto(() => {
        const out = {};
        for (const [k, fn] of childReaders) { const v = fn(); if (v !== undefined) out[k] = v; }
        return out;
      });
      const fs = h("fieldset", { class: "group", "data-field": path.join(".") },
        h("legend", {}, title), n.description ? h("p", { class: "help" }, n.description) : null, children);
      const error = h("p", { class: "field-error", role: "alert" });
      fs.append(error);
      fields.set(path.join("."), { wrap: fs, error });
      return fs;
    }

    if (n.type === "boolean") {
      const input = h("input", { id, type: "checkbox", checked: Boolean(current) });
      readInto(() => input.checked);
      return fieldWrap(path, title, false, n.description, input, { inline: true });
    }

    if (n.enum) {
      const select = h("select", { id },
        n.nullable ? h("option", { value: "" }, "—") : null,
        n.enum.map((v, i) => h("option", { value: v, selected: v === current }, n["x-enum-labels"]?.[i] ?? v)));
      readInto(() => (select.value === "" ? (n.nullable ? null : undefined) : select.value));
      return fieldWrap(path, title, required, n.description, select);
    }

    if (n.type === "integer" || n.type === "number") {
      const input = h("input", { id, type: "number", min: n.minimum, max: n.maximum,
        step: n.type === "integer" ? 1 : "any", value: current ?? "" });
      readInto(() => {
        if (input.value === "") return n.nullable ? null : undefined;
        return Number(input.value);
      });
      return fieldWrap(path, title, required, n.description, input);
    }

    if (n.type === "array") {
      const input = h("input", { id, value: Array.isArray(current) ? current.join(", ") : "",
        placeholder: n.nullable ? "inherit" : "" });
      readInto(() => {
        const items = input.value.split(",").map((s) => s.trim()).filter(Boolean);
        if (!items.length && n.nullable) return null;
        return items;
      });
      const help = [n.description, "comma separated"].filter(Boolean).join(" · ");
      return fieldWrap(path, title, required, help, input);
    }

    const secret = secretFields.includes(key) || n.format === "password";
    const input = h("input", { id, type: secret ? "password" : "text", value: secret ? "" : current ?? "",
      autocomplete: secret ? "new-password" : "off", placeholder: n.nullable ? "inherit" : "",
      minlength: n.minLength, maxlength: n.maxLength });
    readInto(() => {
      const v = input.value.trim();
      if (v === "") return n.nullable ? null : undefined;
      return v;
    });
    return fieldWrap(path, title, required, n.description, input);
  }

  const topReaders = [];
  const req = new Set(schema.required || []);
  // Fields that share an "x-group" (e.g. an OVA's property categories) are shown together in a fieldset.
  const groups = new Map();
  const top = [];
  for (const [k, node] of Object.entries(schema.properties || {})) {
    const field = build(node, [k], initial?.[k], req.has(k), (fn) => topReaders.push([k, fn]));
    const group = node["x-group"];
    if (!group) { top.push(field); continue; }
    if (!groups.has(group)) {
      const fs = h("fieldset", { class: "group", "data-group": group }, h("legend", {}, group));
      groups.set(group, fs);
      top.push(fs);
    }
    groups.get(group).append(field);
  }
  const el = h("div", { class: "schema-form" }, formError, top);
  readers.push(...topReaders);

  return {
    el,
    value() {
      const out = {};
      for (const [k, fn] of readers) { const v = fn(); if (v !== undefined) out[k] = v; }
      return out;
    },
    clearErrors() {
      formError.replaceChildren();
      for (const { wrap, error } of fields.values()) { wrap.classList.remove("invalid"); error.textContent = ""; }
    },
    // Show API errors on their fields; returns true if every error found a field.
    setErrors(errors) {
      this.clearErrors();
      let allPlaced = true;
      for (const e of errors || []) {
        const loc = (e.loc || []).map(String);
        let path = where && loc[0] === where ? loc.slice(1) : loc.slice(loc[0] === "body" ? 1 : 0);
        let target = null;
        while (path.length && !(target = fields.get(path.join(".")))) path = path.slice(0, -1);
        if (target) {
          target.wrap.classList.add("invalid");
          target.error.textContent = [target.error.textContent, e.msg].filter(Boolean).join("; ");
        } else {
          allPlaced = false;
          formError.append(h("p", { class: "error" }, `${loc.join(".")}: ${e.msg}`));
        }
      }
      el.querySelector(".invalid input, .invalid select")?.focus();
      return allPlaced;
    },
  };
}
