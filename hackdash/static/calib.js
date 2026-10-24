// Calibrate: netra-ask's Sites calibration (ask/static/sites.js) as a full-screen screen over the send-drone page.
// One camera record (site_cameras row) at a time: freeze a live frame, click frame point <-> map point pairs, see the
// fit (leave-one-out ground error) after every change, drag pairs / the camera and refit, then Save. Until Save
// everything is a draft held in this page and in hackdash.calib (a frozen frame, a fit computed with netra-ask's own
// camgeo): nothing reaches netra-ask's tables. Save = netra-ask's own frame upload + camera PATCH, as the operator.
// After a save, the live person boxes are projected with the saved calibration and drawn as dots on the map.
// The Site tab draws / edits the site boundary (PATCH /sites/{id}). No placeholders: what isn't there is said so.
(() => {
const API = "/hack/api";
const MAPLIBRE = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const h = html => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const toast = msg => { const t = h(`<div class="toast">${esc(msg)}</div>`); $("#toasts").append(t); setTimeout(() => t.remove(), 6000); };
const fx = (v, d = 1) => v == null ? "–" : Number(v).toFixed(d);
const ll = (lat, lon) => `${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}`;
const ago = iso => { const m = Math.round((Date.now() - new Date(iso)) / 60e3); return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(iso).toLocaleString(); };
function btn(text, cls, fn, disabled) { const b = h(`<button type="button" class="btn ${cls}">${esc(text)}</button>`); b.onclick = fn; b.disabled = !!disabled; return b; }

async function api(path, opts = {}) {
  const r = await fetch(API + path, { credentials: "same-origin", ...opts, headers: opts.body ? { "Content-Type": "application/json" } : {} });
  if (r.status === 401) { location.href = "/map/login?next=/hack/"; throw Object.assign(new Error("auth"), { status: 401 }); }
  if (!r.ok) { let m = `${r.status}`; try { const d = (await r.json()).detail; m = typeof d === "string" ? d : JSON.stringify(d); } catch {} throw Object.assign(new Error(m), { status: r.status }); }
  return r.status === 204 ? null : r.json();
}
const send = (method, path, body) => api(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

// ------------------------------------------------------------------ camera geometry (same model as ask/camgeo.py)
const R_EARTH = 6371008.8, K = Math.PI / 180 * R_EARTH, RAD = Math.PI / 180;
const toEN = (lat, lon, lat0, lon0) => [(lon - lon0) * K * Math.cos(lat0 * RAD), (lat - lat0) * K];
const fromEN = (e, n, lat0, lon0) => [lat0 + n / K, lon0 + e / (K * Math.cos(lat0 * RAD))];
function rot(c) {
  const y = c.yaw * RAD, p = c.pitch * RAD, r = c.roll * RAD;
  const f = [Math.sin(y) * Math.cos(p), Math.cos(y) * Math.cos(p), -Math.sin(p)];
  let rt = [Math.cos(y), -Math.sin(y), 0];
  let dn = [f[1] * rt[2] - f[2] * rt[1], f[2] * rt[0] - f[0] * rt[2], f[0] * rt[1] - f[1] * rt[0]];
  const cr = Math.cos(r), sr = Math.sin(r);
  [rt, dn] = [rt.map((v, i) => cr * v + sr * dn[i]), dn.map((v, i) => -sr * rt[i] + cr * v)];
  return [rt, dn, f];
}
const focal = c => (c.width / 2) / Math.tan(Math.min(Math.max(c.hfov, 0.5), 170) * RAD / 2);
function pixelToGround(c, u, v, maxRange = 500) {
  const R = rot(c), f = focal(c), a = (u - c.width / 2) / f, b = (v - c.height / 2) / f;
  const ray = [0, 1, 2].map(i => a * R[0][i] + b * R[1][i] + R[2][i]);
  if (ray[2] >= -1e-9) return null;
  const t = c.height_m / -ray[2], e = ray[0] * t, n = ray[1] * t;
  return Math.hypot(e, n) > maxRange ? null : [e, n];
}
function groundToPixel(c, e, n) {
  const R = rot(c), pw = [e, n, -c.height_m], pc = R.map(r => r[0] * pw[0] + r[1] * pw[1] + r[2] * pw[2]);
  if (pc[2] <= 1e-6) return null;
  const f = focal(c);
  return [c.width / 2 + f * pc[0] / pc[2], c.height / 2 + f * pc[1] / pc[2]];
}
const bearing = (a, b) => { const [e, n] = toEN(b.lat, b.lng, a.lat, a.lng); return (Math.atan2(e, n) / RAD + 360) % 360; };
function circle(lat, lon, r, n = 40) {
  const ring = [];
  for (let i = 0; i <= n; i++) { const a = 2 * Math.PI * i / n; const [la, lo] = fromEN(r * Math.sin(a), r * Math.cos(a), lat, lon); ring.push([lo, la]); }
  return ring;
}
function cone(m, r = 40) {                   // = ask.sitemap._cone: the placed heading + nominal hfov as a flat wedge
  const ring = [[m.lat, m.lon]];
  for (let i = 0; i <= 12; i++) { const a = (m.yaw - m.hfov / 2 + m.hfov * i / 12) * RAD; ring.push(fromEN(r * Math.sin(a), r * Math.cos(a), m.lat, m.lon)); }
  return [...ring, ring[0]];
}

// ------------------------------------------------------------------ state
const MODEL_KEYS = ["lat", "lon", "height_m", "yaw", "pitch", "roll", "hfov"];
const C = {
  feed: null,            // pipeline camera id the screen was opened for (the live feed frames are frozen from)
  sites: [], liveCams: [], site: null, cid: null, tab: "camera",
  d: null,               // draft: {points, model, fit_position, frame, fit, footprint, dirty, fitting, fitErr}
  mode: null, pending: null, sel: null, bdraft: null,
  people: null, peopleErr: null, peopleT: null, fitSeq: 0, fitT: null, saving: false,
};
const rec = () => C.site?.cameras.find(c => c.id === C.cid) || null;
const frameCam = () => C.d?.frame && { ...C.d.model, width: C.d.frame.width, height: C.d.frame.height };
const fitLine = f => f ? `${f.n} pairs · ${fx(f.rms_px)} px · ${f.loo?.median_m != null ? `±${fx(f.loo.median_m)} m checked` : `±${fx(f.ground_err_m)} m in-sample`}` : "";

function draftFrom(c) {
  return {
    points: c.points.map(p => ({ ...p })), model: Object.fromEntries(MODEL_KEYS.map(k => [k, c[k]])), fit_position: !!c.fit_position,
    frame: c.frame ? { kind: "saved", ...c.frame, url: `${API}/calib/sites/${encodeURIComponent(C.site.id)}/cameras/${encodeURIComponent(c.id)}/frame.jpg?f=${encodeURIComponent(c.frame.file)}` } : null,
    fit: c.fit, footprint: c.footprint, dirty: false, fitting: false, fitErr: null,
  };
}

// ------------------------------------------------------------------ shell (built once, on first open)
let root = null, map = null, mapReady = false;
const markers = { cam: null, head: null, pairs: [], pending: null, test: null, verts: [], others: [] };
function loadOnce(tag, attrs) {
  return new Promise((ok, bad) => { const el = Object.assign(document.createElement(tag), attrs); el.onload = ok; el.onerror = () => bad(new Error(`couldn't load ${attrs.src || attrs.href}`)); document.head.append(el); });
}
async function build() {
  await Promise.all([
    loadOnce("link", { rel: "stylesheet", href: `/hack/static/calib.css?v=${Date.now()}` }),
    window.maplibregl ? null : loadOnce("link", { rel: "stylesheet", href: `${MAPLIBRE}.css` }),
    window.maplibregl ? null : loadOnce("script", { src: `${MAPLIBRE}.js` }),
  ]);
  root = h(`<div id="calib" class="hidden">
    <header class="cbar"><button type="button" class="btn ghost" id="cb-close">← Send drone</button><span class="title">Calibrate</span>
      <div class="ctabs"><button type="button" data-tab="camera">Camera</button><button type="button" data-tab="site">Site setup</button></div>
      <select id="cb-site" aria-label="Site"></select><select id="cb-cam" aria-label="Camera record"></select>
      <div class="grow"></div><span id="cb-state" class="small"></span></header>
    <aside id="cpane"></aside>
    <section id="cframe"><div class="framebar"><span id="cf-cap" class="small"></span><div class="grow"></div><span id="cf-read" class="mono small"></span></div>
      <div id="cf-box"><img id="cf-img" alt="Frozen calibration frame"><svg id="cf-over"></svg><div id="cf-none" class="empty"></div></div></section>
    <section id="cmapwrap"><div id="cmap"></div><div id="c-hint" class="hint hidden"></div></section>
  </div>`);
  document.body.append(root);
  $("#cb-close").onclick = close;
  root.querySelectorAll(".ctabs button").forEach(b => b.onclick = () => { C.tab = b.dataset.tab; C.mode = null; C.pending = null; C.bdraft = null; hint(); render(); });
  $("#cb-site").onchange = e => e.target.value === "+new" ? newSite() : loadSite(e.target.value);
  $("#cb-cam").onchange = e => selectRecord(e.target.value || null);
  map = new maplibregl.Map({
    container: "cmap", center: [-117.2323, 32.8792], zoom: 18, maxZoom: 21, attributionControl: { compact: true },
    style: { version: 8, sources: { sat: { type: "raster", tileSize: 256, maxzoom: 19, attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"] } },
      layers: [{ id: "sat", type: "raster", source: "sat" }] },
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
  new ResizeObserver(() => map.resize()).observe($("#cmap"));
  await new Promise(ok => map.once("style.load", ok));
  for (const id of ["boundary", "others", "cone", "people", "testcirc"]) map.addSource(id, { type: "geojson", data: FC([]) });
  map.addLayer({ id: "boundary-fill", type: "fill", source: "boundary", paint: { "fill-color": "#ffd23f", "fill-opacity": 0.07 } });
  map.addLayer({ id: "boundary-line", type: "line", source: "boundary", paint: { "line-color": "#ffd23f", "line-width": 2, "line-dasharray": [2, 1.5] } });
  map.addLayer({ id: "others", type: "line", source: "others", paint: { "line-color": "#ffffff", "line-width": 1, "line-opacity": 0.5 } });
  map.addLayer({ id: "cone-fill", type: "fill", source: "cone", paint: { "fill-color": ["case", ["get", "fitted"], "#3e8bff", "#ffffff"], "fill-opacity": 0.22 } });
  map.addLayer({ id: "cone-line", type: "line", source: "cone", paint: { "line-color": ["case", ["get", "fitted"], "#3e8bff", "#ffffff"], "line-width": 2 } });
  map.addLayer({ id: "people-r", type: "fill", source: "people", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#2fbf71", "fill-opacity": 0.18 } });
  map.addLayer({ id: "people", type: "circle", source: "people", filter: ["==", ["geometry-type"], "Point"],
    paint: { "circle-radius": 6, "circle-color": "#2fbf71", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
  map.addLayer({ id: "testcirc", type: "line", source: "testcirc", paint: { "line-color": "#ff3df5", "line-width": 2 } });
  mapReady = true;
  map.on("click", onMapClick);
  map.on("mousemove", onMapMove);
  const img = $("#cf-img");
  img.addEventListener("click", onFrameClick);
  img.addEventListener("mousemove", onFrameMove);
  img.addEventListener("mouseleave", () => { markers.test?.remove(); markers.test = null; setData("testcirc", FC([])); $("#cf-read").textContent = ""; });
  new ResizeObserver(() => drawOverlay()).observe($("#cf-box"));
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || root.classList.contains("hidden")) return;
    C.mode = null; C.pending = null; C.bdraft = null; hint(); render();
  });
}
const FC = feats => ({ type: "FeatureCollection", features: feats });
const poly = (ring, props = {}) => ({ type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [ring] } });
const line = coords => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } });
const pt = (lon, lat, props = {}) => ({ type: "Feature", properties: props, geometry: { type: "Point", coordinates: [lon, lat] } });
const setData = (id, fc) => mapReady && map.getSource(id)?.setData(fc);
function hint(text) { const el = $("#c-hint"); if (!el) return; el.textContent = text || ""; el.classList.toggle("hidden", !text); }

// ------------------------------------------------------------------ open / close / load
async function open(feed, tab) {
  try { if (!root) await build(); } catch (err) { toast(`Couldn't open Calibrate: ${err.message}`); root?.remove(); root = null; return; }
  root.classList.remove("hidden");
  map.resize();
  C.feed = feed || C.feed; C.tab = tab === "site" ? "site" : "camera"; C.mode = null; C.pending = null; C.sel = null; C.bdraft = null; hint();
  try {
    const r = await api("/calib/sites");
    C.sites = r.sites; C.liveCams = r.live_cameras;
    // the record this feed's projection uses: the newest calibrated one linking it (= ask.sitemap._row_for), else any
    let pick = null;
    const better = (a, b) => !b || a.calibrated !== b.calibrated ? a.calibrated || !b : a.updated_at > b.updated_at;
    for (const s of C.feed ? C.sites : []) {
      const full = await api(`/calib/sites/${encodeURIComponent(s.id)}`);
      for (const c of full.cameras) if (c.source?.camera_id === C.feed && better(c, pick?.c)) pick = { s: full, c };
    }
    if (pick) { C.site = pick.s; selectRecord(pick.c.id, true); flyTo(); }
    else if (C.site) await loadSite(C.site.id);
    else if (C.sites.length) await loadSite(C.sites[0].id);
    else { C.site = null; C.cid = null; C.d = null; }
  } catch (err) { if (err.status !== 401) toast(`Couldn't load sites: ${err.message}`); }
  render();
}
function close() { root.classList.add("hidden"); stopPeople(); }
async function loadSite(sid, keepCid) {
  C.site = await api(`/calib/sites/${encodeURIComponent(sid)}`);
  const cid = keepCid && C.site.cameras.some(c => c.id === keepCid) ? keepCid
    : (C.site.cameras.find(c => C.feed && c.source?.camera_id === C.feed) || C.site.cameras[0])?.id;
  selectRecord(cid || null, true);
  flyTo();
}
function flyTo() {
  const c = rec();
  if (c) map.jumpTo({ center: [c.lon, c.lat], zoom: Math.max(C.site.zoom || 18, 18.5) });
  else if (C.site) map.jumpTo({ center: [C.site.lon, C.site.lat], zoom: C.site.zoom || 18 });
}
function selectRecord(cid, quiet) {
  if (C.d?.dirty && !quiet && !confirm("Discard the unsaved draft of this camera?")) { render(); return; }
  C.cid = cid; C.sel = null; C.pending = null; C.mode = null; hint();
  C.d = rec() ? draftFrom(rec()) : null;
  stopPeople(); startPeople();
  if (!quiet) { flyTo(); render(); }
}
async function newSite() {
  const name = prompt("New site name (centred on the current map view):");
  if (!name?.trim()) { render(); return; }
  try {
    const c = map.getCenter();
    const s = await send("POST", "/calib/sites", { name: name.trim(), lat: c.lat, lon: c.lng, zoom: map.getZoom() });
    C.sites = (await api("/calib/sites")).sites;
    await loadSite(s.id); C.tab = "site";
  } catch (err) { toast(`Couldn't create the site: ${err.message}`); }
  render();
}

// ------------------------------------------------------------------ draft: refit after every change
function changed() {
  C.d.dirty = true;
  clearTimeout(C.fitT);
  C.fitT = setTimeout(refit, 120);
  render();
}
async function refit() {
  const d = C.d; if (!d) return;
  if (!d.frame || d.points.length < 2) { d.fit = null; d.footprint = null; d.fitting = false; render(); return; }
  const seq = ++C.fitSeq;
  d.fitting = true; renderState();
  try {
    const r = await send("POST", "/calib/fit", { model: d.model, frame: { width: d.frame.width, height: d.frame.height }, points: d.points, fit_position: d.fit_position });
    if (seq !== C.fitSeq || d !== C.d) return;
    d.model = r.model; d.fit = r.fit; d.footprint = r.footprint; d.fitErr = null;
  } catch (err) { if (seq === C.fitSeq) d.fitErr = err.message; }
  if (seq === C.fitSeq) { d.fitting = false; render(); }
}

async function freeze() {
  const d = C.d, c = rec();
  const feed = c?.source?.camera_id || C.freezeFrom || C.feed;
  if (!feed) { toast("Pick the live feed to freeze a frame from."); return; }
  if (d.points.length && !confirm(`A new frame clears the ${d.points.length} draft point pair(s) (their pixels are on the old picture). Continue?`)) return;
  try {
    const f = await send("POST", `/calib/freeze/${encodeURIComponent(feed)}`);
    d.frame = { kind: "frozen", ...f, from: f.source === "ring" ? `live:${feed}` : `netra-ask preview of ${feed}`, url: `${API}/${f.url}` };
    if (f.age_s > 60) toast(`${feed}'s live feed has no current frame: froze its newest picture, ${Math.round(f.age_s / 60)} min old. Fine if the camera hasn't moved.`);
    d.points = []; d.fit = null; d.footprint = null; C.sel = null; C.pending = null;
    changed();
  } catch (err) { toast(`Couldn't freeze a frame: ${err.message}`); }
}

async function save() {
  const d = C.d, c = rec();
  if (!d || C.saving) return;
  if (c.calibrated && d.points.length < 2 && !confirm(`Saving with ${d.points.length} pair(s) removes the calibration of “${c.name}”: its people stop landing on the map. Continue?`)) return;
  if (d.frame?.kind === "frozen" && c.calibrated && !confirm(`Replace the saved frame and calibration of “${c.name}” (${fitLine(c.fit)}) with this draft?`)) return;
  C.saving = true; renderState();
  try {
    let r;
    if (d.frame?.kind === "frozen") r = await send("POST", `/calib/sites/${encodeURIComponent(C.site.id)}/cameras/${encodeURIComponent(c.id)}/frame?frozen=${encodeURIComponent(d.frame.token)}`);
    r = await send("PATCH", `/calib/sites/${encodeURIComponent(C.site.id)}/cameras/${encodeURIComponent(c.id)}`,
      { ...d.model, points: d.points.map(({ u, v, lat, lon, label }) => ({ u, v, lat, lon, ...(label ? { label } : {}) })), fit_position: d.fit_position, refit: true });
    const i = C.site.cameras.findIndex(x => x.id === r.id); C.site.cameras[i] = r;
    const draftLoo = d.fit?.loo?.median_m;
    C.d = draftFrom(r);
    toast(r.calibrated ? `Saved: ${fitLine(r.fit)}${draftLoo != null && r.fit?.loo?.median_m != null && Math.abs(draftLoo - r.fit.loo.median_m) > 0.05 ? ` (draft said ±${fx(draftLoo)} m)` : ""}` : "Saved (not calibrated: fewer than 2 pairs)");
    stopPeople(); startPeople();
  } catch (err) {
    toast(`Couldn't save: ${err.message}`);
    try { await loadSite(C.site.id, c.id); } catch {}      // show what netra-ask holds now, never a stale guess
  }
  C.saving = false; render();
}

async function addCamera(lat, lon, source) {
  try {
    const live = C.liveCams.find(l => l.id === source);
    const c = await send("POST", `/calib/sites/${encodeURIComponent(C.site.id)}/cameras`, {
      name: live ? live.name : `Camera ${C.site.cameras.length + 1}`, lat, lon, yaw: 0,
      source: live ? { kind: "live", camera_id: live.id } : { kind: "upload" } });
    await loadSite(C.site.id, c.id);
    toast(`Added “${c.name}”. Aim it, freeze a frame, then add point pairs.`);
  } catch (err) { toast(`Couldn't add the camera: ${err.message}`); }
  render();
}

// ------------------------------------------------------------------ live people through the saved calibration
function startPeople() {
  const c = rec();
  if (!c?.calibrated || !c.source?.camera_id) { C.people = null; C.peopleErr = null; drawPeople(); return; }
  const id = c.id;
  const tick = async () => {
    if (C.cid !== id || root.classList.contains("hidden")) return;
    try { C.people = await api(`/calib/sites/${encodeURIComponent(C.site.id)}/cameras/${encodeURIComponent(id)}/people`); C.peopleErr = null; }
    catch (err) { C.peopleErr = err.message; }
    if (C.cid !== id) return;
    drawPeople(); renderPeople();
    C.peopleT = setTimeout(tick, 2000);
  };
  tick();
}
function stopPeople() { clearTimeout(C.peopleT); C.peopleT = null; C.people = null; drawPeople(); }
function drawPeople() {
  const feats = [];
  for (const p of C.people?.people || []) if (p.lat != null) {
    feats.push(poly(circle(p.lat, p.lon, Math.max(p.radius_m || 0.5, 0.5))));
    feats.push(pt(p.lon, p.lat));
  }
  setData("people", FC(feats));
}

// ------------------------------------------------------------------ render: top bar + pane
function render() {
  if (!root) return;
  root.querySelectorAll(".ctabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === C.tab));
  const ss = $("#cb-site");
  ss.innerHTML = C.sites.map(s => `<option value="${esc(s.id)}" ${C.site?.id === s.id ? "selected" : ""}>${esc(s.name)}</option>`).join("") + `<option value="+new">+ New site here…</option>`;
  if (!C.site) ss.value = "";
  const cs = $("#cb-cam");
  cs.innerHTML = (C.site?.cameras || []).map(c => `<option value="${esc(c.id)}" ${c.id === C.cid ? "selected" : ""}>${esc(c.name)}${c.source?.camera_id ? ` · ${esc(c.source.camera_id)}` : " · still"}${c.calibrated ? "" : " · not calibrated"}</option>`).join("")
    || `<option value="">No cameras on this site</option>`;
  cs.classList.toggle("hidden", C.tab !== "camera");
  root.classList.toggle("sitetab", C.tab === "site");
  const pane = $("#cpane"); const keep = pane.scrollTop; pane.innerHTML = "";
  if (!C.site) paneNoSite(pane); else if (C.tab === "site") paneSite(pane); else paneCam(pane);
  pane.scrollTop = keep;
  renderState(); drawMap(); drawFrame();
}
function renderState() {
  const d = C.d, el = $("#cb-state"); if (!el) return;
  el.innerHTML = C.saving ? `<span class="chip">Saving…</span>` : d?.fitting ? `<span class="chip">Fitting…</span>`
    : d?.dirty ? `<span class="chip amber">Unsaved draft</span>` : d ? `<span class="chip green">Saved in netra-ask</span>` : "";
}
function paneNoSite(pane) {
  pane.append(h(`<h2>No site yet</h2>`));
  pane.append(h(`<p class="muted small">A site is the place on the satellite map that cameras are calibrated onto. Pan the map to it, then create it here.</p>`));
  pane.append(btn("New site here", "primary", newSite));
}
function paneCam(pane) {
  const c = rec(), d = C.d;
  if (!c) {
    pane.append(h(`<h2>${esc(C.site.name)}</h2>`));
    pane.append(h(`<p class="muted small">${C.feed ? `${esc(C.feed)} isn't on this site's map yet.` : "No camera on this site yet."} Add it by clicking where it is mounted.</p>`));
    addCameraControls(pane);
    return;
  }
  const feed = c.source?.camera_id;
  pane.append(h(`<h2>${esc(c.name)}</h2>`));
  pane.append(h(`<div class="muted small">${feed ? `Live feed <span class="mono">${esc(feed)}</span>` : "Uploaded still (no live feed)"} · record <span class="mono">${esc(c.id)}</span></div>`));
  if (c.calibrated) pane.append(h(`<div class="muted small">Saved: ${esc(fitLine(c.fit))}${c.fit?.fitted_at ? ` · ${esc(ago(c.fit.fitted_at))}` : ""}</div>`));
  const others = feed ? C.site.cameras.filter(x => x.id !== c.id && x.source?.camera_id === feed && x.calibrated) : [];
  if (others.length) pane.append(h(`<div class="step warn">${others.length + 1} calibrated records link ${esc(feed)}. netra-ask projects its people with the most recently saved one.</div>`));

  // 1 frame
  pane.append(h(`<div class="label"><span>1 · Frame</span></div>`));
  if (d.frame) pane.append(h(`<div class="muted small">${d.frame.kind === "frozen" ? "<b>Draft</b> frame frozen" : "Saved frame"} ${d.frame.width}×${d.frame.height} from ${esc(d.frame.from || "?")}, taken ${esc(ago(d.frame.captured_at))}.</div>`));
  else pane.append(h(`<p class="muted small">No frame yet. Freeze one from the live feed. Points you click are on this picture.</p>`));
  const frow = h(`<div class="row" style="margin-top:6px"></div>`);
  if (!feed) {
    const sel = h(`<select class="full"><option value="">Freeze from…</option>${C.liveCams.map(l => `<option value="${esc(l.id)}" ${(C.freezeFrom || C.feed) === l.id ? "selected" : ""}>${esc(l.name)}</option>`).join("")}</select>`);
    sel.onchange = () => { C.freezeFrom = sel.value || null; };
    frow.append(sel);
  }
  frow.append(btn(d.frame ? "Freeze a new frame" : "Freeze the live frame", d.frame ? "" : "primary", freeze));
  pane.append(frow);

  // 2 pairs + fit
  pane.append(h(`<div class="label"><span>2 · Point pairs</span><span>${d.points.length}</span></div>`));
  if (!d.frame) pane.append(h(`<p class="muted small">Then click points that are on the ground and easy to find on the satellite map: kerb corners, paint, drain covers, path junctions. Spread them near and far.</p>`));
  else {
    if (C.mode === "pair") pane.append(h(`<div class="step">${C.pending ? (C.pending.u != null ? "Now click the same point on the map." : "Now click the same point in the frame.") : "Click a ground point in the frame, then the same point on the map (either order). Esc to stop."}</div>`));
    pane.append(btn(C.mode === "pair" ? "Done adding" : "Add point pairs", C.mode === "pair" ? "on" : "primary", () => {
      C.mode = C.mode === "pair" ? null : "pair"; C.pending = null; hint(C.mode === "pair" ? "Pair mode: frame point ↔ map point · Esc to stop" : ""); render();
    }));
    fitBox(pane);
    if (d.points.length) {
      const loo = d.fit?.loo?.per_point_m || [], pp = d.fit?.per_point || [];
      const t = h(`<table class="pairs"><tr><th>#</th><th>px off</th><th>m off</th><th>checked</th><th></th></tr></table>`);
      d.points.forEach((p, i) => {
        const bad = loo[i] != null && loo[i] > Math.max(3, 3 * (d.fit?.loo?.median_m || 0));
        const r = h(`<tr class="${C.sel === i ? "sel" : ""}"><td><span class="num">${i + 1}</span></td><td class="n">${fx(pp[i]?.px)}</td>
          <td class="n">${fx(pp[i]?.m)}</td><td class="n ${bad ? "bad" : ""}">${loo[i] != null ? fx(loo[i]) + " m" : "–"}</td><td><button class="x" title="Remove">×</button></td></tr>`);
        r.onclick = () => { C.sel = i; render(); map.easeTo({ center: [p.lon, p.lat] }); };
        r.querySelector(".x").onclick = ev => { ev.stopPropagation(); d.points.splice(i, 1); C.sel = null; changed(); };
        t.append(r);
      });
      pane.append(t);
      pane.append(h(`<div class="muted small" style="margin-top:4px">“checked” = how far that pixel lands from its map point when the fit is redone without it (leave-one-out). Drag a point in the frame or on the map to adjust it.</div>`));
    }
    const fp = h(`<label class="small" style="display:block;margin-top:8px"><input type="checkbox" ${d.fit_position ? "checked" : ""} ${d.points.length < 6 ? "disabled" : ""}> Also fit the camera position (6+ pairs)</label>`);
    fp.firstElementChild.onchange = e => { d.fit_position = e.target.checked; changed(); };
    pane.append(fp);
  }

  // pose
  pane.append(h(`<div class="label"><span>Pose${d.fit ? " (fitted)" : " (by hand)"}</span></div>`));
  pane.append(h(`<div class="muted small" style="margin-bottom:6px">${ll(d.model.lat, d.model.lon)} · drag the blue marker to move the camera${d.fit ? "" : ", the white handle to aim it"}.</div>`));
  const g = h(`<div class="grid2"></div>`);
  [["height_m", "Height m", 0.1], ["yaw", "Heading°", 1], ["pitch", "Down°", 0.5], ["hfov", "Lens°", 0.5], ["roll", "Roll°", 0.1]].forEach(([k, label, step]) => {
    const f = h(`<div class="field"><label>${label}</label><input type="number" step="${step}" value="${fx(d.model[k], 2)}" ${d.fit ? "disabled" : ""}></div>`);
    f.querySelector("input").onchange = e => { d.model[k] = Number(e.target.value); changed(); };
    g.append(f);
  });
  pane.append(g);
  if (d.fit) pane.append(h(`<div class="muted small" style="margin-top:4px">With 2+ pairs the pose is fitted (height ${d.fit.free.includes("height_m") ? "fitted" : `held at ${fx(d.model.height_m)} m: set it with fewer than 4 pairs`}).</div>`));

  // save
  pane.append(h(`<div class="label"><span>3 · Save</span></div>`));
  const srow = h(`<div class="row"></div>`);
  srow.append(btn(C.saving ? "Saving…" : "Save calibration", "primary", save, !d.dirty || C.saving || d.fitting));
  if (d.dirty) srow.append(btn("Discard draft", "", () => { if (confirm("Discard the draft and go back to what's saved?")) { C.d = draftFrom(c); C.sel = null; render(); } }));
  pane.append(srow);
  pane.append(h(`<div class="muted small" style="margin-top:4px">${d.dirty ? "Nothing is saved yet: the fit above is a draft, computed with netra-ask's own fitting code." : "Saved in netra-ask: sitefuse and pixel_to_latlon use it now."}${d.frame?.kind === "frozen" ? " Saving uploads the frozen frame first, then the pairs." : ""}</div>`));

  // live check
  pane.append(h(`<div class="label"><span>4 · Check against live people</span></div>`));
  pane.append(h(`<div id="cpeople" class="small"></div>`));
  renderPeople();

  pane.append(h(`<div class="label"><span>Camera records</span></div>`));
  addCameraControls(pane);
  pane.append(btn("Delete this camera record", "danger", async () => {
    if (!confirm(`Delete “${c.name}” (${c.id}) and its calibration from netra-ask? This cannot be undone.`)) return;
    try { await send("DELETE", `/calib/sites/${encodeURIComponent(C.site.id)}/cameras/${encodeURIComponent(c.id)}`); C.d = null; await loadSite(C.site.id); }
    catch (err) { toast(`Couldn't delete: ${err.message}`); }
    render();
  }));
}
function fitBox(pane) {
  const d = C.d, f = d.fit;
  if (d.fitErr) { pane.append(h(`<div class="step warn">The fit failed: ${esc(d.fitErr)}</div>`)); return; }
  if (!f) { pane.append(h(`<p class="muted small" style="margin-top:6px">${d.points.length < 2 ? "Add at least 2 pairs (4+ to fit height and lens, 5+ to check the fit)." : "Fitting…"}</p>`)); return; }
  const chk = f.loo?.median_m, pp = f.per_point || [];
  const worst = pp.reduce((w, p, i) => (p.px ?? 1e9) > (pp[w]?.px ?? -1) ? i : w, 0);
  if (f.at_limit?.length || f.rms_px > 15) pane.append(h(`<div class="step warn">These pairs don't agree with any real camera
    (${f.at_limit?.length ? `${esc(f.at_limit.join(", "))} hit a physical limit` : `${fx(f.rms_px)} px off on average`}). Usually one pair is a mis-click
    or a point that isn't on the ground; pair ${worst + 1} is furthest off. Remove or drag it.</div>`));
  const good = !f.at_limit?.length && (chk != null ? chk < 2 : f.ground_err_m < 2);
  pane.append(h(`<div class="fit ${good ? "good" : "poor"}"><b>${chk != null ? `±${fx(chk)} m` : `±${fx(f.ground_err_m)} m`}</b>
    ${chk != null ? `typical ground error on a point the fit didn't see (worst ${fx(f.loo.max_m)} m)` : "in-sample only: add a pair to check it independently"}
    <div class="muted small">${f.n} pairs · reprojection ${fx(f.rms_px)} px rms · fitted ${esc(f.free.join(", "))}${d.dirty ? " · draft" : ""}</div></div>`));
}
function renderPeople() {
  const el = $("#cpeople"); if (!el) return;
  const c = rec(), P = C.people;
  if (!c?.source?.camera_id) { el.innerHTML = `<span class="muted">This record has no live feed, so there are no live people to check against.</span>`; return; }
  if (!c.calibrated) { el.innerHTML = `<span class="muted">Save a calibration first; then every person the camera sees now is drawn on the map with it.</span>`; return; }
  if (C.peopleErr) { el.innerHTML = `<span class="muted">Couldn't project live people: ${esc(C.peopleErr)}</span>`; return; }
  if (!P) { el.innerHTML = `<span class="muted">Loading…</span>`; return; }
  if (P.why) { el.innerHTML = `<span class="muted">${esc(P.why)}</span>`; return; }
  const on = P.people.filter(p => p.lat != null);
  el.innerHTML = `<div><b>${P.people.length}</b> ${P.people.length === 1 ? "person" : "people"} in view now · <b>${on.length}</b> on the map (green dots, saved calibration) · ${fx(P.lag_s, 1)} s behind live</div>
    ${P.people.length - on.length ? `<div class="muted">${P.people.length - on.length} above the horizon or out of range</div>` : ""}
    <div class="muted">Does each dot sit where that person really is? If not, fix the pairs and save again.</div>
    ${on.map(p => `<div class="mono muted">${esc(p.track_uuid.slice(0, 4))} ${ll(p.lat, p.lon)} ±${fx(p.radius_m)} m</div>`).join("")}`;
}
function addCameraControls(pane) {
  const live = C.liveCams.find(l => l.id === C.feed);
  const linked = C.feed && C.site.cameras.some(c => c.source?.camera_id === C.feed && c.calibrated);
  const row = h(`<div class="row"></div>`);
  if (C.mode === "place") {
    row.append(h(`<div class="step">Click the map where the camera is mounted · Esc to cancel</div>`));
  } else {
    if (live) row.append(btn(`Add ${live.id} here`, rec() ? "" : "primary", () => {
      if (linked && !confirm(`${C.feed} already has a calibrated record. A second one, once saved, takes over its people → map projection (newest wins). Add anyway?`)) return;
      C.mode = "place"; C.placeSource = live.id; hint("Click the map where the camera is mounted · Esc to cancel"); render();
    }));
    row.append(btn("Add a still-only camera", "", () => { C.mode = "place"; C.placeSource = null; hint("Click the map where the camera is mounted · Esc to cancel"); render(); }));
  }
  pane.append(row);
}
function paneSite(pane) {
  const s = C.site;
  pane.append(h(`<h2>${esc(s.name)}</h2>`));
  pane.append(h(`<div class="muted small">${ll(s.lat, s.lon)} · ${s.cameras.length} camera${s.cameras.length === 1 ? "" : "s"}, ${s.cameras.filter(c => c.calibrated).length} calibrated</div>`));
  pane.append(h(`<div class="label"><span>Boundary</span><span>${(C.bdraft || s.boundary || []).length} points</span></div>`));
  pane.append(h(`<p class="muted small">The site's outline. The drone uses it as its geofence (GET /ask/api/sites/${esc(s.id)}/boundary.geojson).</p>`));
  const row = h(`<div class="row"></div>`);
  if (C.bdraft) {
    pane.append(h(`<div class="step">${C.mode === "boundary" ? "Click the map to add corners (they join up after the last one). " : ""}Drag a corner to move it; double-click a corner to remove it.</div>`));
    row.append(btn(`Save boundary (${C.bdraft.length})`, "primary", async () => {
      try { C.site = await send("PATCH", `/calib/sites/${encodeURIComponent(s.id)}`, { boundary: C.bdraft }); C.bdraft = null; C.mode = null; hint(); toast("Boundary saved"); }
      catch (err) { toast(`Couldn't save the boundary: ${err.message}`); }
      render();
    }, C.bdraft.length < 3));
    row.append(btn(C.mode === "boundary" ? "Stop adding" : "Add corners", "", () => { C.mode = C.mode === "boundary" ? null : "boundary"; hint(C.mode ? "Click the map to add corners · Esc to cancel" : ""); render(); }));
    row.append(btn("Cancel", "", () => { C.bdraft = null; C.mode = null; hint(); render(); }));
  } else {
    if (s.boundary?.length) row.append(btn("Edit boundary", "primary", () => { C.bdraft = s.boundary.map(p => [...p]); render(); }));
    row.append(btn(s.boundary?.length ? "Redraw" : "Draw boundary", s.boundary?.length ? "" : "primary", () => {
      C.bdraft = []; C.mode = "boundary"; hint("Click the map to outline the site · Esc to cancel"); render();
      map.jumpTo({ center: [s.lon, s.lat] });
    }));
    if (s.boundary?.length) row.append(btn("Clear", "danger", async () => {
      if (!confirm("Remove the site boundary? The drone loses its geofence for this site.")) return;
      try { C.site = await send("PATCH", `/calib/sites/${encodeURIComponent(s.id)}`, { boundary: null }); } catch (err) { toast(`Couldn't save: ${err.message}`); }
      render();
    }));
  }
  pane.append(row);
  pane.append(h(`<div class="label"><span>Map centre</span></div>`));
  pane.append(btn("Centre the site here", "", async () => {
    const c = map.getCenter();
    try { C.site = await send("PATCH", `/calib/sites/${encodeURIComponent(s.id)}`, { lat: c.lat, lon: c.lng, zoom: map.getZoom() }); toast("Site centre saved"); } catch (err) { toast(`Couldn't save: ${err.message}`); }
    render();
  }));
  pane.append(h(`<div class="label"><span>Cameras</span></div>`));
  for (const c of s.cameras) {
    const b = h(`<button type="button" class="card"><div class="t">${esc(c.name)}</div><div class="s">${c.calibrated ? `<span class="dot ok"></span>${esc(fitLine(c.fit))}` : `<span class="dot warn"></span>not calibrated`} · ${c.source?.camera_id ? esc(c.source.camera_id) : "still"}</div></button>`);
    b.onclick = () => { C.tab = "camera"; selectRecord(c.id); };
    pane.append(b);
  }
  if (!s.cameras.length) pane.append(h(`<p class="muted small">No cameras yet.</p>`));
  if (!s.cameras.length) pane.append(btn("Delete this empty site", "danger", async () => {
    if (!confirm(`Delete the site “${s.name}”?`)) return;
    try { await send("DELETE", `/calib/sites/${encodeURIComponent(s.id)}`); C.sites = (await api("/calib/sites")).sites; C.site = null; C.cid = null; C.d = null; if (C.sites.length) await loadSite(C.sites[0].id); }
    catch (err) { toast(`Couldn't delete: ${err.message}`); }
    render();
  }));
}

// ------------------------------------------------------------------ map
function drawMap() {
  if (!mapReady) return;
  const s = C.site, d = C.d, c = rec();
  const ring = C.bdraft || s?.boundary;
  setData("boundary", FC(ring?.length >= 3 ? [poly([...ring, ring[0]].map(([a, b]) => [b, a]))] : ring?.length === 2 ? [line(ring.map(([a, b]) => [b, a]))] : []));
  markers.verts.forEach(m => m.remove()); markers.verts = [];
  if (C.tab === "site" && C.bdraft) C.bdraft.forEach((p, i) => {
    const el = h(`<div class="vertmark" title="Drag to move · double-click to remove"></div>`);
    const m = new maplibregl.Marker({ element: el, draggable: true }).setLngLat([p[1], p[0]]).addTo(map);
    m.on("drag", () => { const q = m.getLngLat(); C.bdraft[i] = [q.lat, q.lng]; drawMapBoundaryOnly(); });
    m.on("dragend", () => render());
    el.addEventListener("click", ev => ev.stopPropagation());
    el.addEventListener("dblclick", ev => { ev.stopPropagation(); C.bdraft.splice(i, 1); render(); });
    markers.verts.push(m);
  });
  setData("others", FC((s?.cameras || []).filter(x => x.id !== C.cid).map(x => x.footprint || x.view_cone).filter(Boolean).map(r => poly(r.map(([a, b]) => [b, a])))));
  markers.others.forEach(m => m.remove()); markers.others = [];
  for (const x of s?.cameras || []) if (x.id !== C.cid) {
    const el = h(`<div class="cammark other" title="${esc(x.name)}"><span style="display:inline-block;transform:rotate(${x.yaw}deg)">▲</span></div>`);
    el.addEventListener("click", ev => { ev.stopPropagation(); C.tab = "camera"; selectRecord(x.id); });
    markers.others.push(new maplibregl.Marker({ element: el }).setLngLat([x.lon, x.lat]).addTo(map));
  }
  markers.cam?.remove(); markers.head?.remove(); markers.cam = markers.head = null;
  if (c && d) {
    const r = d.footprint || cone(d.model);
    setData("cone", FC([poly(r.map(([a, b]) => [b, a]), { fitted: !!d.fit })]));
    const el = h(`<div class="cammark sel" title="${esc(c.name)} · drag to move"><span style="display:inline-block;transform:rotate(${d.model.yaw}deg)">▲</span></div>`);
    markers.cam = new maplibregl.Marker({ element: el, draggable: C.tab === "camera" }).setLngLat([d.model.lon, d.model.lat]).addTo(map);
    el.addEventListener("click", ev => ev.stopPropagation());
    markers.cam.on("dragend", () => { const p = markers.cam.getLngLat(); d.model.lat = p.lat; d.model.lon = p.lng; changed(); });
    if (!d.fit && C.tab === "camera") {
      const [la, lo] = fromEN(25 * Math.sin(d.model.yaw * RAD), 25 * Math.cos(d.model.yaw * RAD), d.model.lat, d.model.lon);
      markers.head = new maplibregl.Marker({ element: h(`<div class="headmark" title="Drag to aim"></div>`), draggable: true }).setLngLat([lo, la]).addTo(map);
      markers.head.on("dragend", () => { d.model.yaw = bearing({ lat: d.model.lat, lng: d.model.lon }, markers.head.getLngLat()); changed(); });
    }
  } else setData("cone", FC([]));
  markers.pairs.forEach(m => m.remove()); markers.pairs = [];
  markers.pending?.remove(); markers.pending = null;
  if (d && C.tab === "camera") {
    d.points.forEach((p, i) => {
      const el = h(`<div class="pairmark ${C.sel === i ? "sel" : ""}" title="Pair ${i + 1} · drag to adjust">${i + 1}</div>`);
      const m = new maplibregl.Marker({ element: el, draggable: true }).setLngLat([p.lon, p.lat]).addTo(map);
      m.on("dragend", () => { const q = m.getLngLat(); p.lat = q.lat; p.lon = q.lng; C.sel = i; changed(); });
      el.addEventListener("click", ev => { ev.stopPropagation(); C.sel = i; render(); });
      markers.pairs.push(m);
    });
    if (C.pending?.lat != null) markers.pending = new maplibregl.Marker({ element: h(`<div class="pairmark pending">${d.points.length + 1}</div>`) }).setLngLat([C.pending.lon, C.pending.lat]).addTo(map);
  }
  drawPeople();
}
function drawMapBoundaryOnly() {
  const ring = C.bdraft;
  setData("boundary", FC(ring?.length >= 3 ? [poly([...ring, ring[0]].map(([a, b]) => [b, a]))] : []));
}
function onMapClick(e) {
  const { lat, lng: lon } = e.lngLat;
  if (C.mode === "boundary") { C.bdraft.push([lat, lon]); render(); }
  else if (C.mode === "place") { C.mode = null; hint(); addCamera(lat, lon, C.placeSource); }
  else if (C.mode === "pair") {
    if (C.pending?.u != null) addPair({ ...C.pending, lat, lon });
    else { C.pending = { lat, lon }; hint("Now click the same point in the camera frame"); render(); }
  }
}
function onMapMove(e) {
  const fc = frameCam();
  if (!C.d?.fit || !fc || C.mode) return;
  const [ee, nn] = toEN(e.lngLat.lat, e.lngLat.lng, fc.lat, fc.lon), px = groundToPixel(fc, ee, nn);
  drawOverlay(px && px[0] >= 0 && px[1] >= 0 && px[0] <= fc.width && px[1] <= fc.height ? px : null);
}
function addPair(p) {
  C.d.points.push({ u: p.u, v: p.v, lat: p.lat, lon: p.lon });
  C.pending = null; C.sel = C.d.points.length - 1;
  hint("Pair added · next point, or Done adding");
  changed();
}

// ------------------------------------------------------------------ frame panel
function drawFrame() {
  const d = C.d, img = $("#cf-img"), none = $("#cf-none");
  const show = C.tab === "camera" && d?.frame;
  img.classList.toggle("hidden", !show); none.classList.toggle("hidden", !!show);
  $("#cf-cap").innerHTML = show ? `<b>${esc(rec().name)}</b> · ${d.frame.kind === "frozen" ? `<span class="chip amber">draft frame</span>` : "saved frame"} · ${d.frame.width}×${d.frame.height}` : "";
  if (!show) {
    none.textContent = C.tab === "site" ? "Site setup: draw the boundary on the map." : !rec() ? "Add the camera to the map first." : "No frame yet. Freeze one from the live feed.";
    $("#cf-over").innerHTML = ""; return;
  }
  if (img.getAttribute("src") !== d.frame.url) { img.onload = () => drawOverlay(); img.setAttribute("src", d.frame.url); }
  else drawOverlay();
}
function frameRect() {
  const img = $("#cf-img"), r = img.getBoundingClientRect(), b = $("#cf-box").getBoundingClientRect();
  return { x: r.left - b.left, y: r.top - b.top, w: r.width, h: r.height, k: r.width / (C.d?.frame?.width || 1) };
}
function drawOverlay(testPx) {
  const d = C.d, img = $("#cf-img"), over = $("#cf-over");
  if (!over) return;
  if (!d?.frame || C.tab !== "camera" || !img.complete || !img.naturalWidth) { over.innerHTML = ""; return; }
  const R = frameRect();
  Object.assign(over.style, { left: R.x + "px", top: R.y + "px", width: R.w + "px", height: R.h + "px" });
  over.setAttribute("viewBox", `0 0 ${d.frame.width} ${d.frame.height}`);
  const s = 1 / R.k, c = frameCam();
  let svg = "";
  if (d.fit) {                                         // the fitted horizon and the 25 / 50 / 100 m range lines
    const hz = [];
    for (let u = 0; u <= c.width; u += c.width / 32) {
      let lo = 0, hi = c.height;
      if (!pixelToGround(c, u, hi - 1, 1e9)) continue;
      for (let i = 0; i < 22; i++) { const mid = (lo + hi) / 2; pixelToGround(c, u, mid, 1e9) ? hi = mid : lo = mid; }
      hz.push(`${u},${hi}`);
    }
    if (hz.length > 1) svg += `<polyline points="${hz.join(" ")}" fill="none" stroke="#7fd1ff" stroke-width="${1.5 * s}" stroke-dasharray="${6 * s} ${4 * s}"/>`;
    for (const rng of [25, 50, 100]) {
      const pts = [];
      for (let a = -c.hfov; a <= c.hfov; a += c.hfov / 24) {
        const b = (c.yaw + a) * RAD, px = groundToPixel(c, rng * Math.sin(b), rng * Math.cos(b));
        if (px && px[0] >= -50 && px[0] <= c.width + 50) pts.push(px);
      }
      if (pts.length > 1) { const m = pts[pts.length >> 1];
        svg += `<polyline points="${pts.map(p => p.join(",")).join(" ")}" fill="none" stroke="rgba(255,255,255,.45)" stroke-width="${s}"/>
          <text x="${m[0]}" y="${m[1] - 4 * s}" fill="rgba(255,255,255,.75)" font-size="${11 * s}" text-anchor="middle">${rng} m</text>`; }
    }
  }
  d.points.forEach((p, i) => {
    if (d.fit) {                                       // where the fit puts this pair's map point: a short line = good
      const [e, n] = toEN(p.lat, p.lon, c.lat, c.lon), q = groundToPixel(c, e, n);
      if (q) svg += `<line x1="${p.u}" y1="${p.v}" x2="${q[0]}" y2="${q[1]}" stroke="#ff3df5" stroke-width="${2 * s}"/>`;
    }
    svg += `<g class="pt" data-i="${i}"><circle cx="${p.u}" cy="${p.v}" r="${(C.sel === i ? 11 : 9) * s}" fill="#ffd23f" stroke="#111" stroke-width="${2 * s}"/>
      <text x="${p.u}" y="${p.v + 4 * s}" font-size="${11 * s}" font-weight="700" text-anchor="middle" fill="#111">${i + 1}</text></g>`;
  });
  if (C.pending?.u != null) svg += `<circle cx="${C.pending.u}" cy="${C.pending.v}" r="${9 * s}" fill="#fff" stroke="#111" stroke-width="${2 * s}"/>`;
  if (testPx) svg += `<g stroke="#ff3df5" stroke-width="${2 * s}"><line x1="${testPx[0] - 14 * s}" y1="${testPx[1]}" x2="${testPx[0] + 14 * s}" y2="${testPx[1]}"/><line x1="${testPx[0]}" y1="${testPx[1] - 14 * s}" x2="${testPx[0]}" y2="${testPx[1] + 14 * s}"/></g>`;
  over.innerHTML = svg;
  over.querySelectorAll(".pt").forEach(g => g.addEventListener("pointerdown", dragPoint));
}
function framePx(ev) {
  const r = $("#cf-img").getBoundingClientRect(), f = C.d.frame;
  return [(ev.clientX - r.left) * f.width / r.width, (ev.clientY - r.top) * f.height / r.height];
}
function onFrameClick(ev) {
  if (!C.d?.frame || C.mode !== "pair") return;
  const [u, v] = framePx(ev);
  if (C.pending?.lat != null) addPair({ ...C.pending, u, v });
  else { C.pending = { u, v }; hint("Now click the same point on the map"); render(); }
}
function onFrameMove(ev) {
  const d = C.d, c = frameCam();
  if (!d?.fit || !c) return;
  const [u, v] = framePx(ev), g = pixelToGround(c, u, v), g1 = pixelToGround(c, u + 1, v), g2 = pixelToGround(c, u, v + 1);
  if (!g) { $("#cf-read").textContent = `px ${Math.round(u)}, ${Math.round(v)} · above the horizon`; markers.test?.remove(); markers.test = null; setData("testcirc", FC([])); return; }
  const r = Math.max(...[g1, g2].filter(Boolean).map(p => Math.hypot(p[0] - g[0], p[1] - g[1])), 0) + (d.fit.loo?.median_m ?? d.fit.ground_err_m ?? 0);
  const [lat, lon] = fromEN(g[0], g[1], c.lat, c.lon);
  $("#cf-read").textContent = `${ll(lat, lon)} ±${fx(r)} m · ${fx(Math.hypot(g[0], g[1]), 0)} m away`;
  if (!markers.test) markers.test = new maplibregl.Marker({ element: h(`<div class="testmark"></div>`) }).setLngLat([lon, lat]).addTo(map);
  else markers.test.setLngLat([lon, lat]);
  setData("testcirc", FC([poly(circle(lat, lon, Math.max(r, 0.3)))]));
}
function dragPoint(ev) {
  ev.preventDefault(); ev.stopPropagation();
  const i = Number(ev.currentTarget.dataset.i), p = C.d.points[i];
  let moved = false;
  const move = e => { [p.u, p.v] = framePx(e); moved = true; drawOverlay(); };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); C.sel = i; if (moved) changed(); else render(); };
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
}

window.Calib = { open, close, state: C };
})();
