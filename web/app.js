// Urbanify Anything — eine Seite, kein Build.
// MapLibre 5: Cluster-Methoden geben Promises zurück, keine Callbacks.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// Links kommen aus fremden Feeds: nur http(s) wird zum href.
const link = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "");
const num = (n) => Number(n || 0).toLocaleString("de-DE");
const api = (path, opt) => fetch(path, opt).then((r) => (r.ok ? r.json() : r.json().then((e) => Promise.reject(e.detail || r.statusText))));

const state = { slug: null, report: null, tab: "sources", filter: null, timer: null };
const EMPTY = { type: "FeatureCollection", features: [] };

// Eine Quelle für die Farben: app.css. Die Karte liest dieselben Token, damit
// Oberfläche und Zonen nicht auseinanderlaufen — und der Dunkelmodus mitkommt.
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
const C = { zone1: css("--zone1"), zone2: css("--zone2"), zone3: css("--zone3"),
  accent: css("--accent"), ink: css("--ink-strong"), soft: css("--ink-soft"), raised: css("--bg-raised") };
// Innen dicht, außen leise: die innerste Zone ist die, in der man wirklich wohnt.
const byZone = (a, b, c) => ["match", ["get", "minutes"], 15, a, 30, b, c];

const map = new maplibregl.Map({
  container: "map",
  style: `https://tiles.openfreemap.org/styles/${dark ? "dark" : "positron"}`,
  center: [10.4, 51.2], zoom: 5, attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

const ready = new Promise((res) => map.on("load", res));
ready.then(() => {
  map.addSource("zones", { type: "geojson", data: EMPTY });
  map.addSource("sites", { type: "geojson", data: EMPTY });
  map.addSource("events", { type: "geojson", data: EMPTY, cluster: true, clusterRadius: 42, clusterMaxZoom: 15 });

  map.addLayer({ id: "zone-fill", type: "fill", source: "zones", filter: ["==", ["get", "profile"], "auto"],
    paint: { "fill-color": byZone(C.zone1, C.zone2, C.zone3),
      "fill-opacity": byZone(0.14, 0.1, 0.07) } });
  map.addLayer({ id: "zone-line", type: "line", source: "zones", filter: ["==", ["get", "profile"], "auto"],
    paint: { "line-color": byZone(C.zone1, C.zone2, C.zone3),
      "line-width": ["match", ["get", "minutes"], 60, 1.2, 0.75], "line-opacity": 0.9 } });
  map.addLayer({ id: "zone-ebike", type: "line", source: "zones", layout: { visibility: "none" },
    filter: ["all", ["==", ["get", "profile"], "ebike"], ["==", ["get", "minutes"], 60]],
    // Die E-Bike-Stunde ist keine weitere Zone, sondern ein anderer Maßstab —
    // darum neutral gestrichelt statt in der Zonenfamilie.
    paint: { "line-color": C.ink, "line-width": 1.8, "line-dasharray": [2.5, 1.5], "line-opacity": 0.8 } });
  map.addLayer({ id: "sites", type: "circle", source: "sites", layout: { visibility: "none" },
    paint: { "circle-radius": 3.5, "circle-stroke-width": 0.6, "circle-stroke-color": C.raised,
      "circle-color": ["match", ["get", "status"], "feed", C.zone1, "nur-html", C.accent, C.soft],
      "circle-opacity": ["match", ["get", "status"], "feed", 1, "nur-html", 1, 0.45] } });
  map.addLayer({ id: "clusters", type: "circle", source: "events", filter: ["has", "point_count"],
    paint: { "circle-color": C.accent, "circle-opacity": 0.88,
      "circle-radius": ["step", ["get", "point_count"], 11, 25, 15, 150, 20, 1000, 27] } });
  map.addLayer({ id: "cluster-count", type: "symbol", source: "events", filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11, "text-font": ["Noto Sans Bold"] },
    paint: { "text-color": "#fff" } });
  map.addLayer({ id: "events", type: "circle", source: "events", filter: ["!", ["has", "point_count"]],
    paint: { "circle-radius": 5, "circle-color": C.accent, "circle-stroke-width": 1.2, "circle-stroke-color": C.raised } });

  map.on("click", "clusters", async (e) => {
    const f = e.features[0], src = map.getSource("events");
    if (map.getZoom() >= 15) {
      const leaves = await src.getClusterLeaves(f.properties.cluster_id, 60, 0);
      popup(f.geometry.coordinates, leaves.map((l) => l.properties));
    } else {
      const zoom = await src.getClusterExpansionZoom(f.properties.cluster_id);
      map.easeTo({ center: f.geometry.coordinates, zoom });
    }
  });
  map.on("click", "events", (e) => popup(e.features[0].geometry.coordinates, e.features.map((f) => f.properties)));
  map.on("click", "sites", (e) => {
    const p = e.features[0].properties;
    new maplibregl.Popup().setLngLat(e.features[0].geometry.coordinates).setHTML(
      `<h3>${esc(p.name)}</h3><p>${esc(p.kind)} · ${esc(p.status)}${p.platform ? " · " + esc(p.platform) : ""}</p>
       <p><a href="${link(p.url)}" target="_blank" rel="noopener">${esc(p.url)}</a></p>`).addTo(map);
  });
  for (const id of ["clusters", "events", "sites"]) {
    map.on("mouseenter", id, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", id, () => (map.getCanvas().style.cursor = ""));
  }
});

function when(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });
  return iso.endsWith("T00:00:00") ? day : `${day} ${iso.slice(11, 16)}`;
}

