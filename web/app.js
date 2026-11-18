// Urbanify Anything — eine Seite, kein Build.
// MapLibre 5: Cluster-Methoden geben Promises zurück, keine Callbacks.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// Links kommen aus fremden Feeds: nur http(s) wird zum href.
const link = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "");
const num = (n) => Number(n || 0).toLocaleString("de-DE");
const api = (path, opt) => fetch(path, opt).then((r) => (r.ok ? r.json() : r.json().then((e) => Promise.reject(e.detail || r.statusText))));

const put = (path, body, method = "PUT") => api(path, { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });
const saved = (k, d) => { try { return JSON.parse(localStorage.getItem("urbanify." + k)) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem("urbanify." + k, JSON.stringify(v)); } catch { /* privates Fenster */ } };

const state = { slug: null, report: null, tab: "sources", filter: null, timer: null,
  // Die Karte zum Leben: was man sehen will. Verkehrsmittel, 18+ und Interessen
  // stehen im Profil auf dem Server, der Rest ist Sache dieses Browsers.
  mode: saved("mode", "karte"), window: saved("window", "14tage"), visibility: saved("visibility", "all"),
  sort: saved("sort", "zeit"), cats: new Set(), kids: false, onlyMarked: false,
  profile: "auto", adult: false, interests: new Set(), categories: [],
  events: [], counts: null, detail: null };
const live = () => state.mode === "karte";
const EMPTY = { type: "FeatureCollection", features: [] };

// Eine Quelle für die Farben: app.css. Die Karte liest dieselben Token, damit
// Oberfläche und Zonen nicht auseinanderlaufen — und der Dunkelmodus mitkommt.
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
const C = { zone1: css("--zone1"), zone2: css("--zone2"), zone3: css("--zone3"),
  accent: css("--accent"), ink: css("--ink-strong"), soft: css("--ink-soft"), raised: css("--bg-raised"),
  kids: css("--kids"), adult: css("--adult"), marked: css("--marked") };
// Kinderprogramm und 18+ in eigener Farbe, alles andere Terracotta.
const EVENT_COLOR = ["case", ["==", ["get", "is_adult"], true], C.adult, ["==", ["get", "is_kids"], true], C.kids, C.accent];
// Groß und mit Zeichen, was hervorgehoben oder vorgemerkt ist; der Rest klein.
const LOUD = ["any", ["==", ["get", "bucket"], "highlight"], ["==", ["get", "bookmarked"], true]];
const single = ["!", ["has", "point_count"]];
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
  map.addSource("events", { type: "geojson", data: EMPTY, cluster: true, clusterRadius: 42, clusterMaxZoom: 15,
    // Ein Kreis weiß, ob etwas Vorgemerktes in ihm steckt — sonst verschwindet es darin.
    clusterProperties: { marked: ["+", ["case", ["==", ["get", "bookmarked"], true], 1, 0]] } });

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
  map.addLayer({ id: "cluster-ring", type: "circle", source: "events",
    filter: ["all", ["has", "point_count"], [">", ["get", "marked"], 0]],
    paint: { "circle-color": "rgba(0,0,0,0)", "circle-stroke-width": 2.5, "circle-stroke-color": C.marked,
      "circle-radius": ["step", ["get", "point_count"], 15, 25, 19, 150, 24, 1000, 31] } });
  map.addLayer({ id: "cluster-count", type: "symbol", source: "events", filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11, "text-font": ["Noto Sans Bold"] },
    paint: { "text-color": "#fff" } });
  map.addLayer({ id: "marked-ring", type: "circle", source: "events",
    filter: ["all", single, ["==", ["get", "bookmarked"], true]],
    paint: { "circle-radius": 13, "circle-color": "rgba(0,0,0,0)", "circle-stroke-width": 2.5, "circle-stroke-color": C.marked } });
  map.addLayer({ id: "events", type: "circle", source: "events", filter: single,
    paint: { "circle-radius": ["case", LOUD, 9, 4.5], "circle-color": EVENT_COLOR,
      "circle-opacity": ["case", ["==", ["get", "bucket"], "hidden"], 0.45, 1],
      "circle-stroke-width": 1.2, "circle-stroke-color": C.raised } });
  installIcons(map, "#ffffff").then(() => map.addLayer({ id: "event-icons", type: "symbol", source: "events",
    filter: ["all", single, LOUD],
    layout: { "icon-image": ["concat", "cat-", ["get", "category"]], "icon-size": 0.5, "icon-allow-overlap": true } }));

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

