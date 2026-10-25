// Send drone: the Sites monitor's layout around one addition. Right: camera tiles. Centre: the opened camera, live
// (~1 fps ring frame + the edge person boxes taken at the same instant), each box with a chip `#id conf · suspicion|—`
// and a Send drone button (inline confirm of the operator's own click; Sauron's autonomous launches have no gate).
// Left: the incidents this demo launched (state, location, forwarded/delivered, what the drone received) + Abort.
// Everything is polled from the real APIs under /hack/api; when a piece is missing the page says so and shows nothing.
const API = "/hack/api";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const h = html => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const toast = msg => { const t = h(`<div class="toast">${esc(msg)}</div>`); $("#toasts").append(t); setTimeout(() => t.remove(), 6000); };
const fx = (v, d = 1) => v == null ? "–" : Number(v).toFixed(d);
const ll = (lat, lon) => `${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}`;
const ago = iso => {
  if (!iso) return "";
  const s = Math.round((Date.now() - new Date(iso)) / 1e3);
  return s < 5 ? "just now" : s < 90 ? `${s} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(iso).toLocaleString();
};
const shortId = tu => `#${String(tu || "").replace(/-/g, "").slice(0, 4)}`;
function btn(text, cls, fn, disabled) { const b = h(`<button type="button" class="btn ${cls}">${esc(text)}</button>`); b.onclick = fn; b.disabled = !!disabled; return b; }

async function api(path, opts = {}) {
  const r = await fetch(API + path, { credentials: "same-origin", ...opts, headers: { "Content-Type": "application/json" } });
  if (r.status === 401) { location.href = "/map/login?next=/hack/"; throw Object.assign(new Error("auth"), { status: 401 }); }
  if (!r.ok) { let m = `${r.status}`; try { m = (await r.json()).detail || m; } catch {} throw Object.assign(new Error(m), { status: r.status }); }
  return r.status === 204 ? null : r.json();
}
const post = (path, body) => api(path, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body || {}) });
// t_ns (~1.8e18) doesn't fit a JS number exactly, and launch matches the clicked obs on the exact t: keep it as the
// digit string from the raw JSON and write it back unquoted
const rawTns = text => text.match(/"t_ns"\s*:\s*(\d+)/)?.[1];

const S = {
  cams: null, camErr: null, cam: null,            // camera list, its error, the open camera id
  gen: 0, live: null, liveErr: null, liveAt: 0,   // live loop generation, the payload on screen, its error
  inc: new Map(), incErr: null,
  pending: new Map(),                             // track_uuid -> {state: "confirm"|"sending", box, t_ns}
  sentByTrack: new Map(),                         // track_uuid -> incident id (launched from this page)
  chips: new Map(),                               // track_uuid -> chip element
};

