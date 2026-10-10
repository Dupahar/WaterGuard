// WaterGuard dashboard. Talks to waterguard/server.py.
const $ = (s) => document.querySelector(s);
const state = { bbox: null, runId: null, facts: null, drawing: false, tracing: false, history: [], corner: null };

const BASES = {
  dark: { tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
          attribution: "Basemap © Esri, HERE, Garmin, © OpenStreetMap contributors (display only)" },
  imagery: { tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
             attribution: "Basemap imagery © Esri (display only, not an analysis input)" },
};

const map = new maplibregl.Map({
  container: "map",
  style: { version: 8, glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: { base: { type: "raster", tiles: BASES.dark.tiles, tileSize: 256, attribution: BASES.dark.attribution } },
    layers: [{ id: "base", type: "raster", source: "base" }] },
  center: [85.3, 28.05], zoom: 9.3,
});
map.addControl(new maplibregl.NavigationControl(), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");

document.querySelectorAll(".basemap button").forEach((b) => b.onclick = () => {
  const k = b.dataset.base;
  document.querySelectorAll(".basemap button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  const src = map.getSource("base");
  src.setTiles(BASES[k].tiles);
});

// ---------------------------------------------------------------- area selection
function setBbox(b) {
  state.bbox = b.map((v) => +(+v).toFixed(4));
  $("#bboxTxt").textContent = `W ${state.bbox[0]}  S ${state.bbox[1]}  E ${state.bbox[2]}  N ${state.bbox[3]}`;
  $("#runBtn").disabled = false;
  const fc = { type: "Feature", geometry: { type: "Polygon", coordinates: [[
    [b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] } };
  if (map.getSource("aoi")) map.getSource("aoi").setData(fc);
  else {
    map.addSource("aoi", { type: "geojson", data: fc });
    map.addLayer({ id: "aoi", type: "line", source: "aoi", paint: { "line-color": "#fab219", "line-width": 2, "line-dasharray": [2, 1] } });
  }
  map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 40, duration: 600 });
}
function hint(t) { const h = $("#hint"); h.hidden = !t; h.textContent = t || ""; }
$("#drawBtn").onclick = () => { state.drawing = true; state.corner = null; hint("Click the first corner of the area"); };
$("#preset").onchange = (e) => {
  if (!e.target.value) return;
  const [bb, dt] = e.target.value.split("|");
  setBbox(bb.split(",").map(Number));
  $("#date").value = dt.slice(0, 10);
  $("#hour").value = +dt.slice(11, 13);
};
map.on("click", async (e) => {
  const { lng, lat } = e.lngLat;
  if (state.drawing) {
    if (!state.corner) { state.corner = [lng, lat]; hint("Click the opposite corner"); return; }
    const c = state.corner;
    setBbox([Math.min(c[0], lng), Math.min(c[1], lat), Math.max(c[0], lng), Math.max(c[1], lat)]);
    state.drawing = false; hint(null); return;
  }
  if (state.tracing) { state.tracing = false; hint(null); await trace(lng, lat); }
});

// ---------------------------------------------------------------- running
$("#runBtn").onclick = async () => {
  const date = `${$("#date").value}T${String($("#hour").value).padStart(2, "0")}:00:00Z`;
  $("#runBtn").disabled = true;
  $("#progress").hidden = false;
  const r = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bbox: state.bbox, date }) }).then((r) => r.json());
  if (r.detail) { alert(r.detail); $("#runBtn").disabled = false; return; }
  poll(r.run_id);
};
async function poll(id) {
  const s = await fetch(`/api/runs/${id}`).then((r) => r.json());
  $("#progress .bar i").style.width = (s.pct || 0) + "%";
  $("#progress span").textContent = s.state === "error" ? `Error: ${s.error}` : `${s.pct || 0}% · ${s.step || ""}`;
  if (s.state === "done") { $("#runBtn").disabled = false; $("#progress").hidden = true; show(id, s.facts); return; }
  if (s.state === "error") { $("#runBtn").disabled = false; return; }
  setTimeout(() => poll(id), 1500);
}
async function loadPast() {
  const runs = await fetch("/api/runs").then((r) => r.json()).catch(() => []);
  if (!runs.length) return;
  $("#pastRuns").innerHTML = "Recent: " + runs.slice(0, 6).map((r) =>
    `<a data-id="${r.run_id}" title="${r.bbox.join(", ")}">${r.event.slice(0, 10)} · ${r.impact_ha} ha</a>`).join("");
  $("#pastRuns").querySelectorAll("a").forEach((a) => a.onclick = () => openRun(a.dataset.id));
}

