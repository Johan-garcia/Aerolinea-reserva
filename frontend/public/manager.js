// Panel gerencial (R9): muestra exactamente el valor de GET /analytics/occupancy.
import { api, cityOf, el, int, money, routePicker } from "./common.js";

const $ = (id) => document.getElementById(id);
const form = $("mgr");
const routeIn = $("route");
const monthIn = $("month");
const readout = $("readout");
let months = [];
let picker = null;

const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`;
const monthName = (m) => {
  const [y, mm] = m.split("-").map(Number);
  return new Date(y, mm - 1, 1).toLocaleDateString("es-CO", { month: "long", year: "numeric" });
};

routeIn.addEventListener("input", () => picker?.setValue(routeIn.value.replace(/\s+/g, "").toUpperCase()));

form.addEventListener("submit", (ev) => {
  ev.preventDefault();
  load(routeIn.value, monthIn.value);
});

async function load(rawRoute, rawMonth) {
  const route = rawRoute.replace(/\s+/g, "").toUpperCase();
  const month = rawMonth.trim();
  if (!/^[A-Z]{3}-[A-Z]{3}$/.test(route) || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) {
    readout.replaceChildren(el("p", { class: "notice error", role: "alert" },
      "Escribe la ruta como BOG-MDE y el mes como 2024-03."));
    return;
  }
  routeIn.value = route;
  monthIn.value = month;
  picker?.setValue(route);
  const btn = form.querySelector("[type=submit]");
  btn.disabled = true;
  readout.replaceChildren(el("p", { class: "empty" }, `Consultando ${route} en ${monthName(month)}…`));
  try {
    const r = await api("/analytics/occupancy", { params: { route, month } });
    render(r);
  } catch (e) {
    const msg = e.status === 404
      ? `No hay vuelos de ${route} en ${monthName(month)}. Revisa la ruta o elige otro mes del histórico.`
      : `No se pudo consultar la ocupación: ${e.message}`;
    readout.replaceChildren(el("p", { class: "notice error", role: "alert" }, msg));
  } finally {
    btn.disabled = false;
  }
}

function render(r) {
  const [o, d] = r.route.split("-");
  const sold = Math.round(r.occupancy * 100);
  const seats = [];
  // 4 filas de 25 asientos con pasillo en medio: 100 asientos, cada uno es 1 %.
  for (let row = 0; row < 4; row++) {
    if (row === 2) seats.push(el("div", { class: "aisle", "aria-hidden": "true" }));
    for (let c = 0; c < 25; c++) {
      const i = c * 4 + row;  // se llena por columnas, de la cabina hacia la cola
      seats.push(el("div", { class: `seat${i < sold ? " sold" : ""}` }));
    }
  }
  const box = el("div", { class: "readout reveal" },
    el("div", {},
      el("div", { class: "readout-route" }, `${o} ${cityOf(o)} a ${d} ${cityOf(d)}, ${monthName(r.month)}`),
      el("div", { class: "occupancy", testid: "occupancy-value" }, pct(r.occupancy)),
      el("dl", {},
        el("div", {}, el("dt", {}, "Sillas vendidas"), el("dd", {}, int.format(r.seats_sold))),
        el("div", {}, el("dt", {}, "Capacidad del mes"), el("dd", {}, int.format(r.seats_capacity))),
        r.revenue_cents != null && el("div", {}, el("dt", {}, "Ingresos confirmados"), el("dd", {}, money(r.revenue_cents))),
        r.cancellations != null && el("div", {}, el("dt", {}, "Cancelaciones"), el("dd", {}, int.format(r.cancellations))),
      ),
      el("p", { class: "source" }, `Fuente: ${r.source === "athena" ? "Amazon Athena" : "DuckDB local (sustituto de Athena)"}, tabla route_month_metrics.`),
    ),
    el("figure", { style: "margin:0" },
      el("div", { class: "cabin", role: "img",
        "aria-label": `${sold} de 100 asientos ocupados` },
        el("div", { class: "cabin-grid" }, seats)),
      el("figcaption", { class: "cabin-caption" },
        `Si el avión tuviera 100 sillas, ${sold} irían ocupadas.`),
    ),
  );
  readout.replaceChildren(box);
}

async function loadRanking() {
  const host = $("ranking");
  try {
    const rows = await api("/analytics/top-routes", { params: { limit: 10 } });
    if (!rows.length) { host.replaceChildren(el("p", { class: "empty" }, "Aún no hay datos curados.")); return; }
    const tip = el("div", { class: "tip", hidden: true, role: "tooltip" });
    const list = el("ol", { class: "bars" }, rows.map((r) => {
      const w = r.occupancy * 100;  // barras desde 0 %: la longitud es la ocupación real
      const pick = () => load(r.route, months[months.length - 1] || "");
      const li = el("li", { class: "bar-row", tabindex: "0",
        "aria-label": `${r.route}: ${pct(r.occupancy)} de ocupación`,
        onclick: pick, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } },
        onmouseenter: () => {
          tip.hidden = false;
          tip.textContent = `${r.route}: ${int.format(r.seats_sold)} de ${int.format(r.seats_capacity)} sillas`;
        },
        onmousemove: (e) => {
          const box = host.getBoundingClientRect();
          tip.style.left = `${e.clientX - box.left}px`;
          tip.style.top = `${e.clientY - box.top}px`;
        },
        onmouseleave: () => { tip.hidden = true; },
      },
        el("span", { class: "bar-route" }, r.route),
        el("span", { class: "bar-track" }, el("span", { class: "bar-fill", style: `display:block;width:${w.toFixed(2)}%` })),
        el("span", { class: "bar-value" }, pct(r.occupancy)),
      );
      return li;
    }));
    host.style.position = "relative";
    host.replaceChildren(list, tip);
  } catch (e) {
    host.replaceChildren(el("p", { class: "notice error" }, `No se pudo cargar el ranking: ${e.message}`));
  }
}

async function loadCatalog() {
  try {
    const c = await api("/analytics/catalog");
    months = c.months;
    // Una opción por ruta del histórico; al elegirla se consulta de inmediato
    // (con el mes escrito, o el más reciente si aún no hay mes).
    picker = routePicker({
      legend: "Elige una ruta",
      routes: c.routes,
      name: "mgr-route",
      onPick: (route) => {
        routeIn.value = route;
        if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(monthIn.value.trim()) && months.length) {
          monthIn.value = months[months.length - 1];
        }
        load(route, monthIn.value);
      },
    });
    $("mgr-routes").replaceChildren(picker.node);
    $("months").replaceChildren(...c.months.map((m) => el("option", { value: m })));
    if (!routeIn.value && c.routes.length) routeIn.placeholder = c.routes[0];
    if (!monthIn.value && c.months.length) monthIn.placeholder = c.months[c.months.length - 1];
  } catch { /* el panel funciona igual sin autocompletar */ }
}

loadCatalog();
loadRanking();
