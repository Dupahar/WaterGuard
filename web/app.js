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
  const [bb, dt, exposure] = e.target.value.split("|");
  setBbox(bb.split(",").map(Number));
  state.exposure = exposure || null;     // an example can pin how people are counted (its published run)
  $("#date").value = dt.slice(0, 10);
  $("#hour").value = +dt.slice(11, 13);
};
map.on("click", async (e) => {
  const { lng, lat } = e.lngLat;
  if (state.drawing) {
    if (!state.corner) { state.corner = [lng, lat]; hint("Click the opposite corner"); return; }
    const c = state.corner;
    setBbox([Math.min(c[0], lng), Math.min(c[1], lat), Math.max(c[0], lng), Math.max(c[1], lat)]);
    state.exposure = null;
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
    body: JSON.stringify({ bbox: state.bbox, date, ...(state.exposure ? { exposure: state.exposure } : {}) }) }).then((r) => r.json());
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
const RUN_LAYER_IDS = ["cells", "cells-hit", "impact", "s2_post", "s2_pre", "sar_change", "buildings", "roads", "bridges-pt", "settlements", "settlements-lbl", "path"];

function clearRunLayers() {
  for (const id of RUN_LAYER_IDS) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of ["cells", "impact", "s2_post", "s2_pre", "sar_change", "buildings", "roads", "bridges", "settlements", "path"])
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
    `<b>${esc(p.name || "Unnamed cluster")}</b><br>${p.buildings} buildings · est. ${p.people_est} people<br>
     Road: <b>${esc(p.vehicle_status)}</b>${p.vehicle_lost ? " (lost: " + esc(p.vehicle_lost) + ")" : ""}<br>
     ${p.vehicle_health_km_before == null ? "No road to a mapped health facility in this area, even before the flood"
       : `Road km to health facility: ${p.vehicle_health_km_before} → ${p.vehicle_health_km_after ?? "no route now"}`}`).addTo(map);
});

// ---------------------------------------------------------------- results panel
const fmt = (n) => (n ?? "–").toLocaleString("en-IN");
/** text from OSM, analysts or a model goes into HTML only escaped */
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
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
      <span>${esc(s.name)}<br><small>${s.buildings} buildings · est. ${s.people_est} people</small></span><span class="pill">cut off</span></li>`).join("")}</ul>`
    : "<p>No settlement lost all road links.</p>") +
    (part.length ? `<h4>Most people stranded</h4><ul class="list">${part.map((s) => `<li data-lon="${s.lon}" data-lat="${s.lat}">
      <span>${esc(s.name)}<br><small>${Math.round((s.share_of_buildings_cut_off ?? 0) * 100)}% of ${s.buildings} buildings have no road · est. ${s.people_est_stranded} people${s.lost ? " · lost: " + esc(s.lost) : ""}</small></span><span class="pill warn">${Math.round((s.share_of_buildings_cut_off ?? 0) * 100)}%</span></li>`).join("")}</ul>` : "") +
    `<p><small>A settlement is judged by up to 25 of its own buildings, each snapped to its nearest road. People: ${esc(a.people_estimate_method)}. Settlements = OSM places + unnamed building clusters.</small></p>`;
  $("#tab-bridges").innerHTML = f.damaged_bridges.length ? `<ul class="list">${f.damaged_bridges.map((b) => `<li data-lon="${b.lon}" data-lat="${b.lat}">
      <span>${esc(b.name)}<br><small>${esc(b.osm_id)}</small></span><span class="pill ${b.status.startsWith("possibly") ? "warn" : ""}">${esc(b.status)}</span></li>`).join("")}</ul>`
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
  loadProof(id);
  loadInspection(id);
}

