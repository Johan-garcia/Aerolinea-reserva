// Utilidades compartidas por la página de clientes y el panel gerencial.
export const API = "/api";

export const AIRPORTS = {
  BOG: "Bogotá", MDE: "Medellín", CLO: "Cali", CTG: "Cartagena", BAQ: "Barranquilla",
  SMR: "Santa Marta", BGA: "Bucaramanga", PEI: "Pereira", CUC: "Cúcuta", ADZ: "San Andrés",
  LET: "Leticia", PSO: "Pasto",
};

export const cityOf = (code) => AIRPORTS[(code || "").toUpperCase()] || "";

const usd = new Intl.NumberFormat("es-CO", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const money = (cents) => usd.format(cents / 100);
export const int = new Intl.NumberFormat("es-CO");

export function fmtDate(iso, opts = { weekday: "short", day: "numeric", month: "short", year: "numeric" }) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("es-CO", opts);
}

export async function api(path, { method = "GET", body, params } = {}) {
  const url = new URL(API + path, window.location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  if (!res.ok) {
    const detail = data && (typeof data.detail === "string" ? data.detail : null);
    const err = new Error(detail || `El servidor respondió ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "testid") node.dataset.testid = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

// Grupo de opciones de ruta: un radio por ruta, rotulado con códigos y ciudades.
// onPick(route) se llama cuando el usuario elige; setValue(route) marca una opción desde fuera.
export function routePicker({ legend, routes, name, onPick }) {
  const options = routes.map((route) => {
    const [o, d] = route.split("-");
    const input = el("input", { type: "radio", name, value: route,
      onchange: () => { if (input.checked) onPick(route); } });
    return el("label", { class: "route-opt" }, input,
      el("span", { class: "route-opt-body" },
        el("span", { class: "route-opt-code" }, `${o}–${d}`),
        el("span", { class: "route-opt-cities" }, `${cityOf(o) || o} a ${cityOf(d) || d}`)));
  });
  const node = el("fieldset", { class: "route-options" },
    el("legend", {}, legend),
    el("div", { class: "route-list" }, options));
  const setValue = (route) => {
    node.querySelectorAll("input").forEach((i) => { i.checked = i.value === route; });
  };
  return { node, setValue };
}