// ---------------------------------------------------------------- layers
const LAYERS = [
  { id: "impact", label: "Flood / debris impact", on: true },
  { id: "s2_post", label: "Sentinel-2 after", on: false },
  { id: "s2_pre", label: "Sentinel-2 before", on: false },
  { id: "sar_change", label: "Radar change", on: false },
  { id: "buildings", label: "Buildings hit", on: true },
  { id: "roads", label: "Roads cut", on: true },
  { id: "bridges", label: "Bridges", on: true },
  { id: "settlements", label: "Settlements", on: true },
];
const RUN_LAYER_IDS = ["impact", "s2_post", "s2_pre", "sar_change", "buildings", "roads", "bridges-pt", "settlements", "settlements-lbl", "path"];

function clearRunLayers() {
  for (const id of RUN_LAYER_IDS) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of ["impact", "s2_post", "s2_pre", "sar_change", "buildings", "roads", "bridges", "settlements", "path"])
    if (map.getSource(id)) map.removeSource(id);
}
const STATUS_COLOR = ["match", ["get", "vehicle_status"], "cut off", "#d03b3b", "partly cut", "#fab219",
  "connected", "#0ca30c", "isolated before event", "#8f8e86", "#5a5a55"];

function addRunLayers(id, f) {
  clearRunLayers();
  const base = `/runs/${id}/`;
  for (const k of ["s2_pre", "s2_post", "sar_change", "impact"]) {
    if (!f.overlays[k]) continue;
    map.addSource(k, { type: "image", url: base + k + ".png", coordinates: f.overlays[k] });
    map.addLayer({ id: k, type: "raster", source: k, paint: { "raster-opacity": k === "impact" ? 0.85 : 1, "raster-resampling": "nearest" } });
  }
  map.addSource("roads", { type: "geojson", data: base + "roads_cut.geojson" });
  map.addLayer({ id: "roads", type: "line", source: "roads", paint: { "line-color": "#ff3b3b", "line-width": 3.5 } });
  map.addSource("buildings", { type: "geojson", data: base + "buildings_affected.geojson" });
  map.addLayer({ id: "buildings", type: "fill", source: "buildings", paint: {
    "fill-color": ["match", ["get", "status"], "likely affected", "#ff2a2a", "#fab219"], "fill-outline-color": "#000" } });
  map.addSource("bridges", { type: "geojson", data: base + "bridges.geojson" });
  map.addLayer({ id: "bridges-pt", type: "line", source: "bridges", paint: {
    "line-width": 7, "line-color": ["match", ["get", "status"], "likely damaged", "#d03b3b", "possibly damaged", "#fab219", "#0ca30c"] } });
  map.addSource("settlements", { type: "geojson", data: base + "settlements.geojson" });
  map.addLayer({ id: "settlements", type: "circle", source: "settlements", paint: {
    "circle-radius": ["interpolate", ["linear"], ["get", "buildings"], 0, 4, 200, 12], "circle-color": STATUS_COLOR,
    "circle-stroke-color": "#000", "circle-stroke-width": 1 } });
  map.addLayer({ id: "settlements-lbl", type: "symbol", source: "settlements", filter: ["has", "name"],
    layout: { "text-field": ["get", "name"], "text-size": 12, "text-offset": [0, 1.2], "text-font": ["Noto Sans Regular"] },
    paint: { "text-color": "#fff", "text-halo-color": "#000", "text-halo-width": 1.2 } });
  buildLayerButtons();
}
function buildLayerButtons() {
  const box = $("#layers"); box.innerHTML = "";
  for (const L of LAYERS) {
    const b = document.createElement("button");
    b.textContent = L.label; b.setAttribute("aria-pressed", L.on);
    const ids = L.id === "bridges" ? ["bridges-pt"] : L.id === "settlements" ? ["settlements", "settlements-lbl"] : [L.id];
    const apply = () => ids.forEach((i) => map.getLayer(i) && map.setLayoutProperty(i, "visibility", L.on ? "visible" : "none"));
    apply();
    b.onclick = () => { L.on = !L.on; b.setAttribute("aria-pressed", L.on); apply(); };
    box.appendChild(b);
  }
  const lg = $("#legend"); lg.hidden = false;
  lg.innerHTML = `<div class="r"><span class="sw" style="background:#c8461a"></span>Flood / debris impact</div>
    <div class="r"><span class="sw" style="background:#e6aa3c"></span>Riverbed, bare before (lower confidence)</div>
    <div class="r"><span class="sw" style="background:#1e6ee6"></span>New open water</div>
    <div class="r"><span class="sw" style="background:#787878"></span>Could not assess</div>
    <div class="r"><span class="sw" style="background:#d03b3b;border-radius:50%"></span>Settlement cut off</div>
    <div class="r"><span class="sw" style="background:#fab219;border-radius:50%"></span>Partly cut</div>
    <div class="r"><span class="sw" style="background:#0ca30c;border-radius:50%"></span>Connected</div>`;
}
map.on("click", "settlements", (e) => {
  if (state.drawing || state.tracing) return;
  const p = e.features[0].properties;
  new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
    `<b>${p.name || "Unnamed cluster"}</b><br>${p.buildings} buildings · est. ${p.people_est} people<br>
     Road: <b>${p.vehicle_status}</b>${p.vehicle_lost ? " (lost: " + p.vehicle_lost + ")" : ""}<br>
     Road km to health facility: ${p.vehicle_health_km_before ?? "–"} → ${p.vehicle_health_km_after ?? "no route"}`).addTo(map);
});