// ---------------------------------------------------------------- inspector agent
const VERDICT = { confirmed: ["ok", "confirmed"], needs_review: ["warn", "needs review"], likely_false_alarm: ["", "likely false alarm"] };
function drawCells(res) {
  const fc = { type: "FeatureCollection", features: (res?.cells || []).map((c) => ({ type: "Feature",
    properties: { id: c.id, verdict: c.review ? "reviewed_" + c.review.decision : c.verdict },
    geometry: { type: "Polygon", coordinates: [c.ring] } })) };
  if (map.getSource("cells")) { map.getSource("cells").setData(fc); showCells(); return; }
  map.addSource("cells", { type: "geojson", data: fc });
  map.addLayer({ id: "cells-hit", type: "fill", source: "cells", paint: { "fill-color": "#fff", "fill-opacity": 0.01 } });
  map.addLayer({ id: "cells", type: "line", source: "cells", paint: { "line-width": 2,
    "line-color": ["match", ["get", "verdict"], "confirmed", "#0ca30c", "needs_review", "#fab219", "likely_false_alarm", "#d03b3b",
                   "reviewed_keep", "#3987e5", "reviewed_remove", "#8f8e86", "#fff"] } });
  showCells();
}
// inspection cells belong to the Inspect tab only
function showCells() {
  const on = document.querySelector('.tabs button[data-tab="inspect"]')?.getAttribute("aria-selected") === "true";
  for (const id of ["cells", "cells-hit"]) if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
}
const lineMarks = (L) => Object.entries(L).map(([k, v]) => (v ? "✓" : "·") + k).join(" ");
function actText(t) {
  if (t.tool === "vision.realign") return t.ok
    ? `realigned ${t.shift_px} px on ${t.inliers} SIFT matches → ${lineMarks(t.lines)}`
    : "no trustworthy SIFT alignment: kept ECC";
  if (t.tool === "vision.zoom") return t.parts.map((p) => `${p.part} ${p.impact_ha} ha ${Object.values(p.lines).filter(Boolean).length}/4`).join(", ")
    + (t.strong_parts.length ? ` → strong: ${t.strong_parts.join(", ")} (${Math.round(100 * t.strong_share)}%)` : "");
  if (t.tool === "nemotron.second_look") return t.error ? `no read (${t.error})`
    : `${t.cause} (${Math.round(100 * t.confidence)}%): ${t.explanation}`;
  return `${t.scenes.length} later scenes, change ${t.persistence}`;
}
function traceText(c) {
  return c.trace.map((t) => t.step === "perceive"
    ? "perceive  " + lineMarks(t.lines)
    : t.step === "act" ? `act       ${t.tool.replace("vision.", "")}: ${actText(t)}`
    : `decide    ${t.action}`).join("\n");
}
async function loadInspection(id) {
  const r = await fetch(`/api/runs/${id}/inspection`).then((r) => r.ok ? r.json() : null).catch(() => null);
  const res = r?.result;
  const running = r?.job?.state === "running";
  $("#inspectState").textContent = running ? `${r.job.pct}% · ${r.job.step}` : res ? `planner: ${res.planner} · ${res.inspected_utc}` : "not inspected yet";
  if (running) setTimeout(() => state.runId === id && loadInspection(id), 2000);
  if (!res || running) { if (!res) { state.inspection = null; $("#inspectTiles").innerHTML = ""; $("#cellList").innerHTML = ""; $("#publishGate").innerHTML = ""; drawCells(null); } return; }
  state.inspection = res;
  state.readonly = !!r.readonly_review;
  const s = res.summary;
  $("#inspectTiles").innerHTML = [["", s.confirmed, `cells confirmed (${s.confirmed_ha} ha)`], ["warn", s.pending_review, "cells waiting for you"],
    ["", res.later_looks, "later images fetched"], ["crit", s.removed_by_analyst, "removed by analyst"]]
    .map(([c, v, t]) => `<div class="tile ${c}"><b>${fmt(v)}</b><span>${t}</span></div>`).join("");
  $("#publishGate").innerHTML = r.readonly_review && !r.ready_to_publish
    ? `<p>⏸ ${r.publish_status}. On this public demo the review queue is read-only.</p>`
    : r.ready_to_publish
    ? `<p>✓ Every cell is confirmed or reviewed. <button id="applyBtn" class="ghost">Apply review &amp; fingerprint</button></p>`
    : `<p>⏸ ${r.publish_status}: the report is not anchored until you decide.</p>`;
  if ($("#applyBtn")) $("#applyBtn").onclick = async () => {
    $("#applyBtn").disabled = true; $("#applyBtn").textContent = "Re-running…";
    const a = await fetch(`/api/runs/${id}/apply-review`, { method: "POST" }).then((r) => r.json());
    if (a.facts) show(id, a.facts); else alert(a.detail || "failed");
  };
  const order = { needs_review: 0, likely_false_alarm: 0, confirmed: 1 };
  const cells = [...res.cells].sort((a, b) => (order[a.verdict] - order[b.verdict]) || (!!a.review - !!b.review) || b.priority - a.priority);
  $("#cellList").innerHTML = cells.map((c) => {
    const [cls, label] = VERDICT[c.verdict];
    const rv = c.review ? `<p class="why">Analyst: <b>${esc(c.review.decision)}</b>${c.review.note ? " · " + esc(c.review.note) : ""}</p>` : "";
    const acts = c.verdict !== "confirmed" && !c.review && state.readonly
      ? `<p class="why">⏸ Waiting for an analyst (read-only on this public demo)</p>`
      : c.verdict !== "confirmed" && !c.review
      ? `<div class="acts"><button class="keep" data-d="keep">Keep: real damage</button><button class="remove" data-d="remove">Remove: not flood</button></div>` : "";
    return `<li data-id="${c.id}" data-lon="${c.lon}" data-lat="${c.lat}">
      <div class="head"><span><b>${c.impact_ha} ha</b> · ${c.buildings_hit} buildings · ${c.road_segments_cut} road segments · ~${fmt(c.people_nearby_est)} people nearby</span><span class="pill ${cls}">${label}</span></div>
      <p class="why">${esc(c.reason)}</p><img src="/runs/${id}/${c.chip}" alt="before, after and colour change for cell ${c.id}">
      ${c.chip_later ? `<img src="/runs/${id}/${c.chip_later}" alt="the same cell weeks later">` : ""}
      <div class="trace">${esc(traceText(c))}</div>${rv}${acts}</li>`;
  }).join("");
  $("#cellList").querySelectorAll("li").forEach((li) => {
    li.querySelector(".head").onclick = () => map.flyTo({ center: [+li.dataset.lon, +li.dataset.lat], zoom: 14.5 });
    const c = res.cells.find((x) => x.id === li.dataset.id);
    li.querySelectorAll("img").forEach((im) => im.onclick = () => openCell(id, c));
    li.querySelectorAll(".acts button").forEach((b) => b.onclick = () => decideCell(id, li.dataset.id, b.dataset.d));
  });
  drawCells(res);
}
function cellCard(id, c, big) {
  const [cls, label] = VERDICT[c.verdict];
  const rv = c.review ? `<p class="why">Analyst: <b>${esc(c.review.decision)}</b>${c.review.note ? " · " + esc(c.review.note) : ""}</p>` : "";
  const acts = c.verdict !== "confirmed" && !c.review && state.readonly
    ? `<p class="why">⏸ Waiting for an analyst. (Reviews are read-only on this public demo.)</p>`
    : c.verdict !== "confirmed" && !c.review
    ? `<div class="acts"><button class="keep" data-d="keep" data-id="${c.id}">Keep: real damage</button><button class="remove" data-d="remove" data-id="${c.id}">Remove: not flood</button></div>` : "";
  return `<h3>${c.impact_ha} ha · ${c.buildings_hit} buildings · ${c.road_segments_cut} road segments cut <span class="pill ${cls}">${label}</span></h3>
    <p class="why">${esc(c.reason)}</p>
    <img src="/runs/${id}/${c.chip}" alt="before, after and colour change">
    ${c.chip_later ? `<p class="why">The same cell weeks later:</p><img src="/runs/${id}/${c.chip_later}" alt="the same cell weeks later">` : ""}
    ${big ? `<div class="trace">${esc(traceText(c))}</div>` : ""}${rv}${acts}`;
}
function openCell(id, c) {
  $("#lbBody").innerHTML = cellCard(id, c, true);
  $("#lightbox").hidden = false;
  $("#lbBody").querySelectorAll(".acts button").forEach((b) => b.onclick = () => decideCell(id, b.dataset.id, b.dataset.d));
}
async function decideCell(id, cell, d) {
  await fetch(`/api/runs/${id}/inspection/${cell}`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: d }) });
  $("#lightbox").hidden = true;
  await loadInspection(id);
  const next = state.inspection?.cells.find((c) => c.verdict !== "confirmed" && !c.review);
  if (next) { map.flyTo({ center: [next.lon, next.lat], zoom: 14.5 }); openCell(id, next); }   // straight to the next one
}
$("#lbClose").onclick = () => { $("#lightbox").hidden = true; };
$("#lightbox").onclick = (e) => { if (e.target.id === "lightbox") $("#lightbox").hidden = true; };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#lightbox").hidden = true; });
map.on("click", "cells-hit", (e) => {
  if (state.drawing || state.tracing || !state.inspection) return;
  if (map.queryRenderedFeatures(e.point, { layers: ["settlements", "bridges-pt"] }).length) return;   // the dot wins
  const c = state.inspection.cells.find((x) => x.id === e.features[0].properties.id);
  if (!c) return;
  const [cls, label] = VERDICT[c.verdict];
  new maplibregl.Popup({ maxWidth: "360px" }).setLngLat(e.lngLat).setHTML(
    `<b>${c.impact_ha} ha · ${label}</b>${c.review ? " · analyst: " + esc(c.review.decision) : ""}<br>${esc(c.reason)}
     <img src="/runs/${state.runId}/${c.chip}" alt="chip"><a href="#" data-open="${c.id}">Open large</a>`).addTo(map);
  setTimeout(() => document.querySelector(`[data-open="${c.id}"]`)?.addEventListener("click", (ev) => { ev.preventDefault(); openCell(state.runId, c); }), 0);
});
$("#inspectBtn").onclick = async () => {
  if (!state.runId) return;
  await fetch(`/api/runs/${state.runId}/inspect`, { method: "POST" });
  loadInspection(state.runId);
};