let lastPopup = null;
function popup(lngLat, items) {
  const head = items[0];
  // Was man angekreuzt hat, steht in der Vorschau eines Kreises vorn.
  if (live()) items = [...items].sort(mineFirst);
  const list = items.slice(0, 60).map((p) =>
    `<li>${when(p.starts_at)} — ${live() ? `<a href="#" data-event="${Number(p.id)}">${esc(p.title)}</a>`
      : link(p.url) ? `<a href="${link(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title)}
     <br><span class="quelle">${esc(p.source_name)}</span></li>`).join("");
  lastPopup?.remove();
  lastPopup = new maplibregl.Popup({ maxWidth: "320px" }).setLngLat(lngLat).setHTML(
    `<h3>${esc(head.venue || "Ort")}</h3><p>${items.length} Termin${items.length > 1 ? "e" : ""}</p><ul>${list}</ul>`).addTo(map);
  lastPopup.getElement().addEventListener("click", (e) => {
    const id = e.target.dataset?.event;
    if (id) { e.preventDefault(); openDetail(Number(id)); }
  });
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
  // Solange noch nichts da ist, gibt es nichts zum Leben: dann die Erhebung.
  if (!rep.totals.inside && state.mode === "karte") state.mode = "erhebung";
  closeDetail();
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
  if (!state.slug) return;
  const q = new URLSearchParams();
  if (live()) {
    q.set("window", state.window); q.set("profile", state.profile); q.set("visibility", state.visibility);
    q.set("adult", state.adult);
    if (state.kids) q.set("kids", "true");
    if (state.onlyMarked) q.set("bookmarked", "true");
    if (state.cats.size) q.set("category", [...state.cats].join(","));
  } else if (state.filter) q.set(state.filter.key, state.filter.value);
  const slug = state.slug, fc = await api(`/api/places/${slug}/events?${q}`);
  if (slug !== state.slug) return;
  map.getSource("events").setData(fc);
  state.events = fc.features.map((x) => ({ ...x.properties, lngLat: x.geometry.coordinates }));
  state.counts = fc.properties.counts;
  // Im Modus „Karte" gelten die Zonen des gewählten Verkehrsmittels.
  const main = live() ? state.profile : "auto", other = main === "auto" ? "ebike" : "auto";
  for (const id of ["zone-fill", "zone-line"]) map.setFilter(id, ["==", ["get", "profile"], main]);
  map.setFilter("zone-ebike", ["all", ["==", ["get", "profile"], other], ["==", ["get", "minutes"], 60]]);
  $("#other-hour").textContent = other === "ebike" ? "E-Bike-Stunde" : "Auto-Stunde";
  if (live()) { renderLive(); loadMarked(); }
  const f = $("#filter");
  f.hidden = !state.filter || live();
  if (state.filter) f.innerHTML = `Karte zeigt nur: <b>${esc(state.filter.label)}</b> · <a id="clear">alle zeigen</a>`;
}

function render() {
  const r = state.report, t = r.totals, s = r.sites;
  const prog = $("#progress");
  prog.hidden = !r.running && r.progress?.step !== "fehler";
  prog.className = r.progress?.step === "fehler" ? "error" : "";
  prog.textContent = r.running ? `Erhebung läuft — ${r.progress?.step || ""}: ${r.progress?.text || ""}` : r.progress?.text || "";

  $("#mode").hidden = false;
  document.querySelectorAll("#mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === state.mode));
  $("#live").hidden = !live(); $("#survey-view").hidden = live();
  document.body.classList.toggle("live", live());
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
  layers.forEach((l) => map.getLayer(l) && map.setLayoutProperty(l, "visibility", e.target.checked ? "visible" : "none")));
toggle("#show-zones", ["zone-fill", "zone-line"]);
toggle("#show-ebike", ["zone-ebike"]);
toggle("#show-events", ["clusters", "cluster-count", "events", "marked-ring", "cluster-ring", "event-icons"]);
toggle("#show-sites", ["sites"]);

// ================================================================ Karte
// Vormerken, urteilen, schärfen. Alles hier ist umkehrbar: nichts, was man
// anklickt, löscht einen Termin.

const CAT_LABEL = { "markt/fest": "markt & fest", draussen: "draußen", kurs: "kurse", vortrag: "vorträge", kulinarik: "essen & trinken" };
const cat = (c) => CAT_LABEL[c] || c || "sonstiges";
// Interessen wirken auf die Reihenfolge und auf nichts sonst.
const isMine = (p) => state.interests.has(p.category);
const mineFirst = (a, b) => Number(isMine(b)) - Number(isMine(a));
const zoneOf = (p) => (p.zone ? `${p.zone}′` : "");
function kidsLabel(p) {
  if (!p.is_kids) return "";
  const lo = p.age_min, hi = p.age_max;
  return lo != null && hi != null ? `Kinder ${lo}–${hi} J.` : lo != null ? `Kinder ab ${lo} J.` : "Kinder";
}
function range(p) {
  if (!p.ends_at || p.ends_at.slice(0, 10) === p.starts_at.slice(0, 10)) return when(p.starts_at);
  return `${when(p.starts_at)} – ${when(p.ends_at)}`;
}

let toastTimer = null;
function toast(text, undo) {
  const t = $("#toast");
  t.innerHTML = esc(text) + (undo ? ` <button class="linklike">zurücknehmen</button>` : "");
  t.hidden = false;
  if (undo) t.querySelector("button").onclick = () => { t.hidden = true; undo(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 6000);
}

function seg(id, key, after) {
  const el = $(id);
  const paint = () => el.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === state[key]));
  el.addEventListener("click", async (e) => {
    const v = e.target.dataset?.v;
    if (!v || v === state[key]) return;
    state[key] = v; keep(key, v); paint();
    await after?.(v);
  });
  paint();
  return paint;
}

function renderLive() {
  const c = state.counts || { highlight: 0, normal: 0, hidden: 0 };
  $("#buckets").textContent = `${num(c.highlight)} hervorgehoben · ${num(c.normal)} im Bestand · ${num(c.hidden)} ausgeblendet`
    + (state.visibility === "highlights" && !c.highlight ? " — noch nichts hervorgehoben: kuratieren oder eine Regel anlegen." : "");
  $("#cats").innerHTML = state.categories.map((k) =>
    `<button data-cat="${esc(k)}" class="${state.cats.has(k) ? "on" : ""}${state.interests.has(k) ? " mine" : ""}">${esc(cat(k))}</button>`).join("");
  $("#cat-all").hidden = !state.cats.size;

  const items = [...state.events];
  if (state.sort === "rang") items.sort((a, b) => mineFirst(a, b) || b.score - a.score || a.starts_at.localeCompare(b.starts_at));
  else items.sort((a, b) => a.starts_at.slice(0, 10).localeCompare(b.starts_at.slice(0, 10)) || mineFirst(a, b) || a.starts_at.localeCompare(b.starts_at));
  $("#list-count").textContent = `${num(items.length)} Termin${items.length === 1 ? "" : "e"}`;
  let day = "";
  $("#list").innerHTML = items.slice(0, 400).map((p) => {
    const d = p.starts_at.slice(0, 10);
    const head = state.sort === "zeit" && d !== day
      ? `<li class="day">${esc(new Date(p.starts_at).toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" }))}</li>` : "";
    day = d;
    return head + row(p);
  }).join("") + (items.length > 400 ? `<li class="muted more">… und ${num(items.length - 400)} weitere. Enger filtern.</li>` : "")
    || `<li class="muted more">Nichts in diesem Ausschnitt.</li>`;
}

const star = (p) => `<button class="star${p.bookmarked ? " on" : ""}" data-mark="${Number(p.id)}" title="${p.bookmarked ? "nicht mehr vormerken" : "vormerken"}" aria-label="vormerken">${p.bookmarked ? "★" : "☆"}</button>`;
function row(p) {
  const tags = [cat(p.category), kidsLabel(p), p.is_adult ? "18+" : "", zoneOf(p)].filter(Boolean).map(esc).join(" · ");
  return `<li class="ev ${esc(p.bucket)}${p.is_kids ? " kids" : ""}${p.is_adult ? " adult" : ""}" data-event="${Number(p.id)}" tabindex="0">
    <span class="t">${state.sort === "zeit" && !p.all_day ? esc(p.starts_at.slice(11, 16)) + " " : ""}<b>${esc(p.title)}</b></span>${star(p)}
    <span class="sub">${state.sort === "rang" ? esc(when(p.starts_at)) + " · " : ""}${esc(p.venue || p.city || "")}${p.venue || p.city ? " · " : ""}${tags}</span></li>`;
}

async function loadMarked() {
  const slug = state.slug, r = await api(`/api/places/${slug}/bookmarks`);
  if (slug !== state.slug) return;
  const today = new Date().toISOString().slice(0, 10);
  const coming = r.bookmarks.filter((b) => (b.ends_at || b.starts_at).slice(0, 10) >= today);
  $("#marked-box").hidden = !coming.length && !r.orphans.length;
  $("#marked-count").textContent = coming.length ? num(coming.length) : "";
  $("#marked").innerHTML = coming.slice(0, 6).map((b) =>
    `<li data-event="${Number(b.id)}" data-lng="${Number(b.lon)}" data-lat="${Number(b.lat)}" tabindex="0">${esc(when(b.starts_at))} — <b>${esc(b.title)}</b></li>`).join("")
    + (coming.length > 6 ? `<li class="muted">… ${num(coming.length - 6)} weitere unter „nur Vorgemerktes"</li>` : "")
    + r.orphans.map((o) => `<li class="muted" title="Seit der letzten Erhebung nicht mehr im Bestand">${esc((o.starts_at || "").slice(0, 10))} — ${esc(o.title)} (nicht mehr im Bestand${o.candidate ? `, vielleicht ${esc(when(o.candidate.starts_at))}` : ""})</li>`).join("");
}

async function toggleMark(id) {
  const p = state.events.find((x) => x.id === id) || state.detail;
  const on = !(p?.bookmarked);
  await api(`/api/places/${state.slug}/events/${id}/bookmark`, { method: on ? "PUT" : "DELETE" });
  toast(on ? "Vorgemerkt." : "Nicht mehr vorgemerkt.");
  await loadEvents();
  if (state.detail?.id === id) openDetail(id);
}

async function setVerdict(id, value, quiet = false) {
  const base = `/api/places/${state.slug}/events/${id}/verdict`;
  const r = value ? await put(base, { value }) : await api(base, { method: "DELETE" });
  if (!quiet) {
    const what = { ja: "Sehr interessant", vielleicht: "Prinzipiell", nein: "Uninteressant — ausgeblendet" }[value];
    toast(value ? `${what}${r.termine > 1 ? `, gilt für ${r.termine} Termine` : ""}.` : "Urteil zurückgenommen.",
      value ? () => setVerdict(id, null) : null);
  }
  await loadEvents();
  if (state.detail?.id === id) openDetail(id);
  return r;
}

async function openDetail(id) {
  let p;
  try { p = await api(`/api/places/${state.slug}/events/${id}`); } catch (err) { return toast(String(err)); }
  state.detail = p;
  const where = [p.venue, [p.street, [p.postal_code, p.city].filter(Boolean).join(" ")].filter(Boolean).join(", ")].filter(Boolean);
  const zones = [p.zone_auto ? `Auto ${p.zone_auto}′` : "", p.zone_ebike ? `E-Bike ${p.zone_ebike}′` : ""].filter(Boolean).join(" · ");
  const why = [...p.white.map((w) => "+ " + w), ...p.black.map((b) => "− " + b)];
  const search = "https://duckduckgo.com/?q=" + encodeURIComponent(`${p.title} ${p.venue || p.city || ""}`);
  const v = (value, label) => `<button data-value="${value}" class="${p.verdict === value ? "on" : ""}">${label}</button>`;
  $("#detail").innerHTML = `
    <button class="linklike" id="detail-back">‹ zurück zur Liste</button>
    <h2>${esc(p.title)}</h2>
    <p class="when">${esc(range(p))}</p>
    <p>${where.map(esc).join("<br>")}</p>
    <p class="muted">${[cat(p.category), kidsLabel(p), p.is_adult ? "18+" : "", zones].filter(Boolean).map(esc).join(" · ")}</p>
    <p class="actions">${star(p).replace("</button>", ` ${p.bookmarked ? "vorgemerkt" : "vormerken"}</button>`)}
      ${link(p.url) ? `<a class="btn" href="${link(p.url)}" target="_blank" rel="noopener">zur Quelle ↗</a>`
        : `<a class="btn" href="${esc(search)}" target="_blank" rel="noopener">im Netz suchen ↗</a>`}
      ${p.lat != null ? `<button class="btn" id="detail-fly">auf der Karte</button>` : ""}</p>
    <div class="verdicts" data-id="${Number(p.id)}">${v("ja", "Sehr interessant")}${v("vielleicht", "Prinzipiell")}${v("nein", "Uninteressant")}</div>
    <p class="muted">${p.verdict ? "Dein Urteil — noch einmal klicken nimmt es zurück." : "Ein Urteil schlägt jede Regel."}
      ${p.termine > 1 ? ` Es gilt für alle ${num(p.termine)} Termine dieser Veranstaltung.` : ""}</p>
    ${p.description ? `<p class="desc">${esc(p.description)}</p>` : ""}
    <p class="muted">Quelle: ${esc(p.source_name || p.source)}${p.license ? ` · Lizenz: ${esc(p.license)}` : ""}
      ${why.length ? `<br>Regeln: ${why.map(esc).join("; ")}` : ""}</p>`;
  $("#detail").hidden = false;
  $("#controls").hidden = $("#list-head").hidden = $("#list").hidden = true;
  lastPopup?.remove();
}
function closeDetail() {
  state.detail = null;
  $("#detail").hidden = true;
  $("#controls").hidden = $("#list-head").hidden = $("#list").hidden = false;
}
const flyTo = (lng, lat) => Number.isFinite(lng) && Number.isFinite(lat) && map.easeTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), 13) });