function popup(lngLat, items) {
  const head = items[0];
  const list = items.slice(0, 60).map((p) =>
    `<li>${when(p.starts_at)} — ${link(p.url) ? `<a href="${link(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title)}
     <br><span class="quelle">${esc(p.source_name)}</span></li>`).join("");
  new maplibregl.Popup({ maxWidth: "320px" }).setLngLat(lngLat).setHTML(
    `<h3>${esc(head.venue || "Ort")}</h3><p>${items.length} Termin${items.length > 1 ? "e" : ""}</p><ul>${list}</ul>`).addTo(map);
}

// ------------------------------------------------------------- Seitenleiste

async function loadPlaces() {
  const places = await api("/api/places");
  $("#places").innerHTML = places.map((p) =>
    `<button data-slug="${esc(p.slug)}" class="${p.slug === state.slug ? "on" : ""}">${esc(p.name)}${p.running ? " …" : ""}</button>`).join("");
  return places;
}

async function open(slug, fly = true) {
  state.slug = slug; state.filter = null;
  // Erst der Befund, dann die Karte: die Liste wartet nicht auf WebGL.
  const rep = state.report = await api(`/api/places/${slug}/report`);
  render();
  loadPlaces();
  clearTimeout(state.timer);
  if (rep.running) state.timer = setTimeout(() => open(slug, false), 5000);
  const [zones, sites] = await Promise.all([api(`/api/places/${slug}/zones`), api(`/api/places/${slug}/sites`)]);
  await ready;
  if (state.slug !== slug) return;
  map.getSource("zones").setData(zones);
  map.getSource("sites").setData(sites);
  await loadEvents();
  if (fly && zones.features.length) {
    const b = new maplibregl.LngLatBounds();
    const walk = (c) => (typeof c[0] === "number" ? b.extend(c) : c.forEach(walk));
    zones.features.filter((f) => f.properties.profile === "auto").forEach((f) => walk(f.geometry.coordinates));
    map.fitBounds(b, { padding: 40, duration: 600 });
  }
}

async function loadEvents() {
  await ready;
  const q = state.filter ? `?${state.filter.key}=${encodeURIComponent(state.filter.value)}` : "";
  map.getSource("events").setData(await api(`/api/places/${state.slug}/events${q}`));
  const f = $("#filter");
  f.hidden = !state.filter;
  if (state.filter) f.innerHTML = `Karte zeigt nur: <b>${esc(state.filter.label)}</b> · <a id="clear">alle zeigen</a>`;
}

function render() {
  const r = state.report, t = r.totals, s = r.sites;
  const prog = $("#progress");
  prog.hidden = !r.running && r.progress?.step !== "fehler";
  prog.className = r.progress?.step === "fehler" ? "error" : "";
  prog.textContent = r.running ? `Erhebung läuft — ${r.progress?.step || ""}: ${r.progress?.text || ""}` : r.progress?.text || "";

  $("#summary").hidden = $("#tabs").hidden = false;
  const withEvents = r.sources.filter((x) => x.events).length;
  $("#tiles").innerHTML = [
    [t.inside, "Termine in der Stunde"], [withEvents, "Quellen mit Terminen"], [t.distinct_inside, "ohne Dubletten"],
  ].map(([n, label]) => `<div class="tile"><b>${num(n)}</b><span>${label}</span></div>`).join("");
  $("#found").innerHTML =
    `<b>${esc(r.place.name)}</b>${r.window.since ? `, ${esc(r.window.since)} bis ${esc(r.window.until)}` : ""}. ` +
    `OpenStreetMap kennt hier <b>${num(s.total)}</b> Websites von Häusern: <b>${num(s.feed)}</b> lassen sich ` +
    `maschinell fragen, <b>${num(s["nur-html"])}</b> haben ein Programm nur für Menschen, ` +
    `${num(s.nichts)} zeigen keines` + (s.offen ? `, ${num(s.offen)} sind noch ungeprüft.` : ".");

  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === state.tab));
  const panel = $("#panel");
  if (state.tab === "sources") {
    const max = Math.max(1, ...r.sources.map((x) => x.inside));
    const rows = r.sources.filter((x) => x.events || x.origin === "katalog");
    panel.innerHTML = rows.map((x) => {
      const cats = Object.entries(x.categories).slice(0, 3).map(([c, n]) => `${esc(c)} ${num(n)}`).join(" · ");
      const bad = x.status === "ok" ? "" : `<span class="tag ${x.status === "offen" ? "" : "bad"}">${esc(x.status)}</span>`;
      const extra = [x.outside ? `${num(x.outside)} außerhalb` : "", x.unplaced ? `${num(x.unplaced)} ohne Ort` : "",
        x.inside ? `${num(x.unique)} nur hier` : ""].filter(Boolean).join(" · ");
      return `<div class="row ${state.filter?.value === x.slug ? "on" : ""}" data-source="${esc(x.slug)}" data-label="${esc(x.name)}">
        <span class="name">${esc(x.name)}</span><span class="n">${num(x.inside)}</span>
        <span class="sub"><span class="tag ${esc(x.origin)}">${esc(x.origin)}</span><span class="tag">${esc(x.kind)}</span>${bad}${cats}</span>
        <span class="sub">${extra}${x.error ? " · " + esc(x.error) : ""}${x.note && x.origin === "katalog" ? " · " + esc(x.note) : ""}</span>
        <span class="bar"><i style="width:${(100 * x.inside) / max}%"></i></span></div>`;
    }).join("") || `<p class="hint">Noch keine Quelle mit Terminen.</p>`;
  } else if (state.tab === "categories") {
    const max = Math.max(1, ...r.categories.map((c) => c.events));
    panel.innerHTML = r.categories.map((c) =>
      `<div class="row ${state.filter?.value === c.category ? "on" : ""}" data-category="${esc(c.category)}">
        <span class="name">${esc(c.category)}</span><span class="n">${num(c.events)}</span>
        <span class="sub">${num(c.sources)} Quellen · ${c.top.map((x) => `${esc(x.name)} (${num(x.n)})`).join(", ")}</span>
        <span class="bar"><i style="width:${(100 * c.events) / max}%"></i></span></div>`).join("");
  } else if (state.tab === "overlap") {
    panel.innerHTML = `<p class="hint">Derselbe Termin in zwei Quellen: gleicher Tag, gleicher Titelanfang, gleicher Ort. Eine Näherung, die eher zu wenig findet.</p>` +
      (r.overlap.map((o) => `<div class="row static"><span class="name">${esc(o.a_name)}</span><span class="n">${num(o.n)}</span>
        <span class="sub">und ${esc(o.b_name)}</span></div>`).join("") || `<p class="hint">Keine gefunden.</p>`);
  } else {
    panel.innerHTML = `<p class="hint">${num(s["nur-html"])} Häuser mit Programmseite, aber ohne Feed — die Liste für die nächsten Adapter. Gezeigt sind die nächstgelegenen.</p>` +
      r.html_only.map((h) => `<div class="row static"><span class="name">${esc(h.name)}</span><span class="n">${h.minutes}′</span>
        <span class="sub"><span class="tag">${esc(h.kind)}</span><a href="${link(h.note || h.url)}" target="_blank" rel="noopener">${esc(h.note || h.url)}</a></span></div>`).join("");
  }
}

// ---------------------------------------------------------------- Ereignisse

$("#search").addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = $("#query").value.trim();
  if (!query) return;
  const prog = $("#progress");
  prog.hidden = false; prog.className = ""; prog.textContent = `Suche „${query}" …`;
  try {
    const res = await api("/api/survey", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query }) });
    $("#query").value = "";
    map.flyTo({ center: [res.place.lon, res.place.lat], zoom: 9 });
    open(res.slug, false);
  } catch (err) { prog.className = "error"; prog.textContent = String(err); }
});
$("#places").addEventListener("click", (e) => e.target.dataset.slug && open(e.target.dataset.slug));
$("#tabs").addEventListener("click", (e) => { if (e.target.dataset.tab) { state.tab = e.target.dataset.tab; render(); } });
$("#panel").addEventListener("click", async (e) => {
  const row = e.target.closest(".row");
  if (!row || e.target.closest("a")) return;
  const next = row.dataset.source ? { key: "source", value: row.dataset.source, label: row.dataset.label }
    : row.dataset.category ? { key: "category", value: row.dataset.category, label: row.dataset.category } : null;
  if (!next) return;
  state.filter = state.filter?.value === next.value ? null : next;
  await loadEvents(); render();
});
$("#legend").addEventListener("click", async (e) => { if (e.target.id === "clear") { state.filter = null; await loadEvents(); render(); } });
const toggle = (box, layers) => $(box).addEventListener("change", (e) =>
  layers.forEach((l) => map.setLayoutProperty(l, "visibility", e.target.checked ? "visible" : "none")));
toggle("#show-zones", ["zone-fill", "zone-line"]);
toggle("#show-ebike", ["zone-ebike"]);
toggle("#show-events", ["clusters", "cluster-count", "events"]);
toggle("#show-sites", ["sites"]);

loadPlaces().then((places) => {
  const wanted = new URLSearchParams(location.search).get("ort");
  const first = places.find((p) => p.slug === wanted) || places[0];
  if (first) open(first.slug);
});