// ---------------------------------------------------------------- results panel
const fmt = (n) => (n ?? "–").toLocaleString("en-IN");
function show(id, f) {
  state.runId = id; state.facts = f; state.history = [];
  $("#results").hidden = false;
  const d = f.damage, a = f.access, i = f.impact;
  $("#tiles").innerHTML = [
    ["crit", a.settlements_cut_off_vehicle, "settlements cut off by road"],
    ["crit", a.people_est_stranded_vehicle ?? a.people_est_cut_off_vehicle, "people with no road left (estimate)"],
    ["warn", d.buildings_likely_affected, "buildings likely hit"],
    ["warn", d.bridges_likely_damaged, "bridges likely damaged"],
    ["", i.impact_ha, "ha flood / debris impact"],
    ["", d.road_km_in_impact, "km of road in impact zone"],
  ].map(([c, v, t]) => `<div class="tile ${c}"><b>${fmt(v)}</b><span>${t}</span></div>`).join("");

  const cut = f.cut_off_settlements, part = f.most_stranded_settlements || f.partly_cut_settlements;
  $("#tab-cut").innerHTML = (cut.length ? `<ul class="list">${cut.map((s) => `<li data-lon="${s.lon}" data-lat="${s.lat}">
      <span>${s.name}<br><small>${s.buildings} buildings · est. ${s.people_est} people</small></span><span class="pill">cut off</span></li>`).join("")}</ul>`
    : "<p>No settlement lost all road links.</p>") +
    (part.length ? `<h4>Most people stranded</h4><ul class="list">${part.map((s) => `<li data-lon="${s.lon}" data-lat="${s.lat}">
      <span>${s.name}<br><small>${Math.round((s.share_of_buildings_cut_off ?? 0) * 100)}% of ${s.buildings} buildings have no road · est. ${s.people_est_stranded} people${s.lost ? " · lost: " + s.lost : ""}</small></span><span class="pill warn">${Math.round((s.share_of_buildings_cut_off ?? 0) * 100)}%</span></li>`).join("")}</ul>` : "") +
    `<p><small>A settlement is judged by up to 25 of its own buildings, each snapped to its nearest road. People = buildings × 4.37 (Nepal census 2021 household size). Settlements = OSM places + unnamed building clusters.</small></p>`;
  $("#tab-bridges").innerHTML = f.damaged_bridges.length ? `<ul class="list">${f.damaged_bridges.map((b) => `<li data-lon="${b.lon}" data-lat="${b.lat}">
      <span>${b.name}<br><small>${b.osm_id}</small></span><span class="pill ${b.status.startsWith("possibly") ? "warn" : ""}">${b.status}</span></li>`).join("")}</ul>`
    : "<p>No mapped bridge in the impact zone.</p>";
  document.querySelectorAll(".list li").forEach((li) => li.onclick = () => map.flyTo({ center: [+li.dataset.lon, +li.dataset.lat], zoom: 15 }));

  const s1 = f.inputs.sentinel1.map((s) => `${s.post_time} (${s.orbit}, track ${s.track}, ${s.pre.length} pre-event images)`).join("<br>");
  const s2 = f.inputs.sentinel2.filter((s) => s.role === "post").map((s) => `${s.date} (${s.clear_pct}% clear)`).join(", ") || "none clear";
  const o = f.inputs.osm;
  $("#tab-basis").innerHTML = `<div class="basis">
    <p><b>Sentinel-1 radar, after:</b><br>${s1}</p>
    <p><b>Sentinel-2, after (cloud-free pixels):</b> ${s2}</p>
    <p><b>Impact decided by:</b> optical ${i.share_decided_by_optical_pct}%, radar ${(100 - i.share_decided_by_optical_pct).toFixed(1)}%. Not assessable: ${i.unassessable_pct_of_area}% of area.</p>
    <p><b>OpenStreetMap:</b> snapshot ${o.snapshot_time}, ${fmt(o.features)} features, latest edit ${o.latest_edit_in_snapshot?.slice(0, 10)}, edited after snapshot: <b>${o.features_edited_after_snapshot}</b> ${o.compliant ? "✓ pre-event only" : "✗"}</p>
    <p><b>Runtime:</b> ${f.runtime_s} s · run <code>${f.run_id}</code></p></div>`;
  $("#repEn").href = `/api/runs/${id}/sitrep?lang=en`;
  $("#repNe").href = `/api/runs/${id}/sitrep?lang=ne`;
  $("#chat").innerHTML = "";
  addRunLayers(id, f);
}
document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.hidden = t.id !== "tab-" + b.dataset.tab);
});