$("#detail").addEventListener("click", (e) => {
  const p = state.detail;
  if (e.target.id === "detail-back") closeDetail();
  else if (e.target.id === "detail-fly") flyTo(p.lon, p.lat);
  else if (e.target.dataset.mark) toggleMark(p.id);
  else if (e.target.dataset.value) setVerdict(p.id, p.verdict === e.target.dataset.value ? null : e.target.dataset.value);
});
function listClick(e) {
  if (e.type === "keydown" && e.key !== "Enter") return;
  const mark = e.target.closest("[data-mark]"), li = e.target.closest("[data-event]");
  if (mark) return toggleMark(Number(mark.dataset.mark));
  if (!li) return;
  if (li.dataset.lng) flyTo(Number(li.dataset.lng), Number(li.dataset.lat));
  openDetail(Number(li.dataset.event));
}
for (const id of ["#list", "#marked"]) { $(id).addEventListener("click", listClick); $(id).addEventListener("keydown", listClick); }

seg("#window", "window", loadEvents);
seg("#visibility", "visibility", loadEvents);
seg("#sort", "sort", renderLive);
const paintProfile = seg("#profile", "profile", async (v) => { await put("/api/profile", { travel_mode: v }); await loadEvents(); });
$("#cats").addEventListener("click", (e) => {
  const k = e.target.dataset.cat;
  if (!k) return;
  state.cats.has(k) ? state.cats.delete(k) : state.cats.add(k);
  loadEvents();
});
$("#cat-all").addEventListener("click", () => { state.cats.clear(); loadEvents(); });
$("#kids").addEventListener("change", (e) => { state.kids = e.target.checked; loadEvents(); });
$("#only-marked").addEventListener("change", (e) => { state.onlyMarked = e.target.checked; loadEvents(); });
$("#adult").addEventListener("change", async (e) => { state.adult = e.target.checked; await put("/api/profile", { show_adult: state.adult }); loadEvents(); });
$("#mode").addEventListener("click", async (e) => {
  const m = e.target.dataset.mode;
  if (!m || m === state.mode) return;
  state.mode = m; keep("mode", m); state.filter = null;
  closeDetail(); render(); await loadEvents();
});
document.querySelectorAll("dialog").forEach((d) => d.addEventListener("click", (e) => {
  if (e.target === d || e.target.dataset.close !== undefined) d.close();
}));