// ------------------------------------------------------------------ cameras (right)
async function pollCams() {
  try {
    const r = await api("/cameras");
    S.cams = Array.isArray(r) ? r : r.cameras || []; S.camErr = null;
    if (!S.cam) {
      const want = new URLSearchParams(location.hash.slice(1)).get("cam");
      const live = S.cams.filter(c => c.live);
      const pick = live.find(c => c.camera_id === want) || (live.length === 1 ? live[0] : null);
      if (pick) openCamera(pick.camera_id);
    }
  } catch (err) { if (err.status !== 401) S.camErr = err.status === 404 ? "The live-view API (hackdash.live) isn't deployed yet." : `Couldn't load cameras: ${err.message}`; }
  renderWall(); renderTop(); renderStage();
}
const camOf = id => S.cams?.find(c => c.camera_id === id);
function renderWall() {
  const wall = $("#wall");
  // only cameras with a current picture: a camera that isn't live (or whose picture won't load) isn't listed
  const cams = (S.cams || []).filter(c => c.live);
  const none = () => h(`<div class="wempty">No camera is live right now.</div>`);
  wall.innerHTML = "";
  wall.append(h(`<div class="whead"><h2>Cameras</h2><span class="muted small">${S.cams ? `${cams.length} live` : ""}</span></div>`));
  if (S.camErr || !cams.length) {
    wall.append(S.camErr || S.cams ? (S.camErr ? h(`<div class="wempty">${esc(S.camErr)}</div>`) : none()) : h(`<div class="wempty">Loading…</div>`));
    return;
  }
  for (const c of cams) {
    const open = S.cam === c.camera_id;
    // the edge preview netra-ask already serves (~30 s old); the open camera falls back to its newest live frame
    const src = `/ask/api/preview/${encodeURIComponent(c.camera_id)}.jpg?m=${Math.floor(Date.now() / 30e3)}`;
    const t = h(`<button class="tile ${open ? "sel" : ""}"><div class="tframe"><img alt="">
      <div class="tover"><i class="live"></i><span>${esc(c.name || c.camera_id)}</span></div></div>
      <div class="tinfo"><div class="tstate">Live${c.fps != null ? ` · ${fx(c.fps, 1)} fps` : ""}${open ? " · open" : ""}</div>
      <div class="tchips">${c.test_rig ? `<span class="chip test">test rig</span>` : ""}${c.calibrated ? `<span class="chip">On the map</span>` : `<span class="chip amber">Not calibrated</span>`}</div></div></button>`);
    const img = t.querySelector("img");
    img.onerror = () => {
      if (open && S.live?.frame_url && !img.dataset.fb) { img.dataset.fb = 1; img.src = frameUrl(S.live.frame_url); return; }
      t.remove(); if (!wall.querySelector(".tile")) wall.append(none());
    };
    img.src = src;
    t.onclick = () => openCamera(c.camera_id);
    const cal = h(`<span class="chip calib" role="button" title="Calibrate this camera on the map">Calibrate</span>`);   // calib.js
    cal.onclick = e => { e.stopPropagation(); openCalib(c.camera_id); };
    t.querySelector(".tchips").append(cal);
    if (S.ptzCams?.has(c.camera_id)) {                                     // ptz.js
      const mv = h(`<span class="chip calib" role="button" title="Pan / tilt / zoom this camera by hand">Move camera</span>`);
      mv.onclick = e => { e.stopPropagation(); openPtz(c.camera_id); };
      t.querySelector(".tchips").append(mv);
    }
    wall.append(t);
  }
}

// Calibrate / Site setup (hackdash/static/calib.js, a full-screen screen over this page), loaded on first use
function openCalib(cam, tab) {
  if (window.Calib) return window.Calib.open(cam, tab);
  const s = document.createElement("script"); s.src = `/hack/static/calib.js?v=${Date.now()}`; s.onload = () => window.Calib.open(cam, tab); document.head.append(s);
}
document.querySelector("#topbar .grow")?.after(btn("Calibrate / site setup", "ghost", () => openCalib(S.cam, "site")));

// Move camera (hackdash/static/ptz.js, full-screen PTZ control over this page), loaded on first use
function openPtz(cam) {
  if (window.Ptz) return window.Ptz.open(cam);
  const l = document.createElement("link"); l.rel = "stylesheet"; l.href = `/hack/static/ptz.css?v=${Date.now()}`; document.head.append(l);
  const s = document.createElement("script"); s.src = `/hack/static/ptz.js?v=${Date.now()}`; s.onload = () => window.Ptz.open(cam); document.head.append(s);
}
api("/ptz").then(r => { S.ptzCams = new Set(r.map(c => c.camera_id)); renderWall(); renderTop(); }).catch(() => {});

// ------------------------------------------------------------------ the open camera, live (centre)
function openCamera(id) {
  if (S.cam === id) return;
  S.cam = id; S.live = null; S.liveErr = null; S.gen++; S.pending.clear();
  S.chips.forEach(el => el.remove()); S.chips.clear();
  history.replaceState(null, "", `#cam=${encodeURIComponent(id)}`);
  $("#frameinner").classList.add("hidden");
  renderWall(); renderStage();
  startStream(S.gen);
  liveTick(S.gen);
}