// ---------------------------------------------------------------- proof
const short = (h) => h ? h.slice(0, 10) + "…" + h.slice(-6) : "–";
async function loadProof(id) {
  state.proof = null;
  $("#verifyLog").textContent = "";
  $("#proofInfo").innerHTML = "<p>Loading…</p>";
  const p = await fetch(`/api/runs/${id}/proof`).then((r) => r.json()).catch(() => null);
  if (!p || p.detail) { $("#proofInfo").innerHTML = "<p>No proof for this run.</p>"; return; }
  state.proof = p;
  const c = p.chain, pub = p.anchors.find((a) => a.kind === "published");
  const unrev = pub?.unreviewed_cells ? ` · <b>published with ${pub.unreviewed_cells} inspected cells not yet reviewed by an analyst</b>` : "";
  const ledgerLine = !c ? "No public ledger configured on this server."
    : !c.published ? `Not anchored yet on ${c.network}.`
    : `${c.final ? "✓ <b>Final</b>" : c.disputed ? "⚠ <b>Disputed</b>" : "… <b>Anchored, awaiting confirmation</b>"} on ${c.network} ·
       ${c.confirmations} independent confirmations (${c.quorum} needed)` +
      (pub?.tx_url ? ` · <a href="${pub.tx_url}" target="_blank">transaction</a>` : "") +
      (c.registry_url ? ` · <a href="${c.registry_url}" target="_blank">registry</a>` : "") + unrev;
  $("#proofInfo").innerHTML = `<p><b>Report root</b> <code>${short(p.report_root)}</code> · ${p.files.length} files</p>
    <p><b>Claims root</b> <code>${short(p.claims_root)}</code> · ${p.settlements.length} settlements</p>
    <p><b>Code</b> <code>${p.code_version.slice(0, 12)}</code></p><p>${ledgerLine}</p>`;
  const lbl = ["reachable", "partly cut", "cut off"];
  const ss = [...p.settlements].sort((a, b) => b.status - a.status || b.people_stranded - a.people_stranded);
  $("#claimsList").innerHTML = ss.slice(0, 40).map((s) => `<li data-lon="${s.lon_e5 / 1e5}" data-lat="${s.lat_e5 / 1e5}">
    <span>${esc(s.name)}<br><small>${s.people_stranded} people stranded · leaf ${short(s.leaf)} · proof ${s.proof.length} hashes</small></span>
    <span class="pill ${["mute", "warn", ""][s.status]}">${lbl[s.status]}</span></li>`).join("");
  $("#claimsList").querySelectorAll("li").forEach((li) => li.onclick = () => map.flyTo({ center: [+li.dataset.lon, +li.dataset.lat], zoom: 15 }));
}
$("#verifyBtn").onclick = async () => {
  if (!state.proof) return;
  const out = $("#verifyLog"); out.textContent = "";
  const log = (t) => { out.textContent += t + "\n"; };
  $("#verifyBtn").disabled = true;
  try { await WGProof.verifyInBrowser(state.runId, state.proof, state.proof.chain, log); }
  catch (e) { log("Error: " + e.message); }
  $("#verifyBtn").disabled = false;
};
document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.hidden = t.id !== "tab-" + b.dataset.tab);
  showCells();
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
  const web = r.web_numbers?.length ? ` · ${r.web_numbers.length} from web reports, not checked against the maps` : "";
  const msg = addMsg("bot", r.answer, `${ok ? "✓" : "⚠"} ${r.numbers_checked} numbers checked against the map results` + web +
    (ok ? "" : ` · unverified: ${r.unverified.join(", ")}`) + ` · ${r.backend}` + (r.tool_calls?.length ? ` · tools: ${r.tool_calls.join(", ")}` : ""), ok ? "ok" : "bad");
  if (r.sources?.length) {   // web reports the answer could draw on: a separate, unverified source
    const box = document.createElement("div"); box.className = "sources";
    box.appendChild(document.createTextNode("Web reports (unverified): "));
    r.sources.slice(0, 5).forEach((s, i) => {
      if (!/^https?:\/\//.test(s.url)) return;
      const a = document.createElement("a"); a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = s.site + (s.published ? ` (${s.published.slice(0, 10)})` : ""); a.title = s.title;
      if (i) box.appendChild(document.createTextNode(" · "));
      box.appendChild(a);
    });
    msg.appendChild(box);
  }
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
  if (r.detail || r.error) { $("#traceOut").innerHTML = `<p>${esc(r.detail || r.error)}</p>`; return; }
  runActions(r.actions);
  $("#traceOut").innerHTML = `<p>Path ${r.path_length_km} km${r.leaves_analysed_area ? " (continues beyond the analysed area)" : ""}.
    Times assume a ${r.assumed_surge_speed_m_per_s} m/s surge: an assumption, not a forecast.</p>
    <ul class="list">${r.settlements_along_path.map((s) => `<li><span>${esc(s.name)}<br><small>${s.buildings} buildings · lowest part ${s.lowest_part_above_river_m} m above river</small></span>
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
const params = new URLSearchParams(location.search), deep = params.get("run");
async function openDeep() {
  await openRun(deep);
  if (params.get("verify")) {
    document.querySelector('.tabs button[data-tab="proof"]').click();
    for (let i = 0; i < 50 && !state.proof; i++) await new Promise((r) => setTimeout(r, 200));
    $("#verifyBtn").click();
  }
}
if (deep) { if (map.loaded()) openDeep(); else map.once("load", openDeep); }
window.addEventListener("error", (e) => console.log("ERR", e.message, e.filename, e.lineno));
window.addEventListener("unhandledrejection", (e) => console.log("REJ", e.reason && (e.reason.stack || e.reason)));