// ------------------------------------------------------------ Interessen

$("#open-interests").addEventListener("click", () => {
  const paint = () => ($("#interest-chips").innerHTML = state.categories.map((k) =>
    `<button data-cat="${esc(k)}" class="${state.interests.has(k) ? "on" : ""}">${esc(cat(k))}</button>`).join(""));
  $("#interest-chips").onclick = async (e) => {
    const k = e.target.dataset.cat;
    if (!k) return;
    state.interests.has(k) ? state.interests.delete(k) : state.interests.add(k);
    paint();
    await put("/api/profile", { interests: [...state.interests] });
    renderLive();
  };
  paint();
  $("#interests").showModal();
});

// ------------------------------------------------------------- Kuratieren

const cur = { queue: [], i: 0, last: null, done: 0 };
async function openCurate() {
  const r = await api(`/api/places/${state.slug}/curate?window=${state.window}&profile=${state.profile}&limit=200`);
  Object.assign(cur, { queue: r.queue, i: 0, last: null, done: 0 });
  renderCurate();
  if (!$("#curate").open) $("#curate").showModal();
}
function renderCurate() {
  const p = cur.queue[cur.i];
  $("#curate-actions").hidden = $("#curate-skip").hidden = !p;
  $("#curate-undo").hidden = !cur.last;
  $("#curate-progress").textContent = p ? `${cur.i + 1} von ${cur.queue.length} · ${cur.done} beurteilt` : "";
  $("#curate-card").innerHTML = !p
    ? `<p class="muted">Für dieses Zeitfenster ist alles beurteilt${cur.done ? ` — ${cur.done} gerade eben` : ""}. Unter „Regeln …" stehen jetzt vielleicht Vorschläge.</p>`
    : `<h3>${esc(p.title)}</h3>
       <p class="when">${esc(range(p))}${p.termine > 1 ? ` · ${num(p.termine)} Termine` : ""}</p>
       <p>${esc([p.venue, p.city].filter(Boolean).join(", "))}</p>
       <p class="muted">${[cat(p.category), kidsLabel(p), zoneOf(p), p.rule_bucket === "highlight" ? "laut Regeln hervorgehoben" : p.rule_bucket === "hidden" ? "laut Regeln ausgeblendet" : ""].filter(Boolean).map(esc).join(" · ")}</p>
       ${p.description ? `<p class="desc">${esc(p.description)}</p>` : ""}`;
}
async function judge(value) {
  const p = cur.queue[cur.i];
  if (!p) return;
  if (value) { await put(`/api/places/${state.slug}/events/${p.id}/verdict`, { value }); cur.last = p; cur.done += 1; }
  cur.i += 1;
  renderCurate();
}
$("#open-curate").addEventListener("click", openCurate);
$("#curate-actions").addEventListener("click", (e) => e.target.closest("button") && judge(e.target.closest("button").dataset.value));
$("#curate-skip").addEventListener("click", () => judge(null));
$("#curate-undo").addEventListener("click", async () => {
  await api(`/api/places/${state.slug}/events/${cur.last.id}/verdict`, { method: "DELETE" });
  cur.i = cur.queue.indexOf(cur.last); cur.last = null; cur.done -= 1;
  renderCurate();
});
$("#curate").addEventListener("keydown", (e) => {
  const v = { 1: "ja", 2: "vielleicht", 3: "nein" }[e.key];
  if (v) judge(v); else if (e.key === "ArrowRight") judge(null);
});
$("#curate").addEventListener("close", loadEvents);