// ------------------------------------------------------------------ live video (WHEP, else LL-HLS); the ring JPEGs are the fallback
// The pod stream at /hack/stream/<cam>/{whep,index.m3u8}. While it plays, /live is only polled for the newest boxes.
const STREAM = cam => `/hack/stream/${encodeURIComponent(cam)}`;
const HLS_JS = "https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.5.20/hls.min.js";
S.st = { state: "off" };                          // state: starting | playing | failed; mode: whep | hls
function stopStream() {
  const st = S.st, v = $("#vid");
  clearTimeout(st.retry); clearInterval(st.watch);
  st.hls?.destroy(); st.pc?.close();
  if (st.whepAt) fetch(st.whepAt, { method: "DELETE", credentials: "same-origin" }).catch(() => {});
  v.onerror = null; v.removeAttribute("src"); v.srcObject = null; v.load(); v.classList.add("hidden"); $("#frame").classList.remove("hidden");
  S.st = { state: "off" };
}
function firstFrame(v, ms) {
  return new Promise((ok, bad) => {
    const t = setTimeout(() => { done(); bad(new Error("no picture")); }, ms);
    const on = () => { if (v.videoWidth) { done(); ok(); } };
    const done = () => { clearTimeout(t); v.removeEventListener("playing", on); v.removeEventListener("loadeddata", on); };
    v.addEventListener("playing", on); v.addEventListener("loadeddata", on);
    v.play().catch(() => {});
  });
}
async function whep(cam, v, st) {
  const pc = st.pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = e => { if (e.track.kind === "video") v.srcObject = e.streams[0] || new MediaStream([e.track]); };
  pc.onconnectionstatechange = () => { if (["failed", "disconnected", "closed"].includes(pc.connectionState) && S.st === st && st.state === "playing") streamFailed(st, `WebRTC ${pc.connectionState}`); };
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(ok => { if (pc.iceGatheringState === "complete") ok(); pc.onicegatheringstatechange = () => pc.iceGatheringState === "complete" && ok(); setTimeout(ok, 1500); });
  const res = await fetch(`${STREAM(cam)}/whep`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/sdp" }, body: pc.localDescription.sdp });
  if (!res.ok) throw new Error(`WHEP ${res.status}`);
  const loc = res.headers.get("Location");
  if (loc) st.whepAt = new URL(loc, location.href).href;
  await pc.setRemoteDescription({ type: "answer", sdp: await res.text() });
  await firstFrame(v, 4000);
}
async function hls(cam, v, st) {
  const url = `${STREAM(cam)}/index.m3u8`;
  // hls.js (lowLatencyMode) wherever MSE exists; the browser's own HLS only without it (iPhone Safari)
  if (!window.Hls) await new Promise(ok => { const s = document.createElement("script"); s.src = HLS_JS; s.onload = s.onerror = ok; document.head.append(s); });
  let fatal;
  const died = new Promise((_, bad) => fatal = bad);
  if (window.Hls?.isSupported()) {
    const x = st.hls = new Hls({ lowLatencyMode: true, backBufferLength: 10 });
    x.on(Hls.Events.ERROR, (_, d) => {
      if (!d.fatal || S.st !== st) return;
      if (st.state === "playing") streamFailed(st, `HLS ${d.details}`); else fatal(new Error(`${d.details}${d.response?.code ? ` ${d.response.code}` : ""}`));
    });
    x.loadSource(url); x.attachMedia(v);
  } else if (v.canPlayType("application/vnd.apple.mpegurl")) {
    v.onerror = () => { if (S.st !== st) return; if (st.state === "playing") streamFailed(st, "HLS error"); else fatal(new Error("HLS error")); };
    v.src = url;
  } else throw new Error("no HLS player");
  await Promise.race([firstFrame(v, 8000), died]);
}
async function startStream(gen) {
  stopStream();
  const cam = S.cam, v = $("#vid"), st = S.st = { state: "starting" };
  renderStage();
  for (const [mode, fn] of [["whep", whep], ["hls", hls]]) {
    try {
      await fn(cam, v, st);
      if (gen !== S.gen || S.st !== st) return;
      st.state = "playing"; st.mode = mode;
      v.classList.remove("hidden"); $("#frame").classList.add("hidden"); $("#frameinner").classList.remove("hidden");
      // a picture that stops moving for 5 s is a failed stream: fall back to the ring and try again later
      let last = -1, still = 0;
      st.watch = setInterval(() => { if (document.hidden) return; if (v.currentTime === last) { if (++still >= 5) streamFailed(st, "video froze"); } else { still = 0; last = v.currentTime; } }, 1000);
      drawBoxes(); renderStage();
      return;
    } catch (err) {
      if (gen !== S.gen || S.st !== st) return;
      st.why = `${mode}: ${err.message}`;
      st.pc?.close(); st.pc = null; st.hls?.destroy(); st.hls = null;
      v.removeAttribute("src"); v.srcObject = null;
    }
  }
  streamFailed(st, st.why);
}
function streamFailed(st, why) {
  if (S.st !== st) return;
  const gen = S.gen;
  stopStream();
  S.st = { state: "failed", why, retry: setTimeout(() => { if (gen === S.gen) startStream(gen); }, 15000) };
  renderStage();
}
const frameUrl = u => /^(https?:)?\//.test(u) ? u : `${API}/${u}`;
async function liveTick(gen) {
  if (gen !== S.gen) return;
  const t0 = performance.now();
  try {
    const res = await fetch(`${API}/cameras/${encodeURIComponent(S.cam)}/live`, { credentials: "same-origin" });
    if (res.status === 401) { location.href = "/map/login?next=/hack/"; return; }
    const text = await res.text();
    if (!res.ok) { let m = `${res.status}`; try { m = JSON.parse(text).detail || m; } catch {} throw Object.assign(new Error(m), { status: res.status }); }
    const r = JSON.parse(text);
    r.t_ns = rawTns(text) || String(r.t_ns);
    if (gen !== S.gen) return;
    if (S.st.state === "playing") {}                // the video is the picture; only the boxes are new
    else if (r.frame_url) {
      // show the frame and its boxes together: preload the JPEG, then swap it in and draw the payload it belongs to
      const img = new Image();
      img.alt = "Live camera frame";
      await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error("frame didn't load")); img.src = frameUrl(r.frame_url); });
      if (gen !== S.gen) return;
      img.id = "frame";
      $("#frame").replaceWith(img);
      $("#frameinner").classList.remove("hidden");
    } else if (S.st.state !== "playing") $("#frameinner").classList.add("hidden");
    S.live = r; S.liveErr = null; S.liveAt = Date.now();
    drawBoxes(); renderStage(); renderTop();
  } catch (err) {
    if (gen !== S.gen) return;
    S.liveErr = err.status === 404 && !S.live ? "The live-view API (hackdash.live) isn't deployed yet, or doesn't know this camera." : err.message;
    renderStage();
  }
  setTimeout(() => liveTick(gen), Math.max(150, (S.st.state === "playing" ? 500 : 1000) - (performance.now() - t0)));
}
function renderStage() {
  const c = camOf(S.cam), r = S.live, nf = $("#noframe");
  const chips = [];
  if (c?.test_rig) chips.push(`<span class="chip test">test rig</span>`);
  if (r) {
    if (S.st.state === "playing") chips.push(`<span class="chip green" title="the camera's video stream (${esc(S.st.mode)})">live video</span>`);
    chips.push(`<span class="chip">${S.st.state === "playing" ? "boxes " : ""}≈${fx(r.lag_s, 1)} s behind live</span>`);
    chips.push(r.judge_on ? `<span class="chip green">judge on</span>` : `<span class="chip amber">judge off</span>`);
    chips.push(`<span class="chip">${r.boxes.length} ${r.boxes.length === 1 ? "person" : "people"} in view</span>`);
  }
  if (S.st.state === "failed") chips.push(`<span class="chip amber" title="${esc(S.st.why || "")}">video stream down · showing stills</span>`);
  if (S.liveErr && r) chips.push(`<span class="chip red" title="${esc(S.liveErr)}">frame ${Math.round((Date.now() - S.liveAt) / 1e3)} s old · retrying</span>`);
  $("#camcap").innerHTML = c ? `<b>${esc(c.name || c.camera_id)}</b> · ${c.live ? `Live${c.fps != null ? ` · ${fx(c.fps, 1)} fps` : ""}` : "Not live"}` : "";
  $("#lag").innerHTML = `<span class="row">${chips.join("")}</span>`;
  let msg = "";
  if (!S.cam) msg = S.camErr ? esc(S.camErr) : "Open a camera on the right to see it live with a box on every person.";
  else if (S.st.state === "playing") msg = "";
  else if (S.st.state === "starting" && !r?.frame_url) msg = `<span class="spin"></span>Starting live video…`;
  else if (!r) msg = S.liveErr ? esc(S.liveErr) : "Connecting to the live frame…";
  else if (!r.frame_url) msg = "No frame from the camera's ring right now.";
  nf.innerHTML = msg; nf.classList.toggle("hidden", !msg);
}

