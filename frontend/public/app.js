// Flujo del cliente: buscar -> elegir vuelo -> nombre del pasajero -> confirmación (R8).
import { api, cityOf, el, fmtDate, money, routePicker } from "./common.js";

const $ = (id) => document.getElementById(id);
const form = $("search");
const origin = $("origin");
const destination = $("destination");
const date = $("date");
const results = $("results");

let lastSearch = null;
let picker = null;

// Mañana como fecha por defecto (en hora local, no UTC).
const tomorrow = new Date(Date.now() + 86400000);
date.value = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, "0")}-${String(tomorrow.getDate()).padStart(2, "0")}`;

function syncCities() {
  picker?.setValue(`${origin.value}-${destination.value}`);
  $("origin-city").textContent = cityOf(origin.value) || (origin.value ? "Aeropuerto no listado" : "");
  $("destination-city").textContent = cityOf(destination.value) || (destination.value ? "Aeropuerto no listado" : "");
}
[origin, destination].forEach((i) => i.addEventListener("input", () => {
  i.value = i.value.replace(/[^a-z]/gi, "").toUpperCase();
  syncCities();
}));
syncCities();

// Rutas con vuelos disponibles: el cliente elige una en vez de escribir los códigos.
async function loadRoutes() {
  try {
    const routes = await api("/flights/routes");
    if (!routes.length) return;
    picker = routePicker({
      legend: "Elige una ruta",
      routes: routes.map((r) => r.route),
      name: "route",
      onPick: (route) => {
        [origin.value, destination.value] = route.split("-");
        syncCities();
        form.requestSubmit();
      },
    });
    $("route-picker").replaceChildren(picker.node);
    syncCities();
  } catch { /* sin lista de rutas se pueden escribir los códigos */ }
}
loadRoutes();

$("swap").addEventListener("click", () => {
  [origin.value, destination.value] = [destination.value, origin.value];
  syncCities();
});

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const o = origin.value.trim().toUpperCase();
  const d = destination.value.trim().toUpperCase();
  if (o.length !== 3 || d.length !== 3 || !date.value) {
    showNotice("Escribe los códigos de 3 letras de origen y destino, y elige una fecha.", true);
    return;
  }
  if (o === d) {
    showNotice("El origen y el destino son el mismo aeropuerto. Cambia uno de los dos.", true);
    return;
  }
  lastSearch = { origin: o, destination: d, date: date.value };
  await runSearch();
});

async function runSearch() {
  const btn = form.querySelector("[type=submit]");
  btn.disabled = true;
  results.hidden = false;
  results.replaceChildren(el("p", { class: "empty" }, "Buscando vuelos…"));
  try {
    const flights = await api("/flights/search", { params: lastSearch });
    renderFlights(flights);
  } catch (e) {
    showNotice(`No se pudo completar la búsqueda: ${e.message}`, true);
  } finally {
    btn.disabled = false;
  }
}

function showNotice(text, isError = false) {
  results.hidden = false;
  results.replaceChildren(el("p", { class: `notice${isError ? " error" : ""}`, role: isError ? "alert" : null }, text));
}

function renderFlights(flights) {
  const { origin: o, destination: d, date: day } = lastSearch;
  const head = el("div", { class: "results-head" },
    el("h2", {}, `${o} a ${d}`),
    el("p", {}, `${fmtDate(day)} · ${flights.length} ${flights.length === 1 ? "vuelo" : "vuelos"}`),
  );
  if (!flights.length) {
    results.replaceChildren(head, el("p", { class: "empty" },
      "No hay vuelos con sillas disponibles en esa fecha. Prueba con otro día o invierte la ruta."));
    return;
  }
  const list = el("ul", { class: "flight-list" }, flights.map(flightRow));
  results.replaceChildren(head, list);
}

function flightRow(f) {
  const low = f.seats_available <= 5;
  const li = el("li", { class: "flight", testid: "flight-row", "data-flight-id": f.flight_id });
  const stub = el("div", { class: "stub" },
    el("div", {}, el("div", { class: "code" }, f.flight_id), el("div", { class: "meta" }, f.route)),
    el("div", {}, el("div", {}, fmtDate(f.flight_date)),
      el("div", { class: `seats-left${low ? " low" : ""}` },
        `${f.seats_available} ${f.seats_available === 1 ? "silla disponible" : "sillas disponibles"}`)),
    el("div", { class: "price" }, money(f.price_cents), el("small", {}, "desde")),
    el("button", { class: "btn", type: "button", testid: "reserve-button",
      "aria-expanded": "false", onclick: () => openBooking(li, f) }, "Reservar"),
  );
  li.append(stub);
  return li;
}

function openBooking(li, f) {
  // Solo un formulario abierto a la vez: así los selectores del pasajero son únicos.
  document.querySelectorAll(".booking").forEach((b) => b.remove());
  document.querySelectorAll("[data-testid=reserve-button]").forEach((b) => b.setAttribute("aria-expanded", "false"));
  li.querySelector("[data-testid=reserve-button]").setAttribute("aria-expanded", "true");

  const nameId = `pax-${f.flight_id}`;
  const error = el("p", { class: "form-error", role: "alert", hidden: true });
  const name = el("input", { id: nameId, class: "input", testid: "passenger-name", required: true,
    autocomplete: "name", placeholder: "Como aparece en el documento" });
  const fare = el("div", { class: "fare-toggle", role: "radiogroup", "aria-label": "Clase" },
    el("label", {}, el("input", { type: "radio", name: "fare", value: "ECONOMY", checked: true }),
      el("span", {}, `Económica · ${money(f.price_cents)}`)),
    el("label", {}, el("input", { type: "radio", name: "fare", value: "BUSINESS" }),
      el("span", {}, `Ejecutiva · ${money(f.price_business_cents ?? Math.round(f.price_cents * 2.5))}`)),
  );
  const submit = el("button", { class: "btn", type: "submit", testid: "confirm-submit" }, "Confirmar reserva");

  const booking = el("form", { class: "booking reveal", novalidate: true },
    el("div", { class: "field" }, el("label", { for: nameId }, "Nombre del pasajero"), name),
    el("div", { class: "field" }, el("label", {}, "Clase"), fare),
    submit, error,
  );
  booking.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const passenger = name.value.trim();
    if (!passenger) {
      error.hidden = false;
      error.textContent = "Escribe el nombre del pasajero para continuar.";
      name.focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = "Confirmando…";
    error.hidden = true;
    try {
      const fareClass = booking.querySelector("input[name=fare]:checked").value;
      const r = await api("/reservations", { method: "POST",
        body: { flight_id: f.flight_id, passenger_name: passenger, fare_class: fareClass } });
      renderConfirmation(r, f);
    } catch (e) {
      submit.disabled = false;
      submit.textContent = "Confirmar reserva";
      error.hidden = false;
      error.textContent = e.status === 409
        ? "Este vuelo se acaba de llenar. Elige otro vuelo de la lista."
        : `No se pudo confirmar la reserva: ${e.message}`;
      if (e.status === 409) runSearch();
    }
  });
  li.append(booking);
  name.focus();
}

function renderConfirmation(r, f, titulo = "Reserva confirmada") {
  const route = r.route || f.route;
  const flightDate = r.flight_date || f.flight_date;
  const [o, d] = route.split("-");
  const pass = el("article", { class: "boarding-pass reveal", "aria-labelledby": "bp-title" },
    el("div", { class: "main" },
      el("span", { class: "status-ok", id: "bp-title" },
        el("span", { "aria-hidden": "true" }, "✓"), titulo),
      el("p", { class: "bp-route" }, o, el("span", { "aria-hidden": "true" }, "→"), d),
      el("dl", { class: "bp-grid" },
        el("div", {}, el("dt", {}, "Pasajero"), el("dd", {}, r.passenger_name)),
        el("div", {}, el("dt", {}, "Vuelo"), el("dd", {}, r.flight_id)),
        el("div", {}, el("dt", {}, "Fecha"), el("dd", {}, fmtDate(flightDate))),
        el("div", {}, el("dt", {}, "Clase"), el("dd", {}, r.fare_class === "BUSINESS" ? "Ejecutiva" : "Económica")),
        r.price_cents != null ? el("div", {}, el("dt", {}, "Precio"), el("dd", {}, money(r.price_cents))) : null,
      ),
    ),
    el("div", { class: "tear" },
      el("div", {}, el("span", { class: "meta" }, "Código de reserva"),
        el("strong", { class: "res-id", testid: "confirmation-id" }, r.reservation_id)),
      el("button", { class: "btn ghost", type: "button", onclick: () => runSearch() }, "Reservar otro vuelo"),
    ),
  );
  results.hidden = false;
  results.replaceChildren(pass);
  pass.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Consultar una reserva ya hecha con su código (GET /reservations/{id}, R3).
const lookup = $("lookup");
const lookupId = $("lookup-id");
lookup.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const code = lookupId.value.trim().toUpperCase();
  if (!code) {
    showNotice("Escribe el código de la reserva, por ejemplo R7K334UNY5S8.", true);
    return;
  }
  const btn = lookup.querySelector("[type=submit]");
  btn.disabled = true;
  try {
    const r = await api(`/reservations/${encodeURIComponent(code)}`);
    renderConfirmation(r, {}, "Reserva encontrada");
  } catch (e) {
    showNotice(e.status === 404 ? `No existe una reserva con el código ${code}.` : `No se pudo consultar la reserva: ${e.message}`, true);
  } finally {
    btn.disabled = false;
  }
});