// ----------------------------------------------------------------- Regeln

const FIELD = { title: "Titel", description: "Beschreibung", category: "Kategorie", venue: "Haus", city: "Stadt", source: "Quelle" };
const MATCH = { contains: "enthält", equals: "ist genau", regex: "Regex" };
const rf = { kind: "white" };
const ruleFromForm = () => ({ kind: rf.kind, field: $("#rule-field").value, matcher: $("#rule-matcher").value,
  pattern: $("#rule-pattern").value.trim(), weight: Number($("#rule-weight").value) || 1 });
let previewTimer = null;
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    const rule = ruleFromForm(), box = $("#rule-preview");
    $("#rule-save").disabled = !rule.pattern;
    if (!rule.pattern) return (box.textContent = "");
    try {
      const r = await put(`/api/places/${state.slug}/rules/preview`, { rule }, "POST");
      box.innerHTML = r.changed
        ? `Verschiebt <b>${num(r.changed)}</b> Termine (${num(r.distinct)} Veranstaltungen) in ${esc(state.report.place.name)}: `
          + r.examples.map((x) => `${esc(x.title)}${x.occurrences > 1 ? ` ×${x.occurrences}` : ""}`).join(" · ")
        : "Trifft hier nichts, was nicht schon so einsortiert wäre.";
    } catch (err) { box.textContent = String(err); $("#rule-save").disabled = true; }
  }, 300);
}
async function renderRules() {
  const [list, sug] = await Promise.all([api("/api/rules"), api(`/api/places/${state.slug}/rules/suggestions`)]);
  $("#suggestions").innerHTML = sug.suggestions.length ? `<h3>Vorschläge aus deinen Urteilen</h3>` + sug.suggestions.map((x, i) =>
    `<p class="sug"><button data-sug="${i}">übernehmen</button> ${x.kind === "white" ? "hervorheben" : "ausblenden"}: ${esc(FIELD[x.field])} ${esc(MATCH[x.matcher])} „${esc(x.pattern)}“
       <span class="muted">(${x.ja}× ja, ${x.nein}× nein)</span></p>`).join("") : "";
  $("#suggestions").onclick = async (e) => {
    const x = sug.suggestions[e.target.dataset.sug];
    if (!x) return;
    await put("/api/rules", { kind: x.kind, field: x.field, matcher: x.matcher, pattern: x.pattern, weight: x.weight, note: x.note }, "POST");
    renderRules();
  };
  $("#rule-table").innerHTML = list.map((r) =>
    `<tr class="${r.enabled ? "" : "off"}"><td>${r.kind === "white" ? "+" : "−"}${esc(r.weight)}</td>
      <td>${esc(FIELD[r.field])} ${esc(MATCH[r.matcher])} „${esc(r.pattern)}“${r.note ? ` <span class="muted">${esc(r.note)}</span>` : ""}</td>
      <td><button class="linklike" data-toggle="${r.id}" data-on="${r.enabled}">${r.enabled ? "aus" : "an"}</button>
          <button class="linklike" data-del="${r.id}">löschen</button></td></tr>`).join("")
    || `<tr><td class="muted">Noch keine. Ohne Regeln und Urteile ist nichts hervorgehoben — und nichts ausgeblendet.</td></tr>`;
}
$("#open-rules").addEventListener("click", () => { renderRules(); schedulePreview(); $("#rules").showModal(); });
$("#rule-kind").addEventListener("click", (e) => {
  if (!e.target.dataset.v) return;
  rf.kind = e.target.dataset.v;
  $("#rule-kind").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === rf.kind));
  schedulePreview();
});
for (const id of ["#rule-field", "#rule-matcher", "#rule-weight", "#rule-pattern"]) $(id).addEventListener("input", schedulePreview);
$("#rule-save").addEventListener("click", async () => {
  try { await put("/api/rules", ruleFromForm(), "POST"); } catch (err) { return toast(String(err)); }
  $("#rule-pattern").value = ""; schedulePreview(); renderRules();
});
$("#rule-table").addEventListener("click", async (e) => {
  const d = e.target.dataset;
  if (d.del) await api(`/api/rules/${d.del}`, { method: "DELETE" });
  else if (d.toggle) await api(`/api/rules/${d.toggle}?enabled=${d.on !== "true"}`, { method: "PATCH" });
  else return;
  renderRules();
});
$("#rules").addEventListener("close", loadEvents);

api("/api/profile").then((p) => {
  state.profile = p.travel_mode; state.adult = p.show_adult;
  state.interests = new Set(p.interests); state.categories = p.categories;
  $("#adult").checked = p.show_adult; paintProfile();
}).then(loadPlaces).then((places) => {

  const wanted = new URLSearchParams(location.search).get("ort");
  const first = places.find((p) => p.slug === wanted) || places[0];
  if (first) open(first.slug);
});