// Box state: sent (an open incident this demo launched on the person, or a real judge incident bound to the box),
// else the judge's verdict on the box, else nothing.
function openInc(id) { const x = id && S.inc.get(id); return x && x.status !== "closed" ? x : null; }
function sentInc(b) {
  const mine = openInc(S.sentByTrack.get(b.track_uuid));
  if (mine) return mine;
  for (const x of S.inc.values()) if (x.status !== "closed" && (x.edge_track === b.track_uuid || (b.site_track_id && x.site_track_id === b.site_track_id))) return x;
  return null;
}
function boxKind(b) {
  if (sentInc(b)) return "sent";
  const v = b.label?.verdict;
  return v === "urgent" || v === "deploy" ? "deploy" : v === "watch" ? "watch" : "none";
}
const COLOR = { sent: "#ef5b50", deploy: "#ef5b50", watch: "#e0a43a", none: "#2fbf71" };
function drawBoxes() {
  const r = S.live, vid = S.st.state === "playing", img = vid ? $("#vid") : $("#frame"), cv = $("#boxes");
  const nw = vid ? img.videoWidth : img.naturalWidth, nh = vid ? img.videoHeight : img.naturalHeight;
  if (!r || (!vid && !r.frame_url) || !nw) return;
  const w = img.clientWidth, hh = img.clientHeight, dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(w * dpr); cv.height = Math.round(hh * dpr); cv.style.width = `${w}px`; cv.style.height = `${hh}px`;
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, hh);
  const sx = w / (r.src_w || nw), sy = hh / (r.src_h || nh);
  const seen = new Set();
  const boxes = r.boxes.map(b => ({ b, t_ns: r.t_ns }));
  // a person being confirmed keeps their chip at the last place they were seen, so the click isn't yanked away
  for (const [tu, p] of S.pending) if (!r.boxes.some(b => b.track_uuid === tu)) boxes.push({ b: p.box, t_ns: p.t_ns, stale: true });
  for (const { b, t_ns, stale } of boxes) {
    const [x1, y1, x2, y2] = b.box, k = boxKind(b);
    const X = x1 * sx, Y = y1 * sy, W = (x2 - x1) * sx, H = (y2 - y1) * sy;
    g.strokeStyle = COLOR[k]; g.lineWidth = k === "none" ? 2 : 3; g.setLineDash(stale ? [5, 4] : []);
    g.strokeRect(X, Y, W, H);
    seen.add(b.track_uuid);
    placeChip(b, t_ns, k, X, Y, Y + H, w, stale);
  }
  for (const [tu, el] of S.chips) if (!seen.has(tu)) { el.remove(); S.chips.delete(tu); }
}
function chipHTML(b, k, stale) {
  const p = S.pending.get(b.track_uuid), L = b.label, inc = sentInc(b), id = shortId(b.track_uuid);
  const sus = L ? `${esc(L.verdict)}${L.why_label ? ` · ${esc(L.why_label)}` : ""}${L.e != null ? ` · E ${fx(L.e, 2)}` : ""}` : "—";
  const facts = L?.facts ? Object.entries(L.facts).slice(0, 2).map(([f, v]) => `${f} ${typeof v === "number" ? fx(v, 2) : v}`).join(" · ") : "";
  // an operator launch is the operator's call, not the judge's: never dress it up as Jev's verdict
  const op = /operator/i.test(`${L?.why_label || ""} ${L?.why || ""}`);
  const why = L && !op ? `<div class="why">${facts ? `${esc(facts)} · ` : ""}scene facts · Jev pointed at this person${L.caption ? `<br>${esc(L.caption)}` : ""}</div>` : "";
  let acts;
  if (inc) acts = `<span class="sentlbl">drone sent</span>`;
  else if (p?.state === "confirm") acts = `<span>Send drone to ${esc(id)}?</span><button class="yes">Yes</button><button class="no">Cancel</button>`;
  else if (p?.state === "sending") acts = `<span>Sending…</span>`;
  else acts = `<button class="send">Send drone</button>`;
  return `<div><span class="pid">${esc(id)}</span> ${fx(b.conf, 2)} · <span class="sus">${sus}</span>${stale ? ` <span class="sus">(last seen)</span>` : ""}</div>${why}<div class="acts">${acts}</div>`;
}
function placeChip(b, t_ns, k, X, top, bottom, w, stale) {
  const tu = b.track_uuid, html = chipHTML(b, k, stale);
  let el = S.chips.get(tu);
  if (!el) { el = h(`<div class="pchip"></div>`); $("#chips").append(el); S.chips.set(tu, el); }
  if (el.dataset.html !== html) {               // re-render only on change, so a click in flight isn't destroyed
    el.dataset.html = html; el.innerHTML = html;
    el.querySelector(".send")?.addEventListener("click", () => { S.pending.set(tu, { state: "confirm", box: b, t_ns }); drawBoxes(); });
    el.querySelector(".no")?.addEventListener("click", () => { S.pending.delete(tu); drawBoxes(); });
    el.querySelector(".yes")?.addEventListener("click", () => launch(tu));
  }
  el.className = `pchip ${k}`;
  const flip = top < 64;                        // too close to the top: put the chip under the box
  el.style.transform = flip ? "none" : "";
  el.style.top = `${flip ? bottom + 4 : top}px`;
  el.style.left = `${Math.max(0, Math.min(X, w - el.offsetWidth))}px`;
}
async function launch(tu) {
  const p = S.pending.get(tu);
  if (!p) return;
  // the newest payload's t_ns if the person is still in it, else the instant they were last seen
  const cur = S.live?.boxes.find(b => b.track_uuid === tu);
  const t_ns = cur ? S.live.t_ns : p.t_ns;
  p.state = "sending"; drawBoxes();
  try {
    const r = await post("/launch", `{"camera_id": ${JSON.stringify(S.cam)}, "track_uuid": ${JSON.stringify(tu)}, "t_ns": ${/^\d+$/.test(t_ns) ? t_ns : "0"}}`);
    S.sentByTrack.set(tu, r.id);
    toast(r.already_dispatched ? `Already dispatched: ${shortId(tu)} is on incident ${r.id}`
      : `Drone sent to ${shortId(tu)} · ${r.located ? `located (${r.loc_source || "?"}) ${ll(r.lat, r.lon)}` : "not located"}`);
    await pollIncidents();
  } catch (err) { if (err.status !== 401) toast(`Couldn't send the drone: ${err.message}`); }
  S.pending.delete(tu); drawBoxes();
}
window.addEventListener("resize", drawBoxes);