// ---------------------------------------------------------------- copilot
function addMsg(role, text, meta, cls) {
  const d = document.createElement("div");
  d.className = "msg " + role; d.textContent = text;
  if (meta) { const m = document.createElement("span"); m.className = "meta " + (cls || ""); m.textContent = meta; d.appendChild(m); }
  $("#chat").appendChild(d); $("#chat").scrollTop = 1e9;
  return d;
}
async function ask(q) {
  if (!state.runId || !q.trim()) return;
  addMsg("user", q);
  const wait = addMsg("bot", "…");
  const r = await fetch(`/api/runs/${state.runId}/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: q, history: state.history }) }).then((r) => r.json()).catch((e) => ({ error: String(e) }));
  wait.remove();
  if (r.error) { addMsg("bot", "Error: " + r.error); return; }
  const ok = !r.unverified.length;
  addMsg("bot", r.answer, `${ok ? "✓" : "⚠"} ${r.numbers_checked} numbers checked against the map results` +
    (ok ? "" : ` · unverified: ${r.unverified.join(", ")}`) + ` · ${r.backend}` + (r.tool_calls?.length ? ` · tools: ${r.tool_calls.join(", ")}` : ""), ok ? "ok" : "bad");
  state.history.push({ role: "user", text: q }, { role: "assistant", text: r.answer });
  runActions(r.actions || []);
}
$("#askForm").onsubmit = (e) => { e.preventDefault(); const q = $("#askIn").value; $("#askIn").value = ""; ask(q); };
document.querySelectorAll("#suggest button").forEach((b) => b.onclick = () => ask(b.textContent));

let markers = [];
function runActions(actions) {
  markers.forEach((m) => m.remove()); markers = [];
  const pts = [];
  for (const a of actions) {
    if (a.type === "fly") { map.flyTo({ center: [a.lon, a.lat], zoom: 14 }); }
    if (a.type === "highlight" || a.type === "fly") {
      markers.push(new maplibregl.Marker({ color: "#fab219" }).setLngLat([a.lon, a.lat]).setPopup(new maplibregl.Popup().setText(a.label)).addTo(map));
      pts.push([a.lon, a.lat]);
    }
    if (a.type === "path") drawPath(a.coords);
  }
  if (pts.length > 1 && !actions.some((a) => a.type === "fly")) {
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]], { padding: 80, maxZoom: 14 });
  }
}
function drawPath(coords) {
  const fc = { type: "Feature", geometry: { type: "LineString", coordinates: coords } };
  if (map.getSource("path")) map.getSource("path").setData(fc);
  else {
    map.addSource("path", { type: "geojson", data: fc });
    map.addLayer({ id: "path", type: "line", source: "path", paint: { "line-color": "#00e5ff", "line-width": 4, "line-dasharray": [1, 1] } });
  }
}

// ---------------------------------------------------------------- flood path
$("#traceBtn").onclick = () => { state.tracing = true; hint("Click a point on the river upstream"); };
async function trace(lon, lat) {
  $("#traceOut").innerHTML = "<p>Tracing…</p>";
  const r = await fetch(`/api/runs/${state.runId}/trace`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lon, lat }) }).then((r) => r.json());
  if (r.detail || r.error) { $("#traceOut").innerHTML = `<p>${r.detail || r.error}</p>`; return; }
  runActions(r.actions);
  $("#traceOut").innerHTML = `<p>Path ${r.path_length_km} km${r.leaves_analysed_area ? " (continues beyond the analysed area)" : ""}.
    Times assume a ${r.assumed_surge_speed_m_per_s} m/s surge: an assumption, not a forecast.</p>
    <ul class="list">${r.settlements_along_path.map((s) => `<li><span>${s.name}<br><small>${s.buildings} buildings · lowest part ${s.lowest_part_above_river_m} m above river</small></span>
    <span>${s.km_downstream} km · ~${s.minutes_at_assumed_speed} min</span></li>`).join("") || "<li>No settlement within reach of the path.</li>"}</ul>`;
}

async function openRun(id) {
  const s = await fetch(`/api/runs/${id}`).then((r) => r.json());
  if (s.facts) {
    setBbox(s.facts.area.bbox);
    $("#date").value = s.facts.event_time_utc.slice(0, 10);
    $("#hour").value = +s.facts.event_time_utc.slice(11, 13);
    show(id, s.facts);
  }
}
loadPast();
const deep = new URLSearchParams(location.search).get("run");
if (deep) { if (map.loaded()) openRun(deep); else map.once("load", () => openRun(deep)); }
window.addEventListener("error", (e) => console.log("ERR", e.message, e.filename, e.lineno));
window.addEventListener("unhandledrejection", (e) => console.log("REJ", e.reason && (e.reason.stack || e.reason)));
