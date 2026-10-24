// Move camera (hackdash/ptz.py): a full-screen screen over the send-drone page for a PTZ camera (the Axis), loaded on
// first use by hack.js. The camera's own JPEG refreshes as fast as it loads; click it to centre there (shift-click = also
// zoom in 2x). Hold the arrow pad / zoom buttons (or arrow keys, + / -): /move is re-sent every 250 ms while held, and the
// camera's ptzd stops by itself if that stops (1.2 s deadman). Release = /stop at once.
(() => {
const API = "/hack/api";
const $ = s => root.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fx = (v, d = 1) => v == null ? "–" : Number(v).toFixed(d);
const toast = msg => { const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.querySelector("#toasts").append(t); setTimeout(() => t.remove(), 6000); };
async function api(path, opts = {}) {
  const r = await fetch(API + path, { credentials: "same-origin", ...opts, headers: { "Content-Type": "application/json" } });
  if (!r.ok) { let m = `${r.status}`; try { m = (await r.json()).detail || m; } catch {} throw Object.assign(new Error(m), { status: r.status }); }
  return r.json();
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

const P = { cam: null, open: false, st: null, err: null, held: { pan: 0, tilt: 0, zoom: 0 }, timer: null, speed: 0.15,
            ms: [], snapGen: 0, snapAt: 0 };
let root = null;

function build() {
  root = document.createElement("div");
  root.id = "ptz";
  root.innerHTML = `
    <div class="pbar"><b>Move camera</b><span id="p-cam" class="mono small"></span><span id="p-calib"></span>
      <div class="grow"></div><span id="p-lat" class="small muted"></span>
      <button class="btn" id="p-lock" title="While on, nobody can move the camera (operators turn it off again)">PTZ lock: OFF</button>
      <button class="btn" id="p-close">Close</button></div>
    <div id="p-view"><img id="p-img" alt="Live picture from the PTZ camera"><div id="p-none" class="empty hidden"></div>
      <div class="p-hint">Click = centre there · shift-click = centre + zoom in 2× · arrows / + − on the keyboard</div></div>
    <div id="p-side">
      <div class="p-pos mono" id="p-pos">–</div>
      <div class="p-pad">
        <span></span><button class="btn" data-m="0,1,0" title="Tilt up (↑)">▲</button><span></span>
        <button class="btn" data-m="-1,0,0" title="Pan left (←)">◀</button><button class="btn" id="p-stop" title="Stop">■</button><button class="btn" data-m="1,0,0" title="Pan right (→)">▶</button>
        <span></span><button class="btn" data-m="0,-1,0" title="Tilt down (↓)">▼</button><span></span>
      </div>
      <div class="p-zoom"><button class="btn" data-m="0,0,-1" title="Zoom out (−)">− Zoom out</button><button class="btn" data-m="0,0,1" title="Zoom in (+)">+ Zoom in</button></div>
      <label class="small">Speed <input type="range" id="p-speed" min="0.02" max="1" step="0.01" value="0.15"> <span id="p-speedv" class="mono"></span></label>
      <div class="p-dn" id="p-dn" title="IR-cut filter: Day = colour, Night = IR (the IR lights follow), Auto = the camera picks">
        <button class="btn" data-dn="day">Day</button><button class="btn" data-dn="night">Night (IR)</button><button class="btn" data-dn="auto">Auto</button></div>
      <div id="p-pic" class="small muted"></div>
      <div class="p-home"><button class="btn" id="p-goto">Go Home</button><button class="btn" id="p-save">Save as Home</button></div>
      <div id="p-note" class="small"></div>
    </div>`;
  document.body.append(root);
  $("#p-close").onclick = close;
  $("#p-lock").onclick = async () => {
    const on = !P.st?.locked;
    if (on) await release();
    try { await post(`/ptz/${encodeURIComponent(P.cam)}/lock`, { locked: on }); toast(on ? "PTZ locked: nobody can move the camera" : "PTZ unlocked"); }
    catch (err) { toast(`PTZ lock: ${err.message}`); }
    poll1();
  };
  $("#p-stop").onclick = () => release(true);
  $("#p-speed").oninput = e => { P.speed = Number(e.target.value); $("#p-speedv").textContent = P.speed.toFixed(2); };
  $("#p-speedv").textContent = P.speed.toFixed(2);
  for (const b of root.querySelectorAll("[data-m]")) {
    const [pan, tilt, zoom] = b.dataset.m.split(",").map(Number);
    b.onpointerdown = e => { e.preventDefault(); b.setPointerCapture(e.pointerId); hold({ pan, tilt, zoom }); };
    for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) b.addEventListener(ev, () => release());
  }
  for (const b of root.querySelectorAll("[data-dn]")) b.onclick = async () => {
    if (!writable()) return toast(P.st?.locked ? "PTZ is locked" : "PTZ is operator-only");
    try { const r = await post(`/ptz/${encodeURIComponent(P.cam)}/daynight`, { mode: b.dataset.dn }); P.dn = r.mode; renderDn(); setTimeout(pollDn1, 2500); toast(`Camera: ${b.textContent}`); }
    catch (err) { toast(`Day/Night failed: ${err.message}`); }
  };
  $("#p-goto").onclick = () => cmd("/home", "Going to Home");
  $("#p-save").onclick = () => { if (confirm("Save the camera's current view as Home?")) cmd("/home/save", "Saved as Home"); };
  const img = $("#p-img");
  img.onclick = e => {
    if (!writable()) return;
    const r = img.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    cmd("/center", e.shiftKey ? "Centring + zoom 2×" : "Centring", { x, y, zoom: e.shiftKey ? 2 : 1 });
  };
  img.onload = () => { $("#p-none").classList.add("hidden"); img.classList.remove("hidden"); const g = P.snapGen, wait = Math.max(0, 800 - (Date.now() - P.snapAt)); P.snapAt = Date.now(); setTimeout(() => snap(g), wait); };
  img.onerror = () => { img.classList.add("hidden"); const n = $("#p-none"); n.classList.remove("hidden"); n.textContent = "No picture from the camera (link down?)"; setTimeout(() => snap(P.snapGen), 2000); };
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", onKey);
  window.addEventListener("blur", () => release());
  document.addEventListener("visibilitychange", () => document.hidden && release());
}

// writes only for an operator while the PTZ lock is off (the server enforces the same: 403 otherwise)
const writable = () => !!P.st?.can_write && !P.st?.locked;

// ------------------------------------------------------------------ hold-to-move
const KEYS = { ArrowLeft: ["pan", -1], ArrowRight: ["pan", 1], ArrowUp: ["tilt", 1], ArrowDown: ["tilt", -1],
               "+": ["zoom", 1], "=": ["zoom", 1], "-": ["zoom", -1], "_": ["zoom", -1] };
const keysDown = new Set();
function onKey(e) {
  if (!P.open) return;
  if (e.key === "Escape" && e.type === "keydown") return close();
  const k = KEYS[e.key];
  if (!k || e.target.tagName === "INPUT") return;
  e.preventDefault();
  if (e.type === "keydown") { if (e.repeat) return; keysDown.add(e.key); } else keysDown.delete(e.key);
  const v = { pan: 0, tilt: 0, zoom: 0 };
  for (const key of keysDown) v[KEYS[key][0]] = KEYS[key][1];
  if (v.pan || v.tilt || v.zoom) hold(v); else release();
}
function hold(v) {
  if (!writable()) return;
  P.held = v;
  send();
  clearInterval(P.timer);
  P.timer = setInterval(send, 250);
}
async function send() {
  if (P.inflight) return;                         // never queue moves behind a slow link: the next tick sends the newest
  const s = P.speed, v = P.held;
  const t0 = performance.now();
  P.inflight = true;
  try {
    const r = await post(`/ptz/${encodeURIComponent(P.cam)}/move`, { pan: v.pan * s, tilt: v.tilt * s, zoom: v.zoom * s });
    lat(performance.now() - t0, r.ms);
  } catch (err) { P.err = err.message; renderNote(); }
  finally { P.inflight = false; }
}
async function release(always) {
  const was = P.timer != null;
  clearInterval(P.timer); P.timer = null; P.held = { pan: 0, tilt: 0, zoom: 0 }; keysDown.clear();
  // a move still in flight could land after this stop: stop again once it is done
  if (P.inflight) setTimeout(() => !P.timer && post(`/ptz/${encodeURIComponent(P.cam)}/stop`).catch(() => {}), 1500);
  if ((!was && !always) || !writable()) return;
  try { const t0 = performance.now(); const r = await post(`/ptz/${encodeURIComponent(P.cam)}/stop`); lat(performance.now() - t0, r.ms); }
  catch (err) { P.err = `Stop failed: ${err.message} (the camera stops by itself within 1.2 s)`; renderNote(); }
}
async function cmd(path, msg, body) {
  if (!writable()) return toast(P.st?.locked ? "PTZ is locked" : "PTZ is operator-only");
  try { const t0 = performance.now(); const r = await post(`/ptz/${encodeURIComponent(P.cam)}${path}`, body); lat(performance.now() - t0, r.ms); toast(msg); }
  catch (err) { toast(`${msg} failed: ${err.message}`); }
}
function lat(pageMs, droplMs) {
  P.ms.push(pageMs); if (P.ms.length > 30) P.ms.shift();
  const med = P.ms.slice().sort((a, b) => a - b)[Math.floor(P.ms.length / 2)];
  $("#p-lat").textContent = `command ${fx(pageMs, 0)} ms (median ${fx(med, 0)} ms; droplet→camera ${fx(droplMs, 0)} ms)`;
}

// ------------------------------------------------------------------ state + picture
async function poll1() {
  try { P.st = await api(`/ptz/${encodeURIComponent(P.cam)}/state`); P.err = null; }
  catch (err) { P.st = null; P.err = err.message; }
  render();
}
async function poll() {
  if (!P.open) return;
  await poll1();
  setTimeout(poll, 500);
}
function snap(gen) {
  if (!P.open || gen !== P.snapGen) return;
  $("#p-img").src = `${API}/ptz/${encodeURIComponent(P.cam)}/snapshot.jpg?t=${Date.now()}`;
}
async function pollDn1() {
  try { const r = await api(`/ptz/${encodeURIComponent(P.cam)}/daynight`); P.dn = r.mode; P.pic = r.picture; renderDn(); } catch {}
}
async function pollDn() {
  if (!P.open) return;
  try { const r = await api(`/ptz/${encodeURIComponent(P.cam)}/daynight`); P.dn = r.mode; P.pic = r.picture; } catch { P.dn = null; P.pic = null; }
  renderDn();
  setTimeout(pollDn, 5000);
}
function renderDn() {
  for (const b of root.querySelectorAll("[data-dn]")) b.classList.toggle("on", b.dataset.dn === P.dn);
  $("#p-pic").textContent = P.pic ? `Picture now: ${P.pic}` : "";
}
function render() {
  $("#p-cam").textContent = P.cam;
  const s = P.st, w = writable();
  for (const b of root.querySelectorAll("#p-side .btn")) b.disabled = !w;
  $("#p-img").style.cursor = w ? "crosshair" : "default";
  const lk = $("#p-lock");
  lk.textContent = `PTZ lock: ${s?.locked ? "ON" : "OFF"}`; lk.classList.toggle("on", !!s?.locked); lk.disabled = !s?.can_write;
  $("#p-pos").innerHTML = s ? `pan ${fx(s.pan, 2)}°  tilt ${fx(s.tilt, 2)}°<br>zoom ${esc(s.zoom_info.x)}× · ${fx(s.zoom_info.hfov_deg, 1)}° wide <span class="muted">(step ${fx(s.zoom, 0)})</span>`
    : esc(P.err ? `Camera not reachable: ${P.err}` : "…");
  const c = s?.calibration, el = $("#p-calib");
  el.className = "chip " + (!c ? "" : !c.calibrated ? "amber" : c.moved === false ? "" : "bad");
  el.textContent = !c ? "" : !c.calibrated ? "Not calibrated" : c.moved === false ? "At calibrated view" : c.moved ? "Moved off calibration: map positions wrong" : "Calibrated, pose unknown";
  el.title = c?.note || "";
  renderNote();
}
function renderNote() {
  const c = P.st?.calibration, s = P.st;
  const gate = !s ? "" : s.locked ? `<p class="bad">PTZ is locked (by ${esc(s.locked.by)}): nobody can move the camera until an operator turns the lock off.</p>`
    : !s.can_write ? `<p class="bad">PTZ is operator-only: you (${esc(s.user || "?")}) can watch but not move the camera.</p>` : "";
  $("#p-note").innerHTML = `${gate}${c ? `<p>${esc(c.note)}.</p>` : ""}<p class="muted">Moving this camera changes what it sees: a calibration is only valid at the view it was made in.</p>${P.err ? `<p class="bad">${esc(P.err)}</p>` : ""}`;
}

async function open(cam) {
  if (!root) build();
  P.cam = cam; P.open = true; P.st = null; P.err = null; P.ms = []; P.snapGen++;
  root.classList.remove("hidden");
  render(); poll(); pollDn(); snap(P.snapGen);
}
function close() { release(); P.open = false; P.snapGen++; root.classList.add("hidden"); }
window.Ptz = { open, close, state: P };
})();