// ------------------------------------------------------------------ drone out (one compact card per open incident, over the video)
async function pollIncidents() {
  try {
    const r = await api("/incidents");
    const rows = Array.isArray(r) ? r : r.incidents || [];
    S.inc = new Map(rows.map(x => [x.id, x])); S.incErr = null;
  } catch (err) { if (err.status !== 401) S.incErr = err.status === 404 ? "The launch API (hackdash.launch) isn't deployed yet." : `Couldn't load incidents: ${err.message}`; }
  renderDrones(); renderTop(); drawBoxes();
}
function renderDrones() {
  const box = $("#droneout"), open = [...S.inc.values()].filter(x => x.status !== "closed");
  const key = open.map(x => `${x.id}|${x.edge_track}|${x.located}|${x.radius_m}`).join();
  if (box.dataset.key === key) return;            // unchanged: keep the button (and a click in flight)
  box.dataset.key = key; box.innerHTML = "";
  for (const x of open) {
    const who = x.edge_track || [...S.sentByTrack].find(([, id]) => id === x.id)?.[0];
    const at = x.opened_at ? new Date(x.opened_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
    const card = h(`<div class="dcard"><span><b>Drone sent</b> → ${who ? esc(shortId(who)) : "person"} · ${x.located ? `located${x.radius_m != null ? ` ±${fx(x.radius_m, 0)} m` : ""}` : "not located"}${at ? ` · ${esc(at)}` : ""}</span></div>`);
    const ab = btn("Abort drone", "dangerfill", async () => {
      ab.disabled = true;
      try { const r = await post(`/incidents/${encodeURIComponent(x.id)}/abort`); toast(`Abort sent${r?.command_id ? `: command ${r.command_id}` : ""}`); await pollIncidents(); }
      catch (err) { if (err.status !== 401) toast(`Couldn't abort: ${err.message}`); ab.disabled = false; }
    });
    card.append(ab); box.append(card);
  }
}

// ------------------------------------------------------------------ top bar
function renderTop() {
  const live = (S.cams || []).filter(c => c.live).length;
  const open = [...S.inc.values()].filter(x => x.status !== "closed").length;
  const c = camOf(S.cam), r = S.live;
  $("#pills").innerHTML = `
    <span class="pill ${open ? "red solid" : "green"}">${open ? `${open} drone${open === 1 ? "" : "s"} out` : "No drone out"}</span>
    ${S.cams ? `<span class="pill ${live ? "green" : ""}">${live ? `${live} camera${live === 1 ? "" : "s"} live` : "No camera live"}</span>` : ""}
    ${r ? `<span class="pill ${r.judge_on ? "green" : "amber"}">${r.judge_on ? "judge on" : "judge off"}</span>` : ""}
    ${c?.test_rig ? `<span class="pill test">${esc(c.name || c.camera_id)}: test rig</span>` : ""}`;
  document.title = `${open ? `(${open}) ` : ""}Send drone · Netra`;
  // Move-camera buttons (ptz.js), only for PTZ cameras that are live
  const ptz = [...S.ptzCams || []].filter(id => camOf(id)?.live);
  if (ptz.join() === S.ptzShown) return;
  S.ptzShown = ptz.join();
  document.querySelectorAll("#topbar .ptzmove").forEach(e => e.remove());
  for (const id of ptz) { const b = btn(`Move ${id}`, "ghost", () => openPtz(id)); b.classList.add("ptzmove"); $("#topbar .grow").after(b); }
}
function tickClock() { $("#clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" }); }

document.addEventListener("keydown", e => { if (e.key === "Escape") { if (S.pending.size) { S.pending.clear(); drawBoxes(); } } });
renderWall(); renderStage(); tickClock();
pollCams(); pollIncidents();
setInterval(pollCams, 5000); setInterval(pollIncidents, 2000); setInterval(tickClock, 1000);
setInterval(() => { if (S.liveErr) renderStage(); }, 1000);
